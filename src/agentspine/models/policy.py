"""Policy Engine 的纯决策结果模型。"""

from dataclasses import dataclass
from enum import Enum

from ._validation import require_enum, require_non_empty


class PolicyOutcome(str, Enum):
    """Policy Engine 对一个合法动作给出的判断。"""

    # 允许 Runner 继续执行该动作。
    ALLOW = "allow"
    # 禁止执行该动作。
    DENY = "deny"
    # 执行前需要人工或外部审批；本阶段只保留判断结果。
    REQUIRE_APPROVAL = "require_approval"


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """只描述 Policy 判断，不包含工具执行或状态修改行为。

    Runner 后续读取该对象决定流程走向；PolicyDecision 自身不调用工具。
    """

    # Policy 给出的最终判断。
    outcome: PolicyOutcome
    # 面向开发者和 Trace 的决策原因。
    reason: str
    # 命中规则的稳定标识；无法对应单条规则时可以为 None。
    rule_id: str | None = None

    def __post_init__(self) -> None:
        require_enum(self.outcome, PolicyOutcome, "outcome")
        require_non_empty(self.reason, "reason")
        if self.rule_id is not None:
            require_non_empty(self.rule_id, "rule_id")
