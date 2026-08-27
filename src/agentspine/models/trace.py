"""RunResult 及最小结构化 Trace 记录。"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from ._validation import (
    require_aware_datetime,
    require_enum,
    require_non_empty,
    require_time_order,
)
from .model import ModelRequest, ModelResponse
from .policy import PolicyDecision
from .runtime import RunStatus
from .tool import ToolCall, ToolResult


@dataclass(frozen=True, slots=True)
class ModelCallRecord:
    """一次完整模型调用的请求、响应和耗时边界。"""

    # 实际处理本次调用的 Provider，例如 openai 或 anthropic。
    provider: str
    # 实际处理本次调用的模型名称。
    model: str
    # 实际发送给 ModelGateway 的统一请求。
    request: ModelRequest
    # ModelGateway 返回的统一响应。
    response: ModelResponse
    # 模型调用开始时间。
    started_at: datetime
    # 模型调用结束时间。
    finished_at: datetime

    def __post_init__(self) -> None:
        require_non_empty(self.provider, "provider")
        require_non_empty(self.model, "model")
        if not isinstance(self.request, ModelRequest):
            raise TypeError("request 必须是 ModelRequest 类型")
        if not isinstance(self.response, ModelResponse):
            raise TypeError("response 必须是 ModelResponse 类型")
        require_aware_datetime(self.started_at, "started_at")
        require_aware_datetime(self.finished_at, "finished_at")
        require_time_order(self.started_at, self.finished_at)


@dataclass(frozen=True, slots=True)
class ToolCallRecord:
    """一个 ToolCall 从提议、Policy 判断到执行结果的 Trace。"""

    # 模型提出的工具调用及其生命周期快照。
    call: ToolCall
    # Policy 判断；未知工具或参数非法发生在 Policy 前，因此可以为 None。
    decision: PolicyDecision | None
    # 工具处理结果；被拒绝或尚未执行时可以为 None。
    result: ToolResult | None
    # 工具真正开始执行的时间，而不是模型提出调用的时间。
    started_at: datetime | None = None
    # 工具执行或前置处理结束的时间。
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.call, ToolCall):
            raise TypeError("call 必须是 ToolCall 类型")
        if self.decision is not None and not isinstance(self.decision, PolicyDecision):
            raise TypeError("decision 必须是 PolicyDecision 或 None")
        if self.result is not None:
            if not isinstance(self.result, ToolResult):
                raise TypeError("result 必须是 ToolResult 或 None")
            if self.result.call_id != self.call.call_id:
                raise ValueError("result.call_id 必须与 call.call_id 一致")
            if self.result.tool_name != self.call.tool_name:
                raise ValueError("result.tool_name 必须与 call.tool_name 一致")
        require_aware_datetime(self.started_at, "started_at")
        require_aware_datetime(self.finished_at, "finished_at")
        require_time_order(self.started_at, self.finished_at)


@dataclass(frozen=True, slots=True)
class TraceError:
    """供调试、评估和 UI 使用的结构化错误记录。"""

    # 错误来源模块，例如 model、tool、policy 或 runtime。
    source: str
    # 供程序稳定识别错误类别的代码。
    code: str
    # 面向开发者或最终用户的可读错误说明。
    message: str
    # 错误发生时间。
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # 错误关联的 ToolCall；非工具错误时为 None。
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.source, "source")
        require_non_empty(self.code, "code")
        require_non_empty(self.message, "message")
        require_aware_datetime(self.occurred_at, "occurred_at")
        if self.tool_call_id is not None:
            require_non_empty(self.tool_call_id, "tool_call_id")


class RunStopReason(str, Enum):
    """整个 Run 停止的原因，与单次模型调用的 StopReason 区分。"""

    # 正常获得最终输出。
    COMPLETED = "completed"
    # 因无法继续处理的错误结束。
    ERROR = "error"
    # 达到 Run.max_steps 限制。
    MAX_STEPS = "max_steps"
    # 达到 Run.max_tool_calls 限制。
    MAX_TOOL_CALLS = "max_tool_calls"
    # 达到 Run.timeout_seconds 限制。
    TIMEOUT = "timeout"
    # 因用户或上层系统请求取消而结束。
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RunResult:
    """一次 Run 的终态输出和结构化可观察性数据。

    这是上层调用者最终拿到的统一结果，同时为调试、Policy、评估和 UI
    提供最小 Trace。它只描述已经发生的事实，不负责持久化或恢复。
    """

    # 对应 Run 的唯一标识。
    run_id: str
    # Run 的最终生命周期状态，只允许终态。
    status: RunStatus
    # 正常完成时返回给调用者的文本结果；失败时可以为 None。
    final_output: str | None
    # Run 为什么停止，用于补充 status 无法表达的细节。
    stop_reason: RunStopReason
    # 本次 Run 内按执行顺序记录的所有模型调用。
    model_calls: tuple[ModelCallRecord, ...] = ()
    # 本次 Run 内按处理顺序记录的所有工具调用。
    tool_calls: tuple[ToolCallRecord, ...] = ()
    # 跨 Runtime、Model、Tool、Policy 汇总的结构化错误。
    errors: tuple[TraceError, ...] = ()
    # 汇总后的 Token 等计量数据。
    usage: Mapping[str, int] = field(default_factory=dict)
    # Run 开始执行的时间；创建后立即失败时可以为 None。
    started_at: datetime | None = None
    # Run 进入终态的时间。
    finished_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        require_non_empty(self.run_id, "run_id")
        require_enum(self.status, RunStatus, "status")
        if self.status in {RunStatus.PENDING, RunStatus.RUNNING}:
            raise ValueError("RunResult 必须使用终态 RunStatus")
        if self.final_output is not None and not isinstance(self.final_output, str):
            raise TypeError("final_output 必须是字符串或 None")
        require_enum(self.stop_reason, RunStopReason, "stop_reason")
        _require_tuple_of(self.model_calls, ModelCallRecord, "model_calls")
        _require_tuple_of(self.tool_calls, ToolCallRecord, "tool_calls")
        _require_tuple_of(self.errors, TraceError, "errors")
        if not isinstance(self.usage, Mapping) or any(
            not isinstance(key, str)
            or not key
            or not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
            for key, value in self.usage.items()
        ):
            raise ValueError("usage 的键必须是非空字符串，值必须是非负整数")
        require_aware_datetime(self.started_at, "started_at")
        require_aware_datetime(self.finished_at, "finished_at")
        require_time_order(self.started_at, self.finished_at)


def _require_tuple_of(value: object, item_type: type, field_name: str) -> None:
    if not isinstance(value, tuple) or not all(isinstance(item, item_type) for item in value):
        raise TypeError(f"{field_name} 必须是由 {item_type.__name__} 组成的元组")
