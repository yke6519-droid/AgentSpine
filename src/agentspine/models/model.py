"""Provider 无关的最小模型请求与响应契约。"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ._validation import require_enum, require_non_empty
from .tool import ToolCall


class MessageRole(str, Enum):
    """消息在单次模型上下文中的角色。"""

    # Harness 提供的系统指令。
    SYSTEM = "system"
    # 当前用户输入。
    USER = "user"
    # 模型在当前 Run 内产生的消息。
    ASSISTANT = "assistant"
    # 工具结果重新注入模型上下文时使用的消息。
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class ModelMessage:
    """单个 Run 内提供给模型的一条消息。"""

    # 消息发送方或消息用途。
    role: MessageRole
    # 提供给模型的文本内容；允许空字符串以兼容部分 Provider 响应。
    content: str

    def __post_init__(self) -> None:
        require_enum(self.role, MessageRole, "role")
        if not isinstance(self.content, str):
            raise TypeError("content 必须是字符串")


@dataclass(frozen=True, slots=True)
class ModelRequest:
    """ModelGateway 将来消费的 Provider 无关请求。

    该对象只表达 Harness 需要什么，不包含任何特定供应商的请求格式。
    """

    # 所属 Run，用于把模型调用记录关联回完整执行过程。
    run_id: str
    # 按发送顺序排列的单次 Run 上下文消息。
    messages: tuple[ModelMessage, ...]
    # 当前允许模型选择的工具 Schema，不包含 Python handler。
    tool_schemas: tuple[Mapping[str, Any], ...] = ()
    # 单次模型请求的超时时间；None 表示使用上层默认配置。
    timeout_seconds: float | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.run_id, "run_id")
        if not isinstance(self.messages, tuple) or not all(
            isinstance(message, ModelMessage) for message in self.messages
        ):
            raise TypeError("messages 必须是由 ModelMessage 组成的元组")
        if not self.messages:
            raise ValueError("messages 不能为空")
        if not isinstance(self.tool_schemas, tuple) or not all(
            isinstance(schema, Mapping) for schema in self.tool_schemas
        ):
            raise TypeError("tool_schemas 必须是由映射对象组成的元组")
        if self.timeout_seconds is not None and (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("提供 timeout_seconds 时，其值必须大于 0")


class StopReason(str, Enum):
    """模型停止生成内容的归一化原因。"""

    # 模型正常完成回答。
    COMPLETED = "completed"
    # 模型请求调用一个或多个工具。
    TOOL_CALLS = "tool_calls"
    # 因长度或 Token 上限停止。
    LENGTH = "length"
    # Provider 调用或响应处理失败。
    ERROR = "error"
    # Provider 返回了当前契约尚未单独归类的原因。
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class ModelResponse:
    """不同 Model Provider 的统一基础响应。"""

    # 模型生成的文本；纯工具调用响应可以没有文本。
    text: str | None = None
    # 模型提出的工具调用，仅代表提议，不代表允许执行。
    tool_calls: tuple[ToolCall, ...] = ()
    # 模型停止生成的归一化原因。
    stop_reason: StopReason = StopReason.COMPLETED
    # Token 等计量数据；键名由后续 Gateway 统一。
    usage: Mapping[str, int] = field(default_factory=dict)
    # Provider 调用失败时的人类可读错误信息。
    error: str | None = None

    def __post_init__(self) -> None:
        if self.text is not None and not isinstance(self.text, str):
            raise TypeError("text 必须是字符串或 None")
        if not isinstance(self.tool_calls, tuple) or not all(
            isinstance(call, ToolCall) for call in self.tool_calls
        ):
            raise TypeError("tool_calls 必须是由 ToolCall 组成的元组")
        require_enum(self.stop_reason, StopReason, "stop_reason")
        _validate_usage(self.usage)
        if self.stop_reason is StopReason.ERROR:
            require_non_empty(self.error, "error")
        elif self.error is not None:
            raise ValueError("设置 error 时，stop_reason 必须为 ERROR")


def _validate_usage(usage: Mapping[str, int]) -> None:
    if not isinstance(usage, Mapping):
        raise TypeError("usage 必须是映射对象")
    if any(
        not isinstance(key, str)
        or not key
        or not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
        for key, value in usage.items()
    ):
        raise ValueError("usage 的键必须是非空字符串，值必须是非负整数")
