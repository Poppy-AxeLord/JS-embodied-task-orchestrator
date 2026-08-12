"""
数据分析服务（analytics）
========================

本模块是数据闭环里的"分析大脑"：纯 SQL + Python 聚合 tasks / task_steps 两张表，
产出数据看板（Dashboard）所需的四组数据，分别对应 SPEC §8 的四个接口：

    overview()         -> /api/dashboard/overview
    failures()         -> /api/dashboard/failures
    tasks_analysis()   -> /api/dashboard/tasks-analysis
    strategy_compare() -> /api/dashboard/strategy-compare

设计原则：
- 严格遵守 SPEC §8 定义的返回"形状"（字段名、嵌套结构），前端 ECharts 直接消费，不得自行发明字段。
- 指标体系遵循 SPEC §7（北极星 / 过程 / 结果 三层）。
- 失败分类配色遵循 SPEC §5（5 类，固定颜色）。
- 趋势类数据：按"最近 30 天"逐日分组，**缺失的日期要补 0**，保证折线/柱状连续不断点。
- 不引入 numpy/pandas，全部用标准库 + 列表推导完成聚合，Apple Silicon 零编译依赖。
- 读 tasks 表里的 JSON 字段（如 steps）一律 json.loads。
"""

import json
from datetime import datetime, timedelta

from database import query_all, query_one

# 失败分类配色表（SPEC §5）统一收敛到 constants（单一事实源），
# 保证看板配色与 executor / data_loop / 前端全链路一致。此处沿用原有变量名，
# 下方聚合逻辑无需改动。
from services.constants import (
    FAILURE_CATEGORIES,
    CATEGORY_COLOR as _CATEGORY_COLOR,
)

# 趋势统计的天数窗口（最近 30 天）
TREND_DAYS = 30


# ---------------------------------------------------------------------------
# 通用辅助函数
# ---------------------------------------------------------------------------
def _recent_date_keys(days: int = TREND_DAYS):
    """
    生成最近 N 天的日期序列，返回 (full_dates, short_dates)：
      - full_dates：["YYYY-MM-DD", ...] 用于和库里 created_at 前 10 位比对；
      - short_dates：["MM-DD", ...] 用于前端展示（SPEC §8 trend.dates 为 "MM-DD"）。
    顺序为从早到晚（最后一个是今天）。这是"缺失日期补 0"的基准轴。
    """
    today = datetime.now().date()
    full_dates = []
    short_dates = []
    for i in range(days - 1, -1, -1):
        d = today - timedelta(days=i)
        full_dates.append(d.isoformat())          # YYYY-MM-DD
        short_dates.append(d.strftime("%m-%d"))   # MM-DD
    return full_dates, short_dates


def _safe_rate(numerator: int, denominator: int) -> float:
    """安全计算比率（0~1），分母为 0 时返回 0.0，并四舍五入到 4 位小数。"""
    if not denominator:
        return 0.0
    return round(numerator / denominator, 4)


def _round1(x: float) -> float:
    """四舍五入到 1 位小数，便于满意度/均值类指标展示。"""
    return round(float(x or 0), 1)


# ===========================================================================
# 1) overview —— /api/dashboard/overview
# ===========================================================================
def overview() -> dict:
    """
    总览数据：顶部 4 张指标卡 + 近 30 天趋势 + 指标体系（北极星/过程/结果）。

    返回形状严格匹配 SPEC §8：
    {
      "cards": {"total_tasks","success_rate","avg_duration_ms","satisfaction"},
      "trend": {"dates":[...],"task_counts":[...],"success_rates":[...]},
      "metrics": {"polaris":{...},"process":[...],"result":[...]}
    }
    """
    # ---------- 4 张指标卡 ----------
    # 总任务数、成功数、平均耗时（成功失败都计入）、满意度（rating 均值）
    row = query_one(
        """
        SELECT
            COUNT(*)                                AS total_tasks,
            COALESCE(SUM(success), 0)               AS success_cnt,
            COALESCE(AVG(total_duration_ms), 0)     AS avg_duration_ms
        FROM tasks
        """,
        (),
    )
    total_tasks = int(row["total_tasks"]) if row else 0
    success_cnt = int(row["success_cnt"]) if row else 0
    avg_duration_ms = int(round(row["avg_duration_ms"])) if row and row["avg_duration_ms"] else 0
    success_rate = _safe_rate(success_cnt, total_tasks)

    # 满意度：只对有 rating 的任务求均值（0~5）
    sat_row = query_one(
        "SELECT AVG(rating) AS avg_rating FROM tasks WHERE rating IS NOT NULL",
        (),
    )
    satisfaction = _round1(sat_row["avg_rating"]) if sat_row and sat_row["avg_rating"] is not None else 0.0

    cards = {
        "total_tasks": total_tasks,
        "success_rate": success_rate,        # 0~1
        "avg_duration_ms": avg_duration_ms,  # 毫秒
        "satisfaction": satisfaction,        # 0~5
    }

    # ---------- 近 30 天趋势（缺失日期补 0）----------
    full_dates, short_dates = _recent_date_keys(TREND_DAYS)
    # 以 created_at 的前 10 位（YYYY-MM-DD）分组，统计每日任务量与成功数
    trend_rows = query_all(
        """
        SELECT substr(created_at, 1, 10) AS day,
               COUNT(*)                  AS cnt,
               COALESCE(SUM(success), 0) AS succ
        FROM tasks
        WHERE substr(created_at, 1, 10) >= ?
        GROUP BY day
        """,
        (full_dates[0],),
    )
    # 把查询结果落到一个 dict，方便按基准轴补 0
    day_map = {r["day"]: (int(r["cnt"]), int(r["succ"])) for r in trend_rows}
    task_counts = []
    success_rates = []
    for d in full_dates:
        cnt, succ = day_map.get(d, (0, 0))
        task_counts.append(cnt)
        success_rates.append(_safe_rate(succ, cnt))

    trend = {
        "dates": short_dates,
        "task_counts": task_counts,
        "success_rates": success_rates,
    }

    # ---------- 指标体系（SPEC §7）----------
    # 过程指标需要的几个聚合量
    proc_row = query_one(
        """
        SELECT
            COALESCE(AVG(step_count), 0)        AS avg_steps,
            COALESCE(AVG(retry_count), 0)       AS avg_retry,
            COALESCE(SUM(needs_review), 0)      AS hitl_cnt,
            COALESCE(AVG(total_duration_ms), 0) AS avg_dur
        FROM tasks
        """,
        (),
    )
    avg_steps = round(proc_row["avg_steps"], 1) if proc_row else 0.0
    avg_retry = round(proc_row["avg_retry"], 2) if proc_row else 0.0
    hitl_cnt = int(proc_row["hitl_cnt"]) if proc_row else 0
    hitl_rate = _safe_rate(hitl_cnt, total_tasks)  # 人工介入率
    avg_dur_s = round((proc_row["avg_dur"] or 0) / 1000.0, 1) if proc_row else 0.0

    # 拆解准确率：近似 = 1 - 理解失败占比（SPEC §7 给出的口径）
    und_row = query_one(
        "SELECT COUNT(*) AS c FROM tasks WHERE failure_category = ?",
        ("理解失败",),
    )
    understanding_cnt = int(und_row["c"]) if und_row else 0
    parse_accuracy = round(1.0 - _safe_rate(understanding_cnt, total_tasks), 4)

    # 结果指标：优质样本数、闭环优化条数（建议条数，惰性引入避免循环依赖）
    golden_row = query_one(
        "SELECT COALESCE(SUM(is_golden), 0) AS g FROM tasks", ()
    )
    golden_cnt = int(golden_row["g"]) if golden_row else 0
    # 闭环优化条数：调用 recommendation 生成的建议条数。
    # 这里在函数内部 import，避免模块级循环引用（recommendation 依赖 analytics）。
    try:
        from services.recommendation import generate_suggestions
        suggestion_cnt = len(generate_suggestions())
    except Exception:
        # 容错：建议生成不应阻塞看板总览
        suggestion_cnt = 0

    metrics = {
        # 北极星指标：任务成功率（百分比）
        "polaris": {
            "name": "任务成功率",
            "value": round(success_rate * 100, 1),
            "unit": "%",
        },
        # 过程指标
        "process": [
            {"name": "拆解准确率", "value": round(parse_accuracy * 100, 1), "unit": "%"},
            {"name": "平均步骤数", "value": avg_steps, "unit": "步"},
            {"name": "平均重试次数", "value": avg_retry, "unit": "次"},
            {"name": "人工介入率", "value": round(hitl_rate * 100, 1), "unit": "%"},
            {"name": "平均执行时长", "value": avg_dur_s, "unit": "秒"},
        ],
        # 结果指标
        "result": [
            {"name": "用户满意度", "value": satisfaction, "unit": "分"},
            {"name": "优质样本积累", "value": golden_cnt, "unit": "条"},
            {"name": "闭环优化条数", "value": suggestion_cnt, "unit": "条"},
        ],
    }

    return {"cards": cards, "trend": trend, "metrics": metrics}


# ===========================================================================
# 2) failures —— /api/dashboard/failures
# ===========================================================================
def failures() -> dict:
    """
    失败分析数据：失败原因 Top10 + 5 类占比饼图 + 近 30 天分类趋势。

    返回形状严格匹配 SPEC §8：
    {
      "top_reasons":[{"reason","count"}... 最多10],
      "category_pie":[{"category","count","color"}... 5类],
      "category_trend":{"dates":[...],"series":[{"category","data":[...]}... 5类]}
    }
    """
    # ---------- 失败原因 Top10（按 failure_reason 文本聚合）----------
    reason_rows = query_all(
        """
        SELECT failure_reason AS reason, COUNT(*) AS count
        FROM tasks
        WHERE success = 0 AND failure_reason IS NOT NULL AND failure_reason <> ''
        GROUP BY failure_reason
        ORDER BY count DESC
        LIMIT 10
        """,
        (),
    )
    top_reasons = [{"reason": r["reason"], "count": int(r["count"])} for r in reason_rows]

    # ---------- 5 类失败占比饼图（固定 5 类，无数据补 0，配色固定）----------
    cat_rows = query_all(
        """
        SELECT failure_category AS category, COUNT(*) AS count
        FROM tasks
        WHERE success = 0 AND failure_category IS NOT NULL
        GROUP BY failure_category
        """,
        (),
    )
    cat_count_map = {r["category"]: int(r["count"]) for r in cat_rows}
    category_pie = []
    for c in FAILURE_CATEGORIES:
        name = c["name"]
        category_pie.append(
            {
                "category": name,
                "count": cat_count_map.get(name, 0),
                "color": c["color"],
            }
        )

    # ---------- 近 30 天分类趋势（5 条 series，每条按基准轴补 0）----------
    full_dates, short_dates = _recent_date_keys(TREND_DAYS)
    trend_rows = query_all(
        """
        SELECT substr(created_at, 1, 10) AS day,
               failure_category          AS category,
               COUNT(*)                  AS count
        FROM tasks
        WHERE success = 0
          AND failure_category IS NOT NULL
          AND substr(created_at, 1, 10) >= ?
        GROUP BY day, category
        """,
        (full_dates[0],),
    )
    # 组织成 {category: {day: count}} 便于按轴补 0
    nested = {c["name"]: {} for c in FAILURE_CATEGORIES}
    for r in trend_rows:
        cat = r["category"]
        if cat in nested:
            nested[cat][r["day"]] = int(r["count"])

    series = []
    for c in FAILURE_CATEGORIES:
        name = c["name"]
        day_counts = nested[name]
        data = [day_counts.get(d, 0) for d in full_dates]  # 缺失日期补 0
        series.append({"category": name, "data": data})

    category_trend = {"dates": short_dates, "series": series}

    return {
        "top_reasons": top_reasons,
        "category_pie": category_pie,
        "category_trend": category_trend,
    }


# ===========================================================================
# 3) tasks_analysis —— /api/dashboard/tasks-analysis
# ===========================================================================
def tasks_analysis() -> dict:
    """
    任务分析数据：高频指令 Top20 + 各类型成功率 + 难度分布 + 最常被修正技能。

    返回形状严格匹配 SPEC §8：
    {
      "top_tasks":[{"instruction","count","success_rate"}... 最多20],
      "type_success":[{"task_type","total","success_rate"}...],
      "difficulty_dist":[{"difficulty","count"}...],
      "most_edited_skills":[{"skill_name","edit_count"}...]
    }
    """
    # ---------- 高频指令 Top20（同一指令聚合，并算其成功率）----------
    top_rows = query_all(
        """
        SELECT instruction,
               COUNT(*)                  AS count,
               COALESCE(SUM(success), 0) AS succ
        FROM tasks
        GROUP BY instruction
        ORDER BY count DESC
        LIMIT 20
        """,
        (),
    )
    top_tasks = [
        {
            "instruction": r["instruction"],
            "count": int(r["count"]),
            "success_rate": _safe_rate(int(r["succ"]), int(r["count"])),
        }
        for r in top_rows
    ]

    # ---------- 各 task_type 的成功率 ----------
    type_rows = query_all(
        """
        SELECT task_type,
               COUNT(*)                  AS total,
               COALESCE(SUM(success), 0) AS succ
        FROM tasks
        WHERE task_type IS NOT NULL AND task_type <> ''
        GROUP BY task_type
        ORDER BY total DESC
        """,
        (),
    )
    type_success = [
        {
            "task_type": r["task_type"],
            "total": int(r["total"]),
            "success_rate": _safe_rate(int(r["succ"]), int(r["total"])),
        }
        for r in type_rows
    ]

    # ---------- 难度分布 ----------
    # 难度并非 tasks 表直接字段，而是来自示例指令的 difficulty（见 SPEC §6）。
    # 这里通过"指令文本 -> 难度"映射，把库里任务归类到难度桶；映射不到的归为"未知"。
    difficulty_map = _load_difficulty_map()
    diff_rows = query_all("SELECT instruction FROM tasks", ())
    diff_counter = {}
    for r in diff_rows:
        diff = difficulty_map.get(r["instruction"], "未知")
        diff_counter[diff] = diff_counter.get(diff, 0) + 1
    # 固定难度顺序，便于前端饼图色序稳定；未知放最后
    order = ["简单", "中等", "困难", "未知"]
    difficulty_dist = [
        {"difficulty": d, "count": diff_counter[d]}
        for d in order
        if diff_counter.get(d)
    ]

    # ---------- 最常被"修正"的技能 ----------
    # 业务含义：被人工修正越多的技能，说明系统在该技能上越薄弱，最值得优化。
    # 数据来源：feedback.corrected_steps（人工修正后的步骤）。统计每个 skill_name 出现次数。
    most_edited_skills = _count_edited_skills()

    return {
        "top_tasks": top_tasks,
        "type_success": type_success,
        "difficulty_dist": difficulty_dist,
        "most_edited_skills": most_edited_skills,
    }


def _load_difficulty_map() -> dict:
    """
    构建"指令文本 -> 难度"的映射，来自 demo_data.json 的 examples 字段（SPEC §6）。

    产品逻辑：难度是分析任务画像的重要维度（困难任务失败率更高），但它不是 tasks 表字段，
    所以从预置示例里取。读取失败时返回空映射，调用方会把任务归为"未知"，不影响其它分析。
    """
    import os

    # demo_data.json 位于 backend/data/ 下；本文件在 backend/services/ 下
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(base_dir, "data", "demo_data.json")
    mapping = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for ex in data.get("examples", []) or []:
            ins = ex.get("instruction")
            diff = ex.get("difficulty")
            if ins and diff:
                mapping[ins] = diff
    except Exception:
        # 文件缺失或格式异常时静默降级
        pass
    return mapping


def _count_edited_skills() -> list:
    """
    统计被人工修正最多的技能（来自 feedback.corrected_steps）。

    返回 [{"skill_name","edit_count"}...]，按 edit_count 降序，最多 10 条。
    若 feedback 表暂无修正数据，返回空列表（前端图表自然为空，不报错）。
    """
    counter = {}
    try:
        rows = query_all(
            "SELECT corrected_steps FROM feedback WHERE corrected_steps IS NOT NULL AND corrected_steps <> ''",
            (),
        )
    except Exception:
        return []
    for r in rows:
        raw = r["corrected_steps"]
        try:
            steps = json.loads(raw)  # JSON 字段必须 json.loads
        except (TypeError, json.JSONDecodeError):
            continue
        if not isinstance(steps, list):
            continue
        for st in steps:
            name = (st or {}).get("skill_name")
            if name:
                counter[name] = counter.get(name, 0) + 1

    ranked = sorted(counter.items(), key=lambda kv: kv[1], reverse=True)[:10]
    return [{"skill_name": name, "edit_count": cnt} for name, cnt in ranked]


# ===========================================================================
# 4) strategy_compare —— /api/dashboard/strategy-compare
# ===========================================================================
def strategy_compare() -> dict:
    """
    策略对比数据：llm vs rule 两种拆解策略的成功率、平均耗时、多维雷达。

    返回形状严格匹配 SPEC §8：
    {
      "success":[{"strategy","success_rate"}...],
      "duration":[{"strategy","avg_duration_ms"}...],
      "radar":{"indicators":[{"name","max"}...],"series":[{"strategy","data":[...]}...]}
    }
    radar 维度（SPEC §8 建议）：成功率、速度（耗时反向归一）、稳定性（低重试）、
    步骤精简度、满意度。每个维度归一化到 0~100，便于雷达图对比。
    """
    # 固定对比两种策略，保证返回顺序稳定
    strategies = ["llm", "rule"]

    # 一次性把两种策略的聚合量查出来
    stat_rows = query_all(
        """
        SELECT strategy,
               COUNT(*)                            AS total,
               COALESCE(SUM(success), 0)           AS succ,
               COALESCE(AVG(total_duration_ms), 0) AS avg_dur,
               COALESCE(AVG(retry_count), 0)       AS avg_retry,
               COALESCE(AVG(step_count), 0)        AS avg_steps,
               AVG(rating)                         AS avg_rating
        FROM tasks
        WHERE strategy IS NOT NULL
        GROUP BY strategy
        """,
        (),
    )
    stat = {r["strategy"]: r for r in stat_rows}

    # 准备 success / duration 两个列表
    success = []
    duration = []
    for s in strategies:
        r = stat.get(s)
        if r:
            total = int(r["total"])
            success.append({"strategy": s, "success_rate": _safe_rate(int(r["succ"]), total)})
            duration.append({"strategy": s, "avg_duration_ms": int(round(r["avg_dur"]))})
        else:
            # 该策略暂无数据，补 0，保证两条都在
            success.append({"strategy": s, "success_rate": 0.0})
            duration.append({"strategy": s, "avg_duration_ms": 0})

    # ---------- 雷达图：5 个维度，统一归一到 0~100 ----------
    # 归一所需的参考极值（取两策略中的最大值，避免某维度恒为满分）
    max_dur = max((stat[s]["avg_dur"] for s in strategies if s in stat), default=0) or 1
    max_retry = max((stat[s]["avg_retry"] for s in strategies if s in stat), default=0) or 1
    max_steps = max((stat[s]["avg_steps"] for s in strategies if s in stat), default=0) or 1

    indicators = [
        {"name": "成功率", "max": 100},
        {"name": "速度", "max": 100},
        {"name": "稳定性", "max": 100},
        {"name": "步骤精简度", "max": 100},
        {"name": "满意度", "max": 100},
    ]

    radar_series = []
    for s in strategies:
        r = stat.get(s)
        if r:
            total = int(r["total"])
            succ_rate = _safe_rate(int(r["succ"]), total)          # 0~1
            # 速度：耗时越短越好 -> 反向归一（耗时占最大耗时比例越小，得分越高）
            speed_score = (1.0 - (r["avg_dur"] / max_dur)) * 100
            # 稳定性：重试越少越好 -> 反向归一
            stability_score = (1.0 - (r["avg_retry"] / max_retry)) * 100
            # 步骤精简度：步骤越少越精简 -> 反向归一
            concise_score = (1.0 - (r["avg_steps"] / max_steps)) * 100
            # 满意度：rating 0~5 -> 0~100
            sat = r["avg_rating"] if r["avg_rating"] is not None else 0
            sat_score = (sat / 5.0) * 100
            data = [
                round(succ_rate * 100, 1),
                round(max(0.0, speed_score), 1),
                round(max(0.0, stability_score), 1),
                round(max(0.0, concise_score), 1),
                round(sat_score, 1),
            ]
        else:
            data = [0, 0, 0, 0, 0]
        radar_series.append({"strategy": s, "data": data})

    radar = {"indicators": indicators, "series": radar_series}

    return {"success": success, "duration": duration, "radar": radar}
