"""Tool 定义、能力描述与调用生命周期模型。"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

from ._validation import (
    require_aware_datetime,
    require_enum,
    require_non_empty,
    require_time_order,
)


class Effect(str, Enum):
    """工具执行时会影响的系统边界。"""

    # 纯本地计算，不访问网络或外部系统。
    NONE = "none"
    # 会访问网络，但不一定修改外部系统。
    NETWORK = "network"
    # 会对数据库、第三方服务等外部系统产生影响。
    EXTERNAL = "external"
    # 当前无法确定工具是否会产生外部影响。
    UNKNOWN = "unknown"


class Replay(str, Enum):
    """同一工具调用能否安全地再次执行。"""

    # 可安全重复执行，不会产生不期望的额外效果。
    SAFE = "safe"
    # 重复执行可能发生调用，但最终外部状态与执行一次相同。
    IDEMPOTENT = "idempotent"
    # 重复执行可能产生重复写入、扣款、发送消息等副作用。
    UNSAFE = "unsafe"
    # 当前无法判断重复执行是否安全。
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ToolCapability:
    """Policy 可读取的统一工具执行属性，不代表风险等级。"""

    # 工具会触达的系统边界。
    effect: Effect = Effect.UNKNOWN
    # 工具调用失败或中断后是否适合重放。
    replay: Replay = Replay.UNKNOWN

    def __post_init__(self) -> None:
        require_enum(self.effect, Effect, "effect")
        require_enum(self.replay, Replay, "replay")


# 工具处理函数可以同步返回结果，也可以返回由执行层 await 的异步结果。
ToolHandler = Callable[[Mapping[str, Any]], Any | Awaitable[Any]]


@dataclass(frozen=True, slots=True)
class Tool:
    """可注册工具的定义；本模型本身不负责参数校验或执行。

    ToolManager 后续会读取该定义完成注册、Schema 校验和调用。模型只能看到
    可公开的名称、描述与参数 Schema，不会直接获得 ``handler`` 执行权限。
    """

    # 工具的唯一名称，也是模型在 ToolCall 中使用的名称。
    name: str
    # 面向模型和开发者的工具用途说明。
    description: str
    # 真正执行领域逻辑的 Python 可调用对象。
    handler: ToolHandler
    # JSON-Schema 风格的参数契约；本阶段仅保存，不负责校验。
    parameters_schema: Mapping[str, Any] = field(default_factory=dict)
    # Policy 和 Retry 逻辑可读取的确定性能力描述。
    capability: ToolCapability = field(default_factory=ToolCapability)

    def __post_init__(self) -> None:
        require_non_empty(self.name, "name")
        require_non_empty(self.description, "description")
        if not callable(self.handler):
            raise TypeError("handler 必须是可调用对象")
        if not isinstance(self.parameters_schema, Mapping):
            raise TypeError("parameters_schema 必须是映射对象")
        if not isinstance(self.capability, ToolCapability):
            raise TypeError("capability 必须是 ToolCapability 类型")


class ToolCallStatus(str, Enum):
    """一个 ToolCall 从模型提议到结束的生命周期。"""

    # 模型已提出调用，但尚未获得执行许可。
    PROPOSED = "proposed"
    # 已通过必要检查，工具正在执行。
    RUNNING = "running"
    # 工具已成功执行。
    SUCCEEDED = "succeeded"
    # 工具执行过程中发生错误。
    FAILED = "failed"
    # ToolCall 未通过工具解析或参数契约校验，尚未进入 Policy。
    REJECTED = "rejected"
    # Policy 明确拒绝了本次执行。
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class ToolCall:
    """模型提出的待授权工具调用，以及其可观察生命周期快照。

    创建 ToolCall 只说明“模型希望调用工具”，不表示已经获得执行权。
    """

    # 单次工具调用的唯一标识，用于关联 ToolResult 和 Trace。
    call_id: str
    # 模型希望调用的工具名称。
    tool_name: str
    # 模型提供的原始参数；后续必须先经过 Schema 校验。
    arguments: Mapping[str, Any] = field(default_factory=dict)
    # 当前调用所处的生命周期阶段。
    status: ToolCallStatus = ToolCallStatus.PROPOSED
    # 工具实际开始执行的时间；尚未执行时为 None。
    started_at: datetime | None = None
    # 工具成功、失败、校验被拒或 Policy 拒绝的时间。
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.call_id, "call_id")
        require_non_empty(self.tool_name, "tool_name")
        if not isinstance(self.arguments, Mapping):
            raise TypeError("arguments 必须是映射对象")
        require_enum(self.status, ToolCallStatus, "status")
        require_aware_datetime(self.started_at, "started_at")
        require_aware_datetime(self.finished_at, "finished_at")
        require_time_order(self.started_at, self.finished_at)


class ToolResultStatus(str, Enum):
    """工具执行结果的成功或失败状态。"""

    # 工具正常返回结果。
    SUCCESS = "success"
    # 工具解析、校验或执行过程中发生错误。
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class ToolResult:
    """一次工具执行的结构化结果。

    垂直业务工具可以自行组织 ``message``，向 Agent 说明执行结果或失败原因；
    Agent 应使用 ``error_code`` 判断错误类型，而不依赖解析自然语言。
    """

    # 对应 ToolCall 的唯一标识。
    call_id: str
    # 实际解析或执行的工具名称。
    tool_name: str
    # 本次执行成功或失败。
    status: ToolResultStatus
    # 成功时的结果；具体类型由工具决定。
    output: Any = None
    # 工具自行封装的可读说明；失败时必须提供，成功时可以省略。
    message: str | None = None
    # 失败时供程序判断错误类别的稳定代码。
    error_code: str | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.call_id, "call_id")
        require_non_empty(self.tool_name, "tool_name")
        require_enum(self.status, ToolResultStatus, "status")
        if self.status is ToolResultStatus.ERROR:
            require_non_empty(self.message, "message")
        elif self.message is not None:
            require_non_empty(self.message, "message")
