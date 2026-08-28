"""DeepSeek/Qwen 共用的私有 OpenAI-compatible 编解码辅助。

为什么需要本文件：DeepSeek 和 Qwen 目前都能由 OpenAI SDK 的兼容接口
调用，请求消息、工具调用和响应结构存在大量相同转换。
把这些纯转换逻辑集中在这里，可以避免两个公开 Client 复制同一套解析代码。

为什么它不是 ModelClient：
本文件没有 ``provider`` 身份，不保存 API Key、base_url 或 SDK client，也不能注册进 ModelGateway。
真正代表 Provider 的仍然只有 DeepSeekClient 和 QwenClient。
未来两家协议出现差异时，可以把差异留在各自 Client 中，而无需改变 Gateway 的公开契约。

一次调用的数据流：

    ModelRequest
        → _build_request()       转成 OpenAI-compatible 请求字典
        → SDK chat.completions   由具体 Provider Client 持有的 SDK 发出请求
        → _parse_response()      转成 AgentSpine ModelResponse

任何 SDK 异常都会在离开本层前转换成 ModelGatewayError。
"""

import json
from collections.abc import Mapping
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)

from ..model_gateway import ModelGatewayError, ModelGatewayErrorCode
from ..models import MessageRole, ModelMessage, ModelRequest, ModelResponse, StopReason, ToolCall


async def _generate(
    *,
    provider: str,
    sdk_client: Any,
    request: ModelRequest,
    model: str,
) -> ModelResponse:
    """串起一次 OpenAI-compatible 调用，但不拥有 SDK client。

    ``provider`` 仅用于给统一错误标记来源；连接配置和 SDK client 生命周期
    仍由调用本函数的 DeepSeekClient/QwenClient 管理。
    """

    try:
        # 第一步：把完全 Provider-independent 的请求转成 SDK 接受的字典。
        payload = _build_request(request, model)
        # timeout 属于本次 ModelRequest，不是 Gateway 的全局 Provider 配置。
        if request.timeout_seconds is not None:
            payload["timeout"] = request.timeout_seconds
        # 第二步：真正网络调用由成熟 SDK 完成，本项目不自行实现 HTTP。
        response = await sdk_client.chat.completions.create(**payload)
        # 第三步：先把 SDK 对象变成普通映射，再构造统一 ModelResponse。
        return _parse_response(_response_to_mapping(response))
    except ModelGatewayError:
        # 已经归一化的异常保持原样，避免被二次包装后丢失错误码。
        raise
    except _InvalidRequest as exc:
        # 本地请求转换失败，说明请求尚未进入 Provider 调用。
        raise ModelGatewayError(
            ModelGatewayErrorCode.INVALID_REQUEST, provider, str(exc), retryable=False
        ) from None
    except Exception as exc:
        # SDK 的所有原始异常都必须在这里截止，不能泄漏给 Gateway 上层。
        raise _map_provider_error(provider, exc) from None


def _response_to_mapping(response: Any) -> Mapping[str, Any]:
    """把 SDK 响应统一成后续解析函数可读取的普通映射。

    OpenAI SDK 通常返回带 ``model_dump`` 的 Pydantic 对象；离线单元测试使用
    普通 dict。两者在这里收敛，后续逻辑便不需要感知 SDK 对象类型。
    """

    if isinstance(response, Mapping):
        return response
    model_dump = getattr(response, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump()
        if isinstance(dumped, Mapping):
            return dumped
    raise ValueError("Provider SDK 响应无法转换为映射对象")


class _InvalidRequest(ValueError):
    """请求转换阶段的私有异常，最终映射为 INVALID_REQUEST。"""

    pass


# ---------------------------------------------------------------------------
# 请求转换：AgentSpine 数据模型 → OpenAI-compatible SDK 参数
# ---------------------------------------------------------------------------
def _build_request(request: ModelRequest, model: str) -> dict[str, Any]:
    """构造 SDK ``chat.completions.create`` 所需的关键字参数。"""

    if not isinstance(request, ModelRequest):
        raise _InvalidRequest("request 必须是 ModelRequest 类型")
    if not isinstance(model, str) or not model.strip():
        raise _InvalidRequest("model 必须是非空字符串")
    payload: dict[str, Any] = {
        # model 来自 ModelConfig，由 Gateway 原样委托给 ModelClient。
        "model": model,
        # 每条统一消息都在这里转换，ModelRequest 本身不会被修改。
        "messages": [_convert_message(message) for message in request.messages],
        # V0 明确只支持非流式响应。
        "stream": False,
    }
    if request.tool_schemas:
        # 没有工具时不发送 tools 字段，避免伪造 Provider 请求数据。
        payload["tools"] = [_convert_tool_schema(schema) for schema in request.tool_schemas]
    return payload


def _convert_message(message: ModelMessage) -> dict[str, Any]:
    """把一条统一消息转换成 OpenAI-compatible 消息。

    SYSTEM/USER 只需要 role 和 content；ASSISTANT 可能携带工具提议；TOOL
    必须通过 tool_call_id 说明自己在回答哪一次工具调用。
    """

    converted: dict[str, Any] = {"role": message.role.value, "content": message.content}
    if message.role is MessageRole.ASSISTANT and message.tool_calls:
        # ToolCall.arguments 在 AgentSpine 中是 Mapping，SDK 协议要求 JSON 字符串。
        converted["tool_calls"] = [
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.tool_name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in message.tool_calls
        ]
    elif message.role is MessageRole.TOOL:
        # 这个关联 ID 让模型知道工具结果属于哪一个 Assistant ToolCall。
        converted["tool_call_id"] = message.tool_call_id
    return converted


def _convert_tool_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """把统一工具 Schema 包装成 SDK 的 ``function`` 工具结构。"""

    # 先在本地验证最小契约，非法 Schema 不应发到 Provider。
    name = schema.get("name")
    description = schema.get("description")
    parameters = schema.get("parameters")
    if not isinstance(name, str) or not name.strip():
        raise _InvalidRequest("tool schema 的 name 必须是非空字符串")
    if not isinstance(description, str) or not description.strip():
        raise _InvalidRequest("tool schema 的 description 必须是非空字符串")
    if not isinstance(parameters, Mapping):
        raise _InvalidRequest("tool schema 的 parameters 必须是映射对象")
    return {
        # 当前 V0 只支持函数式工具调用，不提前实现其他工具类型。
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": dict(parameters),
        },
    }


# ---------------------------------------------------------------------------
# 响应转换：OpenAI-compatible SDK 响应 → AgentSpine 数据模型
# ---------------------------------------------------------------------------
def _parse_response(response: Mapping[str, Any]) -> ModelResponse:
    """读取第一个模型候选，并构造 Provider-independent ModelResponse。"""

    if not isinstance(response, Mapping):
        raise ValueError("Provider 响应必须是映射对象")
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise ValueError("Provider 响应缺少有效 choices")
    # V0 不提供多候选能力，只消费 Provider 返回的第一个 choice。
    choice = choices[0]
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise ValueError("Provider 响应缺少有效 message")
    text = message.get("content")
    if text is not None and not isinstance(text, str):
        raise ValueError("Provider message.content 必须是字符串或 null")
    # 文本和工具调用可以同时存在，因此二者分别解析并一同保留。
    tool_calls = _parse_tool_calls(message.get("tool_calls"))
    return ModelResponse(
        text=text,
        tool_calls=tool_calls,
        stop_reason=_normalize_stop_reason(choice.get("finish_reason"), bool(tool_calls)),
        usage=_normalize_usage(response.get("usage")),
    )


def _parse_tool_calls(value: Any) -> tuple[ToolCall, ...]:
    """把 Provider 工具调用列表转换成待授权 ToolCall 元组。"""

    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("Provider message.tool_calls 必须是列表")
    calls: list[ToolCall] = []
    for raw_call in value:
        if not isinstance(raw_call, Mapping):
            raise ValueError("Provider tool_call 必须是映射对象")
        function = raw_call.get("function")
        if not isinstance(function, Mapping):
            raise ValueError("Provider tool_call 缺少 function")
        # Provider 通常返回 JSON 字符串；部分测试或兼容实现可能直接给 Mapping。
        arguments = function.get("arguments", "{}")
        if isinstance(arguments, str):
            arguments = json.loads(arguments)
        if not isinstance(arguments, Mapping):
            raise ValueError("Provider tool_call.arguments 必须是 JSON 对象")
        calls.append(
            ToolCall(
                call_id=raw_call.get("id"),
                tool_name=function.get("name"),
                arguments=arguments,
                # 不显式传 status，使用 ToolCall 的默认 PROPOSED。
                # 这里只解析模型提议，不授予执行权限，也不执行工具。
            )
        )
    return tuple(calls)


def _normalize_stop_reason(value: Any, has_tool_calls: bool) -> StopReason:
    """把 Provider finish_reason 映射为成功响应的统一停止原因。"""

    # 只要实际解析出 ToolCall，就以工具提议语义为准。
    if has_tool_calls:
        return StopReason.TOOL_CALLS
    return {
        "stop": StopReason.COMPLETED,
        "tool_calls": StopReason.TOOL_CALLS,
        "function_call": StopReason.TOOL_CALLS,
        "length": StopReason.LENGTH,
    # Provider 新增或未知但仍成功的原因统一落到 OTHER，不当作调用异常。
    }.get(value, StopReason.OTHER)


def _normalize_usage(value: Any) -> dict[str, int]:
    """把不同 Token 字段名归一成 input/output/total_tokens。

    Provider 没返回的字段不会推算或补零，避免产生看似精确的伪造 Usage。
    """

    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("Provider usage 必须是映射对象")
    # OpenAI-compatible 常用 prompt/completion；统一契约使用 input/output。
    aliases = {
        "input_tokens": ("input_tokens", "prompt_tokens"),
        "output_tokens": ("output_tokens", "completion_tokens"),
        "total_tokens": ("total_tokens",),
    }
    usage: dict[str, int] = {}
    for normalized, candidates in aliases.items():
        for candidate in candidates:
            token_count = value.get(candidate)
            if isinstance(token_count, int) and not isinstance(token_count, bool) and token_count >= 0:
                # 同一个统一字段只取第一个有效候选名称。
                usage[normalized] = token_count
                break
    return usage


def _map_provider_error(provider: str, exc: Exception) -> ModelGatewayError:
    """把 OpenAI SDK 及兼容 Provider 异常收敛为稳定错误码。

    既识别 SDK 的异常类型，也读取兼容 Provider 异常上的 HTTP status_code。
    ``retryable`` 只是事实描述；V0 不在这里执行 Retry。
    """

    # 部分兼容 Provider 使用 SDK 通用异常，但仍会保留 HTTP 状态码。
    status = getattr(exc, "status_code", None)
    if isinstance(exc, BadRequestError) or status == 400:
        code, retryable = ModelGatewayErrorCode.INVALID_REQUEST, False
    elif isinstance(exc, AuthenticationError) or status in {401, 403}:
        code, retryable = ModelGatewayErrorCode.AUTHENTICATION, False
    elif isinstance(exc, RateLimitError) or status == 429:
        code, retryable = ModelGatewayErrorCode.RATE_LIMIT, True
    elif isinstance(exc, (APITimeoutError, TimeoutError)) or status in {408, 504}:
        code, retryable = ModelGatewayErrorCode.TIMEOUT, True
    elif isinstance(exc, (APIConnectionError, ConnectionError, OSError)) or (
        isinstance(status, int) and status >= 500
    ):
        code, retryable = ModelGatewayErrorCode.PROVIDER_UNAVAILABLE, True
    else:
        code, retryable = ModelGatewayErrorCode.PROVIDER_ERROR, False
    return ModelGatewayError(code, provider, str(exc) or "Provider 调用失败", retryable)
