# -*- coding: utf-8 -*-
"""
技能库 API 路由（原子技能 CRUD）

对应 SPEC §8 skills.py 契约：
  - GET    /skills            技能列表（可按 category 过滤）
  - POST   /skills            新建技能
  - PUT    /skills/{id}       更新技能（部分字段）
  - DELETE /skills/{id}       删除技能 → {ok: true}

数据落在 skills 表（见 §2）。其中：
  - input_params 字段：JSON 数组 [{name,type,desc}]
  - output 字段：JSON 对象 {type,desc}
读出时统一 json.loads，写入时统一 json.dumps(ensure_ascii=False)，
保证返回给前端的是真正的数组/对象而非字符串。

本路由内部路径不带 /api 前缀，由 main.py 挂载时统一加 prefix="/api"。
"""

import json
from typing import Any, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from database import query_all, query_one, execute

router = APIRouter()


# ----------------------------------------------------------------------------
# 请求体模型
# ----------------------------------------------------------------------------
class SkillCreate(BaseModel):
    """新建技能的请求体。code 与 name 必填，其余可缺省。"""

    code: str = Field(..., description="英文编码，唯一，如 MoveTo")
    name: str = Field(..., description="中文名，如 移动到")
    category: str = Field("操作类", description="分类：移动类/操作类/感知类/逻辑类/控制类")
    icon: str = Field("🔧", description="emoji 图标")
    description: str = Field("", description="技能描述")
    # input_params 为对象数组；output 为对象。前端传入的是已解析的结构，这里再序列化入库
    input_params: List[Any] = Field(default_factory=list, description="入参定义 [{name,type,desc}]")
    output: dict = Field(default_factory=dict, description="出参定义 {type,desc}")
    enabled: int = Field(1, description="是否启用 0/1")


class SkillUpdate(BaseModel):
    """更新技能的请求体，所有字段可选（部分更新）。"""

    code: Optional[str] = None
    name: Optional[str] = None
    category: Optional[str] = None
    icon: Optional[str] = None
    description: Optional[str] = None
    input_params: Optional[List[Any]] = None
    output: Optional[dict] = None
    enabled: Optional[int] = None


# ----------------------------------------------------------------------------
# 内部工具：行 → 前端可用的技能对象（解析 JSON 字段）
# ----------------------------------------------------------------------------
def _row_to_skill(row) -> dict:
    """把 skills 表的一行（sqlite3.Row）转为 dict，并反序列化 JSON 字段。"""
    item = dict(row)
    item["input_params"] = json.loads(item["input_params"]) if item.get("input_params") else []
    item["output"] = json.loads(item["output"]) if item.get("output") else {}
    return item


def _fetch_skill(skill_id: int) -> dict:
    """按 id 取单个技能并解析，不存在则抛 404。"""
    row = query_one("SELECT * FROM skills WHERE id = ?", [skill_id])
    if row is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    return _row_to_skill(row)


# ----------------------------------------------------------------------------
# 接口实现
# ----------------------------------------------------------------------------
@router.get("/skills")
def get_skills(category: Optional[str] = Query(None, description="按分类过滤，可选")):
    """
    GET /skills

    返回技能列表（skills 表行，input_params/output 已 json.loads）。
    传入 category 时只返回该分类下的技能；否则返回全部。
    """
    if category:
        rows = query_all("SELECT * FROM skills WHERE category = ? ORDER BY id", [category])
    else:
        rows = query_all("SELECT * FROM skills ORDER BY id")
    return [_row_to_skill(row) for row in rows]


@router.post("/skills")
def create_skill(body: SkillCreate):
    """
    POST /skills

    新建一个技能。code 需唯一（与表上 UNIQUE 约束一致），重复时返回 400。
    返回新建后的完整技能对象。
    """
    # 先检查 code 是否已存在，给出更友好的中文报错（而非裸的数据库异常）
    exists = query_one("SELECT id FROM skills WHERE code = ?", [body.code])
    if exists is not None:
        raise HTTPException(status_code=400, detail=f"技能编码已存在：{body.code}")

    # 入库前把 input_params / output 序列化为 JSON 字符串（中文不转义）
    params_json = json.dumps(body.input_params, ensure_ascii=False)
    output_json = json.dumps(body.output, ensure_ascii=False)

    new_id = execute(
        "INSERT INTO skills (code, name, category, icon, description, input_params, output, enabled) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            body.code,
            body.name,
            body.category,
            body.icon,
            body.description,
            params_json,
            output_json,
            body.enabled,
        ],
    )
    # execute 返回 lastrowid，据此回查完整记录返回
    return _fetch_skill(new_id)


@router.put("/skills/{skill_id}")
def update_skill(skill_id: int, body: SkillUpdate):
    """
    PUT /skills/{id}

    部分更新技能。只更新请求体中显式提供（非 None）的字段。
    返回更新后的完整技能对象。
    """
    # 确认目标技能存在
    _fetch_skill(skill_id)

    # 动态拼接 SET 子句，仅包含提供了值的字段
    fields = []
    params: list = []

    if body.code is not None:
        # 改 code 时需保证不与其它技能冲突
        clash = query_one(
            "SELECT id FROM skills WHERE code = ? AND id != ?", [body.code, skill_id]
        )
        if clash is not None:
            raise HTTPException(status_code=400, detail=f"技能编码已存在：{body.code}")
        fields.append("code = ?")
        params.append(body.code)
    if body.name is not None:
        fields.append("name = ?")
        params.append(body.name)
    if body.category is not None:
        fields.append("category = ?")
        params.append(body.category)
    if body.icon is not None:
        fields.append("icon = ?")
        params.append(body.icon)
    if body.description is not None:
        fields.append("description = ?")
        params.append(body.description)
    if body.input_params is not None:
        # 复合字段需序列化为 JSON 字符串
        fields.append("input_params = ?")
        params.append(json.dumps(body.input_params, ensure_ascii=False))
    if body.output is not None:
        fields.append("output = ?")
        params.append(json.dumps(body.output, ensure_ascii=False))
    if body.enabled is not None:
        fields.append("enabled = ?")
        params.append(body.enabled)

    if fields:
        params.append(skill_id)
        execute(f"UPDATE skills SET {', '.join(fields)} WHERE id = ?", params)

    # 返回更新后的最新数据
    return _fetch_skill(skill_id)


@router.delete("/skills/{skill_id}")
def delete_skill(skill_id: int):
    """
    DELETE /skills/{id}

    删除指定技能。返回 { "ok": true }。
    """
    _fetch_skill(skill_id)  # 不存在则抛 404
    execute("DELETE FROM skills WHERE id = ?", [skill_id])
    return {"ok": True}
