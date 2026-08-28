"""V0-2 手动验收入口；导入本模块不会加载密钥，也不会调用模型。"""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path
from urllib.parse import urlsplit

from agentspine import (
    DeepSeekClient, MessageRole, ModelConfig, ModelGateway, ModelGatewayError,
    ModelMessage, ModelRequest, QwenClient, StopReason, ToolCallStatus,
)


def _load_settings(names: tuple[str, ...], path: Path) -> dict[str, str]:
    """只在手动运行时加载所选 Provider 配置，不把 .env 内容输出到终端。"""
    values: dict[str, str] = {}
    if path.exists():
        # ponytail: 仅支持单行 KEY=VALUE、整行注释和成对引号。
        # 不执行 shell、不展开变量、不支持多行；复杂格式留待确有需要时引入专用库。
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.strip().partition("=")
            name = name.strip()
            if not separator or name not in names:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] in ("'", '"') and value[-1] == value[0]:
                value = value[1:-1]
            values[name] = value.strip()
    # 环境变量优先；显式设为空也不回退，避免意外使用文件里的另一个账号。
    return {name: os.environ.get(name, values.get(name, "")).strip() for name in names}


def _emit(data: dict[str, object], settings: dict[str, str]) -> None:
    """只输出验收字段；即使 Provider 意外回显密钥，也进行遮盖。"""
    output = json.dumps(data, ensure_ascii=False)
    for name, value in settings.items():
        if value and (name.endswith("_API_KEY") or name.endswith("_BASE_URL")):
            # 先按 JSON 字符串规则转义，覆盖引号等特殊字符。
            output = output.replace(json.dumps(value, ensure_ascii=False)[1:-1], "[REDACTED]")
    print(output)


def _invalid_settings(settings: dict[str, str]) -> list[str]:
    """只返回有问题的变量名，不返回配置值，也不猜测地域或修正地址。"""
    invalid = []
    for name, value in settings.items():
        if not value:
            continue
        if any(character.isspace() for character in value) or value[0] in ("'", '"'):
            invalid.append(name)
        elif name.endswith("_BASE_URL"):
            try:
                url = urlsplit(value)
                # HTTPS 保护密钥；拒绝粘连变量、Markdown、内嵌认证和查询参数。
                valid = (
                    url.scheme == "https" and bool(url.hostname)
                    and not url.username and not url.password and not url.query
                    and not url.fragment and not any(char in value for char in "=()<>")
                    and (url.port is None or url.port > 0)
                )
            except ValueError:
                valid = False
            if not valid:
                invalid.append(name)
    return invalid


async def _run(provider: str, settings: dict[str, str], tool_call: bool) -> int:
    """仅使用现有公开入口，连接配置归 Client，模型名称归 ModelConfig。"""
    if provider == "deepseek":
        client = DeepSeekClient(
            api_key=settings["DEEPSEEK_API_KEY"],
            base_url=settings["DEEPSEEK_BASE_URL"] or "https://api.deepseek.com",
        )
        model = settings["DEEPSEEK_MODEL"]
    else:
        # Smoke 不使用 QwenClient 的默认地址，必须显式传入用户的服务地址。
        client = QwenClient(api_key=settings["DASHSCOPE_API_KEY"], base_url=settings["QWEN_BASE_URL"])
        model = settings["QWEN_MODEL"]
    gateway = ModelGateway()
    gateway.register_client(client)
    config = ModelConfig(provider=provider, model=model)
    request = ModelRequest(
        run_id="smoke-test",
        messages=(ModelMessage(role=MessageRole.USER, content="只回复：hello"),),
        timeout_seconds=30,
    )
    response = await gateway.generate(request, config)
    passed = (
        response.text is not None and response.text.strip() == "hello"
        and response.stop_reason is StopReason.COMPLETED and not response.tool_calls
    )
    _emit({
        "status": "PASS" if passed else "FAIL", "stage": "text",
        "provider": provider, "model": model, "text": response.text,
        "stop_reason": response.stop_reason.value, "usage": dict(response.usage),
    }, settings)
    if not passed or not tool_call:
        return 0 if passed else 1

    # 文本通过后才增加一次独立模型调用。只提供 Schema，没有 Python handler。
    request = ModelRequest(
        run_id="smoke-test",
        messages=(ModelMessage(
            role=MessageRole.USER,
            content='请调用 smoke_echo 工具，参数 text 为 hello。不要用普通文本代替工具调用。',
        ),),
        tool_schemas=({
            "name": "smoke_echo", "description": "提出回显给定文本的工具调用。",
            "parameters": {
                "type": "object", "properties": {"text": {"type": "string"}},
                "required": ["text"], "additionalProperties": False,
            },
        },),
        timeout_seconds=30,
    )
    response = await gateway.generate(request, config)
    passed = (
        response.stop_reason is StopReason.TOOL_CALLS and len(response.tool_calls) == 1
        and response.tool_calls[0].status is ToolCallStatus.PROPOSED
        and response.tool_calls[0].tool_name == "smoke_echo"
        and response.tool_calls[0].arguments == {"text": "hello"}
    )
    _emit({
        "status": "PASS" if passed else "FAIL", "stage": "tool_call",
        "provider": provider, "model": model, "text": response.text,
        "stop_reason": response.stop_reason.value, "usage": dict(response.usage),
        "tool_calls": [
            {"call_id": call.call_id, "tool_name": call.tool_name,
             "arguments": dict(call.arguments), "status": call.status.value}
            for call in response.tool_calls
        ],
        "message": "仅检查模型提议，未执行任何工具",
    }, settings)
    return 0 if passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="V0-2 真实模型验收（可能产生 API 费用）")
    parser.add_argument("provider", choices=("deepseek", "qwen"))
    parser.add_argument("--env-file", type=Path, default=Path(__file__).resolve().parents[1] / ".env")
    parser.add_argument("--tool-call", action="store_true", help="文本通过后额外验证工具提议，不执行工具")
    args = parser.parse_args(argv)
    required = (
        ("DEEPSEEK_API_KEY", "DEEPSEEK_MODEL")
        if args.provider == "deepseek"
        else ("DASHSCOPE_API_KEY", "QWEN_BASE_URL", "QWEN_MODEL")
    )
    names = required + (("DEEPSEEK_BASE_URL",) if args.provider == "deepseek" else ())
    try:
        settings = _load_settings(names, args.env_file)
    except (OSError, UnicodeError):
        print('{"status": "FAIL", "message": "无法读取环境文件，请检查权限和 UTF-8 编码"}')
        return 1
    missing = [name for name in required if settings[name] in ("", "sk-xxxx", "...")]
    invalid = _invalid_settings(settings)
    if missing or invalid:
        messages = []
        if missing:
            messages.append("缺少环境变量或仍为占位符：" + ", ".join(missing))
        if invalid:
            messages.append("环境变量格式错误：" + ", ".join(invalid)
                            + "；请使用单行值和纯 HTTPS 地址，检查是否粘连其他变量")
        _emit({"status": "FAIL" if invalid else "SKIP", "provider": args.provider,
               "message": "；".join(messages)}, settings)
        return 1 if invalid else 0
    # SDK 调试日志可能包含请求细节。仅在手动验收调用期间关闭日志。
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        return asyncio.run(_run(args.provider, settings, args.tool_call))
    except ModelGatewayError as exc:
        # 保留现有归一化错误码；不输出可能回显密钥/服务地址的 exc.message。
        _emit({"status": "FAIL", "provider": args.provider,
               "code": exc.code.value, "retryable": exc.retryable,
               "message": "模型调用失败，请根据错误码核对配置或服务状态"}, settings)
        return 1
    except Exception:
        # CLI 最外层避免 traceback 意外暴露本地配置；不重新映射 SDK 异常。
        _emit({"status": "FAIL", "provider": args.provider,
               "message": "验收脚本出现非预期异常，未输出原始异常以保护配置"}, settings)
        return 1
    finally:
        logging.disable(previous_logging)


if __name__ == "__main__":
    raise SystemExit(main())
