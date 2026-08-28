import inspect
import os
from collections.abc import Mapping
from types import SimpleNamespace
from typing import Any
import unittest
from unittest.mock import patch

from agentspine import (
    DeepSeekClient,
    MessageRole,
    ModelConfig,
    ModelGateway,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    QwenClient,
    StopReason,
    ToolCall,
    ToolCallStatus,
)


class FakeCompletions:
    """模拟 AsyncOpenAI 的 chat.completions，不访问网络。"""

    def __init__(self, response: Mapping[str, Any] | None = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def create(self, **payload: Any) -> Mapping[str, Any]:
        self.calls.append(payload)
        if self.error:
            raise self.error
        assert self.response is not None
        return self.response


class FakeSDKClient:
    def __init__(self, response: Mapping[str, Any] | None = None, error: Exception | None = None) -> None:
        self.completions = FakeCompletions(response, error)
        self.chat = SimpleNamespace(completions=self.completions)


class FakeSDKError(Exception):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        self.status_code = status_code
        super().__init__(message)


class StubModelClient:
    provider = "stub"

    def __init__(self) -> None:
        self.received: tuple[ModelRequest, str] | None = None

    async def generate(self, request: ModelRequest, model: str) -> ModelResponse:
        self.received = (request, model)
        return ModelResponse(text="ok")


def text_response(finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "choices": [{"message": {"content": "完成"}, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3},
    }


class ModelGatewayTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.request = ModelRequest(
            "run-1",
            (ModelMessage(MessageRole.USER, "你好"),),
        )

    def test_model_config_validation(self) -> None:
        self.assertEqual(ModelConfig("deepseek", "deepseek-test").provider, "deepseek")
        with self.assertRaisesRegex(ValueError, "provider 必须是非空字符串"):
            ModelConfig("", "model")
        with self.assertRaisesRegex(ValueError, "model 必须是非空字符串"):
            ModelConfig("deepseek", "")

    async def test_register_resolve_and_delegate(self) -> None:
        gateway = ModelGateway()
        client = StubModelClient()
        gateway.register_client(client)
        self.assertIs(gateway.resolve_client("stub"), client)
        response = await gateway.generate(self.request, ModelConfig("stub", "model-a"))
        self.assertEqual(response.text, "ok")
        self.assertEqual(client.received, (self.request, "model-a"))

    def test_duplicate_unknown_and_raw_sdk_client(self) -> None:
        gateway = ModelGateway()
        gateway.register_client(StubModelClient())
        with self.assertRaises(ModelGatewayError) as duplicate:
            gateway.register_client(StubModelClient())
        self.assertEqual(duplicate.exception.code, ModelGatewayErrorCode.INVALID_REQUEST)
        with self.assertRaises(ModelGatewayError) as missing:
            gateway.resolve_client("missing")
        self.assertEqual(missing.exception.code, ModelGatewayErrorCode.PROVIDER_NOT_FOUND)
        with self.assertRaisesRegex(TypeError, "ModelClient"):
            gateway.register_client(FakeSDKClient())  # type: ignore[arg-type]

    def test_provider_clients_create_and_own_sdk_clients(self) -> None:
        deepseek_sdk = FakeSDKClient(text_response())
        with patch("agentspine.providers.deepseek.AsyncOpenAI", return_value=deepseek_sdk) as factory:
            deepseek = DeepSeekClient(api_key="ds-key", base_url="https://ds.test")
        factory.assert_called_once_with(api_key="ds-key", base_url="https://ds.test")
        self.assertIs(deepseek._sdk_client, deepseek_sdk)

        qwen_sdk = FakeSDKClient(text_response())
        with patch("agentspine.providers.qwen.AsyncOpenAI", return_value=qwen_sdk) as factory:
            qwen = QwenClient(api_key="qwen-key", base_url="https://qwen.test/v1")
        factory.assert_called_once_with(api_key="qwen-key", base_url="https://qwen.test/v1")
        self.assertEqual(qwen.base_url, "https://qwen.test/v1")
        self.assertEqual(DeepSeekClient.provider, "deepseek")
        self.assertEqual(QwenClient.provider, "qwen")
        self.assertNotIn("base_url", ModelConfig.__dataclass_fields__)
        self.assertFalse(hasattr(ModelGateway(), "base_url"))
        self.assertNotIn("client", inspect.signature(QwenClient).parameters)
        self.assertNotIn("client", inspect.signature(DeepSeekClient).parameters)

    async def test_switching_provider_does_not_change_request(self) -> None:
        deepseek_sdk = FakeSDKClient(text_response())
        qwen_sdk = FakeSDKClient(text_response())
        with patch("agentspine.providers.deepseek.AsyncOpenAI", return_value=deepseek_sdk):
            deepseek = DeepSeekClient(api_key="ds-key")
        with patch("agentspine.providers.qwen.AsyncOpenAI", return_value=qwen_sdk):
            qwen = QwenClient(api_key="qwen-key")
        gateway = ModelGateway()
        gateway.register_client(deepseek)
        gateway.register_client(qwen)

        await gateway.generate(self.request, ModelConfig("deepseek", "deepseek-test"))
        await gateway.generate(self.request, ModelConfig("qwen", "qwen-test"))

        ds_payload = deepseek_sdk.completions.calls[0]
        qwen_payload = qwen_sdk.completions.calls[0]
        self.assertEqual(ds_payload["messages"], qwen_payload["messages"])
        self.assertEqual(ds_payload["model"], "deepseek-test")
        self.assertEqual(qwen_payload["model"], "qwen-test")


class ModelClientNormalizationTests(unittest.IsolatedAsyncioTestCase):
    def client(self, sdk: FakeSDKClient) -> DeepSeekClient:
        with patch("agentspine.providers.deepseek.AsyncOpenAI", return_value=sdk):
            return DeepSeekClient(api_key="key")

    def request(self, *messages: ModelMessage, tool_schemas: tuple[Mapping[str, Any], ...] = ()) -> ModelRequest:
        return ModelRequest("run-1", messages, tool_schemas=tool_schemas, timeout_seconds=5)

    async def test_text_stop_reason_and_usage_normalization(self) -> None:
        sdk = FakeSDKClient(text_response())
        response = await self.client(sdk).generate(
            self.request(ModelMessage(MessageRole.USER, "你好")), "deepseek-test"
        )
        self.assertEqual(response.text, "完成")
        self.assertEqual(response.stop_reason, StopReason.COMPLETED)
        self.assertEqual(response.usage, {"input_tokens": 2, "output_tokens": 1, "total_tokens": 3})
        self.assertEqual(sdk.completions.calls[0]["timeout"], 5)
        self.assertFalse(sdk.completions.calls[0]["stream"])

    async def test_tool_messages_schema_and_tool_call_normalization(self) -> None:
        request = self.request(
            ModelMessage(
                MessageRole.ASSISTANT,
                "查询中",
                tool_calls=(ToolCall("old", "lookup", {"id": 1}),),
            ),
            ModelMessage(MessageRole.TOOL, '{"value": 2}', tool_call_id="old"),
            tool_schemas=(
                {
                    "name": "lookup",
                    "description": "查询记录",
                    "parameters": {"type": "object", "properties": {}},
                },
            ),
        )
        sdk = FakeSDKClient(
            {
                "choices": [
                    {
                        "message": {
                            "content": "继续处理",
                            "tool_calls": [
                                {
                                    "id": "new",
                                    "type": "function",
                                    "function": {"name": "lookup", "arguments": '{"id": 2}'},
                                }
                            ],
                        },
                        "finish_reason": "tool_calls",
                    }
                ]
            }
        )
        response = await self.client(sdk).generate(request, "model")
        self.assertEqual(response.stop_reason, StopReason.TOOL_CALLS)
        self.assertEqual(response.tool_calls[0].status, ToolCallStatus.PROPOSED)
        self.assertEqual(response.tool_calls[0].arguments, {"id": 2})
        payload = sdk.completions.calls[0]
        self.assertEqual(payload["messages"][1]["tool_call_id"], "old")
        self.assertEqual(payload["tools"][0]["type"], "function")

    async def test_stop_reason_and_missing_usage(self) -> None:
        request = self.request(ModelMessage(MessageRole.USER, "你好"))
        for raw, expected in (("length", StopReason.LENGTH), ("unknown", StopReason.OTHER)):
            with self.subTest(raw=raw):
                sdk = FakeSDKClient(
                    {"choices": [{"message": {"content": "x"}, "finish_reason": raw}]}
                )
                response = await self.client(sdk).generate(request, "model")
                self.assertEqual(response.stop_reason, expected)
                self.assertEqual(response.usage, {})

    async def test_provider_errors_are_normalized_without_leaking(self) -> None:
        request = self.request(ModelMessage(MessageRole.USER, "你好"))
        cases = (
            (FakeSDKError("bad request", 400), ModelGatewayErrorCode.INVALID_REQUEST, False),
            (FakeSDKError("bad key", 401), ModelGatewayErrorCode.AUTHENTICATION, False),
            (FakeSDKError("limited", 429), ModelGatewayErrorCode.RATE_LIMIT, True),
            (TimeoutError("slow"), ModelGatewayErrorCode.TIMEOUT, True),
            (ConnectionError("offline"), ModelGatewayErrorCode.PROVIDER_UNAVAILABLE, True),
            (FakeSDKError("down", 503), ModelGatewayErrorCode.PROVIDER_UNAVAILABLE, True),
            (RuntimeError("sdk boom"), ModelGatewayErrorCode.PROVIDER_ERROR, False),
        )
        for raw_error, code, retryable in cases:
            with self.subTest(code=code):
                with self.assertRaises(ModelGatewayError) as raised:
                    await self.client(FakeSDKClient(error=raw_error)).generate(request, "model")
                self.assertEqual(raised.exception.code, code)
                self.assertEqual(raised.exception.retryable, retryable)
                self.assertNotIsInstance(raised.exception, type(raw_error))

    def test_api_key_validation_and_environment_fallback(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ModelGatewayError) as missing:
                DeepSeekClient()
        self.assertEqual(missing.exception.code, ModelGatewayErrorCode.AUTHENTICATION)

        sdk = FakeSDKClient(text_response())
        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": "env-key"}, clear=True):
            with patch("agentspine.providers.qwen.AsyncOpenAI", return_value=sdk) as factory:
                QwenClient()
        factory.assert_called_once_with(
            api_key="env-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )


if __name__ == "__main__":
    unittest.main()
