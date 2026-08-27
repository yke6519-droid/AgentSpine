from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
import unittest

from agentspine import (
    Effect,
    ModelRequest,
    ModelMessage,
    MessageRole,
    ModelCallRecord,
    PolicyDecision,
    PolicyOutcome,
    Replay,
    Run,
    RunResult,
    RunStatus,
    RunStopReason,
    RuntimeState,
    StopReason,
    Tool,
    ToolCall,
    ToolCallRecord,
    ToolCallStatus,
    ToolCapability,
    ToolResult,
    ToolResultStatus,
    ModelResponse,
)


class CoreModelTests(unittest.TestCase):
    def test_enum_values_are_frozen_contracts(self) -> None:
        self.assertEqual(Effect.NETWORK.value, "network")
        self.assertEqual(Replay.IDEMPOTENT.value, "idempotent")
        self.assertEqual(RunStatus.TIMED_OUT.value, "timed_out")
        self.assertEqual(PolicyOutcome.REQUIRE_APPROVAL.value, "require_approval")

    def test_tool_capability_accepts_only_its_enums(self) -> None:
        capability = ToolCapability(Effect.EXTERNAL, Replay.UNSAFE)
        self.assertEqual(capability.effect, Effect.EXTERNAL)
        with self.assertRaisesRegex(TypeError, "effect 必须是 Effect 类型"):
            ToolCapability(effect="external", replay=Replay.UNSAFE)  # type: ignore[arg-type]

    def test_tool_definition_validates_handler(self) -> None:
        tool = Tool("echo", "返回输入", lambda arguments: arguments)
        self.assertEqual(tool.capability, ToolCapability())
        with self.assertRaises(TypeError):
            Tool("echo", "返回输入", "not-callable")  # type: ignore[arg-type]

    def test_tool_call_and_result_basic_construction(self) -> None:
        call = ToolCall("call-1", "echo", {"text": "hello"})
        result = ToolResult(
            "call-1",
            "echo",
            ToolResultStatus.SUCCESS,
            output="hello",
            message="已返回输入内容",
        )
        self.assertEqual(call.status, ToolCallStatus.PROPOSED)
        self.assertEqual(result.output, "hello")
        self.assertEqual(result.message, "已返回输入内容")

    def test_tool_result_rejects_inconsistent_error_state(self) -> None:
        with self.assertRaisesRegex(ValueError, "message 必须是非空字符串"):
            ToolResult("call-1", "echo", ToolResultStatus.ERROR)
        with self.assertRaisesRegex(ValueError, "message 必须是非空字符串"):
            ToolResult(
                "call-1",
                "echo",
                ToolResultStatus.SUCCESS,
                output="ok",
                message="",
            )

    def test_runtime_state_is_a_frozen_run_snapshot(self) -> None:
        state = RuntimeState("run-1")
        running = replace(
            state,
            status=RunStatus.RUNNING,
            step_count=1,
            started_at=datetime.now(timezone.utc),
        )
        self.assertEqual(running.step_count, 1)
        with self.assertRaises(FrozenInstanceError):
            state.step_count = 2  # type: ignore[misc]
        with self.assertRaises(ValueError):
            RuntimeState("run-1", step_count=-1)

    def test_runtime_state_excludes_future_state_domains(self) -> None:
        fields = RuntimeState.__dataclass_fields__
        for excluded in ("conversation_history", "session_memory", "plan_state", "task_memory_card"):
            self.assertNotIn(excluded, fields)

    def test_run_validates_execution_limits(self) -> None:
        run = Run("run-1", "hello", max_steps=4, max_tool_calls=3, timeout_seconds=30)
        later_run = Run("run-2", "hello", max_steps=4, max_tool_calls=3, timeout_seconds=30)
        self.assertEqual(run.max_steps, 4)
        self.assertIsNot(run.created_at, later_run.created_at)
        with self.assertRaises(ValueError):
            Run("run-1", "hello", max_steps=0, max_tool_calls=3, timeout_seconds=30)

    def test_model_request_requires_typed_non_empty_messages(self) -> None:
        request = ModelRequest(
            "run-1", (ModelMessage(MessageRole.USER, "hello"),)
        )
        self.assertEqual(request.messages[0].role, MessageRole.USER)
        with self.assertRaisesRegex(ValueError, "messages 不能为空"):
            ModelRequest("run-1", ())

    def test_model_response_and_trace_basic_construction(self) -> None:
        now = datetime.now(timezone.utc)
        request = ModelRequest(
            "run-1", (ModelMessage(MessageRole.USER, "hello"),)
        )
        response = ModelResponse(
            text="done",
            stop_reason=StopReason.COMPLETED,
            usage={"total_tokens": 3},
        )
        record = ModelCallRecord(request, response, now, now)
        self.assertEqual(record.response.usage["total_tokens"], 3)
        with self.assertRaises(ValueError):
            ModelResponse(
                stop_reason=StopReason.ERROR,
                usage={"total_tokens": -1},
                error="provider failed",
            )

    def test_policy_decision_is_data_only(self) -> None:
        decision = PolicyDecision(PolicyOutcome.DENY, "tool is not allowed", "rule-1")
        self.assertEqual(decision.outcome, PolicyOutcome.DENY)
        self.assertFalse(hasattr(decision, "execute"))

    def test_tool_trace_requires_matching_result(self) -> None:
        call = ToolCall("call-1", "echo")
        decision = PolicyDecision(PolicyOutcome.ALLOW, "allowed")
        wrong_result = ToolResult(
            "call-2", "echo", ToolResultStatus.SUCCESS, output="ok"
        )
        with self.assertRaises(ValueError):
            ToolCallRecord(call, decision, wrong_result)

    def test_tool_trace_can_record_pre_policy_failure(self) -> None:
        call = ToolCall("call-1", "missing-tool")
        result = ToolResult(
            "call-1",
            "missing-tool",
            ToolResultStatus.ERROR,
            message="未找到名称为 missing-tool 的工具",
            error_code="unknown_tool",
        )
        record = ToolCallRecord(call, None, result)
        self.assertIsNone(record.decision)

    def test_run_result_basic_construction_and_validation(self) -> None:
        now = datetime.now(timezone.utc)
        result = RunResult(
            run_id="run-1",
            status=RunStatus.COMPLETED,
            final_output="done",
            stop_reason=RunStopReason.COMPLETED,
            usage={"input_tokens": 2, "output_tokens": 1},
            started_at=now - timedelta(seconds=1),
            finished_at=now,
        )
        self.assertEqual(result.final_output, "done")
        with self.assertRaises(ValueError):
            replace(result, status=RunStatus.RUNNING)
        with self.assertRaises(ValueError):
            replace(result, usage={"input_tokens": -1})

    def test_naive_timestamps_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            RuntimeState("run-1", started_at=datetime.now())


if __name__ == "__main__":
    unittest.main()
