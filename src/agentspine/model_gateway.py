"""Provider 无关的模型调用入口与错误契约。

本模块只定义“如何选择并调用一个已经配置完成的模型客户端”。它不创建
DeepSeek/Qwen 的 SDK client，也不理解任何 Provider 请求字段。
"""

from dataclasses import dataclass
from enum import Enum
from inspect import iscoroutinefunction
from typing import Protocol

from .models import ModelRequest, ModelResponse
from .models._validation import require_non_empty


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """一次模型调用所选择的 Provider 和模型。

    连接信息不属于本对象：API Key、base_url 和底层 SDK client 都由具体
    ModelClient 管理。这样同一个 ModelRequest 可以只换配置，不改请求内容。
    """

    # 用来从 ModelGateway 注册表中查找 ModelClient，例如 ``deepseek``。
    provider: str
    # 传给 Provider 的实际模型名称；Gateway 不解释这个字符串。
    model: str

    def __post_init__(self) -> None:
        require_non_empty(self.provider, "provider")
        require_non_empty(self.model, "model")


class ModelClient(Protocol):
    """已配置完成、可以调用一个具体 Provider 的最小异步协议。

    Protocol 只约束公开形状，不提供实现。DeepSeekClient 和 QwenClient
    分别负责连接自己的 Provider，并把结果统一成 ModelResponse。
    """

    # Provider 的稳定注册名称，也是 ModelConfig.provider 的匹配目标。
    provider: str

    async def generate(self, request: ModelRequest, model: str) -> ModelResponse:
        """把统一请求交给 Provider，并返回统一响应。"""


class ModelGatewayErrorCode(str, Enum):
    """上层可以稳定判断的模型调用错误类型。"""

    # ModelConfig 指定的 Provider 没有注册对应 ModelClient。
    PROVIDER_NOT_FOUND = "provider_not_found"
    # AgentSpine 请求或 Provider 请求参数不合法。
    INVALID_REQUEST = "invalid_request"
    # API Key 缺失、错误或没有访问权限。
    AUTHENTICATION = "authentication"
    # Provider 拒绝调用，因为当前请求频率或额度达到限制。
    RATE_LIMIT = "rate_limit"
    # 模型调用超过允许时间。
    TIMEOUT = "timeout"
    # 网络连接失败，或 Provider 服务端暂时不可用。
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    # 无法归入以上类型的 Provider/SDK 调用错误。
    PROVIDER_ERROR = "provider_error"


class ModelGatewayError(Exception):
    """Gateway/ModelClient 向上层暴露的统一异常。

    上层只依赖这些稳定字段，不需要导入或识别 OpenAI SDK 的异常类型。
    ``retryable`` 只表达“技术上是否值得重试”，本阶段不负责实际重试。
    """

    def __init__(self, code: ModelGatewayErrorCode, provider: str, message: str, retryable: bool) -> None:
        if not isinstance(code, ModelGatewayErrorCode):
            raise TypeError("code 必须是 ModelGatewayErrorCode 类型")
        require_non_empty(provider, "provider")
        require_non_empty(message, "message")
        if not isinstance(retryable, bool):
            raise TypeError("retryable 必须是布尔值")
        # 供确定性代码进行分支判断的稳定错误码。
        self.code = code
        # 发生错误的 Provider，便于 Trace 和日志定位。
        self.provider = provider
        # 面向开发者或用户的可读错误说明。
        self.message = message
        # 仅作为后续 Retry Policy 的输入，不在这里触发重试。
        self.retryable = retryable
        super().__init__(message)


class ModelGateway:
    """保存 ModelClient 注册表，并把统一请求委托给选定 Provider。

    Gateway 是一个很薄的路由层：注册、查找、委托。Provider-specific 的
    payload、认证、错误映射都必须留在 ModelClient 或其私有辅助层。
    """

    def __init__(self) -> None:
        # 一个 Provider 只能对应一个 ModelClient，防止注册时被静默覆盖。
        self._clients: dict[str, ModelClient] = {}

    def register_client(self, client: ModelClient) -> None:
        """注册 ModelClient；不接受原始 Provider SDK client。"""

        # Protocol 在运行时不会自动校验，因此在注册边界检查必要成员。
        provider = getattr(client, "provider", None)
        generate = getattr(client, "generate", None)
        if (
            not isinstance(provider, str)
            or not provider.strip()
            or not callable(generate)
            or not iscoroutinefunction(generate)
        ):
            raise TypeError("client 必须实现 ModelClient 协议")
        if provider in self._clients:
            raise ModelGatewayError(
                ModelGatewayErrorCode.INVALID_REQUEST,
                provider,
                f"Provider ModelClient 已注册：{provider}",
                retryable=False,
            )
        self._clients[provider] = client

    def resolve_client(self, provider: str) -> ModelClient:
        """按 Provider 名称查找已配置完成的 ModelClient。"""

        require_non_empty(provider, "provider")
        try:
            return self._clients[provider]
        except KeyError:
            raise ModelGatewayError(
                ModelGatewayErrorCode.PROVIDER_NOT_FOUND,
                provider,
                f"未注册 Provider ModelClient：{provider}",
                retryable=False,
            ) from None

    async def generate(self, request: ModelRequest, config: ModelConfig) -> ModelResponse:
        """找到 config.provider 对应的 Client，并异步委托一次模型调用。

        Gateway 不修改 request，也不捕获 Provider SDK 异常；具体 ModelClient
        必须先把 SDK 异常转换成 ModelGatewayError 再向上传递。
        """

        if not isinstance(request, ModelRequest):
            raise TypeError("request 必须是 ModelRequest 类型")
        if not isinstance(config, ModelConfig):
            raise TypeError("config 必须是 ModelConfig 类型")
        # 这里没有任何 ``if provider == ...``，新增 Provider 只需注册新 Client。
        return await self.resolve_client(config.provider).generate(request, config.model)
