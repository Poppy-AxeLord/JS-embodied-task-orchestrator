# -*- coding: utf-8 -*-
"""
配置模块（技术契约 SPEC §10）
------------------------------------------------------------------
职责：
  1. 用 python-dotenv 读取 backend/.env（若存在），加载环境变量；
  2. 暴露统一的 settings 对象，集中提供 LLM_PROVIDER / 各家 API_KEY /
     LLM_MODEL / LLM_TEMPERATURE / BACKEND_PORT 等配置；
  3. 提供 is_mock_mode() 判断当前是否运行在「Mock 模式」（未配置任何真实 Key）。

产品逻辑要点：
  - 「是否 Mock」是整个数据闭环演示能否开箱即用的关键开关。
  - 判定规则：provider 为 mock，或所选 provider 对应的 API Key 为空，即视为 Mock。
    这样即使用户把 provider 填成 openai 却忘了填 Key，也不会崩，而是平滑回退到本地拆解。
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ------------------------------------------------------------------
# 1. 定位并加载 .env
#    BASE_DIR 指向 backend/ 目录（本文件所在目录）。
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"

# load_dotenv 不会覆盖系统中已存在的同名环境变量（override=False），
# 便于在部署环境用真实环境变量覆盖 .env。
load_dotenv(dotenv_path=ENV_PATH, override=False)


def _get_str(key: str, default: str = "") -> str:
    """读取字符串环境变量；None 或纯空白都归一化为默认值。"""
    val = os.getenv(key)
    if val is None:
        return default
    val = val.strip()
    return val if val else default


def _get_float(key: str, default: float) -> float:
    """读取浮点环境变量，解析失败则回退默认值。"""
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _get_int(key: str, default: int) -> int:
    """读取整数环境变量，解析失败则回退默认值。"""
    raw = os.getenv(key)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


# ------------------------------------------------------------------
# 2. 各 provider 的默认模型名（用户未显式指定 LLM_MODEL 时使用）
# ------------------------------------------------------------------
_DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "qwen": "qwen-plus",
    "zhipu": "glm-4",
    "mock": "mock-model",
}


class Settings:
    """集中式配置对象。一次实例化，全局共享（见文件底部 settings）。"""

    def __init__(self) -> None:
        # 数据目录与数据库路径（database.py 也会用到，这里统一定义一份）
        self.BASE_DIR: Path = BASE_DIR
        self.DATA_DIR: Path = BASE_DIR / "data"
        self.DB_PATH: Path = self.DATA_DIR / "app.db"
        self.DEMO_DATA_PATH: Path = self.DATA_DIR / "demo_data.json"

        # 大模型相关配置
        self.LLM_PROVIDER: str = _get_str("LLM_PROVIDER", "mock").lower()
        self.OPENAI_API_KEY: str = _get_str("OPENAI_API_KEY", "")
        self.QWEN_API_KEY: str = _get_str("QWEN_API_KEY", "")
        self.ZHIPU_API_KEY: str = _get_str("ZHIPU_API_KEY", "")

        # 模型名：未显式配置时按 provider 取默认值
        self.LLM_MODEL: str = _get_str(
            "LLM_MODEL", _DEFAULT_MODELS.get(self.LLM_PROVIDER, "mock-model")
        )

        # 采样温度与端口
        self.LLM_TEMPERATURE: float = _get_float("LLM_TEMPERATURE", 0.3)
        self.BACKEND_PORT: int = _get_int("BACKEND_PORT", 8000)

    # --------------------------------------------------------------
    # 工具方法
    # --------------------------------------------------------------
    def current_api_key(self) -> str:
        """返回「当前所选 provider」对应的 API Key（mock 没有 Key 返回空串）。"""
        mapping = {
            "openai": self.OPENAI_API_KEY,
            "qwen": self.QWEN_API_KEY,
            "zhipu": self.ZHIPU_API_KEY,
        }
        return mapping.get(self.LLM_PROVIDER, "")

    def is_mock_mode(self) -> bool:
        """
        是否处于 Mock 模式。
        规则：provider 为 mock，或当前 provider 没有配置真实 API Key。
        """
        if self.LLM_PROVIDER == "mock":
            return True
        return not bool(self.current_api_key())

    def as_dict(self) -> dict:
        """以字典形式暴露配置（不含敏感明文 Key，仅给出是否已设置）。"""
        return {
            "llm_provider": self.LLM_PROVIDER,
            "llm_model": self.LLM_MODEL,
            "llm_temperature": self.LLM_TEMPERATURE,
            "backend_port": self.BACKEND_PORT,
            "api_key_set": bool(self.current_api_key()),
            "mock_mode": self.is_mock_mode(),
        }


# ------------------------------------------------------------------
# 3. 全局单例。其它模块统一 `from config import settings` 使用。
# ------------------------------------------------------------------
settings = Settings()


def is_mock_mode() -> bool:
    """模块级便捷函数，等价于 settings.is_mock_mode()。"""
    return settings.is_mock_mode()
