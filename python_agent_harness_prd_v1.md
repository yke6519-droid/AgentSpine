# Python Agent Harness — 产品需求文档（PRD）

> 文档状态：Scope Freeze v1.1（Terminology Audit）  
> 目标读者：产品设计者、架构设计者、Codex / 开发者  
> 当前目标：冻结 V0 / V1 硬边界，作为正式编码输入  

---

## 1. 产品概述

### 1.1 产品定位

构建一个 **Python-first、面向垂直 Agent 开发者、强调 Harness 骨架可迁移性的 Agent Runtime Framework**。

开发者能够复用统一的 Agent 执行骨架，而将主要精力放在垂直领域能力上，例如：

- Domain Tools
- Domain Prompt
- Domain Policy
- Domain Runtime Extension
- Domain Planner（可选）

框架负责通用的：

- Run 生命周期
- Session 生命周期
- Runtime 状态管理
- Context 构建
- Memory / History
- Tool 注册与调用
- Model Gateway
- Policy 决策
- Planning（可选）
- Structured Result / Trace

### 1.2 核心问题

开发者在构建不同垂直 Agent 时，经常重复实现：

- Agent Loop
- Tool Calling
- Runtime 状态
- Context 管理
- Memory / Session
- Provider 适配
- Policy / execution control
- 执行结果与 Trace

这些能力难以从一个 Agent 迁移到另一个 Agent。

### 1.3 核心价值

**让 Agent 的横向 Harness 能力可复用、可迁移，让开发者只编写垂直领域能力。**

优先级：

1. 可迁移 / 可复用
2. 结构清晰、边界明确
3. 可靠、可控、可观察
4. 尽可能轻量，但不以“极致轻量”为最高目标

---

## 2. 目标用户

具备 Python 和 Agent 基础的开发者，他们能够：

- 编写 Tool
- 编写 Prompt
- 定义领域规则
- 理解基本 Tool Calling

但不希望每个项目都重新实现完整 Harness。

---

## 3. First Success Moment

开发者完成：

1. 安装 / 引入框架
2. 配置 Model Provider
3. 注册一个自定义 Tool
4. 调用 `agent.run(...)`
5. Harness 自动完成 Model → ToolCall → Tool → ToolResult → Model
6. 返回结构化 RunResult

示意：

```python
agent = Agent(
    model=...,
    tools=[get_weather],
)

result = agent.run("查询南京天气")
```

成功标准：开发者无需自行编写 Agent Loop。

---

# 4. 核心设计原则

## 4.1 LLM 提议，确定性系统约束

核心原则：

> LLM 负责提出“想做什么”，确定性代码负责维护状态并判断“能不能这么做”。

典型模式：

```text
LLM / Planner
    ↓
Proposal
    ↓
确定性 Manager / Policy Engine
    ↓
Validated State / Decision
```

LLM 不直接写入权威状态。

## 4.2 单一状态 Owner

每类权威状态必须只有一个明确 Owner。

- PlanState → PlanManager
- RuntimeState → RuntimeManager
- Conversation History → MemoryManager
- Session identity / lifecycle → Session

避免多个模块复制同一权威状态。

## 4.3 能推导则不重复持久化

如果一个字段可以从权威状态稳定推导，则优先使用 Projection，而不是复制存储。

## 4.4 Core 与 Domain 分离

Core 不理解光伏、合同、图库等业务语义。

Core 提供：

- 扩展接口
- 生命周期
- 状态管理
- Policy Engine
- Tool System

Domain 提供：

- Tool
- Policy
- Prompt
- Planner
- Runtime Extension

## 4.5 术语规范

PRD 优先采用 Agent / 软件工程领域中已经广泛使用的术语，不为已有概念额外创造同义名称。

统一使用：

- `AgentRunner`：负责运行 Agent Loop。`Runner` 是常见 Agent SDK 命名；本项目使用 `AgentRunner` 避免与通用 runner 混淆。
- `Session`：多轮交互的会话抽象；不额外创造同义的管理层术语。
- `Run` / `RunState`：一次执行及其状态。
- `Runtime`：Agent 运行时及当前执行环境中的状态语义。
- `Context`：提供给模型或运行代码使用的上下文；具体 LLM Context 由 ContextManager 构建。
- `Memory` / `Conversation History`：跨 Run 保留的信息与对话历史。
- `Tool` / `ToolCall` / `ToolResult` / `Tool Schema`：工具定义、调用、结果与参数契约。
- `Policy Engine` / `PolicyDecision`：策略评估组件及其决策结果。
- `Planner` / `Plan` / `Task`：规划器、计划和任务。
- `Trace`：一次 Run 的结构化执行追踪。
- `Model Provider` / `Provider Adapter`：模型供应方及其适配器。

以下名称是**本项目内部组件或数据模型命名**，不是行业标准术语；保留它们是为了表达本项目明确的职责边界，而不是声称其为通用标准：

- `RuntimeManager`
- `ContextManager`
- `MemoryManager`
- `ToolManager`
- `ModelGateway`
- `PlanManager`
- `PlanState`
- `PlanSchema` / `PlanProposal` / `PlanRevisionProposal`
- `ToolCapability`（其中 `effect` / `replay` 为本项目定义的归一化元数据字段）
- `TaskMemoryCard`（V1.x 候选的项目自定义记忆 Schema）
- `Runtime Extension`（本项目的领域运行状态扩展约定）

`Planning Decision`、`DIRECT / PLAN / REPLAN` 仅作为本项目内部流程标签，不定义为新的行业概念或独立 Manager。

---

# 5. 版本规划

# 5.1 V0 — Harness Core Validation

## 目标

验证：

> 一次 Agent Run 是否可以稳定、可控、可观察地完成。

V0 为内部开发里程碑，不要求作为完整对外产品发布。

## V0 Must Have

### 核心模块

- AgentRunner
- RuntimeManager
- ContextManager（单 Run）
- ToolManager
- ModelGateway
- Policy Engine

### Agent / Run

- 创建 Agent
- `agent.run(...)`
- 创建唯一 `run_id`
- 基础 Run lifecycle
- Run status
- max_steps
- timeout
- cancel

### ModelGateway

V0 直接实现真正的 Gateway 抽象，而非只定义接口。

要求：

- 至少实际支持 2 个 Provider Adapter
- 上层 Agent 代码无需因 Provider 切换而修改
- 统一基础 ModelResponse
- 归一化：
  - text/content
  - tool calls
  - stop reason
  - usage
  - error

### Tool System

支持：

- Tool 注册
- Tool resolve
- Tool schema validation
- Tool execution
- ToolResult
- Unknown Tool 结构化错误
- Invalid Arguments 结构化错误

### Tool Capability — 最小版

`ToolCapability` 是本项目定义的归一化工具元数据契约，不宣称为行业统一标准；其目标是让 Policy / Retry 等确定性逻辑能够读取机器可判定的工具执行属性。

V0 必须支持：

```text
effect
replay
```

建议初始枚举：

```text
effect:
  none
  network
  external
  unknown

replay:
  safe
  idempotent
  unsafe
  unknown
```

说明：Capability 描述 Tool 的执行属性，不直接等同于风险等级。

### Policy Engine

采用行业常见的 Policy Engine / Policy Layer 概念。

职责：

> 对一个已经通过接口契约校验的 Action / ToolCall，在当前 Context、Runtime、Capability 和 Policy Rules 下做执行决策。

基础 Decision：

```text
ALLOW
DENY
REQUIRE_APPROVAL（接口预留；V0 可不实现完整审批流）
```

V0 Core Policy 至少覆盖：

- max_steps
- max_tool_calls
- retry eligibility
- timeout
- cancel state
- Tool Capability 相关决策

边界：

- Tool 参数是否合法 → ToolManager / Schema Validator
- 当前是否允许执行 → Policy Engine
- Policy Engine 只返回 PolicyDecision
- AgentRunner / 对应 Manager 负责执行 Decision

支持扩展 Domain Policy。

### Retry

Retry 必须考虑 Tool Capability：

- replay=safe → 可根据 Retry Policy 自动重试
- replay=idempotent → 可按规则重试
- replay=unsafe / unknown → 默认不自动重试，除非显式策略允许

### Runtime

RuntimeManager 管理当前 Run 的瞬时执行状态。

最小信息：

```text
run_id
status
step_count
retry_count
current_tool_call
cancel_requested
started_at
finished_at
```

Runtime 核心状态不允许业务代码任意修改。

### Context

V0 ContextManager 负责单 Run Context 构建，包括：

- System Prompt
- Current User Input
- 当前 Run 内已有 Model / Tool 交互
- 可用 Tools
- 必要 Runtime Snapshot

### Structured RunResult / Trace

必须返回结构化结果，至少包括：

```text
RunResult
├── run_id
├── status
├── final_output
├── model_calls
├── tool_calls
├── errors
├── stop_reason
└── usage
```

ToolCall Trace 至少包括：

```text
tool_name
arguments
status
result / error
started_at
finished_at
```

目的：为后续 Debug、Policy、Evaluation、UI 和 Decision Layer 提供结构化数据。

## V0 明确不做

- Session
- 多轮对话
- 持久化 Memory
- Planner
- PlanState
- TaskMemoryCard 自动维护
- Pause / Resume
- Checkpoint / Restore
- Sandbox
- ArtifactStore
- Browser
- Multi-Agent

---

# 5.2 V1 — Usable Agent Harness

## 目标

验证：

> 开发者是否可以使用该 Harness 构建真正可持续使用的垂直 Agent。

V1 包含 V0 全部能力。

---

## 6. Session 与 Memory

### 6.1 Session — Must Have

`Session` 作为 V1 的一等会话抽象，负责标识一段可持续的多轮交互；V1 产品层不额外引入独立的 Session 管理组件。一个 Session 包含多个 Run：

```text
Session
├── Run #1
├── Run #2
└── Run #3
```

每次用户 `chat()` 创建新的 Run。

### 6.2 多轮 API

目标体验：

```python
session = agent.session("session_001")

session.chat("南京今天天气怎么样？")
session.chat("那明天呢？")
session.chat("和上海比较一下")
```

### 6.3 Conversation History — Must Have

MemoryManager 负责：

- 保存 Conversation History
- 加载 Conversation History

ContextManager 负责：

- 决定本次 Model Call 消费哪些 History

边界：

```text
MemoryManager
→ 提供 History

ContextManager
→ 选择哪些进入 Context
```

### 6.4 Recent Messages — Must Have

V1 默认提供 Recent Messages Context Source。

禁止将 Memory 抽象写死为 `list[Message]`，必须允许未来增加新的 Memory Source。

### 6.5 Session Persistence — Must Have

要求：

```text
程序退出
↓
重新启动
↓
session_id
↓
恢复历史对话
↓
继续多轮
```

### 6.6 MemoryStore

必须提供：

- MemoryStore Interface
- 默认本地持久化 Store
- 用户可替换自定义 Store

具体存储技术不是产品硬要求；默认实现应满足：

- 零或低配置
- 本地可持久化
- 支持 session_id 恢复

SQLite 可作为实现候选，但不在 PRD 层强绑定。

---

# 7. Planning — V1 Optional Capability

Planning 是 V1 官方能力，但单个 Agent 可以选择不开启。

合法配置：

```python
Agent(planner=None)
```

简单 Agent 不应被强制经过 Planning。

## 7.1 Planning Decision

当 Agent 配置 Planner 时，需要区分：

```text
DIRECT
PLAN
REPLAN
```

示例：

```text
“你好”
→ DIRECT

“查询南京天气”
→ DIRECT

“调研三家公司并生成比较报告”
→ PLAN

“第二步失败，换方案继续”
→ REPLAN
```

V1 不要求为该能力单独创建新的 Manager；可先作为 AgentRunner 的 Planning Decision 阶段。

## 7.2 Planner Interface — Must Have

Planner 不绑定 LLM。

概念契约：

```python
class Planner:
    def plan(...) -> PlanProposal: ...
    def replan(...) -> PlanRevisionProposal: ...
```

用户可以实现：

- LLMPlanner
- CodePlanner
- RulePlanner
- 其他自定义 Planner

## 7.3 LLMPlanner — 官方实现

V1 官方应至少提供一个 LLMPlanner。

要求：

- 产生结构化 PlanProposal
- 不依赖自由文本解析
- 使用明确 PlanSchema

推荐实现方案：

```text
LLM
↓
Structured Output
↓
Pydantic Schema
↓
PlanProposal
```

Instructor 可以作为具体实现选择，但不是产品硬依赖。

## 7.4 PlanSchema

Plan 至少支持：

```text
plan_id
goal
version
status
tasks
```

Task 至少支持：

```text
task_id
description / action
status
depends_on
```

## 7.5 PlanProposal / PlanRevisionProposal

Planner 只能输出 Proposal，不直接修改权威 PlanState。

```text
Planner
↓
PlanProposal / PlanRevisionProposal
↓
Policy / Validation
↓
PlanManager
↓
PlanState
```

## 7.6 PlanManager — Must Have

PlanManager 是 PlanState 的唯一 Owner。

负责：

- 创建 PlanState
- 校验 Plan Schema
- 校验依赖关系
- 防止非法循环依赖
- 更新 Task Status
- 应用 PlanRevision
- 维护 Plan Version
- 校验 PlanState Transition
- 调用 PlanStore 持久化

Planner 不直接操作 PlanStore。

## 7.7 Agent Model 与 Plan 的关系

Agent Model 根据 Context 中的 PlanState 自主决定下一步行动。

不要求 PlanManager 强制调度下一 Task。

原则：

```text
Agent Model
→ 自主选择行动

PlanManager
→ 校验该行动是否违反 Plan invariant

Policy Engine
→ 校验该行动在当前规则 / 风险下是否允许
```

例如：

```text
task_3 depends_on task_2
且 task_2 != completed
```

模型若尝试执行 task_3：

- PlanManager 拒绝：Plan invariant 不满足
- 返回结构化拒绝原因
- Agent Model 重新决策

## 7.8 PlanState 与 RuntimeState

边界：

```text
PlanState
= 任务结构与任务进度

RuntimeState
= 当前 Run 此刻正在发生什么
```

示例：

```text
PlanState:
  task_2.status = running

RuntimeState:
  current_task_id = task_2
  current_tool_call = call_123
```

两者语义不同，不视为重复 Source of Truth。

## 7.9 PlanStore

Planning 启用时，PlanState 必须可持久化。

PlanStore 为抽象接口。

不要求所有 Harness 状态统一存入 `plan_state` 表。

V1 产品层明确要求的持久化边界为：

```text
MemoryStore  → Conversation History / session_id 关联的会话记忆
PlanStore    → PlanState（仅启用 Planning 时）
```

物理上允许由同一个本地数据库承载。`SessionStore`、`RunStore` 是否需要独立抽象，留到技术设计阶段根据实际持久化需求决定，不作为 V1 Must Have。

---

# 8. Policy Engine — V1 设计边界

## 8.1 定位

Policy Engine 负责：

> 对一个合法 Action，在当前状态、Capability、Context 和规则下做确定性的执行决策。

## 8.2 Core Policy 与 Domain Policy

`Core Policy` / `Domain Policy` 是本项目用于区分“框架通用规则”和“垂直业务规则”的内部分类，不作为行业标准术语。

### Core Policy

框架提供通用规则机制，例如：

- 调用次数限制
- retry
- timeout
- cancel
- approval requirement
- Tool Capability 相关规则

### Domain Policy

垂直领域注入业务规则，例如：

```text
合同 Agent：
某类合同禁止自动提交审批

光伏 Agent：
未完成数据校验不得覆盖正式预测结果
```

原则：

```text
Core 提供 Policy Engine 与规则扩展点
Domain 提供业务 Policy
```

## 8.3 Policy 不承担的职责

Policy Engine 不负责：

- Tool 是否存在
- Tool 参数 Schema 是否正确
- Plan dependency 是否满足
- 直接修改 PlanState
- 直接执行 Tool

Policy 只输出 PolicyDecision。

---

# 9. Tool 执行生命周期

当 Model 输出 ToolCall 时：

```text
Agent Model
      ↓
ToolCall（待授权 Action）
      ↓
ToolManager.resolve()
      ↓
Schema Validation
      ↓
Tool Capability
      ↓
Policy Engine
      ↓
PolicyDecision
      ↓
AgentRunner
      ↓
Tool Execution
      ↓
ToolResult
```

重要原则：

> Model 输出 ToolCall 只表示模型请求调用工具，不等于已经获得执行权。

### 分层错误语义

```text
Unknown Tool
→ ToolManager / Registry

Invalid Arguments
→ ToolManager / Schema Validation

Plan Dependency Violation
→ PlanManager

Execution Not Allowed
→ Policy Engine

Tool Runtime Failure
→ Tool execution / Runtime
```

---

# 10. Runtime Extension — V1 Must Have

允许垂直 Agent 扩展 Runtime，但不能任意修改 Harness Core Runtime。

概念模型：

```text
Runtime
├── core
│   └── Harness-owned
└── extensions
    └── Domain-owned
```

例如：

```yaml
core:
  status: running

extensions:
  solar:
    selected_station: station_01
```

要求：

- Core Runtime 只能通过受控 API 更新
- Domain Extension 有独立 namespace
- Domain Extension 不覆盖 Core 字段

---

# 11. TaskMemoryCard — V1 只预留，不自动维护

原 Task State Card 拆分后：

- 任务结构 / 进度 → PlanState
- 任务认知记忆 → TaskMemoryCard

TaskMemoryCard 未来用于：

```text
constraints
confirmed_facts
hypotheses
decisions
failed_attempts
important_resources
open_questions
summary
```

V1：

- 允许定义 Schema / Memory Source Interface
- 不实现自动抽取
- 不实现自动更新
- 不实现 Context Compaction

V1.x 再实现。

---

# 12. Run 生命周期（当前冻结版）

完整 V1 目标流程：

```text
User Input
   ↓
Resolve / Create Session
   ↓
Create Run
   ↓
RuntimeManager.start()
   ↓
MemoryManager.load(session_id)
   ↓
Conversation History
   ↓
Planning Decision
   ├── DIRECT
   ├── PLAN
   └── REPLAN
   ↓
[需要时] Planner
   ↓
PlanProposal / RevisionProposal
   ↓
PlanManager / Policy
   ↓
PlanState
   ↓
ContextManager
   ↓
ModelGateway
   ↓
Agent Model
   ↓
ToolCall（待授权 Action）
   ↓
ToolManager / Schema Validation
   ↓
Plan Validation（启用 Planning 时）
   ↓
Policy Engine
   ↓
Tool Execution
   ↓
ToolResult
   ↓
Runtime / PlanState 更新
   ↓
ToolResult 回到 Model Loop
   ↓
继续行动 / Replan / Final Answer
   ↓
Run Complete
   ↓
Persist History / Plan（Trace 持久化不作为 V1 硬要求）
   ↓
Structured RunResult
```

说明：ToolResult 返回后的具体循环终止算法属于实现设计，可在编码阶段在不破坏上述边界的前提下细化。

---

# 13. V1 非目标 / Later

以下能力明确不进入 V1 Must Have：

- TaskMemoryCard 自动维护
- Context Compaction
- Retrieved Memory / Vector Memory
- Vector DB
- Pause / Resume
- Checkpoint / Restore
- 完整 Crash Recovery
- Tool Capability concurrency
- Tool Capability checkpoint
- Tool Capability durability
- ExecutionEnvironment
- Docker Sandbox
- ArtifactStore
- Browser
- Multi-Agent
- Knowledge Graph
- 复杂 Event Bus
- Distributed Runtime

---

# 14. Core 不内置的具体能力

Core 不强制提供：

```text
read
write
edit
bash
```

也不强制绑定：

- MySQL
- PostgreSQL
- Redis
- Vector DB
- 某个 LLM Provider
- 某个业务 Tool

所有此类能力通过 Adapter / Extension / Domain Layer 提供。

---

# 15. 初始核心模块清单

当前产品层确认的核心模块：

```text
AgentRunner
RuntimeManager
ContextManager
MemoryManager
ToolManager
ModelGateway
PolicyEngine
```

V1 Optional Planning：

```text
Planner
PlanManager
PlanStore
```

注意：是否最终映射为相同数量的 Python class / package 属于后续技术设计，不由 PRD 强制。

---

# 16. 推荐的最小公开 API 方向（非最终实现约束）

## V0

```python
agent = Agent(
    model=model,
    tools=[get_weather],
    policy=policy,
)

result = agent.run("查询南京天气")
```

## V1

```python
agent = Agent(
    model=model,
    tools=[get_weather],
    planner=planner,       # optional
    memory_store=store,   # optional, has default local store
)

session = agent.session("session_001")
result = session.chat("查询南京天气并和上海比较")
```

---

# 17. 验收标准

## V0 验收

满足以下条件即可认为 V0 完成：

1. 同一个 Agent 可仅修改配置切换至少 2 个模型 Provider。
2. 一个自定义 Tool 可注册并由模型成功调用。
3. Tool 参数错误不会进入实际 Tool 执行。
4. Policy Engine 可阻止一个不允许执行的合法 ToolCall。
5. unsafe replay Tool 不会被默认自动重试。
6. max_steps / timeout / cancel 能终止 Run。
7. Run 返回结构化 RunResult / Trace。
8. 单 Run Model → Tool → Model 闭环稳定完成。

## V1 验收

在 V0 基础上：

1. 一个 Session 可连续执行多个 Run。
2. 程序重启后，通过 session_id 可恢复 Conversation History。
3. 默认本地 Store 开箱可用。
4. 用户可替换自定义 MemoryStore。
5. Agent 可以关闭 Planner 并直接执行简单任务。
6. Agent 可以启用 Planner 处理复杂任务。
7. Planner 输出遵循统一 PlanSchema。
8. LLMPlanner 与自定义 CodePlanner 均可接入统一 Planner Interface。
9. PlanManager 是 PlanState 唯一写入口。
10. 模型可以依据 PlanState 自主选择行动。
11. PlanManager 能拒绝违反 dependency / state transition 的行动。
12. Policy Engine 能在 Tool 执行阶段进行独立决策。
13. Domain Policy 可注入，不修改 Harness Core。
14. Runtime Extension 可添加领域状态且不污染 core namespace。

---

# 18. 开发顺序建议

建议按以下顺序交给 Codex 实现：

```text
V0-1  基础数据模型
V0-2  ModelGateway
V0-3  ToolManager + ToolCapability
V0-4  RuntimeManager
V0-5  PolicyEngine
V0-6  ContextManager
V0-7  AgentRunner / Agent Loop
V0-8  RunResult / Trace / Control
V0 验收

V1-1  Session
V1-2  MemoryManager + Default Local Store
V1-3  Session Restore
V1-4  Planner Interface + PlanSchema
V1-5  PlanManager + PlanStore
V1-6  LLMPlanner
V1-7  Planning Decision / Replan
V1-8  Runtime Extension
V1 验收
```

---

# 19. 当前设计断点

产品需求与 Scope 已冻结。

后续技术设计需要继续细化的第一个位置是：

> ToolResult 返回后，AgentRunner 如何把结果重新注入 Model Loop，如何判断当前 Task 完成、是否继续下一个 Action、何时触发 REPLAN，以及何时结束 Run。

这些属于下一阶段“技术设计 / 编码实现”，不再作为 PRD Scope 扩张理由。

---

# 20. 最终一句话定义

> 一个 Python-first、可迁移、可扩展、可观察且可控制的 Agent Harness / Runtime Framework，用统一的运行骨架承载不同垂直领域 Agent。
