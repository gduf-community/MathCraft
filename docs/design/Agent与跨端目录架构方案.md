# Agent 与跨端目录架构方案

**状态**：第一阶段目录重构已实施；Agent 运行时、SSE 会话和业务模块仍按本方案逐步实现。

**更新日期**：2026-11-03。

## 1. 目标

为 OpenAI Agents SDK 出题智能体、知识库领域和 Windows/macOS 跨端客户端建立长期可演进的目录与接口分层。方案保留现有 MathCraft 后端的运行时数据边界。第一阶段已经完成源码根目录、知识库领域、出题领域、客户端预留目录和契约预留目录的落位，Agent 运行时及应用装配继续按后续实施任务推进。

## 2. 目标目录

```text
MathCraft/
├── apps/
│   ├── desktop/                 # Windows/macOS 跨端客户端
│   └── web/                     # 可选 Web 客户端
├── backend/
│   ├── src/
│   │   ├── app/                 # 应用装配、启动、依赖注入
│   │   ├── agents/              # OpenAI Agents SDK 运行时与 Agent 工具
│   │   │   ├── runtime/
│   │   │   ├── tools/
│   │   │   ├── skills/
│   │   │   ├── sessions/
│   │   │   └── models/
│   │   ├── knowledge/           # 知识库、解析、索引、检索
│   │   ├── questions/            # 题目、草稿、版本、确认
│   │   ├── settings/            # 模型和应用设置
│   │   ├── transport/            # HTTP、SSE、WebSocket
│   │   └── shared/               # 少量跨领域基础类型
│   └── tests/
├── packages/
│   └── contracts/               # OpenAPI、JSON Schema、事件契约
├── frontend/                    # 现有 React 前端的过渡位置
└── docs/
```

当前仓库已经具备 `backend/src/MathCraft/`、`backend/src/knowledge/`、`backend/src/questions/`、`backend/src/agents/`、`backend/src/app/`、`backend/src/settings/`、`backend/src/transport/`、`backend/src/shared/`、`apps/desktop/` 和 `packages/contracts/` 这些目录入口。其中 `MathCraft` 仍是现有运行时兼容锚点，后续可按领域边界逐步收缩；`agents`、`app`、`settings`、`transport`、`shared` 和跨端契约目录目前保留最小入口文件。

`backend/src/agents/` 是领域目录名称，不能直接作为项目自己的顶层 Python 包名。OpenAI Agents SDK 使用 `from agents import Agent, Runner`，因此实现阶段必须避免本地目录遮蔽第三方 `agents` 包。可采用正式 Python 包命名空间、显式包发现配置或将实现包命名为 `mathcraft_agent`；具体迁移方式在实施设计中确定。

## 3. 领域职责

### 3.1 Agent

Agent 模块负责 Agent 定义、OpenAI Agents SDK Runner、Function Tools、Skill 读取、会话适配、模型适配和 SDK 事件转换。它不直接决定题目版本如何保存，也不直接操作知识库物理路径。

### 3.2 Knowledge

Knowledge 模块负责资料、解析、索引、检索和来源定位。Agent 只能通过受约束的知识库工具读取资料，工具参数使用逻辑标识和范围约束，不暴露物理路径。

### 3.3 Questions

Questions 模块负责出题任务、任务计划、草稿候选、题目实体、题目版本和人工确认记录。保存版本、删除历史版本、扩大资料范围和改变已确认计划都必须经过该模块的业务规则校验。

### 3.4 Transport

Transport 模块负责把内部 Agent 运行结果转换为稳定的 HTTP、SSE 和 WebSocket 契约。客户端不依赖 `Agent`、`Runner`、`RunState`、`SQLiteSession` 或 OpenAI 原始事件类型。

### 3.5 Contracts

Contracts 模块保存 OpenAPI、请求响应 Schema 和 SSE 事件语义，作为 Web 客户端、桌面客户端和后端之间的共享契约来源。

## 4. Q10 会话决策

Q10 已与当前架构对齐，最终决策如下：

> 第一版使用 OpenAI Agents SDK 的 Session 接口管理 Agent 对话上下文。单机开发和 Windows/macOS 本地客户端优先使用运行时目录中的 SQLite；服务端多进程或云端部署时，可以通过 Session Adapter 切换到 SQLAlchemy、Redis 或其他适合的后端。出题任务、候选题、正式题目版本和确认记录属于 MathCraft 业务数据，由业务模块单独建模和持久化。

### 4.1 SDK Session 的职责

SDK Session 保存当前 Agent 会话的对话历史、工具调用和模型上下文。单机模式可以使用官方 `SQLiteSession` 或异步 SQLite Session，数据库文件必须位于运行时数据目录，不得进入仓库。

同一个会话选择一种主要的上下文续接策略：使用 SDK Session 时，不再同时把本地回放历史与 `conversation_id` 或 `previous_response_id` 混合作为同一会话的权威来源。

### 4.2 MathCraft 业务数据的职责

SDK Session 不保存以下业务事实，或不作为以下事实的权威来源：

- 出题任务及任务状态；
- 任务计划和教师确认结果；
- 未保存题目候选；
- 题目实体和题目版本；
- 版本引用、删除保护和幂等记录；
- 知识库文档、解析结果和索引状态。

这些数据由 MathCraft 的业务模块和 Repository 管理。SDK Session 可以通过 `session_id` 与任务关联，但不能代替业务数据模型。

### 4.3 人工确认和恢复

Agent 需要人工确认时，使用 SDK 的暂停和恢复能力保存运行状态；MathCraft 同时保存确认对象、业务版本和幂等信息。SDK 恢复状态用于继续 Agent 运行，业务记录用于判断确认是否有效以及防止重复写入。

## 5. 跨端运行模式

客户端只依赖产品协议，后端可以采用以下部署方式：

| 模式 | Agent 运行位置 | 会话存储 | 适用范围 |
| --- | --- | --- | --- |
| 本地 | 客户端启动的本地后端或 sidecar | 运行时目录 SQLite | 单机和本地知识库 |
| 云端 | 远程 MathCraft 后端 | 服务端数据库或 Session Adapter | 多设备和集中知识库 |
| 混合 | 云端为权威，本地保存缓存 | 服务端权威数据，本地保存草稿队列 | 断线恢复和多设备使用 |

第一版不承诺完全离线生成。客户端可以离线查看缓存和编辑未提交草稿，恢复网络后通过幂等请求提交；模型调用、Agent 运行和正式版本保存仍由可用的后端负责。

## 6. 对外事件契约

Agent SDK 的原始事件由后端转换成产品事件，第一版至少保留以下语义：

```text
turn.started
message.delta
tool.started
tool.completed
source.found
draft.updated
approval.required
turn.completed
turn.failed
```

Agent 使用 SSE 输出文本、工具调用、检索来源、草稿变化、等待确认和完成状态。知识库索引进度继续使用现有 WebSocket；两者不共用同一套客户端状态机。

## 7. 异常边界

- SDK Session 写入失败时，不能静默报告业务版本保存成功。
- SSE 在最后一个文本事件后仍可能需要等待 SDK 完成会话保存、审批状态和上下文压缩；只有 Agent 运行真正结束后才能发送 `turn.completed`。
- 客户端断线不能自动判定任务失败；客户端通过事件游标或任务查询恢复状态。
- Agent 工具失败、模型失败和业务校验失败必须使用不同的产品错误类别。
- 客户端提交的“已确认”状态不具有写入权限；后端必须重新校验确认记录、任务版本和幂等键。

## 8. 验收标准

1. 目标目录作为后续重构基线记录，当前文档明确区分目标结构和实际结构。
2. Agent 会话可以通过 SDK Session 恢复多轮上下文。
3. 本地模式可以把 Session 数据写入运行时目录 SQLite，仓库不出现运行时数据库。
4. 题目任务、草稿、版本和确认记录可以独立于 SDK Session 查询和恢复。
5. SSE 客户端不需要导入 OpenAI Agents SDK 类型。
6. 同一套 HTTP、SSE 和业务 Schema 可以供 Web、Windows 和 macOS 客户端使用。
7. 后续切换 Session 后端不会改变客户端协议和题目业务契约。

## 9. 实施顺序

1. 先建立领域模块和包发现规则，消除旧顶层 `api`、`services`、`schemas` 对正式包的反向依赖。
2. 固定 `packages/contracts` 中的 Agent、任务和题目版本契约。
3. 接入 OpenAI Agents SDK 的 Agent、Tools、Skills 和 Session Adapter。
4. 新增 Agent SSE 路由，保留知识库 WebSocket。
5. 建立题目任务和版本持久化，再开放保存、删除和确认操作。
6. 最后接入桌面客户端；桌面客户端只消费契约，不直接依赖后端 Python 模块。
