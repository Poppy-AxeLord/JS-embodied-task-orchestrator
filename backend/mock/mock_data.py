# -*- coding: utf-8 -*-
"""
mock_data.py —— 演示数据播种器（让数据看板开箱即丰富）。

核心函数 seed_demo(conn)：
    当 tasks 表为空时，用 random.seed(42) **确定性**生成约 150 条历史任务，
    并为每条任务生成对应的 task_steps 行，以及少量 feedback。
    覆盖最近 30 天、7 种 task_type、两种 strategy(llm/rule)，
    总体成功率约 72%~78%，失败分布于 SPEC §5 的 5 类，部分任务含 1-5 评分，
    8~12 条 needs_review=1（待人工介入），若干 is_golden=1（优质样本）。

设计原则：
    - 确定性：固定随机种子，保证每次播种结果一致，便于演示与对照。
    - 真实感：耗时/重试/失败原因/评分等都遵循贴近真实业务的分布规律。
    - 自洽：tasks 与 task_steps、feedback 数据互相对应，历史详情可完整回放。

依赖：仅标准库（random / json / datetime / sqlite3 经由传入的 conn）。Apple Silicon 友好。
"""

import json
import random
from datetime import datetime, timedelta

# 技能元数据（英文码→中文名/分类）与「分类基准耗时」统一收敛到 services/constants.py
# （单一事实源），与 demo_data.json / mock_llm 保持一致，避免技能改名/新增时多处遗漏。
from services.constants import SKILL_META, CATEGORY_BASE_MS


# ============================================================================
# 一、基础配置与字典（与 SPEC 严格对齐）
# ============================================================================

# 7 种任务类型（SPEC §2 task_type）
TASK_TYPES = ["整理", "分拣", "取送", "巡检", "养护", "排序", "检查"]

# 两种拆解/执行策略（SPEC：strategy ∈ {"llm","rule"}）
STRATEGIES = ["llm", "rule"]

# 难度（SPEC §6 difficulty）。难度影响失败率与步骤数。
DIFFICULTIES = ["简单", "中等", "困难"]

# 5 类失败分类——存中文（SPEC §5 强调 tasks.failure_category 存中文）。
# 每类附带一组「具体失败原因文字」，使 Top 原因图表更真实可读。
FAILURE_CATEGORIES = {
    "感知失败": [
        "目标物体被遮挡，未能正确识别",
        "光照不足导致颜色判别错误",
        "小目标（钥匙）识别置信度过低",
        "相似物体混淆，识别到错误目标",
        "反光表面造成定位坐标偏差",
    ],
    "理解失败": [
        "指令存在歧义，目标位置理解偏差",
        "复合指令的先后顺序理解错误",
        "未能正确理解“轻轻”等模糊约束",
        "代词指代不清导致目标对象错误",
    ],
    "规划失败": [
        "步骤顺序不合理，先放置后抓取",
        "未规划避障路径，撞上障碍物",
        "缺少必要的前置感知步骤",
        "排序依据选取错误导致结果不对",
    ],
    "执行失败": [
        "抓取力度不足，物体中途滑落",
        "放置对位偏差，物体跌落上层货架",
        "倾倒过量导致液体溢出",
        "抓取易碎品力度过大造成损坏",
        "电量不足，动作执行中断",
    ],
    "环境异常": [
        "巡检途中有人员闯入禁行区",
        "目标物体被移动，到位后已不在原处",
        "通道被临时堆放的杂物阻断",
        "抽屉被锁住，无法打开检查",
    ],
}

# 每种任务类型对应的一批「典型指令」。
# 既包含 SPEC §6 的预置示例，也补充同类常见指令，让“高频任务 Top”图表更丰富。
TASK_INSTRUCTIONS = {
    "整理": [
        "先整理桌面，再去厨房拿一瓶水",
        "清理桌面上的书和笔，放到收纳盒里",
        "把散落的玩具收进玩具箱",
        "整理书架，把书按高度摆好",
        "收拾会议桌，清走纸杯和文件",
    ],
    "分拣": [
        "分拣所有蓝色的方块到A区，红色的放到B区",
        "把快递按楼层分拣到不同推车",
        "将回收物分成可回收与不可回收两类",
        "把零件按大小分到三个料盒",
    ],
    "取送": [
        "把红色的杯子放到桌子右边",
        "把易碎品轻轻放到上层货架",
        "找到遥控器，送到客厅沙发上",
        "把文件夹送到前台",
        "去仓库取一箱A4纸送到打印室",
    ],
    "巡检": [
        "帮我规划仓库巡检路线，避开有人的区域",
        "巡检一楼所有消防通道是否畅通",
        "沿货架巡检并记录缺货位置",
    ],
    "养护": [
        "给植物浇水，然后开窗通风",
        "给办公区所有绿植浇一次水",
        "傍晚关闭所有窗户",
    ],
    "排序": [
        "按照从大到小的顺序排列这些盒子",
        "把档案盒按编号从小到大排列",
        "将样品按重量升序摆放",
    ],
    "检查": [
        "检查所有抽屉里有没有钥匙",
        "检查货架上是否有破损包装",
        "核对仓位标签与实物是否一致",
    ],
}

# 每种任务类型「典型的步骤骨架」：技能 code 序列。
# 用于为每条任务生成对应的 task_steps 行，体现该类型的一般执行范式。
# 注意：这些 code 必须全部来自 SPEC §4 技能表。
TYPE_STEP_SKELETON = {
    "整理": ["Scan", "Loop", "Grasp", "Place", "Wipe"],
    "分拣": ["Scan", "Loop", "Recognize", "If", "Grasp", "Place"],
    "取送": ["Recognize", "Locate", "MoveTo", "Grasp", "Navigate", "Place"],
    "巡检": ["Scan", "Navigate", "Patrol", "Notify", "ReturnHome"],
    "养护": ["Locate", "MoveTo", "Grasp", "Pour", "Open"],
    "排序": ["Scan", "Loop", "Measure", "Sort", "Place"],
    "检查": ["Scan", "Loop", "Open", "Recognize", "If", "Notify"],
}

# 技能 code -> (中文名, 分类) 与「分类基准耗时」见文件顶部的
# `from services.constants import SKILL_META, CATEGORY_BASE_MS`（单一事实源）。


# ============================================================================
# 二、辅助函数
# ============================================================================

def _iso(dt):
    """datetime -> SPEC 约定的 ISO8601 字符串（精确到秒）。"""
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


def _difficulty_for(task_type, instruction):
    """根据任务类型/指令推断难度。困难类型与含“避开/检查所有”的指令更难。"""
    if task_type in ("巡检", "检查"):
        # 巡检/检查整体偏难
        return random.choices(DIFFICULTIES, weights=[1, 3, 4])[0]
    if task_type in ("分拣", "排序", "整理"):
        return random.choices(DIFFICULTIES, weights=[2, 5, 2])[0]
    # 取送/养护整体偏简单
    return random.choices(DIFFICULTIES, weights=[5, 3, 1])[0]


def _fail_prob(difficulty):
    """难度 -> 基础失败概率。困难任务失败率更高（呼应 SPEC §9 executor）。"""
    return {"简单": 0.14, "中等": 0.26, "困难": 0.40}[difficulty]


def _build_steps(task_type, will_fail, created_dt):
    """为一条任务生成步骤数据。

    返回 (steps_for_tasks_json, step_rows, step_count, retry_count,
          total_duration_ms, failure_step_index)
    其中：
        steps_for_tasks_json  —— 写入 tasks.steps 字段的 step 对象数组（SPEC §3 形状）。
        step_rows             —— 写入 task_steps 表的逐步记录（最终态）。
        failure_step_index    —— 若任务失败，失败发生在第几步（1 基），否则 None。

    逻辑：
        - 步骤骨架取自 TYPE_STEP_SKELETON；
        - 每步耗时 = 分类基准 * (0.6~1.6) 抖动；
        - 若任务失败：随机选一步为失败步，其后步骤不再执行（不计入最终落库的成功步），
          失败步可能触发 1~2 次重试（计入 retry_count）。
    """
    skeleton = TYPE_STEP_SKELETON[task_type]
    n = len(skeleton)

    # 决定失败步（若失败）。倾向于发生在中后段，更贴近真实。
    failure_step_index = None
    if will_fail:
        failure_step_index = random.randint(max(1, n // 2), n)

    retry_count = 0
    total_duration_ms = 0
    steps_for_tasks_json = []
    step_rows = []

    # 逐步生成；失败步之后的步骤视为未执行，不落 task_steps（更符合真实执行中断语义）。
    last_index = failure_step_index if will_fail else n
    for i, code in enumerate(skeleton[:last_index], start=1):
        name, category = SKILL_META[code]
        base = CATEGORY_BASE_MS.get(category, 800)
        dur = int(base * random.uniform(0.6, 1.6))

        is_fail_step = will_fail and i == failure_step_index
        # 失败步可能先重试 1~2 次再判失败，重试也消耗时间。
        if is_fail_step:
            retries = random.randint(1, 2)
            retry_count += retries
            dur += int(base * 0.5 * retries)  # 重试额外耗时
        total_duration_ms += dur

        # tasks.steps 里的 step 对象（计划态，含描述与预期）
        steps_for_tasks_json.append({
            "index": i,
            "skill_code": code,
            "skill_name": name,
            "category": category,
            "params": _demo_params(code),
            "description": f"{name}（{category}）",
            "expected_result": "完成该步骤",
        })

        # task_steps 行（最终态）
        status = "failed" if is_fail_step else "success"
        error = None
        if is_fail_step:
            error = "该步骤执行失败，已触发重试仍未成功"
        step_rows.append({
            "step_index": i,
            "skill_code": code,
            "skill_name": name,
            "params": _demo_params(code),
            "status": status,
            "duration_ms": dur,
            "error": error,
            "created_at": _iso(created_dt + timedelta(milliseconds=total_duration_ms)),
        })

    step_count = n  # 计划步骤总数按完整骨架计（拆解出的步骤数）
    return (steps_for_tasks_json, step_rows, step_count, retry_count,
            total_duration_ms, failure_step_index)


def _demo_params(code):
    """为某技能生成一组示例参数（仅用于演示展示，不参与真实执行）。"""
    samples = {
        "MoveTo": {"target": "目标位置"},
        "Navigate": {"from": "起点", "to": "终点", "avoid": ["障碍物"]},
        "Rotate": {"angle": 90},
        "Patrol": {"route": ["点A", "点B", "点C"]},
        "ReturnHome": {},
        "Grasp": {"object": "目标物体", "force": 40},
        "Place": {"object": "目标物体", "location": "目标位置"},
        "Push": {"object": "目标物体", "direction": "前"},
        "Pour": {"container": "水壶", "target": "植物"},
        "Open": {"target": "抽屉"},
        "Wipe": {"area": "桌面"},
        "Recognize": {"target": "目标物体"},
        "Locate": {"object": "目标物体"},
        "Measure": {"object": "目标物体", "attr": "尺寸"},
        "Scan": {"area": "目标区域"},
        "CheckColor": {"object": "目标物体"},
        "If": {"condition": "满足条件"},
        "Loop": {"collection": "对象集合"},
        "Compare": {"a": "值1", "b": "值2"},
        "Sort": {"items": "对象集合", "order": "asc"},
        "Filter": {"items": "对象集合", "criteria": "条件"},
        "Wait": {"duration": 1000},
        "Retry": {"max_attempts": 2},
        "Confirm": {"message": "请确认"},
        "Notify": {"message": "任务通知"},
    }
    return samples.get(code, {})


def _pick_failure(task_type):
    """为失败任务挑选一个失败分类与具体原因。

    不同任务类型对失败分类有不同倾向（更真实）：
        巡检/取送 偏 环境异常/执行失败；检查/分拣 偏 感知失败；
        其余 在 5 类间相对均匀。
    返回 (category_cn, reason_text)。
    """
    bias = {
        "巡检": ["环境异常", "环境异常", "规划失败", "感知失败", "执行失败", "理解失败"],
        "取送": ["执行失败", "执行失败", "感知失败", "环境异常", "理解失败", "规划失败"],
        "检查": ["感知失败", "感知失败", "环境异常", "理解失败", "规划失败", "执行失败"],
        "分拣": ["感知失败", "感知失败", "理解失败", "执行失败", "规划失败", "环境异常"],
        "整理": ["执行失败", "感知失败", "理解失败", "规划失败", "环境异常", "执行失败"],
        "排序": ["感知失败", "规划失败", "执行失败", "理解失败", "感知失败", "环境异常"],
        "养护": ["执行失败", "理解失败", "环境异常", "感知失败", "执行失败", "规划失败"],
    }
    pool = bias.get(task_type, list(FAILURE_CATEGORIES.keys()))
    category = random.choice(pool)
    reason = random.choice(FAILURE_CATEGORIES[category])
    return category, reason


# ============================================================================
# 三、主播种函数
# ============================================================================

def seed_demo(conn):
    """若 tasks 表为空，确定性生成约 150 条历史任务及配套数据。

    参数：
        conn —— 已打开的 sqlite3 连接（row_factory 已设为 sqlite3.Row）。
                本函数内部自行 commit。

    生成内容：
        - tasks：约 150 条，覆盖近 30 天、7 类型、2 策略；成功率约 72%~78%；
          失败任务含 failure_category(中文)/failure_reason；部分含 rating；
          8~12 条 needs_review=1；若干 is_golden=1。
        - task_steps：每条任务对应的逐步执行日志（失败任务在失败步中断）。
        - feedback：为部分有评分的任务补充 feedback 行（少量）。

    若表非空则直接返回（幂等，避免重复播种）。
    """
    cur = conn.cursor()

    # 幂等保护：仅在 tasks 表为空时播种。
    existing = cur.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()
    if existing and existing["c"] > 0:
        return

    # 固定随机种子，保证每次生成结果完全一致（便于演示对照）。
    random.seed(42)

    total = 150                 # 目标任务条数
    now = datetime(2026, 6, 30, 18, 0, 0)  # 以一个固定“现在”为基准，保证确定性
    feedback_rows = []          # 暂存待插入的 feedback（task_id 先占位，插完任务再回填）

    # 控制全局成功率落在 72%~78%：目标成功条数 ≈ total * 0.75。
    target_success = int(total * 0.75)
    success_remaining = target_success
    slots_remaining = total

    # 预先决定 needs_review 名额（8~12 条）与 is_golden 名额（若干，取 10~16）。
    needs_review_quota = random.randint(8, 12)
    golden_quota = random.randint(10, 16)

    inserted_task_meta = []  # 记录每条任务的 (task_id, has_rating) 供后续 feedback 使用

    for k in range(total):
        # —— 1) 选类型/指令/策略/难度 ——
        task_type = random.choice(TASK_TYPES)
        instruction = random.choice(TASK_INSTRUCTIONS[task_type])
        strategy = random.choices(STRATEGIES, weights=[3, 2])[0]  # llm 略多于 rule
        difficulty = _difficulty_for(task_type, instruction)

        # —— 2) 判定成功/失败 ——
        # 在“基础失败概率”之上，用剩余配额做轻度纠偏，让总成功率收敛到 ~75%。
        base_fail = _fail_prob(difficulty)
        # rule 策略整体略逊于 llm（演示策略对比时有区分度）
        if strategy == "rule":
            base_fail += 0.05
        # 配额纠偏：若成功名额吃紧则提高失败概率，反之降低。
        expected_success_rate = success_remaining / slots_remaining if slots_remaining else 0
        if expected_success_rate < 0.7:
            base_fail = max(0.05, base_fail - 0.15)
        elif expected_success_rate > 0.85:
            base_fail = min(0.85, base_fail + 0.15)

        will_fail = random.random() < base_fail
        # 末尾兜底：若剩余槽位必须全成功/全失败才能达标，则强制。
        if success_remaining <= 0:
            will_fail = True
        elif success_remaining >= slots_remaining:
            will_fail = False

        success = 0 if will_fail else 1
        if success:
            success_remaining -= 1
        slots_remaining -= 1

        status = "failed" if will_fail else "success"

        # —— 3) 时间：均匀散布在最近 30 天 ——
        days_ago = random.randint(0, 29)
        created_dt = now - timedelta(
            days=days_ago,
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
            seconds=random.randint(0, 59),
        )

        # —— 4) 生成步骤与耗时 ——
        (steps_json, step_rows, step_count, retry_count,
         total_duration_ms, fail_idx) = _build_steps(task_type, will_fail, created_dt)

        # —— 5) 失败分类/原因 ——
        failure_category = None
        failure_reason = None
        if will_fail:
            failure_category, failure_reason = _pick_failure(task_type)

        # —— 6) 评分（部分任务含 1-5）——
        # 约 60% 的任务有评分；成功任务评分偏高，失败任务评分偏低。
        rating = None
        feedback_text = None
        if random.random() < 0.6:
            if success:
                rating = random.choices([3, 4, 5], weights=[2, 4, 5])[0]
            else:
                rating = random.choices([1, 2, 3], weights=[4, 4, 2])[0]
            feedback_text = _rating_comment(rating, success, task_type)

        # —— 7) needs_review / is_golden ——
        needs_review = 0
        is_golden = 0
        # 失败且无评分的任务，按配额标记为待人工介入（呼应 SPEC §9 record_task 规则）。
        if will_fail and rating is None and needs_review_quota > 0:
            # 约 1/2 概率消耗一个名额，避免集中在前面
            if random.random() < 0.5:
                needs_review = 1
                needs_review_quota -= 1
        # 成功且高分（>=5 或 ==4）的任务，按配额沉淀为优质样本。
        if success and rating is not None and rating >= 4 and golden_quota > 0:
            if random.random() < 0.45:
                is_golden = 1
                golden_quota -= 1

        # —— 8) 约束/异常处理（演示用，按类型给通用文案）——
        constraints, exception_handling = _demo_constraints(task_type)

        # —— 9) 写入 tasks ——
        cur.execute(
            """
            INSERT INTO tasks (
                instruction, task_type, strategy, goal, constraints, steps,
                exception_handling, status, success, failure_category, failure_reason,
                total_duration_ms, step_count, retry_count, rating, feedback_text,
                needs_review, is_golden, created_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                instruction, task_type, strategy,
                f"完成「{instruction}」",
                json.dumps(constraints, ensure_ascii=False),
                json.dumps(steps_json, ensure_ascii=False),
                json.dumps(exception_handling, ensure_ascii=False),
                status, success, failure_category, failure_reason,
                total_duration_ms, step_count, retry_count, rating, feedback_text,
                needs_review, is_golden, _iso(created_dt),
            ),
        )
        task_id = cur.lastrowid
        inserted_task_meta.append((task_id, rating is not None))

        # —— 10) 写入 task_steps ——
        for r in step_rows:
            cur.execute(
                """
                INSERT INTO task_steps (
                    task_id, step_index, skill_code, skill_name, params,
                    status, duration_ms, error, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    task_id, r["step_index"], r["skill_code"], r["skill_name"],
                    json.dumps(r["params"], ensure_ascii=False),
                    r["status"], r["duration_ms"], r["error"], r["created_at"],
                ),
            )

        # —— 11) 收集 feedback（为有评分的任务中的一部分生成 feedback 行）——
        # 约一半有评分的任务额外落一条 feedback（演示反馈数据，不强求全覆盖）。
        if rating is not None and random.random() < 0.5:
            corrected = None
            # 优质样本可附“修正后的步骤”（这里直接复用计划步骤，演示用）。
            if is_golden:
                corrected = json.dumps(steps_json, ensure_ascii=False)
            feedback_rows.append((
                task_id, rating, feedback_text or "",
                corrected, _iso(created_dt + timedelta(minutes=2)),
            ))

    # —— 12) 批量写入 feedback ——
    for fb in feedback_rows:
        cur.execute(
            """
            INSERT INTO feedback (task_id, rating, comment, corrected_steps, created_at)
            VALUES (?,?,?,?,?)
            """,
            fb,
        )

    conn.commit()


def _rating_comment(rating, success, task_type):
    """根据评分与成败生成一句中文反馈文案（演示用）。"""
    if rating >= 5:
        return f"{task_type}任务完成得很好，步骤清晰、执行流畅。"
    if rating == 4:
        return f"{task_type}任务整体不错，个别步骤还能更快一点。"
    if rating == 3:
        return f"{task_type}任务基本完成，但过程有些波折。"
    if rating == 2:
        return f"{task_type}任务执行不太理想，希望优化拆解逻辑。"
    return f"{task_type}任务失败了，期望能更准确地理解我的指令。"


def _demo_constraints(task_type):
    """按任务类型返回一组通用的（约束, 异常处理）文案，用于历史数据展示。"""
    mapping = {
        "整理": (["不损坏物品", "保持原有分类"], ["无收纳位则请求人工确认", "抓取失败重试2次"]),
        "分拣": (["分类判别准确", "不混淆类别"], ["置信度低请求人工确认", "无法归类则单独存放"]),
        "取送": (["途中不遗落", "轻拿轻放"], ["未识别目标请求人工确认", "路径受阻重新规划"]),
        "巡检": (["避让人员与障碍", "提高覆盖率"], ["发现人员立即停车重规划", "路径阻断请求人工干预"]),
        "养护": (["操作适量", "不损伤对象"], ["资源不足先补给", "对象异常请求人工确认"]),
        "排序": (["测量准确", "排列均匀"], ["属性接近时复测", "过重请求人工协助"]),
        "检查": (["不遗漏对象", "检查后恢复原状"], ["对象无法访问则跳过记录", "结果不确定请求人工确认"]),
    }
    return mapping.get(task_type, (["规范执行"], ["异常时请求人工确认"]))
