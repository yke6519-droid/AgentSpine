"""Run 身份配置与当前执行状态。"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from ._validation import (
    require_aware_datetime,
    require_enum,
    require_non_empty,
    require_time_order,
)
from .tool import ToolCall


class RunStatus(str, Enum):
    """一次 Run 的生命周期状态。"""

    # 已创建，尚未开始执行。
    PENDING = "pending"
    # 正在执行模型调用、工具调用或其他运行步骤。
    RUNNING = "running"
    # 已正常完成并产生最终结果。
    COMPLETED = "completed"
    # 因执行错误而终止。
    FAILED = "failed"
    # 收到取消请求后终止。
    CANCELLED = "cancelled"
    # 超过允许的执行时间后终止。
    TIMED_OUT = "timed_out"


@dataclass(frozen=True, slots=True)
class Run:
    """一次 Run 的不可变身份、输入与执行限制。

    这里保存的是创建 Run 时就确定的配置；执行过程中不断变化的数据放在
    ``RuntimeState`` 中，避免同一状态出现两个数据源。
    """

    # 一次执行的唯一标识，用于关联 RuntimeState、Trace 和 RunResult。
    run_id: str
    # 用户触发本次 Run 的原始输入。
    user_input: str
    # Agent Loop 最多允许推进的步骤数。
    max_steps: int
    # 本次 Run 最多允许执行的工具调用次数。
    max_tool_calls: int
    # 本次 Run 允许执行的总时长，单位为秒。
    timeout_seconds: float
    # Run 的创建时间；统一使用带时区的 UTC 时间。
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        require_non_empty(self.run_id, "run_id")
        require_non_empty(self.user_input, "user_input")
        if not isinstance(self.max_steps, int) or isinstance(self.max_steps, bool) or self.max_steps <= 0:
            raise ValueError("max_steps 必须是正整数")
        if (
            not isinstance(self.max_tool_calls, int)
            or isinstance(self.max_tool_calls, bool)
            or self.max_tool_calls <= 0
        ):
            raise ValueError("max_tool_calls 必须是正整数")
        if (
            not isinstance(self.timeout_seconds, (int, float))
            or isinstance(self.timeout_seconds, bool)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds 必须大于 0")
        require_aware_datetime(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class RuntimeState:
    """仅保存当前 Run 的瞬时执行状态，由未来 RuntimeManager 管理。

    ``frozen=True`` 表示状态快照不能被业务代码原地修改。未来的
    RuntimeManager 应基于旧快照创建新快照，从而保持状态变更可追踪。
    """

    # 所属 Run 的唯一标识。
    run_id: str
    # Run 当前所处的生命周期阶段，默认为pending状态
    status: RunStatus = RunStatus.PENDING
    # 已推进的 Agent Loop 步骤数。
    step_count: int = 0
    # 当前 Run 已发生的重试次数。
    retry_count: int = 0
    # 当前正在处理的工具调用；没有工具执行时为 None。
    current_tool_call: ToolCall | None = None
    # 是否已收到取消请求；它只记录请求，不负责执行取消动作。
    cancel_requested: bool = False
    # Run 真正开始执行的时间。
    started_at: datetime | None = None
    # Run 进入终态的时间。
    finished_at: datetime | None = None

    def __post_init__(self) -> None:
        require_non_empty(self.run_id, "run_id")
        require_enum(self.status, RunStatus, "status")
        for field_name, value in (
            ("step_count", self.step_count),
            ("retry_count", self.retry_count),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{field_name} 必须是非负整数")
        if self.current_tool_call is not None and not isinstance(self.current_tool_call, ToolCall):
            raise TypeError("current_tool_call 必须是 ToolCall 或 None")
        if not isinstance(self.cancel_requested, bool):
            raise TypeError("cancel_requested 必须是布尔值")
        require_aware_datetime(self.started_at, "started_at")
        require_aware_datetime(self.finished_at, "finished_at")
        require_time_order(self.started_at, self.finished_at)
