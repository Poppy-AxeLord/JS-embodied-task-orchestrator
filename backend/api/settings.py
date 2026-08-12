# -*- coding: utf-8 -*-
"""
系统设置 / 健康检查 API 路由

对应 SPEC §8 settings.py 契约：
  - GET  /settings   读取大模型 / 仿真 / 数据三块配置
  - POST /settings   写入部分配置（保存到 settings 表）
  - GET  /health     健康检查，返回运行模式

安全约定（重要的产品逻辑）：
  - api_key 永远不回传明文。GET /settings 只返回布尔位 api_key_set
    表示"是否已配置密钥"，供前端展示"已配置 / 未配置"，避免密钥泄露。
  - mock_mode（Mock 模式）的判定：未配置任何真实 API Key 即视为 Mock。
    判定优先以 settings 表中用户保存的配置为准，其次回退到 .env / config 默认值。

数据存储：
  - settings 表为 key-value 结构（key TEXT PK, value TEXT(JSON)）。
  - 本模块用三个 key 分别存三块配置：'llm' / 'sim' / 'data'。
  - 读写 value 时统一 json.loads / json.dumps(ensure_ascii=False)。

本路由内部路径不带 /api 前缀，由 main.py 挂载时统一加 prefix="/api"。
"""

import json
from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from database import query_one, execute
# config 提供来自 .env 的默认值（provider、model、各家 api_key、temperature 等）
import config

router = APIRouter()

# settings 表中使用的三个配置键
_KEY_LLM = "llm"
_KEY_SIM = "sim"
_KEY_DATA = "data"


# ----------------------------------------------------------------------------
# 默认配置（当 settings 表中尚无对应记录时回退使用）
# 大模型默认值优先取自 config（即 .env），保证与启动模式一致。
# ----------------------------------------------------------------------------
def _default_llm() -> dict:
    # 大模型默认值取自 config.settings（.env 单例），与启动横幅/拆解链路口径一致
    return {
        "provider": config.settings.LLM_PROVIDER,
        "model": config.settings.LLM_MODEL,
        # 注意：内部存储用 api_key（明文），但对外永不回传，见 _public_llm
        "api_key": "",
        "temperature": config.settings.LLM_TEMPERATURE,
    }


def _default_sim() -> dict:
    # 仿真默认参数：房间尺寸（米）与机器人速度（米/秒）
    return {"room_size": 10, "robot_speed": 1.0}


def _default_data() -> dict:
    # 数据治理默认参数：历史保留天数与是否自动清理
    return {"retention_days": 90, "auto_clean": False}


# ----------------------------------------------------------------------------
# settings 表读写辅助
# ----------------------------------------------------------------------------
def _read_setting(key: str, default: dict) -> dict:
    """
    从 settings 表读取某个配置块（JSON），不存在则返回 default 的拷贝。
    并把 default 中缺失的子键补齐，保证字段完整（便于后续新增字段平滑兼容）。
    """
    row = query_one("SELECT value FROM settings WHERE key = ?", [key])
    if row is None:
        return dict(default)
    try:
        stored = json.loads(row["value"]) if row["value"] else {}
    except (ValueError, TypeError):
        stored = {}
    # 以 default 为基底合并已存值，确保所有预期字段都存在
    merged = dict(default)
    merged.update(stored)
    return merged


def _write_setting(key: str, value: dict) -> None:
    """把配置块以 JSON 字符串 upsert 进 settings 表。"""
    value_json = json.dumps(value, ensure_ascii=False)
    # SQLite UPSERT：主键冲突时更新 value
    execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        [key, value_json],
    )


def _resolve_llm_api_key(llm_cfg: dict) -> str:
    """
    解析"当前生效的"大模型 API Key。
    优先用用户在 settings 中保存的 api_key；若为空，则回退到 .env 中对应
    provider 的 Key（openai/qwen/zhipu）。用于判定是否处于 Mock 模式。
    """
    saved = (llm_cfg.get("api_key") or "").strip()
    if saved:
        return saved

    provider = (llm_cfg.get("provider") or "mock").lower()
    if provider == "openai":
        return (config.settings.OPENAI_API_KEY or "").strip()
    if provider == "qwen":
        return (config.settings.QWEN_API_KEY or "").strip()
    if provider == "zhipu":
        return (config.settings.ZHIPU_API_KEY or "").strip()
    # provider=mock 或未知，视为无 Key
    return ""


def _is_mock_mode(llm_cfg: dict) -> bool:
    """
    Mock 模式判定：provider 显式为 mock，或解析后无任何可用真实 Key。
    这是平台"无需联网即可全功能演示"的关键开关。
    """
    provider = (llm_cfg.get("provider") or "mock").lower()
    if provider == "mock":
        return True
    return _resolve_llm_api_key(llm_cfg) == ""


def _public_llm(llm_cfg: dict) -> dict:
    """
    构造对外可返回的大模型配置：剔除明文 api_key，仅暴露 api_key_set 布尔位。
    """
    return {
        "provider": llm_cfg.get("provider", "mock"),
        "model": llm_cfg.get("model", ""),
        # 是否已配置密钥（用户保存的或 .env 中存在），不回传明文
        "api_key_set": _resolve_llm_api_key(llm_cfg) != "",
        "temperature": llm_cfg.get("temperature", 0.3),
    }


# ----------------------------------------------------------------------------
# 请求体模型
# ----------------------------------------------------------------------------
class LLMSettingsIn(BaseModel):
    """大模型配置入参（均可选，部分更新）。api_key 仅在传入非空时才覆盖保存。"""

    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    temperature: Optional[float] = None


class SimSettingsIn(BaseModel):
    """仿真配置入参。"""

    room_size: Optional[float] = None
    robot_speed: Optional[float] = None


class DataSettingsIn(BaseModel):
    """数据治理配置入参。"""

    retention_days: Optional[int] = None
    auto_clean: Optional[bool] = None


class SettingsIn(BaseModel):
    """POST /settings 请求体：三块配置均可选，仅更新提供的部分。"""

    llm: Optional[LLMSettingsIn] = None
    sim: Optional[SimSettingsIn] = None
    data: Optional[DataSettingsIn] = None


# ----------------------------------------------------------------------------
# 接口实现
# ----------------------------------------------------------------------------
@router.get("/settings")
def get_settings():
    """
    GET /settings

    返回三块配置：
        {
          "llm":  { provider, model, api_key_set: bool, temperature },
          "sim":  { room_size, robot_speed },
          "data": { retention_days, auto_clean }
        }
    其中 llm 不含明文 api_key，只有 api_key_set 布尔位。
    """
    llm_cfg = _read_setting(_KEY_LLM, _default_llm())
    sim_cfg = _read_setting(_KEY_SIM, _default_sim())
    data_cfg = _read_setting(_KEY_DATA, _default_data())

    return {
        "llm": _public_llm(llm_cfg),
        "sim": sim_cfg,
        "data": data_cfg,
    }


@router.post("/settings")
def save_settings(body: SettingsIn):
    """
    POST /settings

    保存部分配置到 settings 表。规则：
      - 仅更新请求体中提供的块/字段（部分更新，不覆盖未提供项）。
      - llm.api_key 若传入非空则保存（明文存于 settings 表），但 GET 永不回传明文；
        若传入为空字符串或未传，则保留原有 api_key 不变。
    返回 { "ok": true }。
    """
    # --- 大模型配置 ---
    if body.llm is not None:
        current = _read_setting(_KEY_LLM, _default_llm())
        if body.llm.provider is not None:
            current["provider"] = body.llm.provider
        if body.llm.model is not None:
            current["model"] = body.llm.model
        if body.llm.temperature is not None:
            current["temperature"] = body.llm.temperature
        # api_key：仅在传入非空时覆盖，避免前端因不回显明文而误清空已存密钥
        if body.llm.api_key is not None and body.llm.api_key.strip() != "":
            current["api_key"] = body.llm.api_key.strip()
        _write_setting(_KEY_LLM, current)

    # --- 仿真配置 ---
    if body.sim is not None:
        current = _read_setting(_KEY_SIM, _default_sim())
        if body.sim.room_size is not None:
            current["room_size"] = body.sim.room_size
        if body.sim.robot_speed is not None:
            current["robot_speed"] = body.sim.robot_speed
        _write_setting(_KEY_SIM, current)

    # --- 数据治理配置 ---
    if body.data is not None:
        current = _read_setting(_KEY_DATA, _default_data())
        if body.data.retention_days is not None:
            current["retention_days"] = body.data.retention_days
        if body.data.auto_clean is not None:
            current["auto_clean"] = body.data.auto_clean
        _write_setting(_KEY_DATA, current)

    return {"ok": True}


@router.get("/health")
def get_health():
    """
    GET /health

    健康检查 / 运行模式探针，前端顶栏据此显示「Mock 模式」或「已接入 {provider}」。
    返回：
        { "status": "ok", "mock_mode": bool, "llm_provider": str }
    mock_mode = 未配置任何真实 API Key（含 provider=mock）。
    """
    llm_cfg = _read_setting(_KEY_LLM, _default_llm())
    return {
        "status": "ok",
        "mock_mode": _is_mock_mode(llm_cfg),
        "llm_provider": llm_cfg.get("provider", "mock"),
    }
