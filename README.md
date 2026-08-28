# AgentSpine

AgentSpine 是一个 Python-first 的 Agent Harness / Runtime Framework，目标是为不同垂直领域 Agent 提供可迁移、可控制、可观察的通用运行骨架。

> AgentSpine is a Python-first runtime harness for building reusable vertical agents.

当前开发阶段为 **V0-2 — ModelGateway**。项目在 V0-1 数据契约之上新增了 Provider-independent 模型入口，但还不是一个可以执行完整 Agent Loop 的框架版本。

## 核心设计原则

### Async-first，兼容同步工具

> AgentSpine is async-first.
> Tool handlers may be either synchronous or asynchronous.
> Async handlers are awaited by the execution layer.
> Sync handlers remain supported for lightweight/local tools.

AgentSpine 采用 async-first 设计。Tool handler 可以是同步函数，也可以是异步函数；后续执行层会 await 异步 handler，同时继续支持适合轻量、本地工作的同步 handler。

当前阶段只定义该类型契约，尚未实现工具执行层。

### LLM 提议，确定性组件约束

> LLM proposes actions.
> Deterministic components validate state transitions, tool contracts and policy decisions before execution.

LLM 负责提出行动。真正执行前，确定性组件负责校验状态迁移、工具契约和 Policy 决策。模型提出 ToolCall 不代表已经获得工具执行权限。

### Frozen Snapshot，Manager 控制状态迁移

> Runtime and execution state models use immutable-style snapshots.
> State transitions are intended to be performed by the corresponding managers, rather than through direct mutation by business code.

Runtime 与执行状态模型使用不可原地修改的快照。状态迁移应由对应 Manager 基于旧快照创建新快照，而不是由业务代码直接修改权威状态。

## 当前已经具备

- `Run` 和 `RuntimeState`：区分一次执行的静态配置与瞬时状态。
- `Tool`、`ToolCall` 和 `ToolResult`：描述工具定义、模型提出的调用和执行结果。
- `ToolCapability`：通过 `effect` 和 `replay` 描述工具执行属性。
- `ModelRequest` 和 `ModelResponse`：提供与模型供应商无关的基础请求、响应契约。
- `PolicyDecision`：只表达 Policy 判断，不直接执行动作。
- `RunResult` 和最小 Trace：记录模型调用、工具调用、错误、Usage 和停止原因。
- 中文字段注释、中文校验异常和基础单元测试。
- `ModelGateway`：统一注册、查找并委托 `ModelClient`。
- `DeepSeekClient` / `QwenClient`：两个独立 Provider Client，通过 `ModelConfig` 切换。
- 文本、ToolCall、StopReason、Usage 和 Provider 错误归一化。

## ModelGateway

V0-2 的调用边界是：

```text
ModelGateway
    ↓
ModelClient
    ↓
Provider SDK client
```

`ModelRequest` 只表达“模型处理什么”，不包含 provider/model。`ModelConfig` 只选择 Provider 和模型：

```python
from agentspine import DeepSeekClient, ModelConfig, ModelGateway

gateway = ModelGateway()
gateway.register_client(DeepSeekClient())  # 默认读取 DEEPSEEK_API_KEY

response = await gateway.generate(
    request,
    ModelConfig(provider="deepseek", model="deepseek-v4-flash"),
)
```

Qwen 的 `base_url` 只属于 `QwenClient`，可按地域或工作空间显式配置，不进入 `ModelConfig` 或 Gateway：

```python
from agentspine import QwenClient

gateway.register_client(
    QwenClient(
        api_key="...",
        base_url="https://your-workspace.example/compatible-mode/v1",
    )
)
```

`DeepSeekClient` 和 `QwenClient` 会各自创建并管理内部异步 SDK client。两者当前复用 OpenAI-compatible 编解码逻辑，但这只是私有实现细节，不是可注册的通用 Provider。V0 不支持传入已有原始 SDK client，也不允许把原始 SDK client 直接注册到 Gateway。

正常响应统一返回 `ModelResponse`；认证、限流、超时、服务不可用等异常统一抛出 `ModelGatewayError`，原始 Provider SDK 异常不会泄漏到上层。

## 环境要求

- Python 3.11 或更高版本
- OpenAI Python SDK（作为 DeepSeek/Qwen 的成熟底层传输）

## 本地安装

在项目根目录执行：

```bash
python -m pip install -e .
```

安装后可直接从 `agentspine` 导入公开模型：

```python
from agentspine import Run, RunStatus, RuntimeState

run = Run(
    run_id="run-001",
    user_input="查询南京天气",
    max_steps=8,
    max_tool_calls=4,
    timeout_seconds=30,
)

state = RuntimeState(
    run_id=run.run_id,
    status=RunStatus.PENDING,
)
```

## 垂直业务工具返回结果

垂直业务工具可以通过 `ToolResult.message` 自行封装面向 Agent 的说明，并通过 `error_code` 提供机器可判定的错误类型：

```python
from agentspine import ToolResult, ToolResultStatus

result = ToolResult(
    call_id="call-001",
    tool_name="get_weather",
    status=ToolResultStatus.ERROR,
    message="未找到城市编码，请补充省份或城市全称",
    error_code="city_not_found",
)
```

其中：

- `message` 负责告诉 Agent 具体发生了什么，以及可以如何调整。
- `error_code` 负责让 Agent 或确定性代码稳定识别错误类型。
- `output` 用于保存工具成功时的领域结果。

`ToolResult(ERROR)` 仅表示真实 handler 执行失败；Unknown Tool、参数校验失败和 Policy 拒绝分别使用 `REJECTED` 或 `DENIED`，不创建 ToolResult。

`ToolCall` 只是模型提出的待授权调用，不代表模型已经获得工具执行权限。

## 核心模型边界

| 模型 | 职责 |
| --- | --- |
| `Run` | 保存 Run 身份、原始输入和静态执行限制 |
| `RuntimeState` | 保存当前 Run 的瞬时执行状态 |
| `Tool` | 描述可注册工具，不负责调用编排 |
| `ToolCall` | 表示模型提出的待授权工具调用 |
| `ToolResult` | 表示工具成功或失败的结构化结果 |
| `ToolCapability` | 为 Policy 和 Retry 提供工具执行属性 |
| `ModelRequest` / `ModelResponse` | 隔离上层 Runtime 与具体 Model Provider |
| `PolicyDecision` | 只表达允许、拒绝或需要审批 |
| `RunResult` | 汇总最终输出和结构化 Trace |

`RuntimeState` 不保存 Conversation History、Session Memory、PlanState 或 TaskMemoryCard。这些属于后续阶段的独立状态域。

## 项目结构

```text
AgentSpine/
├── .env.example
├── pyproject.toml
├── README.md
├── python_agent_harness_prd_v1.md
├── scripts/
│   └── smoke_model_gateway.py
├── src/
│   └── agentspine/
│       ├── __init__.py
│       ├── model_gateway.py
│       ├── models/
│       │   ├── __init__.py
│       │   ├── _validation.py
│       │   ├── model.py
│       │   ├── policy.py
│       │   ├── runtime.py
│       │   ├── tool.py
│       │   └── trace.py
│       └── providers/
│           ├── __init__.py
│           ├── _openai_compatible.py
│           ├── deepseek.py
│           └── qwen.py
└── tests/
    ├── test_model_gateway.py
    ├── test_models.py
    └── test_smoke_model_gateway.py
```

## 运行测试

完成本地安装后执行：

```bash
python -m unittest discover -s tests -v
```

不安装包时，也可以把 `src` 临时加入 Python 模块搜索路径后运行测试。

### V0-2 真实模型 Smoke Test（手动执行）

普通单元测试始终离线；新增的脚本测试只使用临时假配置和模拟 HTTP 返回。
真实验收入口是 `scripts/smoke_model_gateway.py`，不会被上述测试命令自动执行，也不会在导入时加载密钥或联网。

**本地配置**

参照 [.env.example](.env.example)，在项目根目录的 `.env` 中本地填写配置。如果已有 `.env`，不要覆盖它。

| Provider | 必填变量 | 可选变量 |
| --- | --- | --- |
| DeepSeek | `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL` | `DEEPSEEK_BASE_URL`，未设置或留空时使用 `https://api.deepseek.com` |
| Qwen | `DASHSCOPE_API_KEY`、`QWEN_BASE_URL`、`QWEN_MODEL` | 无 |

Qwen 必须填写与 API Key 匹配的区域 / 工作空间 / 计费或服务计划的 OpenAI-compatible Base URL。
脚本不硬编码 Qwen 地域地址，而是显式传给 `QwenClient(api_key=..., base_url=...)`。
两家的模型名称都通过 `ModelConfig(provider=..., model=...)` 传入，不进入 Client 初始化参数。

脚本只加载所选 Provider 的上述变量，**已有进程环境变量优先于文件**；不会修改 `.env`。
文件使用 UTF-8（允许 BOM），每个变量独占一行，支持整行 `#` 注释和成对的单 / 双引号。
这是标准库实现的最小加载器，不支持 `export`、行尾注释、多行值或变量展开，也不执行文件中的命令。
Base URL 必须是纯 HTTPS 地址，不要粘贴 Markdown 链接、认证信息、查询参数，或将 `QWEN_MODEL=...` 粘在地址尾部。

API Key 只在本机编辑器或进程环境中配置；不要贴入聊天、日志、README 或命令参数。
`.env`、`.env.*` 已被 Git 忽略，只保留无密钥的 `.env.example`；不要使用 `git add -f` 强行加入 Secret。

**运行方式**

完成 `python -m pip install -e .` 后，在项目根目录手动执行：

```bash
python -m scripts.smoke_model_gateway deepseek
python -m scripts.smoke_model_gateway qwen
# 可选：先验收文本，通过后再增加一次工具提议请求。
python -m scripts.smoke_model_gateway deepseek --tool-call
```

默认使用项目根目录的 `.env`；也可用 `--env-file <本地文件路径>` 指定配置文件。
每次文本验收发出一次 Gateway 调用；`--tool-call` 文本通过后再增加一次调用，可能产生 API 费用。
请求沿用现有 `timeout_seconds=30` 契约。脚本不新增重试逻辑，底层 SDK 沿用现有 Client 配置。

**如何判断结果**

- 输出 JSON 包含 `status`、`stage`、`provider`、`model`、`text`、`stop_reason` 和 `usage`。
- 文本验收要求去除首尾空白后恰好为 `hello`，停止原因为 `COMPLETED`，且没有 ToolCall。
- ToolCall 验收要求提出 `smoke_echo(text="hello")`，状态为 `PROPOSED`。只提供 Schema，没有 handler，不执行工具。
- 缺少必填变量或仍为示例占位符：输出 `SKIP` 和变量名，不联网，退出码为 `0`。**SKIP 不代表通过**。
- 格式错误、响应不满足验收条件或调用失败：输出 `FAIL`，退出码为 `1`；通过为 `PASS`、退出码 `0`。
- SDK 异常仍由现有 Client 转成 `ModelGatewayError`；脚本保留 `code` / `retryable`，不打印原始异常、Authorization、密钥或完整服务配置。验收期间关闭 SDK 日志，响应意外回显当前密钥时也会遮盖。

## 当前明确没有实现

当前版本没有实现：

- 完整 Agent Loop 和 `AgentRunner`
- ToolManager、真实工具执行和执行编排
- RuntimeManager、ContextManager 和 Policy Engine
- Session、多轮对话和持久化 Memory
- Planner、PlanState 和 PlanStore
- Pause / Resume、Checkpoint / Recovery
- Sandbox、ArtifactStore 和 Multi-Agent
- Streaming、Structured Output、Reasoning 和 Multimodal
- Provider Fallback、自动路由、负载均衡和运行时 Retry
- 用户注入已有 SDK client、动态 Provider 插件发现和自动 Client Factory

## 需求依据

当前范围和版本边界以 [python_agent_harness_prd_v1.md](python_agent_harness_prd_v1.md) 为最高优先级需求依据。
