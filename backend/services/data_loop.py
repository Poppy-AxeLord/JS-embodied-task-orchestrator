"""
数据闭环服务（data_loop）
========================

本模块是整个"数据飞轮"的入口与落库点，承担**闭环数据采集**的职责。

为什么数据闭环如此重要（产品视角）：
- 具身机器人平台的核心竞争力不在于一次任务能不能完成，而在于**能否"越用越好"**。
- 每一次"自然语言 -> 任务拆解 -> 仿真执行 -> 结果"的过程，都会沉淀出宝贵数据：
  指令长什么样、被拆成了哪些原子技能、哪一步失败了、属于哪类失败、耗时多少、
  用户是否满意。把这些数据结构化地存下来，才能在后续：
    1) 做分析（analytics）找出系统薄弱点；
    2) 生成优化建议（recommendation）驱动迭代；
    3) 通过 Human-in-the-loop（人工介入）把失败样本修正为"优质样本"（golden），
       反哺拆解模板 / 模型微调。
- 因此 record_task 不仅仅是"写一条日志"，它是数据飞轮的第一节，决定了上游数据的质量。

本模块提供：
- record_task(parsed, exec_result, strategy) -> int：核心落库函数，写 tasks 与 task_steps 两张表，
  返回新建任务的 task_id。
- classify_failure(...)：失败分类辅助函数，若 executor 已给出分类则沿用，否则按线索兜底归类。

约定（严格遵守 SPEC）：
- 所有写入 JSON 字段统一使用 json.dumps(ensure_ascii=False)，保证库里是可读中文。
- failure_category 存**中文**（"感知失败"/"理解失败"/"规划失败"/"执行失败"/"环境异常"）。
- 时间统一 ISO8601 字符串（YYYY-MM-DDTHH:MM:SS）。
"""

import json
import random
from datetime import datetime

# 依赖 database.py 暴露的连接与执行辅助函数（见 SPEC §2）
from database import get_conn

# 失败分类相关的合法值、英文↔中文映射、技能类别→失败分类亲和表，
# 统一收敛到 constants（单一事实源）。原本 data_loop 与 executor 各写一份
# 「技能类别→失败分类」，且「控制类」两处不一致，现统一引用同一口径。
from services.constants import (
    FAILURE_CATEGORY_CN,
    FAILURE_KEY_TO_CN as _FAILURE_KEY_TO_CN,
    CATEGORY_TO_FAILURE as _CATEGORY_TO_FAILURE,
)


def classify_failure(exec_result: dict, parsed: dict) -> str:
    """
    失败分类辅助函数。

    产品逻辑：失败分类是数据闭环里最关键的"标签"，它直接决定后续分析能否定位到
    系统的真正短板（是看不清？还是没听懂？还是动作做不到？）。因此分类要尽量准确，
    并保证落库的一定是 SPEC §5 中合法的 5 个中文分类之一。

    优先级：
      1) 若 executor 已经给出了 failure_category（最权威，因为它知道具体哪步、为什么失败），
         直接沿用（必要时把英文 key 归一化为中文）。
      2) 否则，根据失败步骤所属技能分类做兜底推断（感知类->感知失败，操作类->执行失败 ……）。
      3) 再兜底，返回"执行失败"（最常见、最保守的一类）。

    :param exec_result: ExecutionResult（executor.simulate_execution 的返回）
    :param parsed:      ParsedTask（任务拆解结果）
    :return: 5 类失败之一的中文字符串
    """
    # 1) 优先采用 executor 给出的分类
    cat = exec_result.get("failure_category")
    if cat:
        # 若上游传的是英文 key，归一化为中文
        cat = _FAILURE_KEY_TO_CN.get(cat, cat)
        if cat in FAILURE_CATEGORY_CN:
            return cat

    # 2) 根据失败步骤的技能分类兜底推断
    #    找到 exec_result.steps 中第一个 status == "failed" 的步骤，
    #    再到 parsed.steps 里取它的 category。
    failed_step = None
    for st in exec_result.get("steps", []) or []:
        if st.get("status") == "failed":
            failed_step = st
            break

    if failed_step is not None:
        # 用 skill_code 在 parsed.steps 里找对应步骤的分类
        skill_code = failed_step.get("skill_code")
        for ps in parsed.get("steps", []) or []:
            if ps.get("skill_code") == skill_code:
                category = ps.get("category")
                guess = _CATEGORY_TO_FAILURE.get(category)
                if guess:
                    return guess
                break

    # 3) 最终兜底
    return "执行失败"


def _now_iso() -> str:
    """返回当前时间的 ISO8601 字符串（精确到秒，去掉微秒，符合 SPEC 时间约定）。"""
    return datetime.now().replace(microsecond=0).isoformat()


def _decide_needs_review(success: bool, has_rating: bool) -> int:
    """
    判定一个任务是否需要人工介入（Human-in-the-loop）。

    产品逻辑：失败任务是改进系统最有价值的样本。如果一个任务失败了、又没有用户评分
    （即没有人为它"盖棺定论"），就应该有一定比例进入人工复核队列，由人来：
      - 确认/修正失败分类；
      - 修正错误的拆解步骤；
      - 把修好的样本标记为 golden（优质样本）反哺系统。

    规则（遵循 SPEC §9）：失败且无评分的任务，约 1/3 置 needs_review=1。
    这里用随机抽样实现"约 1/3"，既避免全部涌入复核队列把人淹没，
    又能持续不断地有新鲜失败样本进入闭环。

    :param success:    任务是否最终成功
    :param has_rating: 是否已有用户评分
    :return: 0 或 1
    """
    if (not success) and (not has_rating):
        # 约 1/3 概率标记需要人工介入
        return 1 if random.random() < (1.0 / 3.0) else 0
    return 0


def record_task(parsed: dict, exec_result: dict, strategy: str) -> int:
    """
    将一次完整的"任务执行"落库，写入 tasks 与 task_steps 两张表，返回新建 task_id。

    这是数据闭环的核心采集动作。每调用一次，就为数据飞轮添了一条新数据。

    入参：
    :param parsed:      ParsedTask（见 SPEC §3）——任务拆解结果，提供 instruction/task_type/
                        goal/constraints/steps/exception_handling。
    :param exec_result: ExecutionResult（见 SPEC §3）——仿真执行结果，提供 status/success/
                        total_duration_ms/step_count/retry_count/failure_*/steps。
    :param strategy:    "llm" 或 "rule"，本次拆解所用策略，便于后续策略对比分析。
    :return: 新建任务的 task_id（INTEGER）

    落库要点：
    - constraints / steps / exception_handling 等结构化字段统一 json.dumps(ensure_ascii=False)。
    - failure_category 通过 classify_failure 归一化为 5 类中文之一（成功任务为 NULL）。
    - needs_review 按"失败且无评分约 1/3"规则置位。
    - task_steps 逐步落库，便于历史详情页"回放"每一步。
    """
    success = bool(exec_result.get("success"))
    # 状态字段：成功 -> "success"，失败 -> "failed"
    status = exec_result.get("status") or ("success" if success else "failed")

    # 失败分类与原因：仅失败任务才有，成功任务置 NULL
    if success:
        failure_category = None
        failure_reason = None
    else:
        failure_category = classify_failure(exec_result, parsed)
        failure_reason = exec_result.get("failure_reason") or "执行过程中发生未明确归因的错误"

    # 本场景下记录时刻还没有用户评分（评分通过 feedback 接口后补），故 rating 缺失
    rating = exec_result.get("rating")  # 一般为 None
    has_rating = rating is not None

    # 人工介入判定（Human-in-the-loop）
    needs_review = _decide_needs_review(success, has_rating)

    # 步骤数 / 重试次数 / 总耗时，优先取 exec_result，缺失时从 steps 兜底推算
    steps = exec_result.get("steps", []) or []
    step_count = exec_result.get("step_count")
    if step_count is None:
        step_count = len(steps)
    retry_count = int(exec_result.get("retry_count", 0) or 0)
    total_duration_ms = exec_result.get("total_duration_ms")
    if total_duration_ms is None:
        total_duration_ms = sum(int(s.get("duration_ms", 0) or 0) for s in steps)

    created_at = _now_iso()

    # 使用同一个连接完成 tasks + task_steps 的写入，保证一致性
    conn = get_conn()
    try:
        cur = conn.cursor()

        # ---------------- 写 tasks 表 ----------------
        # 注意：JSON 字段全部 json.dumps(ensure_ascii=False)
        cur.execute(
            """
            INSERT INTO tasks (
                instruction, task_type, strategy, goal, constraints, steps,
                exception_handling, status, success, failure_category, failure_reason,
                total_duration_ms, step_count, retry_count, rating, feedback_text,
                needs_review, is_golden, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                parsed.get("instruction", ""),
                parsed.get("task_type", ""),
                strategy,
                parsed.get("goal", ""),
                json.dumps(parsed.get("constraints", []), ensure_ascii=False),
                json.dumps(parsed.get("steps", []), ensure_ascii=False),
                json.dumps(parsed.get("exception_handling", []), ensure_ascii=False),
                status,
                1 if success else 0,
                failure_category,
                failure_reason,
                int(total_duration_ms),
                int(step_count),
                int(retry_count),
                rating,                 # None -> SQLite NULL
                None,                   # feedback_text：落库时还没有，后续 feedback 接口补
                needs_review,
                0,                      # is_golden：初始非优质样本，人工复核后才置 1
                created_at,
            ),
        )
        task_id = cur.lastrowid

        # ---------------- 写 task_steps 表（逐步日志，便于回放）----------------
        # step_index 从 1 开始；params 为 JSON；error 仅失败步骤有。
        for idx, st in enumerate(steps, start=1):
            cur.execute(
                """
                INSERT INTO task_steps (
                    task_id, step_index, skill_code, skill_name, params,
                    status, duration_ms, error, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    st.get("index", idx),
                    st.get("skill_code", ""),
                    st.get("skill_name", ""),
                    json.dumps(st.get("params", {}), ensure_ascii=False),
                    st.get("status", "success"),
                    int(st.get("duration_ms", 0) or 0),
                    st.get("error"),        # None -> NULL
                    created_at,
                ),
            )

        conn.commit()
        return int(task_id)
    finally:
        conn.close()
