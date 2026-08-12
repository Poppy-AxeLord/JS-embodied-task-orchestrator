"""
数据看板 API 路由（第 2 组）。

本文件把分析与建议的“计算”全部委托给服务层，路由层只做转发，
保证“数据看板”各端点的返回形状与计算口径单一来源（services.analytics / services.recommendation）。

端点（前缀 /api 由 main.py 统一挂载，本文件不带 /api）：
- GET /dashboard/overview         → 概览卡片 + 趋势 + 指标体系
- GET /dashboard/failures         → 失败 Top 原因 + 5 类占比饼 + 分类趋势
- GET /dashboard/tasks-analysis   → 高频任务 / 类型成功率 / 难度分布 / 高频修正技能
- GET /dashboard/strategy-compare → 策略成功率 / 耗时 / 雷达
- GET /dashboard/suggestions      → 优化建议列表（数据闭环输出）

返回形状严格遵守 SPEC §8，不在路由层重塑数据。
"""

from fastapi import APIRouter
from typing import Any

# 分析服务：纯 SQL + Python 聚合，直接产出 §8 对应形状。
from services import analytics
# 推荐服务：基于 analytics 结果生成可执行的优化建议。
from services import recommendation

# 导出名必须为 router，供 main.py 挂载。
router = APIRouter()


# ----------------------------------------------------------------------------
# GET /dashboard/overview
# ----------------------------------------------------------------------------
@router.get("/dashboard/overview")
def get_overview() -> dict[str, Any]:
    """
    数据看板总览。

    返回（SPEC §8）：
    {
      "cards":   {"total_tasks","success_rate"(0-1),"avg_duration_ms","satisfaction"(0-5)},
      "trend":   {"dates":["MM-DD"...],"task_counts":[Int...],"success_rates":[Float...]},
      "metrics": {"polaris":{...},"process":[...],"result":[...]}
    }

    产品含义：
    - cards 是 4 张核心指标卡的数据来源（总任务数 / 总成功率 / 平均时长 / 满意度）。
    - trend 是近 30 天“任务量柱 + 成功率折线”双 Y 轴趋势图的数据。
    - metrics 是分层指标体系（北极星 / 过程 / 结果），用于指标体系展示区。
    计算细节全部在 analytics.overview() 内完成，本层不做任何加工。
    """
    return analytics.overview()


# ----------------------------------------------------------------------------
# GET /dashboard/failures
# ----------------------------------------------------------------------------
@router.get("/dashboard/failures")
def get_failures() -> dict[str, Any]:
    """
    失败分析。

    返回（SPEC §8）：
    {
      "top_reasons":   [{"reason","count"}... 最多10],
      "category_pie":  [{"category","count","color"}... 5类],
      "category_trend":{"dates":["MM-DD"...],"series":[{"category","data":[Int...]}... 5类]}
    }

    产品含义：
    - top_reasons：最高频的失败原因文字，定位“最该先修的问题”。
    - category_pie：5 类失败（感知/理解/规划/执行/环境）占比，颜色取自 §5 统一配色。
    - category_trend：5 类失败随时间的变化，观察治理是否见效。
    """
    return analytics.failures()


# ----------------------------------------------------------------------------
# GET /dashboard/tasks-analysis
# ----------------------------------------------------------------------------
@router.get("/dashboard/tasks-analysis")
def get_tasks_analysis() -> dict[str, Any]:
    """
    任务维度分析。

    返回（SPEC §8）：
    {
      "top_tasks":          [{"instruction","count","success_rate"}... 最多20],
      "type_success":       [{"task_type","total","success_rate"}...],
      "difficulty_dist":    [{"difficulty","count"}...],
      "most_edited_skills": [{"skill_name","edit_count"}...]
    }

    产品含义：
    - top_tasks：高频指令及其成功率，识别“高频但低成功率”的重点场景。
    - type_success：各任务类型（整理/分拣/取送/巡检/养护/排序/检查）成功率。
    - difficulty_dist：难度分布（简单/中等/困难）。
    - most_edited_skills：被人工修正最多的技能，反映拆解模板薄弱点。
    """
    return analytics.tasks_analysis()


# ----------------------------------------------------------------------------
# GET /dashboard/strategy-compare
# ----------------------------------------------------------------------------
@router.get("/dashboard/strategy-compare")
def get_strategy_compare() -> dict[str, Any]:
    """
    策略对比（llm vs rule）的聚合分析。

    返回（SPEC §8）：
    {
      "success":  [{"strategy","success_rate"}...],
      "duration": [{"strategy","avg_duration_ms"}...],
      "radar":    {"indicators":[{"name","max"}...],
                   "series":[{"strategy","data":[Num...]}...]}
    }

    产品含义：
    - success / duration：两策略的成功率与平均耗时对比（柱状）。
    - radar：多维综合对比（成功率、速度、稳定性、步骤精简度、满意度），
      帮助在“快/稳/准”之间做策略选型。
    """
    return analytics.strategy_compare()


# ----------------------------------------------------------------------------
# GET /dashboard/suggestions
# ----------------------------------------------------------------------------
@router.get("/dashboard/suggestions")
def get_suggestions() -> list[dict[str, Any]]:
    """
    优化建议列表（数据闭环的“反哺”输出）。

    返回（SPEC §8）：
    [{"title","detail","priority":"高"|"中"|"低","evidence","metric"}]

    产品含义：
    - 这是“越用越好”飞轮的可见落点：系统根据真实数据（失败占比、修正率、满意度等）
      自动产出 3~6 条具体、可执行、带数据支撑的优化建议（如“感知失败占比 35%，建议
      补充遮挡场景数据”），并标注优先级、证据与关联指标。
    - 计算逻辑在 recommendation.generate_suggestions() 内完成。
    """
    return recommendation.generate_suggestions()
