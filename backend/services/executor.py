# -*- coding: utf-8 -*-
"""
执行模拟服务 executor
====================================================================
在不接入真实机器人/物理仿真的前提下，"逼真地"模拟一次任务执行，产出
ExecutionResult（SPEC §3，不含 task_id —— task_id 由 data_loop 落库时填）。

对外主函数：`simulate_execution(parsed, strategy) -> dict`

模拟逻辑（产品逻辑，核心价值在于让数据闭环"看起来真实"）：
  1. 逐步执行：每个 step 依据其技能**类别**给一个基准耗时，再叠加随机抖动，
     得到 duration_ms。不同类别耗时差异明显（移动慢、感知中、逻辑快）。
  2. 概率判定成败：每步有一个基础失败率，受"任务难度"放大——困难任务失败率
     更高。一旦某步失败，可能触发 1~2 次重试（Retry），重试也按概率成功；
     重试次数计入 retry_count，重试本身也会增加耗时。
  3. 失败定性：若某步重试后仍失败，则整个任务失败；该步即"失败步"，
     从 SPEC §5 的 5 类失败分类中按"技能类别 -> 最可能失败类型"挑一类（中文），
     并给出一段具体的失败原因文字。失败步之后的步骤不再执行。
  4. 一致性：整体 success ⇔ 所有已执行步骤最终成功；total_duration_ms 为各步
     （含重试）耗时之和；step_count 为 parsed.steps 的总数（流程规模），
     与落库口径一致。

重要约定：
  - 本模块使用 `random`，但**绝不**调用 `random.seed()`——确定性 seed 是
    mock_data 造历史数据时的职责。这里每次执行都应有真实的随机性。

未来对接真机 / 真实 VLA 模型的替换点（设计留痕）：
  `simulate_execution(parsed, strategy)` 是执行层的唯一入口，与上层编排 / 评测 / 数据闭环
  完全解耦。落地真机时，只需保持它的**入参（ParsedTask）与出参（ExecutionResult）契约不变**，
  把内部"概率模拟"替换为真实执行即可，例如：

      def simulate_execution(parsed, strategy):
          # 1) 把 parsed.steps 的 25 个原子技能（VLA 动作原语接口层）
          #    逐条下发给真机 SDK / ROS Action，或调用真实 VLA（视觉-语言-动作）模型推理；
          # 2) 用真实传感器回读每步 status / duration_ms / error；
          # 3) 感知类失败由真实置信度阈值触发 → 归入"感知失败"；
          # 4) 组装成同样形状的 ExecutionResult 返回。
          ...

  因为契约不变，data_loop 落库、失败 5 分类归因、看板评测（benchmark）与优质样本闭环
  全部零改动即可复用真机数据——这正是"编排层 / 执行层解耦"带来的 Sim2Real 平滑迁移能力。
"""

from __future__ import annotations

import random

# 技能类别→失败分类的映射统一收敛到 constants（单一事实源），
# 避免 executor 与 data_loop 各写一份导致「控制类」映射不一致。
from services.constants import CATEGORY_TO_FAILURE as _CATEGORY_FAILURE, DEFAULT_FAILURE as _DEFAULT_FAILURE

# ====================================================================
# 各技能类别的"基准耗时（毫秒）"与"抖动范围（毫秒）"。
# 体现物理直觉：移动最慢、操作较慢、感知中等、逻辑最快、控制偏快。
# ====================================================================
_CATEGORY_TIMING = {
    "移动类": {"base": 1800, "jitter": 900},   # 移动/导航较慢
    "操作类": {"base": 1500, "jitter": 800},   # 抓取/放置等机械动作
    "感知类": {"base": 900, "jitter": 500},    # 识别/扫描中等
    "逻辑类": {"base": 350, "jitter": 250},    # 条件/排序等纯计算很快
    "控制类": {"base": 500, "jitter": 400},    # 等待/通知/确认偏快
}
# 未知类别的兜底耗时
_DEFAULT_TIMING = {"base": 1000, "jitter": 600}

# 注：技能类别→失败分类（_CATEGORY_FAILURE）与兜底 _DEFAULT_FAILURE
# 已统一收敛至 services/constants.py（见文件顶部 import），此处不再重复定义。

# ====================================================================
# 5 类失败分类对应的"具体原因文案"模板，让历史详情更可读、看板更丰富。
# ====================================================================
_FAILURE_REASONS = {
    "感知失败": [
        "目标物体被遮挡，识别置信度过低",
        "光照不足导致颜色判别错误",
        "相似物体干扰，识别到了错误目标",
        "目标超出视野范围，未能定位",
    ],
    "理解失败": [
        "指令存在歧义，未能确定目标物体",
        "未理解空间方位描述（左/右/上层）",
        "多目标指令拆解出现偏差",
        "省略主语导致操作对象不明确",
    ],
    "规划失败": [
        "步骤顺序不合理，先放置后抓取",
        "缺少必要的前置感知步骤",
        "循环边界设置错误，遗漏部分物体",
        "路径规划未覆盖全部目标点",
    ],
    "执行失败": [
        "抓取力度不足，物体中途掉落",
        "放置位置偏移，物体未稳定就位",
        "机械臂运动超限，动作中断",
        "倾倒角度过大，发生洒漏",
    ],
    "环境异常": [
        "前方出现障碍物，无法继续移动",
        "目标物体被他人移动，位置失效",
        "作业区域有人员进入，触发安全停止",
        "地面湿滑导致导航偏离路线",
    ],
}

# ====================================================================
# 任务难度 -> 每步基础失败概率（困难任务失败率更高）。
# 难度从 parsed 中推断（见 _infer_difficulty）。
# ====================================================================
_DIFFICULTY_FAIL_RATE = {
    "简单": 0.04,
    "中等": 0.09,
    "困难": 0.18,
}
_DEFAULT_FAIL_RATE = 0.09

# 策略带来的微调：规则策略略保守稳定，LLM 策略灵活但偶有跳步
# （此处仅做轻微差异，用于让"策略对比"页有可观察的区别）
_STRATEGY_FAIL_DELTA = {
    "rule": -0.01,   # 规则更稳，失败率略低
    "llm": 0.0,
}


def _infer_difficulty(parsed: dict) -> str:
    """从 ParsedTask 推断难度（简单/中等/困难）。

    优先用 parsed 显式携带的 difficulty；否则用启发式：
      - 步骤越多越难；
      - 巡检/检查类任务天然更难（避障、遍历）。
    """
    explicit = parsed.get("difficulty")
    if explicit in _DIFFICULTY_FAIL_RATE:
        return explicit

    steps = parsed.get("steps") or []
    n = len(steps)
    task_type = parsed.get("task_type", "")

    # 巡检/检查类直接判定为困难
    if task_type in ("巡检", "检查"):
        return "困难"
    # 步骤规模启发式
    if n <= 4:
        return "简单"
    if n <= 7:
        return "中等"
    return "困难"


def _timing_for(category: str) -> dict:
    """取某技能类别的耗时配置，未知类别用默认值。"""
    return _CATEGORY_TIMING.get(category, _DEFAULT_TIMING)


def _step_duration(category: str) -> int:
    """生成单步耗时（毫秒）= 基准 + 随机抖动，最低不少于 200ms。"""
    cfg = _timing_for(category)
    base = cfg["base"]
    jitter = cfg["jitter"]
    # 在 [base - jitter/2, base + jitter] 之间取值，整体偏向基准之上
    duration = base + random.randint(-jitter // 2, jitter)
    return max(200, int(duration))


def _pick_failure(category: str) -> tuple[str, str]:
    """根据失败步的技能类别，挑选失败分类（中文）与一条具体原因文案。"""
    fail_category = _CATEGORY_FAILURE.get(category, _DEFAULT_FAILURE)
    reason = random.choice(_FAILURE_REASONS.get(fail_category, ["未知执行异常"]))
    return fail_category, reason


def simulate_execution(parsed: dict, strategy: str) -> dict:
    """模拟一次任务执行，返回 ExecutionResult（不含 task_id）。

    参数：
        parsed:   ParsedTask（dict），需含 steps 列表
        strategy: "llm" 或 "rule"，影响失败率微调
    返回：
        {
          status, success, total_duration_ms, step_count, retry_count,
          failure_category, failure_reason,
          steps: [ {index, skill_code, skill_name, params, status,
                    duration_ms, error} ... ]
        }
    """
    parsed = parsed or {}
    steps_in = parsed.get("steps") or []
    step_count = len(steps_in)

    # 计算本次执行的"每步基础失败率"
    difficulty = _infer_difficulty(parsed)
    base_fail_rate = _DIFFICULTY_FAIL_RATE.get(difficulty, _DEFAULT_FAIL_RATE)
    base_fail_rate += _STRATEGY_FAIL_DELTA.get(strategy, 0.0)
    # 概率夹紧在合理区间，避免出现负数或过高
    base_fail_rate = min(0.45, max(0.01, base_fail_rate))

    out_steps: list[dict] = []
    total_duration = 0
    retry_count = 0
    overall_success = True
    failure_category = None
    failure_reason = None

    # 空流程兜底：没有步骤视为"无可执行内容"，记为失败需人工介入
    if step_count == 0:
        return {
            "status": "failed",
            "success": False,
            "total_duration_ms": 0,
            "step_count": 0,
            "retry_count": 0,
            "failure_category": "规划失败",
            "failure_reason": "拆解结果为空，没有可执行的步骤",
            "steps": [],
        }

    # 逐步"执行"
    for raw in steps_in:
        category = raw.get("category", "")
        index = raw.get("index", len(out_steps) + 1)

        # 本步首次执行耗时
        duration = _step_duration(category)

        # 是否本步出问题（首次判定）
        step_failed = random.random() < base_fail_rate

        # 若首次失败，尝试 1~2 次重试（控制类/逻辑类一般不重试，更多是流程问题，
        # 但为统一行为这里对所有类别都允许重试，符合"失败重试"技能语义）
        if step_failed:
            max_retry = random.randint(1, 2)  # 触发 1~2 次重试
            for _ in range(max_retry):
                retry_count += 1
                # 重试也要花时间（约为正常耗时的 60%~100%）
                duration += int(_step_duration(category) * random.uniform(0.6, 1.0))
                # 重试有较大概率成功（成功率随重试提升）
                if random.random() > base_fail_rate * 0.8:
                    step_failed = False
                    break

        if step_failed:
            # 重试后仍失败 -> 整个任务失败，本步为失败步，后续步骤不再执行
            overall_success = False
            failure_category, failure_reason = _pick_failure(category)
            out_steps.append(
                {
                    "index": index,
                    "skill_code": raw.get("skill_code", ""),
                    "skill_name": raw.get("skill_name", ""),
                    "params": raw.get("params", {}),
                    "status": "failed",
                    "duration_ms": duration,
                    "error": failure_reason,
                }
            )
            total_duration += duration
            break

        # 本步成功
        out_steps.append(
            {
                "index": index,
                "skill_code": raw.get("skill_code", ""),
                "skill_name": raw.get("skill_name", ""),
                "params": raw.get("params", {}),
                "status": "success",
                "duration_ms": duration,
                "error": None,
            }
        )
        total_duration += duration

    status = "success" if overall_success else "failed"

    return {
        "status": status,
        "success": overall_success,
        "total_duration_ms": int(total_duration),
        # step_count 取流程总规模（与落库/看板口径一致），
        # 即便因失败提前中断，也反映原始拆解的步骤数
        "step_count": step_count,
        "retry_count": retry_count,
        "failure_category": failure_category,
        "failure_reason": failure_reason,
        "steps": out_steps,
    }
