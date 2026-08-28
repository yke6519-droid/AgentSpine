"""DeepSeek 的独立 Provider ModelClient。"""

import os

from openai import AsyncOpenAI

from ..model_gateway import ModelGatewayError, ModelGatewayErrorCode
from ..models import ModelRequest, ModelResponse
from ._openai_compatible import _generate


class DeepSeekClient:
    """封装 DeepSeek 连接配置和内部异步 SDK client。

    本类代表已经配置完成的 DeepSeek 连接。它拥有底层 SDK client，调用者
    只能通过统一的 ``generate`` 接口使用它，不能把原始 SDK client 注入进来。
    """

    # Gateway 使用该名称解析 DeepSeekClient。
    provider = "deepseek"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = "https://api.deepseek.com",
    ) -> None:
        # 显式参数优先；未传入时才读取标准环境变量。
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not isinstance(self.api_key, str) or not self.api_key.strip():
            raise ModelGatewayError(
                ModelGatewayErrorCode.AUTHENTICATION,
                self.provider,
                "DeepSeek API Key 未配置，请显式传入或设置 DEEPSEEK_API_KEY",
                retryable=False,
            )
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url 必须是非空字符串")
        # base_url 属于 DeepSeekClient 自己，不进入 ModelConfig 或 Gateway。
        self.base_url = base_url
        # V0 由 Provider Client 自己创建并独占底层 SDK client。
        try:
            self._sdk_client = AsyncOpenAI(api_key=self.api_key, base_url=base_url)
        except Exception as exc:
            raise ModelGatewayError(
                ModelGatewayErrorCode.INVALID_REQUEST,
                self.provider,
                f"DeepSeek SDK client 创建失败：{exc}",
                retryable=False,
            ) from None

    async def generate(self, request: ModelRequest, model: str) -> ModelResponse:
        """调用 DeepSeek，并返回 AgentSpine 统一的 ModelResponse。"""

        # 两家 Provider 当前协议相似，因此只复用私有编解码流程。
        return await _generate(
            provider=self.provider,
            sdk_client=self._sdk_client,
            request=request,
            model=model,
        )
