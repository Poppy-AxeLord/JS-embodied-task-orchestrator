# -*- coding: utf-8 -*-
"""
任务相关 API 路由（第 1 组）

本文件同时承载两类接口（见 SPEC §8）：
  1) 任务编排相关：
     - GET  /task/examples   读取 10 条预置示例指令（来自 demo_data.json）
     - POST /task/parse      自然语言指令拆解为结构化 ParsedTask
  2) 任务历史相关（数据闭环的"历史回放"）：
     - GET    /tasks         历史任务列表（支持筛选与排序）
     - GET    /tasks/{id}    单条任务详情（含步骤日志、反馈）
     - DELETE /tasks/{id}    删除一条历史任务

注意：
  - 本路由内部路径不带 /api 前缀，统一由 main.py 挂载时加 prefix="/api"。
  - 所有读 JSON 字段处用 json.loads，写处用 json.dumps(ensure_ascii=False)。
  - 技能列表从数据库 skills 表读取后传给拆解服务，保证 skill_code 来自 §4 技能表。
"""

import json
import os

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

# 数据库访问辅助（标准库 sqlite3 封装，无 ORM）
from database import query_all, query_one, execute
# 任务拆解服务（strategy=llm 走大模型/Mock，strategy=rule 走规则拆解）
from services.task_parser import parse_task

# 每个 api 文件按契约导出名为 router 的 APIRouter
router = APIRouter()

# demo_data.json 的绝对路径：backend/data/demo_data.json
# __file__ = backend/api/task.py → 上溯两级到 backend/，再拼 data/demo_data.json
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
_DEMO_DATA_PATH = os.path.join(_DATA_DIR, "demo_data.json")


# ----------------------------------------------------------------------------
# 请求体模型（pydantic）
# ----------------------------------------------------------------------------
class ParseRequest(BaseModel):
    """POST /task/parse 的请求体。"""

    # 用户原始自然语言指令
    instruction: str = Field(..., description="用户输入的自然语言任务指令")
    # 拆解策略：llm（大模型/Mock）或 rule（规则关键词）；默认 llm
    strategy: str = Field("llm", description='拆解策略，"llm" 或 "rule"，默认 llm')


# ----------------------------------------------------------------------------
# 内部工具函数
# ----------------------------------------------------------------------------
def _load_skills():
    """
    从数据库 skills 表读取全部技能，并把 input_params / output 两个 JSON 字段反序列化。

    返回的列表会传给 parse_task，保证拆解出的步骤所用 skill_code 都来自真实技能库。
    """
    rows = query_all(
        "SELECT id, code, name, category, icon, description, input_params, output, enabled "
        "FROM skills ORDER BY id"
    )
    skills = []
    for row in rows:
        item = dict(row)
        # input_params 存的是 JSON 数组字符串，反序列化为 Python 列表
        item["input_params"] = json.loads(item["input_params"]) if item.get("input_params") else []
        # output 存的是 JSON 对象字符串，反序列化为 Python 字典
        item["output"] = json.loads(item["output"]) if item.get("output") else {}
        skills.append(item)
    return skills


# ----------------------------------------------------------------------------
# 1) 任务编排接口
# ----------------------------------------------------------------------------
@router.get("/task/examples")
def get_task_examples():
    """
    GET /task/examples

    返回 10 条预置示例指令，形如：
        [{ "instruction": "...", "task_type": "取送", "difficulty": "简单" }, ...]
    数据来源为 demo_data.json 的 examples 字段。前端用作可点击的快捷指令标签。
    """
    if not os.path.exists(_DEMO_DATA_PATH):
        # 演示数据文件缺失时返回空列表，避免前端报错（属于可降级场景）
        return []
    with open(_DEMO_DATA_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # 仅取 examples 字段，缺省给空列表
    return data.get("examples", [])


@router.post("/task/parse")
def post_task_parse(body: ParseRequest):
    """
    POST /task/parse

    将自然语言指令拆解为结构化 ParsedTask（流程图组件消费）。
    流程：
      1. 从数据库读取技能库（保证 skill_code 合法）。
      2. 调用 services.task_parser.parse_task 完成拆解。
      3. 直接返回 ParsedTask（不在此处落库；落库发生在执行阶段）。

    返回形状（ParsedTask，见 SPEC §3）：
        { instruction, task_type, goal, constraints, steps, exception_handling }
    """
    skills = _load_skills()
    # strategy=="llm" 时内部可能因无真实 Key 而走 Mock，对调用方透明
    parsed = parse_task(body.instruction, body.strategy, skills)
    return parsed


# ----------------------------------------------------------------------------
# 2) 任务历史接口
# ----------------------------------------------------------------------------
@router.get("/tasks")
def get_tasks(
    status: str = Query(None, description="按状态过滤：success / failed / pending"),
    task_type: str = Query(None, description="按任务类型过滤：整理/分拣/取送/巡检/养护/排序/检查"),
    sort: str = Query("time", description="排序方式：time（时间倒序）/ success / duration"),
):
    """
    GET /tasks

    历史任务列表，支持按 status、task_type 过滤，按 sort 排序。
    返回每条任务的摘要字段（见 SPEC §8 tasks 历史）：
        [{id, instruction, task_type, strategy, status, success,
          failure_category, total_duration_ms, step_count, rating, created_at}]
    """
    # 动态拼接 WHERE 条件，参数化查询防注入
    where_clauses = []
    params = []
    if status:
        where_clauses.append("status = ?")
        params.append(status)
    if task_type:
        where_clauses.append("task_type = ?")
        params.append(task_type)
    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # 排序规则：
    #   time     → 按创建时间倒序（最新在前）
    #   success  → 成功的在前（success 降序），再按时间倒序
    #   duration → 按总耗时降序（最耗时在前）
    if sort == "success":
        order_sql = "ORDER BY success DESC, created_at DESC"
    elif sort == "duration":
        order_sql = "ORDER BY total_duration_ms DESC"
    else:
        order_sql = "ORDER BY created_at DESC"

    sql = (
        "SELECT id, instruction, task_type, strategy, status, success, "
        "failure_category, total_duration_ms, step_count, rating, created_at "
        f"FROM tasks {where_sql} {order_sql}"
    )
    rows = query_all(sql, params)
    # sqlite3.Row → dict，便于 FastAPI 序列化为 JSON
    return [dict(row) for row in rows]


@router.get("/tasks/{task_id}")
def get_task_detail(task_id: int):
    """
    GET /tasks/{id}

    返回单条任务的完整详情：
        {
          "task": { 所有字段，其中 steps / constraints / exception_handling 已 json.loads },
          "steps": [ task_steps 行（params 已解析） ],
          "feedback": [ feedback 行（corrected_steps 已解析） ]
        }
    """
    task_row = query_one("SELECT * FROM tasks WHERE id = ?", [task_id])
    if task_row is None:
        # 任务不存在返回 404
        raise HTTPException(status_code=404, detail="任务不存在")

    task = dict(task_row)
    # 解析任务中以 JSON 字符串形式存储的复合字段
    task["constraints"] = json.loads(task["constraints"]) if task.get("constraints") else []
    task["steps"] = json.loads(task["steps"]) if task.get("steps") else []
    task["exception_handling"] = (
        json.loads(task["exception_handling"]) if task.get("exception_handling") else []
    )

    # 逐步执行日志（task_steps 表），按 step_index 升序回放
    step_rows = query_all(
        "SELECT * FROM task_steps WHERE task_id = ? ORDER BY step_index ASC", [task_id]
    )
    steps = []
    for row in step_rows:
        s = dict(row)
        # params 字段以 JSON 存储，反序列化为对象
        s["params"] = json.loads(s["params"]) if s.get("params") else {}
        steps.append(s)

    # 用户反馈（feedback 表）
    feedback_rows = query_all(
        "SELECT * FROM feedback WHERE task_id = ? ORDER BY created_at ASC", [task_id]
    )
    feedback = []
    for row in feedback_rows:
        fb = dict(row)
        # corrected_steps 以 JSON 存储，可能为空
        fb["corrected_steps"] = (
            json.loads(fb["corrected_steps"]) if fb.get("corrected_steps") else []
        )
        feedback.append(fb)

    return {"task": task, "steps": steps, "feedback": feedback}


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int):
    """
    DELETE /tasks/{id}

    删除一条历史任务，并级联清理其步骤日志与反馈，保持数据一致性。
    返回 { "ok": true }。
    """
    task_row = query_one("SELECT id FROM tasks WHERE id = ?", [task_id])
    if task_row is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 先删子表再删主表，避免悬挂的步骤/反馈记录
    execute("DELETE FROM task_steps WHERE task_id = ?", [task_id])
    execute("DELETE FROM feedback WHERE task_id = ?", [task_id])
    execute("DELETE FROM tasks WHERE id = ?", [task_id])
    return {"ok": True}
