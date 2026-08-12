# -*- coding: utf-8 -*-
"""
大模型服务层 LLMService
====================================================================
本模块封装"对话补全"能力，统一对外暴露 `chat(system, user) -> str` 方法，
屏蔽 OpenAI / 通义千问(qwen) / 智谱(zhipu) 三家厂商的接口差异。

设计要点（产品逻辑）：
1. **Mock 优先、永不崩溃**：演示/无网络/无 API Key 的场景下，必须能跑通全部
   功能。因此当 provider == "mock" 或对应厂商的 api_key 缺失时，
   `is_mock = True`，`chat()` 直接转调本地 `mock.mock_llm.mock_chat`，
   不发任何网络请求。
2. **真实调用容错回退**：即便配置了 Key，真实网络请求也可能超时/限流/报错。
   任何异常都会被捕获并**回退到 Mock**，保证上层（task_parser）拿到可用文本，
   绝不让整个请求 500 崩溃。
3. **三家差异**：三家都"兼容 OpenAI 的 Chat Completions 形状"，但 base_url、
   默认 model、鉴权 header 略有不同，见下方各 _call_* 方法注释。

注意：本类只负责"把一段对话发出去、拿一段文本回来"。如何把这段文本解析成
结构化拆解（ParsedTask），是 task_parser 的职责，不在此处耦合。
"""

from __future__ import annotations

import logging

import httpx

# 本地 Mock 兜底实现：无网络也能产出合理文本
# 绝对导入：以 `uvicorn main:app`（在 backend 目录）启动时 mock 为顶层包
from mock import mock_llm

# 模块级日志器，所有日志中文输出，便于运维排查
logger = logging.getLogger("llm_service")


# 各厂商默认配置：base_url（OpenAI 兼容的 chat/completions 接口）+ 默认模型名
# 三家均提供"OpenAI 兼容模式"，因此可以共用同一套 _post_openai_compatible 逻辑。
_PROVIDER_DEFAULTS = {
    # OpenAI 官方：标准 Chat Completions
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
    },
    # 通义千问（阿里云灵积 DashScope）兼容模式：
    # base_url 末尾为 /compatible-mode/v1，调用方式与 OpenAI 完全一致
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "default_model": "qwen-plus",
    },
    # 智谱 AI（GLM 系列）：开放平台提供 /api/paas/v4 的 OpenAI 兼容接口
    "zhipu": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "default_model": "glm-4-flash",
    },
}


class LLMService:
    """大模型对话服务。

    构造参数 `config` 为一个 dict（来自 backend/config.py 读取的环境变量），
    至少包含以下键（缺失时取合理默认）：
        - provider:   "openai" | "qwen" | "zhipu" | "mock"
        - openai_api_key / qwen_api_key / zhipu_api_key: 各家 Key（可空）
        - model:      指定模型名（可空，空则用该 provider 的默认模型）
        - temperature: 采样温度，默认 0.3（拆解任务偏确定性）

    公开属性：
        - provider: str   当前厂商标识
        - is_mock:  bool  是否处于 Mock 模式（无真实 Key 或 provider=mock）
    """

    def __init__(self, config: dict):
        # 容错：config 可能为 None，统一成 dict
        config = config or {}
        self.config = config

        # 1) 读取 provider，并做小写规整；无法识别的一律视为 mock
        provider = str(config.get("provider", "mock") or "mock").lower().strip()
        if provider not in _PROVIDER_DEFAULTS and provider != "mock":
            logger.warning("未知的 LLM provider=%s，已回退为 mock 模式", provider)
            provider = "mock"
        self.provider = provider

        # 2) 根据 provider 取出对应的 API Key
        #    约定 config 中的键名为 "{provider}_api_key"
        self.api_key = ""
        if provider != "mock":
            self.api_key = str(config.get(f"{provider}_api_key", "") or "").strip()

        # 3) 解析 base_url 与 model（允许 config 覆盖默认值）
        defaults = _PROVIDER_DEFAULTS.get(provider, {})
        self.base_url = str(
            config.get("base_url") or defaults.get("base_url", "")
        ).rstrip("/")
        self.model = str(
            config.get("model") or defaults.get("default_model", "")
        ).strip()

        # 4) 采样温度，拆解任务希望偏稳定，默认 0.3
        try:
            self.temperature = float(config.get("temperature", 0.3))
        except (TypeError, ValueError):
            self.temperature = 0.3

        # 5) 判定是否 Mock：provider=mock 或缺少真实 Key 即为 Mock 模式
        self.is_mock = provider == "mock" or not self.api_key

        if self.is_mock:
            logger.info("LLMService 初始化为 Mock 模式（provider=%s）", provider)
        else:
            logger.info(
                "LLMService 初始化完成：provider=%s, model=%s", provider, self.model
            )

    # ------------------------------------------------------------------
    # 对外主方法
    # ------------------------------------------------------------------
    def chat(self, system: str, user: str) -> str:
        """发起一次对话补全，返回模型回复的纯文本。

        参数：
            system: 系统提示词（设定角色与输出格式约束）
            user:   用户消息（具体的任务指令等）
        返回：
            模型回复文本（str）。Mock 模式或真实调用异常时，返回 Mock 文本。
        """
        # Mock 模式：直接走本地兜底，不联网
        if self.is_mock:
            return mock_llm.mock_chat(system, user)

        # 真实模式：根据 provider 分派；任何异常都回退到 Mock，保证不崩溃
        try:
            if self.provider in ("openai", "qwen", "zhipu"):
                # 三家均为 OpenAI 兼容形状，复用同一实现
                return self._post_openai_compatible(system, user)
            # 理论上不会走到这里（构造时已规整），兜底回退
            return mock_llm.mock_chat(system, user)
        except Exception as exc:  # noqa: BLE001 —— 故意捕获所有异常以保证服务可用
            logger.warning(
                "调用真实大模型失败（provider=%s）：%s —— 已自动回退到 Mock 模式",
                self.provider,
                exc,
            )
            return mock_llm.mock_chat(system, user)

    # ------------------------------------------------------------------
    # 内部实现：OpenAI 兼容 Chat Completions
    # ------------------------------------------------------------------
    def _post_openai_compatible(self, system: str, user: str) -> str:
        """以 OpenAI 兼容协议发送请求。

        三家厂商差异说明：
          - **OpenAI**：base_url = https://api.openai.com/v1，
            鉴权 header 为 `Authorization: Bearer <OPENAI_API_KEY>`。
          - **通义千问 qwen**：使用 DashScope 的"兼容模式"
            base_url = .../compatible-mode/v1，鉴权同为 Bearer，
            模型名如 qwen-plus / qwen-turbo。请求体与 OpenAI 完全一致。
          - **智谱 zhipu**：base_url = .../api/paas/v4，鉴权同为 Bearer
            （新版 GLM 开放平台已支持直接 Bearer <ZHIPU_API_KEY>），
            模型名如 glm-4-flash / glm-4。请求体与 OpenAI 一致。

        因为三家请求/响应形状一致，这里用统一逻辑处理，仅 base_url / model
        / api_key 不同。
        """
        url = f"{self.base_url}/chat/completions"

        # 统一的鉴权与内容类型头部
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        # OpenAI 兼容请求体：messages 数组 + 温度等采样参数
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            # 拆解 JSON 通常不会太长，限制最大输出长度，避免超时
            "max_tokens": 1500,
        }

        # 使用 httpx 同步客户端，设置合理超时（连接/读取）
        # 失败会抛异常，由上层 chat() 捕获并回退 Mock
        with httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        # 解析 OpenAI 兼容响应：choices[0].message.content
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            # 响应形状异常时也抛出，交由上层回退 Mock
            raise ValueError(f"大模型返回结构不符合预期：{data}") from exc

        return content if isinstance(content, str) else str(content)
