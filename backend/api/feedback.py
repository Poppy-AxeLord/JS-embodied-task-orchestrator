"""
反馈与人工介入（Human-in-the-loop）API 路由（第 2 组）。

这是“数据闭环”里把人类判断回灌进系统的关键环节：
- 用户对执行结果打分/留言 → 沉淀满意度数据。
- 用户提交“修正后的步骤” → 标记为优质样本（is_golden），用于反哺拆解模板/模型。
- 需人工介入（needs_review）的失败任务进入 HITL 队列，被人工修正后解除标记。

端点（前缀 /api 由 main.py 统一挂载，本文件不带 /api）：
- POST /feedback                    提交反馈
- GET  /feedback/hitl               获取需人工介入任务列表
- POST /feedback/hitl/{id}/resolve  人工修正并解除介入标记

数据库表字段严格遵守 SPEC §2（tasks / feedback）。
JSON 字段写库统一 json.dumps(ensure_ascii=False)，读出统一 json.loads。
"""

import json
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

# 数据库辅助：见 §2，database.py 提供这些函数。
# - execute(sql, params)   ：执行写操作（INSERT/UPDATE/DELETE），返回受影响信息（如 lastrowid）。
# - query_one(sql, params) ：取一行（sqlite3.Row）或 None。
# - query_all(sql, params) ：取多行列表。
from database import execute, query_one, query_all

# 导出名必须为 router，供 main.py 挂载。
router = APIRouter()


# ----------------------------------------------------------------------------
# 工具函数
# ----------------------------------------------------------------------------
def _now_iso() -> str:
    """返回当前时间的 ISO8601 字符串（YYYY-MM-DDTHH:MM:SS），与全局时间约定一致。"""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _dumps(obj: Any) -> str:
    """JSON 序列化，保留中文（ensure_ascii=False），用于写入 TEXT(JSON) 字段。"""
    return json.dumps(obj, ensure_ascii=False)


# ----------------------------------------------------------------------------
# 请求体模型
# ----------------------------------------------------------------------------
class FeedbackRequest(BaseModel):
    """POST /feedback 的请求体（SPEC §8）。"""

    task_id: int = Field(..., description="被反馈的任务 id")
    rating: int = Field(..., description="评分 1-5")
    comment: Optional[str] = Field(None, description="文字评价（可选）")
    # corrected_steps：用户修正后的步骤数组（step 对象，见 §3）。非空即视为优质样本。
    corrected_steps: Optional[list[dict[str, Any]]] = Field(
        None, description="修正后的步骤（可选），非空则标记为优质样本"
    )


class ResolveRequest(BaseModel):
    """POST /feedback/hitl/{id}/resolve 的请求体（SPEC §8）。"""

    corrected_steps: list[dict[str, Any]] = Field(..., description="人工修正后的步骤数组")
    failure_category: Optional[str] = Field(
        None, description="可选：修正/确认的失败分类（中文，如“感知失败”）"
    )


# ----------------------------------------------------------------------------
# POST /feedback
# ----------------------------------------------------------------------------
@router.post("/feedback")
def submit_feedback(req: FeedbackRequest) -> dict[str, Any]:
    """
    提交用户反馈。

    产品逻辑（严格按 §8）：
    1) 更新 tasks 表：写入 rating 与 feedback_text（评价文字）。
    2) 向 feedback 表插入一行（task_id / rating / comment / corrected_steps / created_at）。
    3) 若 corrected_steps 非空：
       - 视为“优质样本”，置 tasks.is_golden = 1；
       - 同时解除人工介入：tasks.needs_review = 0；
       - 并把修正后的步骤写回 tasks.steps（让历史详情回放看到的是修正后的正确拆解）。

    这三步共同构成满意度采集 + 优质样本沉淀，是数据飞轮的输入。
    """
    now = _now_iso()
    has_correction = bool(req.corrected_steps)

    # 1) 更新 tasks 的评分与反馈文字。
    #    feedback_text 对应“用户反馈意见”字段（§2）。
    execute(
        "UPDATE tasks SET rating = ?, feedback_text = ? WHERE id = ?",
        (req.rating, req.comment, req.task_id),
    )

    # 2) 插入 feedback 行。corrected_steps 以 JSON 字符串存储（无修正则存 NULL）。
    execute(
        """
        INSERT INTO feedback (task_id, rating, comment, corrected_steps, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            req.task_id,
            req.rating,
            req.comment,
            _dumps(req.corrected_steps) if has_correction else None,
            now,
        ),
    )

    # 3) 有修正 → 标记优质样本、解除人工介入、回写步骤。
    if has_correction:
        execute(
            """
            UPDATE tasks
            SET is_golden = 1,
                needs_review = 0,
                steps = ?
            WHERE id = ?
            """,
            (_dumps(req.corrected_steps), req.task_id),
        )

    return {"ok": True}


# ----------------------------------------------------------------------------
# GET /feedback/hitl
# ----------------------------------------------------------------------------
@router.get("/feedback/hitl")
def get_hitl_list() -> list[dict[str, Any]]:
    """
    获取“需人工介入”任务列表（Human-in-the-loop 队列）。

    口径（§8）：tasks 表中 needs_review = 1 的任务。
    每条摘要包含：id, instruction, task_type, failure_category, created_at, steps。
    （steps 为已解析的 step 对象数组，便于前端弹窗里直接展示/修正。）

    产品含义：把“机器没把握、需要人来判一判”的失败任务集中起来，
    人工修正后即可转化为优质样本，闭环效率最高的入口。
    """
    rows = query_all(
        """
        SELECT id, instruction, task_type, failure_category, created_at, steps
        FROM tasks
        WHERE needs_review = 1
        ORDER BY created_at DESC
        """,
        (),
    )

    result: list[dict[str, Any]] = []
    for row in rows:
        # sqlite3.Row 支持按列名取值；steps 是 JSON 字符串，需解析为对象数组。
        raw_steps = row["steps"]
        try:
            steps = json.loads(raw_steps) if raw_steps else []
        except (json.JSONDecodeError, TypeError):
            # 容错：脏数据不应导致整个列表接口 500。
            steps = []

        result.append(
            {
                "id": row["id"],
                "instruction": row["instruction"],
                "task_type": row["task_type"],
                "failure_category": row["failure_category"],
                "created_at": row["created_at"],
                "steps": steps,
            }
        )

    return result


# ----------------------------------------------------------------------------
# POST /feedback/hitl/{id}/resolve
# ----------------------------------------------------------------------------
@router.post("/feedback/hitl/{id}/resolve")
def resolve_hitl(id: int, req: ResolveRequest) -> dict[str, Any]:
    """
    解决一条人工介入任务：人工给出正确步骤后解除介入并沉淀为优质样本。

    产品逻辑（严格按 §8）：
    - 置 tasks.is_golden = 1（优质样本）、needs_review = 0（解除介入）；
    - 用 corrected_steps 更新 tasks.steps（回写正确拆解）；
    - 若传入 failure_category，则一并更新（人工确认/纠正失败分类）；
    - 向 feedback 表插入一行（记录这次人工修正，corrected_steps 入库）。

    这是 HITL 流程的收尾动作，每解决一条就向系统注入一个高质量训练/模板样本。
    """
    now = _now_iso()

    # 1) 更新 tasks：解除介入 + 标记优质 + 回写步骤 (+ 可选更新失败分类)。
    #    用动态拼装的方式，避免在未提供 failure_category 时误把字段写成 NULL。
    set_clauses = ["is_golden = 1", "needs_review = 0", "steps = ?"]
    params: list[Any] = [_dumps(req.corrected_steps)]

    if req.failure_category is not None:
        set_clauses.append("failure_category = ?")
        params.append(req.failure_category)

    params.append(id)  # WHERE id = ?
    execute(
        f"UPDATE tasks SET {', '.join(set_clauses)} WHERE id = ?",
        tuple(params),
    )

    # 2) 读取该任务当前评分，作为 feedback 行的 rating（HITL 解决一般无新评分，沿用原值）。
    row = query_one("SELECT rating FROM tasks WHERE id = ?", (id,))
    rating = row["rating"] if row is not None else None

    # 3) 插入 feedback 行，留痕本次人工修正。comment 给一句说明性文字。
    execute(
        """
        INSERT INTO feedback (task_id, rating, comment, corrected_steps, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            id,
            rating,
            "人工介入修正：已确认正确步骤并沉淀为优质样本",
            _dumps(req.corrected_steps),
            now,
        ),
    )

    return {"ok": True}
