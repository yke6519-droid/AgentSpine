"""验收入口的离线测试：仅使用临时配置，绝不读取项目真实 .env。"""

from contextlib import redirect_stdout
from io import StringIO
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from scripts import smoke_model_gateway as smoke


class SmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env_file = Path(self.directory.name) / ".env"
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        # 拦住真正的 HTTP 出口；不拦 socket，Windows 事件循环自身需要本地 socketpair。
        self.network = patch.object(
            httpx.AsyncHTTPTransport, "handle_async_request",
            side_effect=AssertionError("离线测试禁止联网"),
        )
        self.connect = self.network.start()
        self.addCleanup(self.network.stop)

    def invoke(self, provider: str, *options: str) -> tuple[int, str]:
        output = StringIO()
        with redirect_stdout(output):
            code = smoke.main([provider, "--env-file", str(self.env_file), *options])
        self.connect.assert_not_called()
        return code, output.getvalue()

    def test_missing_configuration_skips_without_network(self) -> None:
        for provider, names in (
            ("deepseek", ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL")),
            ("qwen", ("DASHSCOPE_API_KEY", "QWEN_BASE_URL", "QWEN_MODEL")),
        ):
            with self.subTest(provider=provider):
                code, output = self.invoke(provider)
                self.assertEqual(code, 0)
                self.assertIn("SKIP", output)
                for name in names:
                    self.assertIn(name, output)

    def test_invalid_base_url_is_rejected_before_network_without_echoing_it(self) -> None:
        for base_url in (
            "https://private.example/v1QWEN_MODEL=qwen-test",
            "[https://private.example/v1](https://private.example/v1)",
            "http://private.example/v1",
            "https://user:fake-password@private.example/v1",
            "https://private.example:wrong/v1",
            "https://private.example/v1?api_key=fake-secret",
            "https://private.example/v1#fragment",
        ):
            with self.subTest(base_url=base_url), patch.dict(os.environ, {
                "DASHSCOPE_API_KEY": "fake-secret", "QWEN_MODEL": "qwen-test",
                "QWEN_BASE_URL": base_url,
            }):
                code, output = self.invoke("qwen")
                self.assertEqual(code, 1)
                self.assertIn("QWEN_BASE_URL", output)
                self.assertNotIn("private.example", output)
                self.assertNotIn("fake-secret", output)

    def test_text_call_uses_env_file_and_real_sdk_serialization(self) -> None:
        # 全是测试占位值。只替换 HTTP 出口，Gateway、两个 Client、SDK 都真实运行。
        self.env_file.write_text(
            "# 测试配置\nDEEPSEEK_API_KEY='fake-ds-secret'\nDEEPSEEK_MODEL=ds-test\n"
            'DASHSCOPE_API_KEY="fake-qwen-secret"\n'
            "QWEN_BASE_URL=https://workspace.example/compatible-mode/v1\nQWEN_MODEL=qwen-test\n",
            encoding="utf-8-sig",
        )
        payloads = []
        for provider, model, host, key in (
            ("deepseek", "ds-test", "api.deepseek.com", "fake-ds-secret"),
            ("qwen", "qwen-test", "workspace.example", "fake-qwen-secret"),
        ):
            with self.subTest(provider=provider):
                async def send(request: httpx.Request, **kwargs: object) -> httpx.Response:
                    self.assertEqual(request.url.host, host)
                    self.assertEqual(request.headers["authorization"], "Bearer " + key)
                    payload = json.loads(request.content)
                    self.assertEqual(payload["model"], model)
                    payloads.append(payload)
                    return httpx.Response(200, request=request, json={
                        "id": "smoke-response", "object": "chat.completion",
                        "created": 0, "model": model,
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"},
                                     "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
                    })

                with patch.object(httpx.AsyncClient, "send", new=AsyncMock(side_effect=send)) as http:
                    code, output = self.invoke(provider)
                self.assertEqual(code, 0)
                result = json.loads(output)
                self.assertEqual(result["status"], "PASS")
                self.assertEqual(result["provider"], provider)
                self.assertEqual(result["model"], model)
                self.assertEqual(result["text"], "hello")
                self.assertEqual(result["stop_reason"], "completed")
                self.assertEqual(result["usage"], {"input_tokens": 4, "output_tokens": 1, "total_tokens": 5})
                self.assertNotIn(key, output)
                self.assertEqual(http.await_count, 1)
        self.assertEqual(payloads[0]["messages"], [{"role": "user", "content": "只回复：hello"}])
        self.assertEqual(payloads[0]["messages"], payloads[1]["messages"])

    def test_tool_call_is_only_proposed_after_text_passes(self) -> None:
        self.env_file.write_text(
            "DEEPSEEK_API_KEY=fake-secret\nDEEPSEEK_MODEL=ds-test\n", encoding="utf-8",
        )
        for tool_name, arguments, expected in (
            ("smoke_echo", '{"text":"hello"}', "PASS"),
            ("smoke_echo", '{"text":"wrong"}', "FAIL"),
            ("unknown_tool", '{"text":"hello"}', "FAIL"),
            (None, "{}", "FAIL"),
        ):
            with self.subTest(tool_name=tool_name, arguments=arguments):
                async def send(request: httpx.Request, **kwargs: object) -> httpx.Response:
                    payload = json.loads(request.content)
                    message = {"role": "assistant", "content": "hello"}
                    finish = "stop"
                    if "tools" in payload:
                        self.assertEqual(payload["tools"][0]["function"]["name"], "smoke_echo")
                        self.assertNotIn("tool_choice", payload)
                        if tool_name is not None:
                            message = {"role": "assistant", "content": None, "tool_calls": [{
                                "id": "call-smoke", "type": "function",
                                "function": {"name": tool_name, "arguments": arguments},
                            }]}
                            finish = "tool_calls"
                    return httpx.Response(200, request=request, json={
                        "id": "smoke-response", "object": "chat.completion", "created": 0, "model": "ds-test",
                        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
                    })

                with patch.object(httpx.AsyncClient, "send", new=AsyncMock(side_effect=send)) as http:
                    code, output = self.invoke("deepseek", "--tool-call")
                records = [json.loads(line) for line in output.splitlines()]
                self.assertEqual(records[0]["status"], "PASS")
                self.assertEqual(records[1]["stage"], "tool_call")
                self.assertEqual(records[1]["status"], expected)
                self.assertEqual(code, 0 if expected == "PASS" else 1)
                self.assertEqual(http.await_count, 2)
                if expected == "PASS":
                    self.assertEqual(records[1]["tool_calls"][0]["status"], "proposed")
                    self.assertEqual(records[1]["tool_calls"][0]["arguments"], {"text": "hello"})
                    self.assertEqual(records[1]["stop_reason"], "tool_calls")

    def test_provider_authentication_error_does_not_echo_secret(self) -> None:
        self.env_file.write_text(
            "DEEPSEEK_API_KEY=fake-secret\nDEEPSEEK_MODEL=ds-test\n", encoding="utf-8",
        )

        async def send(request: httpx.Request, **kwargs: object) -> httpx.Response:
            return httpx.Response(401, request=request, json={
                "error": {"message": "Authorization: Bearer fake-secret", "type": "authentication_error"},
            })

        with patch.object(httpx.AsyncClient, "send", new=AsyncMock(side_effect=send)):
            code, output = self.invoke("deepseek")
        result = json.loads(output)
        self.assertEqual(code, 1)
        self.assertEqual(result["code"], "authentication")
        self.assertFalse(result["retryable"])
        self.assertNotIn("fake-secret", output)
        self.assertNotIn("Authorization", output)

    def test_each_required_variable_is_checked_independently(self) -> None:
        for provider, complete in (
            ("deepseek", {"DEEPSEEK_API_KEY": "fake-secret", "DEEPSEEK_MODEL": "ds-test"}),
            ("qwen", {"DASHSCOPE_API_KEY": "fake-secret", "QWEN_MODEL": "qwen-test",
                      "QWEN_BASE_URL": "https://workspace.example/v1"}),
        ):
            for missing in complete:
                with self.subTest(provider=provider, missing=missing):
                    partial = {name: value for name, value in complete.items() if name != missing}
                    with patch.dict(os.environ, partial, clear=True):
                        code, output = self.invoke(provider)
                    self.assertEqual(code, 0)
                    self.assertEqual(json.loads(output)["status"], "SKIP")
                    self.assertIn(missing, output)

    def test_environment_overrides_file_and_deepseek_url_is_explicit(self) -> None:
        self.env_file.write_text(
            "DEEPSEEK_API_KEY=file-secret\nDEEPSEEK_MODEL=file-model\n"
            "DEEPSEEK_BASE_URL=https://file.example/v1\n", encoding="utf-8",
        )

        async def send(request: httpx.Request, **kwargs: object) -> httpx.Response:
            self.assertEqual(request.url.host, "environment.example")
            self.assertEqual(request.headers["authorization"], "Bearer env-secret")
            self.assertEqual(json.loads(request.content)["model"], "env-model")
            return httpx.Response(200, request=request, json={
                "id": "smoke-response", "object": "chat.completion", "created": 0, "model": "env-model",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": "hello"},
                             "finish_reason": "stop"}],
            })

        with patch.dict(os.environ, {
            "DEEPSEEK_API_KEY": "env-secret", "DEEPSEEK_MODEL": "env-model",
            "DEEPSEEK_BASE_URL": "https://environment.example/v1",
        }), patch.object(httpx.AsyncClient, "send", new=AsyncMock(side_effect=send)):
            code, output = self.invoke("deepseek")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output)["usage"], {})  # 不伪造 Provider 缺失的 Usage。

    def test_text_failure_stops_before_tool_and_redacts_echoed_key(self) -> None:
        self.env_file.write_text(
            "DEEPSEEK_API_KEY=fake-secret\nDEEPSEEK_MODEL=ds-test\n", encoding="utf-8",
        )
        for content in (None, "wrong answer", "fake-secret"):
            with self.subTest(content=content):
                async def send(request: httpx.Request, **kwargs: object) -> httpx.Response:
                    return httpx.Response(200, request=request, json={
                        "id": "smoke-response", "object": "chat.completion", "created": 0, "model": "ds-test",
                        "choices": [{"index": 0, "message": {"role": "assistant", "content": content},
                                     "finish_reason": "stop"}],
                    })
                with patch.object(httpx.AsyncClient, "send", new=AsyncMock(side_effect=send)) as http:
                    code, output = self.invoke("deepseek", "--tool-call")
                self.assertEqual(code, 1)
                self.assertEqual(json.loads(output)["status"], "FAIL")
                self.assertEqual(http.await_count, 1)
                self.assertNotIn("fake-secret", output)

    def test_import_does_not_read_env_or_start_http(self) -> None:
        with patch.object(Path, "read_text", side_effect=AssertionError("导入时禁止读文件")) as read:
            importlib.reload(smoke)
        read.assert_not_called()
        self.connect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
