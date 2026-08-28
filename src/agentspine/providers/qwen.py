"""Qwen 的独立 Provider ModelClient。"""

import os

from openai import AsyncOpenAI

from ..model_gateway import ModelGatewayError, ModelGatewayErrorCode
from ..models import ModelRequest, ModelResponse
from ._openai_compatible import _generate


class QwenClient:
    """封装 Qwen 连接配置和内部异步 SDK client。

    Qwen 可能因地域或工作空间使用不同 base_url，所以连接配置必须由本类
    自己持有，不能放到 ModelConfig 或 ModelGateway 的全局配置中。
    """

    # Gateway 使用该名称解析 QwenClient；它与 DeepSeek 身份完全独立。
    provider = "qwen"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ) -> None:
        # 显式参数优先；未传入时才读取 DashScope 标准环境变量。
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ModelGatewayError(
                ModelGatewayErrorCode.AUTHENTICATION,
                self.provider,
                "Qwen API Key 未配置，请显式传入或设置 DASHSCOPE_API_KEY",
                retryable=False,
            )
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url 必须是非空字符串")
        self.base_url = base_url
        # base_url 只属于这个 QwenClient，不进入 Gateway 或 ModelConfig。
        try:
            self._sdk_client = AsyncOpenAI(api_key=self.api_key, base_url=base_url)
        except Exception as exc:
            raise ModelGatewayError(
                ModelGatewayErrorCode.INVALID_REQUEST,
                self.provider,
                f"Qwen SDK client 创建失败：{exc}",
                retryable=False,
            ) from None

    async def generate(self, request: ModelRequest, model: str) -> ModelResponse:
        """调用 Qwen，并返回 AgentSpine 统一的 ModelResponse。"""

        # SDK client 仍属于 QwenClient；共享辅助层不会保存 Provider 配置。
        return await _generate(
            provider=self.provider,
            sdk_client=self._sdk_client,
            request=request,
            model=model,
        )
