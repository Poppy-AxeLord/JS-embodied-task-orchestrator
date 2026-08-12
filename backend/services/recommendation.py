"""
优化建议服务（recommendation）
==============================

本模块是数据闭环的"输出端"，也是整个数据飞轮真正产生价值的地方：
把 analytics 沉淀出来的分析结果，翻译成**具体、可执行、带数据支撑**的优化建议。

产品逻辑（为什么需要它）：
- 看板上的图表只能"呈现问题"，但管理者真正需要的是"下一步该做什么"。
- 一条好的建议必须满足三点：
    1) 具体可执行——告诉团队"补充哪类数据 / 调整哪个模板 / 优化哪个技能"，而非空泛的"提升质量"；
    2) 带数据支撑——每条建议都配 evidence（如"感知失败占比 35%"），让决策有依据、可追溯；
    3) 分优先级——用 priority(高/中/低) 帮团队排期，把有限的工程资源投到 ROI 最高处。
- 这些建议本身也是"闭环优化条数"这个结果指标的来源（见 SPEC §7）。

实现方式：基于 analytics 的四组聚合结果，按一系列业务规则生成建议，最终裁剪/排序到 3~6 条。
返回每条建议形如：
    {title, detail, priority("高"|"中"|"低"), evidence, metric}
（字段严格匹配 SPEC §8 的 /api/dashboard/suggestions 契约）
"""

from services import analytics


# 优先级排序权重，用于最终排序（高优先在前）
_PRIORITY_WEIGHT = {"高": 3, "中": 2, "低": 1}

# 失败分类 -> 针对性改进动作的话术模板。
# 不同失败大类对应完全不同的改进方向，这是建议"可执行"的关键。
_CATEGORY_ACTION = {
    "感知失败": "补充遮挡、强反光、弱光照等困难场景的感知训练数据，并增加识别前的二次扫描确认步骤",
    "理解失败": "为高频歧义指令补充澄清式追问模板，必要时在拆解前插入 Confirm（人工确认）步骤",
    "规划失败": "复盘这些任务的步骤顺序，沉淀为优质拆解模板，约束规划阶段优先复用已验证流程",
    "执行失败": "为易掉落/易出错的操作类技能（抓取、放置）增加 Retry 重试与力控参数调优",
    "环境异常": "增强动态避障与环境感知，在移动类步骤前插入 Scan 扫描，遇人员干扰自动降速或等待",
}


def _round_pct(rate: float) -> float:
    """把 0~1 的比率转成 1 位小数的百分数（如 0.3567 -> 35.7）。"""
    return round((rate or 0) * 100, 1)


def generate_suggestions() -> list:
    """
    生成 3~6 条优化建议。

    数据来源：analytics 的 overview / failures / tasks_analysis / strategy_compare 四组结果。
    生成逻辑覆盖以下几条规则（每条规则在数据满足条件时产出一条建议）：
      规则 1：占比最高的失败分类 -> 给出针对性改进动作（最核心的一条）。
      规则 2：成功率最低的任务类型/高频指令 -> 提示重点攻坚。
      规则 3：出现频次最高的具体失败原因 -> 直接定位到最痛的单点问题。
      规则 4：人工介入率偏高 -> 提示扩充复核人力 / 优化拆解以降负荷。
      规则 5：两种策略差异明显 -> 建议默认采用更优策略。
      规则 6：被人工修正最多的技能 -> 提示优先优化该技能拆解逻辑。
    最后按优先级排序，裁剪到 [3, 6] 条返回。

    :return: list[{title, detail, priority, evidence, metric}]
    """
    # 一次性取出四组分析结果
    ov = analytics.overview()
    fa = analytics.failures()
    ta = analytics.tasks_analysis()
    sc = analytics.strategy_compare()

    suggestions = []

    total_tasks = ov["cards"]["total_tasks"]
    # 失败总数（用于把"分类计数"换算成占比）
    total_failures = sum(item["count"] for item in fa["category_pie"]) or 0

    # ---------- 规则 1：占比最高的失败分类 ----------
    # 找出 category_pie 里 count 最大的那一类，按占失败总数的比例给建议。
    if total_failures > 0:
        top_cat = max(fa["category_pie"], key=lambda x: x["count"])
        if top_cat["count"] > 0:
            ratio = top_cat["count"] / total_failures  # 占全部失败的比例
            cat_name = top_cat["category"]
            action = _CATEGORY_ACTION.get(cat_name, "针对该失败类型补充对应场景数据并优化处理流程")
            # 占比越高优先级越高
            priority = "高" if ratio >= 0.30 else ("中" if ratio >= 0.18 else "低")
            suggestions.append(
                {
                    "title": f"重点治理「{cat_name}」",
                    "detail": (
                        f"「{cat_name}」是当前占比最高的失败类型，建议优先{action}，"
                        f"预计可显著拉升整体任务成功率。"
                    ),
                    "priority": priority,
                    "evidence": f"{cat_name}占全部失败的 {_round_pct(ratio)}%（{top_cat['count']}/{total_failures} 次）",
                    "metric": "失败分类占比",
                }
            )

    # ---------- 规则 2：成功率最低的任务类型 ----------
    # 只考虑有一定样本量（>=5）的类型，避免被偶发小样本误导。
    eligible_types = [t for t in ta["type_success"] if t["total"] >= 5]
    if eligible_types:
        worst_type = min(eligible_types, key=lambda x: x["success_rate"])
        # 成功率明显偏低（<0.7）才提建议
        if worst_type["success_rate"] < 0.70:
            sr = worst_type["success_rate"]
            priority = "高" if sr < 0.55 else "中"
            suggestions.append(
                {
                    "title": f"攻坚低成功率任务类型「{worst_type['task_type']}」",
                    "detail": (
                        f"「{worst_type['task_type']}」类任务成功率仅 {_round_pct(sr)}%，"
                        f"明显低于平均水平。建议针对该类任务沉淀专用拆解模板、"
                        f"补充对应场景数据，并将失败样本纳入人工复核优先队列。"
                    ),
                    "priority": priority,
                    "evidence": f"「{worst_type['task_type']}」成功率 {_round_pct(sr)}%（样本 {worst_type['total']} 条）",
                    "metric": "任务类型成功率",
                }
            )

    # ---------- 规则 3：频次最高的具体失败原因 ----------
    if fa["top_reasons"]:
        top_reason = fa["top_reasons"][0]
        # 该单一原因占失败总数比例
        reason_ratio = (top_reason["count"] / total_failures) if total_failures else 0
        priority = "高" if reason_ratio >= 0.20 else "中"
        suggestions.append(
            {
                "title": "消除最高频失败原因",
                "detail": (
                    f"失败原因「{top_reason['reason']}」累计出现 {top_reason['count']} 次，"
                    f"是最高频的单点问题。建议针对该原因做专项复盘，"
                    f"在拆解或执行环节加入对应的前置校验与异常处理。"
                ),
                "priority": priority,
                "evidence": f"「{top_reason['reason']}」出现 {top_reason['count']} 次，占失败 {_round_pct(reason_ratio)}%",
                "metric": "失败原因频次",
            }
        )

    # ---------- 规则 4：人工介入率偏高 ----------
    # 从 overview.metrics.process 里取"人工介入率"（单位 %）。
    hitl_item = next((m for m in ov["metrics"]["process"] if m["name"] == "人工介入率"), None)
    if hitl_item and hitl_item["value"] >= 8.0:
        suggestions.append(
            {
                "title": "降低人工介入率，释放复核人力",
                "detail": (
                    f"当前人工介入率为 {hitl_item['value']}%，复核队列压力较大。"
                    f"建议通过沉淀更多优质拆解模板、提升自动拆解准确率来减少需人工介入的任务，"
                    f"同时为高频介入场景配置半自动修正能力。"
                ),
                "priority": "中",
                "evidence": f"人工介入率 {hitl_item['value']}%（全部任务 {total_tasks} 条）",
                "metric": "人工介入率",
            }
        )

    # ---------- 规则 5：两种策略差异明显，建议采用更优策略 ----------
    if len(sc["success"]) == 2:
        better = max(sc["success"], key=lambda x: x["success_rate"])
        worse = min(sc["success"], key=lambda x: x["success_rate"])
        gap = better["success_rate"] - worse["success_rate"]
        # 成功率差距超过 8 个百分点才认为有显著差异
        if gap >= 0.08:
            suggestions.append(
                {
                    "title": f"默认采用「{better['strategy']}」拆解策略",
                    "detail": (
                        f"「{better['strategy']}」策略成功率为 {_round_pct(better['success_rate'])}%，"
                        f"显著高于「{worse['strategy']}」的 {_round_pct(worse['success_rate'])}%。"
                        f"建议在新任务中默认采用前者，并对后者继续观察是否在低延迟场景仍有价值。"
                    ),
                    "priority": "中",
                    "evidence": (
                        f"{better['strategy']} {_round_pct(better['success_rate'])}% vs "
                        f"{worse['strategy']} {_round_pct(worse['success_rate'])}%，差距 {_round_pct(gap)}pp"
                    ),
                    "metric": "策略成功率对比",
                }
            )

    # ---------- 规则 6：被人工修正最多的技能 ----------
    if ta["most_edited_skills"]:
        top_skill = ta["most_edited_skills"][0]
        suggestions.append(
            {
                "title": f"优化最常被修正的技能「{top_skill['skill_name']}」",
                "detail": (
                    f"技能「{top_skill['skill_name']}」在人工复核中被修正 {top_skill['edit_count']} 次，"
                    f"说明系统在该技能的拆解或参数选择上偏差较大。"
                    f"建议复盘其参数默认值与适用场景，并将修正后的样本固化为优质拆解参考。"
                ),
                "priority": "低",
                "evidence": f"「{top_skill['skill_name']}」被人工修正 {top_skill['edit_count']} 次",
                "metric": "技能修正次数",
            }
        )

    # ---------- 兜底：若规则触发太少，补一条通用建议保证不少于 3 条 ----------
    if len(suggestions) < 3:
        sr = ov["cards"]["success_rate"]
        suggestions.append(
            {
                "title": "持续积累优质样本，做厚数据飞轮",
                "detail": (
                    f"当前整体任务成功率为 {_round_pct(sr)}%。建议保持人工复核节奏，"
                    f"持续把修正后的失败样本沉淀为优质样本（golden），"
                    f"反哺拆解模板与模型，让系统在使用中越来越准。"
                ),
                "priority": "低",
                "evidence": f"整体成功率 {_round_pct(sr)}%，累计任务 {total_tasks} 条",
                "metric": "任务成功率",
            }
        )

    # ---------- 排序 + 裁剪到 [3, 6] 条 ----------
    # 按优先级权重降序，权重相同保持插入顺序（稳定排序）。
    suggestions.sort(key=lambda s: _PRIORITY_WEIGHT.get(s["priority"], 0), reverse=True)
    # 上限 6 条，避免信息过载；下限已由兜底规则保证 >=3。
    return suggestions[:6]
