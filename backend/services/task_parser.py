# -*- coding: utf-8 -*-
"""
任务拆解服务 task_parser
====================================================================
把一条自然语言指令拆解为结构化的 ParsedTask（见 SPEC §3）：
    { instruction, task_type, goal, constraints, steps, exception_handling }

对外主函数：`parse_task(instruction, strategy, skills) -> dict`

两种拆解策略（产品逻辑）：
  - strategy == "llm"  ：调用 LLMService.chat()，让大模型产出结构化拆解。
                         大模型可能处于 Mock 模式（无 Key），其返回文本会先
                         尝试解析为 JSON；解析失败则回退到本地 mock_parse，
                         保证永远有合理结果。
  - strategy == "rule" ：完全基于关键词的规则引擎拆解（不依赖任何大模型），
                         可解释、零成本、可离线。

无论哪种策略，steps 里的 skill_code **必须**取自 SPEC §4 的 25 个原子技能，
绝不发明新技能。skills 参数为 skills 表行（含 code/name/category），用于
校验与补全 skill_name / category。
"""

from __future__ import annotations

import json
import logging
import re

from .llm_service import LLMService
# 绝对导入：backend 目录为顶层，mock 为顶层包（避免越过顶层包的相对导入）
from mock import mock_llm

logger = logging.getLogger("task_parser")


def _load_llm_config() -> dict:
    """读取 LLM 配置（来自 backend/config.py）。

    为避免与 config.py 的具体导出名强耦合，这里做一层容错适配：
    优先使用 `config.get_llm_config()`，否则从模块级常量拼装一个等价 dict。
    任何异常都回退为空 dict（LLMService 见空 Key 即 Mock 模式）。
    """
    try:
        import config as cfg  # 绝对导入：backend 为顶层，config 为顶层模块

        # config.settings 单例集中暴露全部 LLM 配置（均来自 .env / 环境变量）
        s = cfg.settings
        return {
            "provider": s.LLM_PROVIDER,
            "openai_api_key": s.OPENAI_API_KEY,
            "qwen_api_key": s.QWEN_API_KEY,
            "zhipu_api_key": s.ZHIPU_API_KEY,
            "model": s.LLM_MODEL,
            "temperature": s.LLM_TEMPERATURE,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 LLM 配置失败：%s —— 将以 Mock 模式运行", exc)
        return {}


# ====================================================================
# SPEC §4 的 25 个原子技能（编码 -> (中文名, 分类)）
# 作为"事实来源"内嵌一份，确保即使 skills 表/参数缺失，校验依然可用。
# ====================================================================
SKILL_TABLE = {
    # 移动类
    "MoveTo": ("移动到", "移动类"),
    "Navigate": ("路径规划", "移动类"),
    "Rotate": ("转向", "移动类"),
    "Patrol": ("巡检", "移动类"),
    "ReturnHome": ("返回原点", "移动类"),
    # 操作类
    "Grasp": ("抓取", "操作类"),
    "Place": ("放置", "操作类"),
    "Push": ("推", "操作类"),
    "Pour": ("倾倒", "操作类"),
    "Open": ("打开", "操作类"),
    "Wipe": ("擦拭", "操作类"),
    # 感知类
    "Recognize": ("识别", "感知类"),
    "Locate": ("定位", "感知类"),
    "Measure": ("测量", "感知类"),
    "Scan": ("扫描", "感知类"),
    "CheckColor": ("颜色判别", "感知类"),
    # 逻辑类
    "If": ("条件判断", "逻辑类"),
    "Loop": ("循环", "逻辑类"),
    "Compare": ("比较", "逻辑类"),
    "Sort": ("排序", "逻辑类"),
    "Filter": ("筛选", "逻辑类"),
    # 控制类
    "Wait": ("等待", "控制类"),
    "Retry": ("失败重试", "控制类"),
    "Confirm": ("人工确认", "控制类"),
    "Notify": ("通知", "控制类"),
}


# 任务归类关键词表（SPEC §2：整理/分拣/取送/巡检/养护/排序/检查）
# 命中即归类，未命中默认"取送"（最常见的搬运类）。
_TASK_TYPE_KEYWORDS = {
    "整理": ["整理", "收纳", "清理", "归位", "收拾"],
    "分拣": ["分拣", "分类", "区分", "归类"],
    "巡检": ["巡检", "巡逻", "检查路线", "安防"],
    "养护": ["浇水", "养护", "通风", "开窗", "照料"],
    "排序": ["排序", "排列", "从大到小", "从小到大", "顺序排"],
    "检查": ["检查", "查看", "确认有没有", "盘点"],
    "取送": ["拿", "取", "送", "放到", "搬", "递", "放置"],
}


def _build_skill_lookup(skills: list[dict] | None) -> dict:
    """合并外部传入的 skills 表与内置 SKILL_TABLE，返回 code->(name,category)。

    优先使用数据库传入的 skills（可能含用户自定义的中文名调整），
    缺失项用内置表补齐。这样既尊重运行时数据，又保证健壮。
    """
    lookup = {code: (name, cat) for code, (name, cat) in SKILL_TABLE.items()}
    for s in skills or []:
        code = s.get("code")
        if not code:
            continue
        name = s.get("name") or lookup.get(code, (code, ""))[0]
        cat = s.get("category") or lookup.get(code, ("", ""))[1]
        lookup[code] = (name, cat)
    return lookup


def _normalize_step(raw: dict, index: int, lookup: dict) -> dict:
    """把一个原始 step 规整为 SPEC §3 标准 step 对象。

    - 强制 skill_code 合法（不在技能表内则降级为 MoveTo 并告警）
    - 补全 skill_name / category（以技能表为准）
    - 补全 index、params、description、expected_result
    """
    code = raw.get("skill_code") or raw.get("code") or "MoveTo"
    if code not in lookup:
        logger.warning("步骤 #%s 使用了非法技能 %s，已降级为 MoveTo", index, code)
        code = "MoveTo"
    name, category = lookup[code]

    params = raw.get("params")
    if not isinstance(params, dict):
        params = {}

    return {
        "index": index,
        "skill_code": code,
        # skill_name / category 以技能表为准，避免大模型给错中文名
        "skill_name": name,
        "category": category,
        "params": params,
        "description": str(raw.get("description") or f"{name}操作"),
        "expected_result": str(raw.get("expected_result") or "执行成功"),
    }


def _finalize_parsed(parsed: dict, instruction: str, lookup: dict) -> dict:
    """对一份候选 ParsedTask 做最终规整：补全字段、校验 steps、统一形状。"""
    if not isinstance(parsed, dict):
        parsed = {}

    # 任务归类：优先用已有值，否则按关键词推断
    task_type = parsed.get("task_type") or _classify_task_type(instruction)

    # constraints / exception_handling 必须是字符串数组
    constraints = parsed.get("constraints")
    if not isinstance(constraints, list):
        constraints = []
    constraints = [str(c) for c in constraints if str(c).strip()]

    exception_handling = parsed.get("exception_handling")
    if not isinstance(exception_handling, list):
        exception_handling = []
    exception_handling = [str(e) for e in exception_handling if str(e).strip()]

    # steps 规整：逐个标准化并重排 index（从 1 开始）
    raw_steps = parsed.get("steps") if isinstance(parsed.get("steps"), list) else []
    steps = []
    for i, raw in enumerate(raw_steps, start=1):
        if isinstance(raw, dict):
            steps.append(_normalize_step(raw, i, lookup))

    # 兜底：若没有任何合法步骤，给一个最小可执行流程，避免前端空白
    if not steps:
        steps = _fallback_steps(instruction, lookup)

    return {
        "instruction": instruction,
        "task_type": task_type,
        "goal": str(parsed.get("goal") or f"完成指令：{instruction}"),
        "constraints": constraints or ["轻拿轻放", "不得碰倒其它物品"],
        "steps": steps,
        "exception_handling": exception_handling
        or ["若识别失败则请求人工确认", "抓取失败重试2次"],
    }


def _fallback_steps(instruction: str, lookup: dict) -> list[dict]:
    """通用最小流程：扫描->识别->定位->移动->抓取->放置。"""
    raw = [
        {"skill_code": "Scan", "params": {"area": "工作区"}, "description": "扫描工作区域"},
        {"skill_code": "Recognize", "params": {"target": "目标物体"}, "description": "识别目标物体"},
        {"skill_code": "Locate", "params": {"object": "目标物体"}, "description": "定位目标坐标"},
        {"skill_code": "MoveTo", "params": {"target": "目标物体"}, "description": "移动到目标附近"},
        {"skill_code": "Grasp", "params": {"object": "目标物体", "force": "适中"}, "description": "抓取目标物体"},
        {"skill_code": "Place", "params": {"object": "目标物体", "location": "目标位置"}, "description": "放置到目标位置"},
    ]
    return [_normalize_step(s, i, lookup) for i, s in enumerate(raw, start=1)]


def _classify_task_type(instruction: str) -> str:
    """根据关键词把指令归入 7 类任务之一，默认"取送"。"""
    text = instruction or ""
    for task_type, kws in _TASK_TYPE_KEYWORDS.items():
        if any(kw in text for kw in kws):
            return task_type
    return "取送"


# ====================================================================
# 对外主函数
# ====================================================================
def parse_task(instruction: str, strategy: str, skills: list[dict]) -> dict:
    """把自然语言指令拆解为 ParsedTask。

    参数：
        instruction: 用户原始指令
        strategy:    "llm" 或 "rule"
        skills:      skills 表行列表（含 code/name/category），用于校验补全
    返回：
        ParsedTask（dict，形状见 SPEC §3）
    """
    instruction = (instruction or "").strip()
    lookup = _build_skill_lookup(skills)

    if strategy == "rule":
        # 规则策略：完全离线、可解释
        parsed = _rule_parse(instruction, lookup)
    else:
        # 默认 / "llm" 策略：走大模型（可能内部 Mock），失败回退本地拆解
        parsed = _llm_parse(instruction, skills, lookup)

    return _finalize_parsed(parsed, instruction, lookup)


# ====================================================================
# 策略一：LLM 拆解
# ====================================================================
def _llm_parse(instruction: str, skills: list[dict], lookup: dict) -> dict:
    """调用 LLMService 让大模型产出结构化拆解。

    流程：
      1. 构造带"可用技能清单 + 输出 JSON 格式约束"的提示词；
      2. 调 chat() 拿回文本（Mock 模式下为本地兜底文本）；
      3. 尝试从文本中抽取 JSON 并解析为 ParsedTask；
      4. 解析失败 -> 回退 mock_llm.mock_parse（高质量本地拆解）。
    """
    # 构造 LLMService（配置来自环境变量；无 Key 即 Mock）
    try:
        service = LLMService(_load_llm_config())
    except Exception as exc:  # noqa: BLE001
        logger.warning("构造 LLMService 失败：%s —— 回退本地拆解", exc)
        return mock_llm.mock_parse(instruction, skills)

    # 系统提示词：明确角色、可用技能、输出格式（强约束为 JSON）
    skill_lines = "\n".join(
        f"- {code} {name}（{cat}）" for code, (name, cat) in lookup.items()
    )
    system = (
        "你是具身机器人任务编排专家。请把用户的自然语言指令拆解为可执行的原子步骤。\n"
        "只能使用下列原子技能（skill_code 必须严格取自其中之一）：\n"
        f"{skill_lines}\n\n"
        "请严格输出 JSON（不要任何多余文字、不要 Markdown 代码块），格式如下：\n"
        '{"task_type":"整理|分拣|取送|巡检|养护|排序|检查",'
        '"goal":"任务目标",'
        '"constraints":["约束1","约束2"],'
        '"steps":[{"skill_code":"MoveTo","params":{"target":"桌子"},'
        '"description":"移动到桌子旁","expected_result":"到达桌子附近"}],'
        '"exception_handling":["异常处理1","异常处理2"]}'
    )
    user = f"请拆解以下指令：{instruction}"

    # 发起对话（内部可能 Mock，且异常已在 chat 内回退）
    reply = service.chat(system, user)

    # 尝试解析为结构化 JSON
    parsed = _try_extract_json(reply)
    if parsed is not None and isinstance(parsed.get("steps"), list):
        logger.info("LLM 拆解成功解析为结构化 JSON")
        return parsed

    # 解析失败：回退到本地高质量拆解
    logger.info("LLM 返回无法解析为 JSON，回退到本地 mock_parse")
    return mock_llm.mock_parse(instruction, skills)


def _try_extract_json(text: str) -> dict | None:
    """从可能含 Markdown / 多余文字的文本中抽取并解析第一个 JSON 对象。

    依次尝试：
      1. 直接整体 json.loads；
      2. 去掉 ```json ... ``` 代码块围栏后再解析；
      3. 用括号匹配抓取第一个 {...} 平衡子串再解析。
    任一成功即返回 dict，全部失败返回 None。
    """
    if not text or not isinstance(text, str):
        return None

    # 尝试 1：整体解析
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass

    # 尝试 2：剥离 ```json 围栏
    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.IGNORECASE)
    if fenced != text:
        try:
            obj = json.loads(fenced)
            return obj if isinstance(obj, dict) else None
        except (json.JSONDecodeError, ValueError):
            pass

    # 尝试 3：括号平衡匹配，抓第一个完整 JSON 对象
    start = text.find("{")
    if start != -1:
        depth = 0
        for i in range(start, len(text)):
            ch = text[i]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        obj = json.loads(candidate)
                        return obj if isinstance(obj, dict) else None
                    except (json.JSONDecodeError, ValueError):
                        break
    return None


# ====================================================================
# 策略二：规则拆解（关键词驱动，完全离线）
# ====================================================================
def _rule_parse(instruction: str, lookup: dict) -> dict:
    """基于关键词的规则拆解。

    设计思路（产品逻辑）：
      不同动词/名词触发不同的"技能片段"，再按"感知->移动->操作->收尾"
      的合理顺序拼装成完整步骤序列。规则可解释、可离线、零成本，
      适合作为 LLM 的对照基线（strategy 对比页会用到）。
    """
    text = instruction or ""
    task_type = _classify_task_type(text)

    steps: list[dict] = []

    # —— 1. 感知阶段：几乎所有任务都先扫描/识别环境 ——
    steps.append({"skill_code": "Scan", "params": {"area": "工作区"}, "description": "扫描工作区域，建立环境感知"})

    # 颜色相关 -> 颜色判别
    if any(c in text for c in ["红", "蓝", "绿", "黄", "黑", "白", "颜色"]):
        steps.append({"skill_code": "CheckColor", "params": {"object": "目标物体"}, "description": "判别物体颜色"})

    # 识别 + 定位目标
    steps.append({"skill_code": "Recognize", "params": {"target": "目标物体"}, "description": "识别目标物体类别"})
    steps.append({"skill_code": "Locate", "params": {"object": "目标物体"}, "description": "定位目标物体坐标"})

    # —— 2. 任务专属逻辑 ——
    if task_type == "巡检":
        # 巡检类：路径规划 + 巡检 + 通知
        steps.append({"skill_code": "Navigate", "params": {"from": "起点", "to": "巡检区", "avoid": "有人区域"}, "description": "规划避障巡检路径"})
        steps.append({"skill_code": "Patrol", "params": {"route": "仓库巡检路线"}, "description": "按路线执行巡检"})
        steps.append({"skill_code": "Notify", "params": {"message": "巡检完成"}, "description": "发送巡检完成通知"})
    elif task_type == "排序":
        # 排序类：测量 + 比较 + 排序
        steps.append({"skill_code": "Measure", "params": {"object": "盒子", "attr": "尺寸"}, "description": "测量各物体尺寸"})
        steps.append({"skill_code": "Compare", "params": {"a": "物体A", "b": "物体B"}, "description": "两两比较大小"})
        steps.append({"skill_code": "Sort", "params": {"items": "盒子集合", "order": "从大到小"}, "description": "按尺寸排序"})
    elif task_type == "分拣":
        # 分拣类：循环 + 筛选 + 抓取 + 放置
        steps.append({"skill_code": "Loop", "params": {"collection": "待分拣物体"}, "description": "遍历所有待分拣物体"})
        steps.append({"skill_code": "Filter", "params": {"items": "物体集合", "criteria": "按颜色"}, "description": "按颜色筛选分组"})
        steps.append({"skill_code": "MoveTo", "params": {"target": "目标物体"}, "description": "移动到物体旁"})
        steps.append({"skill_code": "Grasp", "params": {"object": "目标物体", "force": "适中"}, "description": "抓取物体"})
        steps.append({"skill_code": "Place", "params": {"object": "目标物体", "location": "对应分区"}, "description": "放置到对应分区"})
    elif task_type == "检查":
        # 检查类：循环打开 + 扫描内部 + 条件判断 + 通知
        steps.append({"skill_code": "Loop", "params": {"collection": "所有抽屉"}, "description": "遍历所有抽屉"})
        steps.append({"skill_code": "Open", "params": {"target": "抽屉"}, "description": "逐个打开抽屉"})
        steps.append({"skill_code": "Scan", "params": {"area": "抽屉内部"}, "description": "扫描抽屉内部"})
        steps.append({"skill_code": "If", "params": {"condition": "是否发现目标"}, "description": "判断是否发现目标物"})
        steps.append({"skill_code": "Notify", "params": {"message": "检查结果"}, "description": "上报检查结果"})
    elif task_type == "养护":
        # 养护类：移动 + 倾倒（浇水）+ 打开（开窗）
        steps.append({"skill_code": "MoveTo", "params": {"target": "植物"}, "description": "移动到植物旁"})
        if "浇水" in text or "水" in text:
            steps.append({"skill_code": "Pour", "params": {"container": "水壶", "target": "植物"}, "description": "为植物浇水"})
        if "开窗" in text or "通风" in text:
            steps.append({"skill_code": "MoveTo", "params": {"target": "窗户"}, "description": "移动到窗户旁"})
            steps.append({"skill_code": "Open", "params": {"target": "窗户"}, "description": "打开窗户通风"})
    elif task_type == "整理":
        # 整理类：循环 + 抓取 + 放置（到收纳盒）+ 可选擦拭
        steps.append({"skill_code": "Loop", "params": {"collection": "桌面物品"}, "description": "遍历桌面物品"})
        steps.append({"skill_code": "MoveTo", "params": {"target": "物品"}, "description": "移动到物品旁"})
        steps.append({"skill_code": "Grasp", "params": {"object": "物品", "force": "适中"}, "description": "抓取物品"})
        steps.append({"skill_code": "Place", "params": {"object": "物品", "location": "收纳盒"}, "description": "放入收纳盒"})
        if "擦" in text or "清洁" in text:
            steps.append({"skill_code": "Wipe", "params": {"area": "桌面"}, "description": "擦拭桌面"})
    else:
        # 取送类（默认）：移动 + 抓取 + 移动 + 放置
        steps.append({"skill_code": "MoveTo", "params": {"target": "目标物体"}, "description": "移动到物体旁"})
        steps.append({"skill_code": "Grasp", "params": {"object": "目标物体", "force": "适中"}, "description": "抓取目标物体"})
        steps.append({"skill_code": "MoveTo", "params": {"target": "目标位置"}, "description": "移动到目标位置"})
        steps.append({"skill_code": "Place", "params": {"object": "目标物体", "location": "目标位置"}, "description": "放置到目标位置"})

    # —— 3. 易碎/轻放等约束触发"轻放"提示，已在 constraints 体现 ——
    constraints = ["不得碰倒其它物品"]
    if any(k in text for k in ["轻", "易碎", "小心"]):
        constraints.append("轻拿轻放，控制抓取力度")
    else:
        constraints.append("轻拿轻放")

    # —— 4. 收尾：完成通知 ——
    steps.append({"skill_code": "Notify", "params": {"message": "任务完成"}, "description": "发送任务完成通知"})

    return {
        "task_type": task_type,
        "goal": f"完成指令：{instruction}",
        "constraints": constraints,
        "steps": steps,
        "exception_handling": [
            "若未识别到目标物体则请求人工确认",
            "抓取失败自动重试2次",
            "遇到障碍物则重新规划路径",
        ],
    }
