# -*- coding: utf-8 -*-
"""
mock_llm.py —— 纯本地、无网络的「大模型」任务拆解器。

设计目标：
    在未配置任何真实大模型 API Key 时（Mock 模式），平台仍要能演示完整闭环。
    本模块用规则 + 预置模板模拟 LLM 的「自然语言指令 -> 结构化任务」能力。

产品逻辑要点：
    1. 对 SPEC §6 的 10 条预置示例指令，给出**各自定制化、高质量**的拆解结果——
       步骤贴合该指令真实语义、使用真实技能 code（见 SPEC §4）、含针对性约束与异常处理。
    2. 对其它任意指令，走通用模板拆解：根据关键词推断任务类型，组合出
       「感知 -> 移动 -> 操作 -> 校验」的合理骨架，保证返回结构永远合法。
    3. 返回的数据结构严格符合 SPEC §3 的 ParsedTask 形状，可直接被流程图组件消费。

注意：本文件仅依赖标准库与本项目内的 services.constants（第一方常量表），
不依赖任何第三方库，Apple Silicon 友好、零编译依赖。
"""

# 技能 code -> (中文名, 分类) 的映射统一收敛到 services/constants.py（单一事实源），
# 与 demo_data.json / mock_data 保持一致，仅用于 Mock 拆解时填充步骤的展示字段，
# 避免每次都去查数据库，保证离线可用；沿用原有变量名，下方逻辑无需改动。
from services.constants import SKILL_META as _SKILL_META

# ============================================================================
# 一、步骤构造辅助函数
# ============================================================================
# step 对象形状（SPEC §3）：
# { "index", "skill_code", "skill_name", "category", "params",
#   "description", "expected_result" }
# 为减少重复，这里用一个工厂函数生成单个步骤；index 由调用方统一重排。
# ----------------------------------------------------------------------------


def _step(skill_code, params, description, expected_result):
    """构造单个 step 对象（index 先占位 0，最终由 _finalize 统一编号）。

    参数：
        skill_code      原子技能英文编码，必须存在于 _SKILL_META。
        params          dict，该步骤的执行参数。
        description     中文步骤描述（给人看）。
        expected_result 中文预期结果（用于执行模拟判定与展示）。
    """
    name, category = _SKILL_META.get(skill_code, (skill_code, "逻辑类"))
    return {
        "index": 0,
        "skill_code": skill_code,
        "skill_name": name,
        "category": category,
        "params": params,
        "description": description,
        "expected_result": expected_result,
    }


def _finalize(instruction, task_type, goal, constraints, steps, exception_handling):
    """把零散字段组装成合法 ParsedTask，并为步骤重新编号（从 1 开始）。"""
    for i, s in enumerate(steps, start=1):
        s["index"] = i
    return {
        "instruction": instruction,
        "task_type": task_type,
        "goal": goal,
        "constraints": constraints,
        "steps": steps,
        "exception_handling": exception_handling,
    }


# ============================================================================
# 二、10 条预置示例指令的定制化高质量拆解
# ============================================================================
# 每个函数对应 SPEC §6 的一条示例。拆解思路均贴合该指令的真实语义：
#   - 先感知/定位，再移动，再操作，必要时加逻辑分支与校验；
#   - 约束体现该任务的安全/质量要求；
#   - 异常处理覆盖该任务最可能出现的失败点（呼应 SPEC §5 的 5 类失败）。
# ----------------------------------------------------------------------------

def _ex_red_cup(instruction):
    """1. 把红色的杯子放到桌子右边 —— 取送 —— 简单。

    产品逻辑：典型的「识别-定位-抓取-移动-放置」取送链路。
    红色是关键区分属性，故先做颜色判别避免抓错杯子；杯子易倾倒，抓取力度适中。
    """
    steps = [
        _step("Recognize", {"target": "杯子"}, "在桌面区域识别所有杯子", "得到候选杯子列表"),
        _step("CheckColor", {"object": "杯子"}, "判别各杯子颜色，筛出红色的那一只", "锁定红色杯子"),
        _step("Locate", {"object": "红色杯子"}, "定位红色杯子的精确坐标", "获取红色杯子坐标"),
        _step("MoveTo", {"target": "红色杯子"}, "移动到红色杯子旁边", "到达红色杯子附近"),
        _step("Grasp", {"object": "红色杯子", "force": 35}, "以适中力度抓起红色杯子（防止滑落或捏变形）", "稳稳抓住红色杯子"),
        _step("MoveTo", {"target": "桌子右边"}, "移动到桌子右侧目标区域", "到达桌子右边"),
        _step("Place", {"object": "红色杯子", "location": "桌子右边"}, "将红色杯子轻放到桌子右边", "红色杯子已放好"),
    ]
    return _finalize(
        instruction, "取送", "把红色的杯子准确放置到桌子的右侧",
        ["仅移动红色杯子，不得碰倒其它杯子", "杯内可能有液体，需轻拿轻放保持平稳"],
        steps,
        ["若识别不到红色杯子，请求人工确认是否存在", "抓取失败最多重试2次，仍失败则停止并通知"],
    )


def _ex_tidy_then_water(instruction):
    """2. 先整理桌面，再去厨房拿一瓶水 —— 整理 —— 中等。

    产品逻辑：复合任务，存在明确的「先后」时序依赖。
    第一阶段整理桌面（扫描-循环归位），第二阶段跨房间取水。用 Loop 体现批量整理。
    """
    steps = [
        _step("Scan", {"area": "桌面"}, "扫描桌面，盘点需要整理的零散物品", "得到桌面待整理物品清单"),
        _step("Loop", {"collection": "桌面物品清单"}, "依次将每件物品归位到对应收纳处", "桌面物品逐一归位"),
        _step("Grasp", {"object": "桌面物品", "force": 40}, "抓取当前待归位物品", "抓住物品"),
        _step("Place", {"object": "桌面物品", "location": "对应收纳位"}, "放置到对应收纳位置", "物品归位完成"),
        _step("Wipe", {"area": "桌面"}, "整理完成后擦拭桌面", "桌面整洁"),
        _step("Navigate", {"from": "书房", "to": "厨房", "avoid": ["障碍物"]}, "从当前房间规划路径前往厨房", "到达厨房"),
        _step("Recognize", {"target": "瓶装水"}, "在厨房识别一瓶水", "找到瓶装水"),
        _step("Grasp", {"object": "瓶装水", "force": 45}, "抓起一瓶水", "抓住水瓶"),
        _step("ReturnHome", {}, "携水返回出发位置交付", "完成取水"),
    ]
    return _finalize(
        instruction, "整理", "先把桌面整理干净，再从厨房取回一瓶水",
        ["必须先完成桌面整理再去取水（时序约束）", "跨房间移动需避让行人与障碍"],
        steps,
        ["若桌面物品无对应收纳位，标记并请求人工确认", "厨房未找到水则通知用户并返回"],
    )


def _ex_sort_blocks(instruction):
    """3. 分拣所有蓝色的方块到A区，红色的放到B区 —— 分拣 —— 中等。

    产品逻辑：典型分拣任务，核心是「遍历 + 颜色判别 + 条件分流」。
    用 Loop 遍历方块，CheckColor 判色，If 分支决定去 A 区还是 B 区。
    """
    steps = [
        _step("Scan", {"area": "方块堆放区"}, "扫描区域，找出所有方块", "得到全部方块列表"),
        _step("Loop", {"collection": "方块列表"}, "逐个处理每一块方块", "开始遍历分拣"),
        _step("CheckColor", {"object": "方块"}, "判别当前方块颜色", "得到方块颜色"),
        _step("If", {"condition": "颜色 == 蓝色"}, "若为蓝色则目标设为A区，否则若为红色则设为B区", "确定目标分拣区"),
        _step("Grasp", {"object": "方块", "force": 50}, "抓取当前方块", "抓住方块"),
        _step("Place", {"object": "方块", "location": "对应分拣区(A区/B区)"}, "放置到对应颜色分拣区", "方块入区完成"),
        _step("Notify", {"message": "分拣完成，汇报各区数量"}, "全部处理完后汇报分拣结果", "分拣报告已发送"),
    ]
    return _finalize(
        instruction, "分拣", "把蓝色方块全部放入A区、红色方块全部放入B区",
        ["颜色判别需准确，避免错分", "只处理蓝色与红色方块，其它颜色暂不动并记录"],
        steps,
        ["颜色判别置信度低于阈值时请求人工确认", "出现非红非蓝方块则跳过并记录数量"],
    )


def _ex_warehouse_patrol(instruction):
    """4. 帮我规划仓库巡检路线，避开有人的区域 —— 巡检 —— 困难。

    产品逻辑：困难任务，核心是「先感知人员分布 -> 动态避障路径规划 -> 巡检执行」。
    强调避开有人区域（安全约束），巡检中持续扫描异常。
    """
    steps = [
        _step("Scan", {"area": "整个仓库"}, "扫描仓库，识别当前有人员活动的区域", "得到人员分布与禁行区"),
        _step("Filter", {"items": "全部巡检点", "criteria": "排除有人区域及其缓冲区"}, "从巡检点中剔除有人区域", "得到安全巡检点集合"),
        _step("Navigate", {"from": "起始点", "to": "巡检终点", "avoid": ["有人区域", "缓冲区", "障碍物"]}, "规划一条覆盖安全巡检点且避开人员的路线", "生成避障巡检路线"),
        _step("Patrol", {"route": "避障巡检路线"}, "沿规划路线执行巡检", "按路线巡检中"),
        _step("Scan", {"area": "途经货架与通道"}, "巡检途中持续扫描异常（杂物/缺货/隐患）", "记录沿途异常"),
        _step("Notify", {"message": "巡检完成，输出异常清单与覆盖率"}, "巡检结束汇报结果", "巡检报告已发送"),
        _step("ReturnHome", {}, "巡检完毕返回充电原点", "回到原点"),
    ]
    return _finalize(
        instruction, "巡检", "在避开所有有人区域的前提下完成仓库全覆盖巡检",
        ["严禁进入有人活动区域（安全红线）", "人员可能移动，需动态更新避障区", "尽量保证巡检覆盖率"],
        steps,
        ["发现新出现的人员立即停车并重新规划路线", "路径被完全阻断时请求人工干预"],
    )


def _ex_clean_desk(instruction):
    """5. 清理桌面上的书和笔，放到收纳盒里 —— 整理 —— 中等。

    产品逻辑：定向整理——只针对「书」和「笔」两类物品归入收纳盒。
    用 Filter 筛出目标品类，Loop 批量收纳，最后擦拭桌面收尾。
    """
    steps = [
        _step("Scan", {"area": "桌面"}, "扫描桌面上的所有物品", "得到桌面物品列表"),
        _step("Filter", {"items": "桌面物品列表", "criteria": "类别为书或笔"}, "筛选出所有书和笔", "得到待收纳的书与笔"),
        _step("Locate", {"object": "收纳盒"}, "定位收纳盒位置", "获取收纳盒坐标"),
        _step("Loop", {"collection": "书与笔列表"}, "逐件把书和笔放进收纳盒", "开始批量收纳"),
        _step("Grasp", {"object": "书/笔", "force": 35}, "抓取当前的书或笔", "抓住物品"),
        _step("Place", {"object": "书/笔", "location": "收纳盒"}, "放入收纳盒", "物品已入盒"),
        _step("Wipe", {"area": "桌面"}, "清空后擦拭桌面", "桌面整洁"),
    ]
    return _finalize(
        instruction, "整理", "把桌面上的书和笔全部收纳进收纳盒并清洁桌面",
        ["只收纳书和笔，其它物品保持原位", "书本较重需稳抓，避免散页"],
        steps,
        ["收纳盒已满时通知用户并暂停", "无法判断物品是否为书/笔时请求人工确认"],
    )


def _ex_fragile_shelf(instruction):
    """6. 把易碎品轻轻放到上层货架 —— 取送 —— 中等。

    产品逻辑：核心是「易碎」与「上层」两个难点。
    需测量重量/尺寸辅助抓取规划，全程低力度、慢速、稳放；上层需转向/抬升对位。
    """
    steps = [
        _step("Recognize", {"target": "易碎品"}, "识别待搬运的易碎品", "确认易碎品"),
        _step("Measure", {"object": "易碎品", "attr": "重量与尺寸"}, "测量易碎品重量与尺寸以规划抓取", "得到重量尺寸参数"),
        _step("MoveTo", {"target": "易碎品"}, "移动到易碎品旁", "到达易碎品附近"),
        _step("Grasp", {"object": "易碎品", "force": 18}, "以极低力度轻柔抓取易碎品", "稳而轻地抓住易碎品"),
        _step("MoveTo", {"target": "上层货架"}, "缓速移动到上层货架前", "到达上层货架"),
        _step("Place", {"object": "易碎品", "location": "上层货架"}, "对准上层货位，轻缓放置易碎品", "易碎品安全上架"),
    ]
    return _finalize(
        instruction, "取送", "把易碎品安全、轻柔地放置到上层货架",
        ["全程低力度、慢速搬运，禁止急停急转", "上层放置需对位精准防止跌落"],
        steps,
        ["重量超出安全抓取范围时请求人工协助", "抓取出现打滑迹象立即降速并重试1次"],
    )


def _ex_find_remote(instruction):
    """7. 找到遥控器，送到客厅沙发上 —— 取送 —— 简单。

    产品逻辑：先搜寻定位（遥控器位置不确定），再抓取跨区送达沙发。
    搜寻是关键，故先 Scan 再 Locate。
    """
    steps = [
        _step("Scan", {"area": "周边区域"}, "扫描周边寻找遥控器", "在视野内搜寻遥控器"),
        _step("Recognize", {"target": "遥控器"}, "识别确认遥控器", "确认遥控器"),
        _step("Locate", {"object": "遥控器"}, "定位遥控器坐标", "获取遥控器位置"),
        _step("MoveTo", {"target": "遥控器"}, "移动到遥控器旁", "到达遥控器附近"),
        _step("Grasp", {"object": "遥控器", "force": 30}, "抓起遥控器", "抓住遥控器"),
        _step("Navigate", {"from": "当前位置", "to": "客厅沙发", "avoid": ["障碍物"]}, "规划路径前往客厅沙发", "到达客厅沙发"),
        _step("Place", {"object": "遥控器", "location": "客厅沙发"}, "把遥控器放到沙发上", "遥控器已送达"),
    ]
    return _finalize(
        instruction, "取送", "找到遥控器并把它送到客厅沙发上",
        ["送达过程避免遗落物品", "放置位置应在沙发显眼且稳固处"],
        steps,
        ["搜寻一轮未找到遥控器则扩大范围再搜一次，仍无则请求人工确认", "路径受阻则重新规划"],
    )


def _ex_sort_boxes(instruction):
    """8. 按照从大到小的顺序排列这些盒子 —— 排序 —— 中等。

    产品逻辑：排序任务核心是「测量尺寸 -> 排序 -> 依序摆放」。
    先逐个测量盒子尺寸，用 Sort 按降序排列，再 Loop 依序归位。
    """
    steps = [
        _step("Scan", {"area": "盒子摆放区"}, "扫描找出所有盒子", "得到盒子集合"),
        _step("Loop", {"collection": "盒子集合"}, "逐个测量每个盒子的尺寸", "开始测量"),
        _step("Measure", {"object": "盒子", "attr": "尺寸"}, "测量当前盒子尺寸", "得到盒子尺寸"),
        _step("Sort", {"items": "盒子集合", "order": "desc"}, "按尺寸从大到小排序盒子", "得到从大到小的排列顺序"),
        _step("Loop", {"collection": "已排序盒子序列"}, "按排序结果依次摆放盒子", "开始依序摆放"),
        _step("Grasp", {"object": "盒子", "force": 45}, "抓取当前盒子", "抓住盒子"),
        _step("Place", {"object": "盒子", "location": "对应序位"}, "放到从大到小的对应位置", "盒子就位"),
    ]
    return _finalize(
        instruction, "排序", "把所有盒子按尺寸从大到小依次排列整齐",
        ["排列需对齐、间距均匀", "测量需准确，避免大小判断错误"],
        steps,
        ["两个盒子尺寸非常接近时复测一次再排序", "盒子过重无法搬动则请求人工协助"],
    )


def _ex_check_drawers(instruction):
    """9. 检查所有抽屉里有没有钥匙 —— 检查 —— 困难。

    产品逻辑：困难任务，需「逐个打开抽屉 -> 扫描内部 -> 判断是否有钥匙 -> 汇总」。
    遮挡与小目标识别是难点。用 Loop 遍历抽屉，每个 Open + Scan + If 判断。
    """
    steps = [
        _step("Scan", {"area": "柜体"}, "扫描定位所有抽屉", "得到抽屉列表"),
        _step("Loop", {"collection": "抽屉列表"}, "逐个检查每个抽屉", "开始逐屉检查"),
        _step("Open", {"target": "抽屉"}, "打开当前抽屉", "抽屉已打开"),
        _step("Scan", {"area": "抽屉内部"}, "扫描抽屉内部物品", "得到抽屉内物品"),
        _step("Recognize", {"target": "钥匙"}, "识别抽屉内是否有钥匙", "判断是否含钥匙"),
        _step("If", {"condition": "识别到钥匙"}, "若发现钥匙则记录其所在抽屉", "记录钥匙位置或标记未发现"),
        _step("Notify", {"message": "汇报哪些抽屉里有钥匙"}, "全部检查完后汇总并汇报", "检查报告已发送"),
    ]
    return _finalize(
        instruction, "检查", "逐一检查所有抽屉，确认是否存在钥匙并汇报位置",
        ["每个抽屉都需开到位以避免遮挡漏检", "检查后将抽屉恢复原状"],
        steps,
        ["抽屉打不开（锁住/卡住）则记录并跳过，最后统一汇报", "物品堆叠遮挡严重时翻找一次再判断，仍不确定则请求人工确认"],
    )


def _ex_water_plant(instruction):
    """10. 给植物浇水，然后开窗通风 —— 养护 —— 简单。

    产品逻辑：两段顺序养护任务——先浇水（取水壶-倾倒），后开窗。
    时序明确：先浇水后开窗。
    """
    steps = [
        _step("Locate", {"object": "水壶"}, "定位水壶位置", "获取水壶坐标"),
        _step("MoveTo", {"target": "水壶"}, "移动到水壶旁", "到达水壶附近"),
        _step("Grasp", {"object": "水壶", "force": 45}, "拿起水壶", "抓住水壶"),
        _step("MoveTo", {"target": "植物"}, "移动到植物旁", "到达植物附近"),
        _step("Pour", {"container": "水壶", "target": "植物"}, "向植物缓缓倾倒适量水", "完成浇水"),
        _step("MoveTo", {"target": "窗户"}, "浇完水后移动到窗户旁", "到达窗户附近"),
        _step("Open", {"target": "窗户"}, "打开窗户通风", "窗户已打开通风"),
    ]
    return _finalize(
        instruction, "养护", "先给植物浇适量水，再打开窗户通风",
        ["必须先浇水再开窗（时序约束）", "浇水适量，避免水量过多溢出"],
        steps,
        ["水壶无水则先去接水或通知用户", "窗户卡住打不开时请求人工协助"],
    )


# 指令文本 -> 定制化拆解函数 的精确匹配表。
# key 为 SPEC §6 的原文指令，命中即返回高质量定制拆解。
_EXAMPLE_HANDLERS = {
    "把红色的杯子放到桌子右边": _ex_red_cup,
    "先整理桌面，再去厨房拿一瓶水": _ex_tidy_then_water,
    "分拣所有蓝色的方块到A区，红色的放到B区": _ex_sort_blocks,
    "帮我规划仓库巡检路线，避开有人的区域": _ex_warehouse_patrol,
    "清理桌面上的书和笔，放到收纳盒里": _ex_clean_desk,
    "把易碎品轻轻放到上层货架": _ex_fragile_shelf,
    "找到遥控器，送到客厅沙发上": _ex_find_remote,
    "按照从大到小的顺序排列这些盒子": _ex_sort_boxes,
    "检查所有抽屉里有没有钥匙": _ex_check_drawers,
    "给植物浇水，然后开窗通风": _ex_water_plant,
}


# ============================================================================
# 三、通用模板拆解（兜底）
# ============================================================================
# 对未命中预置示例的任意指令，根据关键词推断任务类型，再套用与该类型匹配的
# 「感知 -> 移动 -> 操作 -> 校验」骨架，保证返回结构合法且语义大致合理。
# ----------------------------------------------------------------------------

# 关键词 -> 任务类型 的推断规则。命中靠前的优先。
# 任务类型取值与 SPEC 一致：整理/分拣/取送/巡检/养护/排序/检查。
_TYPE_KEYWORDS = [
    ("分拣", ["分拣", "分类", "归类", "分开"]),
    ("排序", ["排序", "排列", "顺序", "从大到小", "从小到大"]),
    ("巡检", ["巡检", "巡逻", "路线", "覆盖"]),
    ("检查", ["检查", "查看", "确认有没有", "排查", "核对"]),
    ("养护", ["浇水", "通风", "养护", "开窗", "清洁保养"]),
    ("整理", ["整理", "清理", "收纳", "归位", "打扫"]),
    ("取送", ["拿", "取", "送", "搬", "递", "放到", "放置", "抓"]),
]


def _infer_task_type(instruction):
    """根据指令关键词推断任务类型，默认归为「取送」。"""
    for task_type, words in _TYPE_KEYWORDS:
        for w in words:
            if w in instruction:
                return task_type
    return "取送"


# 各任务类型对应的通用步骤骨架构造器。
# 这些骨架不针对具体物体，但符合该类型的一般执行范式。
def _tpl_generic(instruction, task_type):
    """根据任务类型返回（goal, constraints, steps, exception_handling）。"""
    if task_type == "整理":
        steps = [
            _step("Scan", {"area": "目标区域"}, "扫描目标区域，盘点待整理物品", "得到待整理清单"),
            _step("Loop", {"collection": "待整理清单"}, "逐件将物品归位", "开始批量整理"),
            _step("Grasp", {"object": "物品", "force": 40}, "抓取当前物品", "抓住物品"),
            _step("Place", {"object": "物品", "location": "对应收纳位"}, "放置到对应收纳位置", "物品归位"),
            _step("Wipe", {"area": "目标区域"}, "整理后清洁区域", "区域整洁"),
        ]
        goal = "整理目标区域，使物品归位、环境整洁"
        cons = ["不损坏物品", "保持原有分类逻辑"]
        exc = ["无对应收纳位的物品标记后请求人工确认", "抓取失败重试2次"]
    elif task_type == "分拣":
        steps = [
            _step("Scan", {"area": "待分拣区"}, "扫描待分拣物品", "得到物品列表"),
            _step("Loop", {"collection": "物品列表"}, "逐个处理物品", "开始遍历"),
            _step("Recognize", {"target": "物品"}, "识别当前物品类别/属性", "得到分类依据"),
            _step("If", {"condition": "符合分拣规则"}, "依据规则确定目标区域", "确定目标区"),
            _step("Grasp", {"object": "物品", "force": 45}, "抓取物品", "抓住物品"),
            _step("Place", {"object": "物品", "location": "对应分拣区"}, "放入对应分拣区", "入区完成"),
        ]
        goal = "按规则把物品分拣到对应区域"
        cons = ["分类判别准确", "不混淆不同类别"]
        exc = ["判别置信度低时请求人工确认", "无法归类的物品单独存放并记录"]
    elif task_type == "巡检":
        steps = [
            _step("Scan", {"area": "巡检范围"}, "扫描巡检范围与障碍/人员", "得到环境信息"),
            _step("Navigate", {"from": "起点", "to": "终点", "avoid": ["障碍物", "人员"]}, "规划避障巡检路线", "生成巡检路线"),
            _step("Patrol", {"route": "巡检路线"}, "沿路线执行巡检", "巡检中"),
            _step("Notify", {"message": "汇报巡检结果与异常"}, "汇总并汇报", "报告已发送"),
            _step("ReturnHome", {}, "返回原点", "回到原点"),
        ]
        goal = "完成指定范围的巡检并汇报异常"
        cons = ["避让人员与障碍", "尽量提高覆盖率"]
        exc = ["路径受阻重新规划", "发现严重异常立即通知并停车"]
    elif task_type == "检查":
        steps = [
            _step("Scan", {"area": "检查范围"}, "扫描确定检查对象", "得到检查对象列表"),
            _step("Loop", {"collection": "检查对象列表"}, "逐个检查", "开始逐项检查"),
            _step("Recognize", {"target": "目标项"}, "识别/核对当前对象", "得到检查结果"),
            _step("If", {"condition": "符合预期"}, "记录是否符合预期", "记录结果"),
            _step("Notify", {"message": "汇报检查结论"}, "汇总检查结论", "报告已发送"),
        ]
        goal = "逐项检查并汇报结论"
        cons = ["不遗漏任何检查对象", "检查后恢复原状"]
        exc = ["对象无法访问则记录跳过", "结果不确定时请求人工确认"]
    elif task_type == "排序":
        steps = [
            _step("Scan", {"area": "待排序区"}, "扫描待排序对象", "得到对象集合"),
            _step("Loop", {"collection": "对象集合"}, "逐个测量排序依据属性", "开始测量"),
            _step("Measure", {"object": "对象", "attr": "尺寸"}, "测量当前对象属性", "得到属性值"),
            _step("Sort", {"items": "对象集合", "order": "asc"}, "按属性排序", "得到排序结果"),
            _step("Loop", {"collection": "已排序序列"}, "依序摆放对象", "依序摆放"),
            _step("Place", {"object": "对象", "location": "对应序位"}, "放到对应序位", "对象就位"),
        ]
        goal = "把对象按指定属性排序摆放整齐"
        cons = ["测量准确", "排列对齐均匀"]
        exc = ["属性接近时复测", "对象过重请求人工协助"]
    elif task_type == "养护":
        steps = [
            _step("Locate", {"object": "养护对象"}, "定位养护对象", "获取对象位置"),
            _step("MoveTo", {"target": "养护对象"}, "移动到对象旁", "到达对象附近"),
            _step("Pour", {"container": "工具", "target": "养护对象"}, "执行养护操作（如浇水）", "完成养护动作"),
            _step("Notify", {"message": "养护完成"}, "汇报养护结果", "报告已发送"),
        ]
        goal = "对目标对象完成养护操作"
        cons = ["操作适量，避免过度", "不损伤养护对象"]
        exc = ["资源不足（如无水）则先补给或通知", "对象状态异常时请求人工确认"]
    else:  # 取送（默认）
        steps = [
            _step("Recognize", {"target": "目标物体"}, "识别目标物体", "确认目标物体"),
            _step("Locate", {"object": "目标物体"}, "定位目标物体坐标", "获取坐标"),
            _step("MoveTo", {"target": "目标物体"}, "移动到目标物体旁", "到达物体附近"),
            _step("Grasp", {"object": "目标物体", "force": 35}, "抓取目标物体", "抓住物体"),
            _step("Navigate", {"from": "当前位置", "to": "目标位置", "avoid": ["障碍物"]}, "规划路径前往目标位置", "到达目标位置"),
            _step("Place", {"object": "目标物体", "location": "目标位置"}, "放置到目标位置", "放置完成"),
        ]
        goal = "取得目标物体并送达指定位置"
        cons = ["途中不遗落物品", "轻拿轻放"]
        exc = ["未识别到目标物体则请求人工确认", "抓取失败重试2次", "路径受阻重新规划"]
    return goal, cons, steps, exc


def _template_parse(instruction):
    """通用模板拆解：推断类型 -> 套用骨架 -> 组装 ParsedTask。"""
    task_type = _infer_task_type(instruction)
    goal, cons, steps, exc = _tpl_generic(instruction, task_type)
    return _finalize(instruction, task_type, goal, cons, steps, exc)


# ============================================================================
# 四、对外主入口
# ============================================================================

def mock_parse(instruction, skills=None):
    """本地模拟「大模型拆解」入口（SPEC §9 签名）。

    参数：
        instruction  用户自然语言指令（str）。
        skills       可选，技能列表（list[dict]）。本地实现不强依赖它，
                     仅在需要时可用于校验 skill_code 合法性；保留参数以契合签名。

    返回：
        ParsedTask（dict），形状严格符合 SPEC §3。

    逻辑：
        1. 去除首尾空白后，先尝试精确命中 10 条预置示例 -> 返回定制化高质量拆解。
        2. 未命中则走通用模板拆解。
        3. 全程纯本地、无任何网络请求。
    """
    text = (instruction or "").strip()

    # 1) 预置示例精确命中
    handler = _EXAMPLE_HANDLERS.get(text)
    if handler is not None:
        return handler(text)

    # 2) 通用模板兜底
    return _template_parse(text)


def mock_chat(system=None, user=None):
    """本地模拟「大模型对话补全」入口（SPEC §9：作为 LLMService.chat 的 Mock 兜底）。

    LLMService 在 Mock 模式（未配置真实 API Key）或真实调用异常时会转调本函数。
    task_parser 传入的 user 形如「请拆解以下指令：<指令原文>」，这里据此还原出
    指令文本，复用 mock_parse 产出结构化拆解，再以 **JSON 字符串** 返回——这样上层
    task_parser._try_extract_json 能把它解析回 ParsedTask，链路与真实大模型完全一致，
    保证默认 Mock 模式下 POST /api/task/parse(strategy=llm) 也能正常拆解、不报 500。

    参数：
        system  系统提示词（本地实现不依赖，仅为契合 chat 签名）。
        user    用户消息，通常为「请拆解以下指令：xxx」。
    返回：
        一段 JSON 字符串（ParsedTask 形状，中文不转义）。
    """
    import json  # 局部导入，保持本模块零顶层第三方/标准库耦合

    text = (user or "").strip()
    # 还原指令：剥离 task_parser 约定的「请拆解以下指令：」前缀（若存在）
    prefix = "请拆解以下指令："
    pos = text.find(prefix)
    instruction = text[pos + len(prefix):].strip() if pos != -1 else text

    return json.dumps(mock_parse(instruction), ensure_ascii=False)
