# AgentSpine

AgentSpine 是一个 Python-first 的 Agent Harness / Runtime Framework，目标是为不同垂直领域 Agent 提供可迁移、可控制、可观察的通用运行骨架。

> AgentSpine is a Python-first runtime harness for building reusable vertical agents.

当前发布版本为 **V0.0.0 — 基础数据模型与最小项目骨架**，对应 PRD 的 V0 第一阶段。目前提供的是后续 Runtime、Tool、Model、Policy 和 Trace 模块之间的稳定数据契约，还不是一个可以执行完整 Agent Loop 的框架版本。

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

## 环境要求

- Python 3.11 或更高版本
- 当前没有运行时第三方依赖

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
├── pyproject.toml
├── README.md
├── python_agent_harness_prd_v1.md
├── src/
│   └── agentspine/
│       ├── __init__.py
│       └── models/
│           ├── __init__.py
│           ├── _validation.py
│           ├── model.py
│           ├── policy.py
│           ├── runtime.py
│           ├── tool.py
│           └── trace.py
└── tests/
    └── test_models.py
```

## 运行测试

完成本地安装后执行：

```bash
python -m unittest discover -s tests -v
```

不安装包时，也可以把 `src` 临时加入 Python 模块搜索路径后运行测试。

## 当前明确没有实现

当前版本没有实现：

- 完整 Agent Loop 和 `AgentRunner`
- ModelGateway 和 Provider Adapter
- ToolManager、真实工具执行和执行编排
- RuntimeManager、ContextManager 和 Policy Engine
- Session、多轮对话和持久化 Memory
- Planner、PlanState 和 PlanStore
- Pause / Resume、Checkpoint / Recovery
- Sandbox、ArtifactStore 和 Multi-Agent

## 需求依据

当前范围和版本边界以 [python_agent_harness_prd_v1.md](python_agent_harness_prd_v1.md) 为最高优先级需求依据。
