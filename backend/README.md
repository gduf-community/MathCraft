# backend 目录说明

`backend/` 包含统一的 MathCraft Python 后端，知识库、模型配置和出题路由运行在同一个 FastAPI 进程中。

## 目录结构

```text
backend/
├── MathCraft/          # 唯一 Python 主实现包
│   ├── __main__.py     # python -m MathCraft 启动入口
│   ├── app.py          # 统一 FastAPI 应用与路由装配
│   ├── api/            # 正式业务路由、运行时生命周期与公开导出
│   │   ├── main.py     # 导出 MathCraft.app 中的同一个 app
│   │   ├── runtime.py  # lifespan、运行时初始化与 CORS 中间件
│   │   └── routers/    # 原实现包路由迁入此处
│   │       └── profile.py # 教师资料与头像 HTTP 能力
│   ├── capabilities/   # 外部能力与 MarginNote4 连接器
│   ├── config/         # 进程配置
│   ├── core/           # 跨层协议、工具和流事件
│   ├── knowledge/      # 知识库管理、索引与进度事件
│   │   └── model_references.py # 嵌入绑定查询，异常注册表阻止删除
│   ├── logging/        # 日志与调用统计
│   ├── multi_user/     # 上游多用户兼容模块（当前由单租户替身驱动）
│   ├── runtime/        # 数据根、运行模式与隔离 worker
│   │   ├── isolated_worker.py # 父进程调度、超时、并发与取消回收
│   │   ├── worker_process.py # 固定 python -m 入口、pickle 请求及结果封套
│   │   └── worker_tasks.py # 惰性文本提取与 UTF-8 Markdown 写入
│   ├── services/       # LLM、嵌入、RAG、解析、设置等业务服务
│   │   ├── config/direct_model_config.py # 独立配置迁移、名称与有效参数快照
│   │   ├── settings/direct_model_edit.py # 当前项锁内合并、默认与任务模式
│   │   └── profile/    # 单租户资料与头像独立存储
│   ├── tools/          # RAG 检索、网页抓取等工具入口
│   └── utils/          # 通用文件、JSON、网络与校验工具
├── api/                # 出题编排路由：generate、chat
├── services/           # 出题业务与正式知识库/LLM 适配器
│   ├── chat_flow.py    # 多轮追问，必填信息齐备后生成
│   ├── slots.py        # 累积要求与各题型数量检查
│   ├── prompts.py      # 题目生成与信息抽取提示词
│   ├── knowledge.py    # 正式知识库目录与文档访问
│   ├── retrieval.py    # RAGService 检索适配器
│   └── llm.py          # 正式 LLM 配置适配器
├── schemas/            # 出题服务与个人资料的请求／响应契约
│   └── profile.py      # 资料字段、只读身份与学段年级校验
├── scripts/            # 出题和对话联测脚本（使用正式知识库）
├── tests/              # 后端测试套件
│   ├── test_isolated_document_extraction.py # 真实子进程提取、预览、错误与回收
│   ├── test_chat_requirements.py # 缺项阻止生成及多轮补齐回归
│   ├── test_direct_model_settings.py # 单项保存、并发与错误边界
│   ├── test_direct_model_migration.py # 迁移、名称、掩码与环境优先级
│   ├── test_direct_model_discovery.py # 本地假服务发现及 HTTP 反馈
│   ├── test_direct_model_references.py # 有效依赖与知识库删除保护
│   ├── test_direct_model_knowledge.py # 已发布索引迁移与实际检索
│   ├── test_direct_model_lifecycle.py # 只读、无变化和失败写入保持客户端与日志安全
│   └── test_model_workspace_draft.py # 隔离设置草稿、无请求体应用与凭据回归
└── main.py             # 统一应用兼容入口
```

## 运行边界

- 使用 `python -m MathCraft` 启动统一后端；`MathCraft.api.main:app` 是对外 ASGI 入口，包含知识库、模型配置和出题路由。
- `MathCraft/` 同时承载从 DeepTutor 裁剪而来的正式实现与统一应用入口。出题服务通过薄适配器调用 `MathCraft` 内的 RAGService、LLM 和知识库访问层。旧 `math_q_agent` import 与命令停止支持，不保留旧目录兼容壳。
- `MathCraft.app` 装配正式知识库、模型配置和出题编排服务。`python -m MathCraft` 启动时加载根目录 `.env`；监听地址按 `--host`、`BACKEND_HOST`、默认值 `127.0.0.1` 的优先级确定，端口按 `--port`、`BACKEND_PORT`、已保存系统设置、默认值 `8000` 的优先级确定。shell 中同名变量优先于 `.env`；默认前端端口为 `5173`。统一应用在启动后读取 `CORS_ORIGIN` / `CORS_ORIGINS`，默认无认证模式保持跨域放行。
- `MathCraft/api/runtime.py` 保存原实现包 `api/main.py` 中的 lifespan 与中间件；`MathCraft/api/main.py` 仅导出统一 app。正式业务路由统一位于 `MathCraft/api/routers/`，HTTP 和 WebSocket 路径保持不变。
- 数据根环境变量现统一为 `MATHCRAFT_HOME`，不提供旧名回退；将其值指向原 home 目录时，运行数据、索引和本地配置继续从同一 `data/` 读取，无需搬迁或重建。

迁移范围、契约、协作边界与验收标准见 [后端包统一与接口对齐](../docs/design/后端包统一与接口对齐.md)。

前后端端口统一由根 `.env` 配置时，后端使用 `python -m MathCraft` 启动。直接运行 Uvicorn 并指定 `--port` 会使用其命令行端口；应用 lifespan 加载 `.env` 无法修改已经解析的监听参数，可能导致 Vite 按 `.env` 转发到没有监听的端口。

应用模块导入仅装配路由，ASGI lifespan 负责加载 `.env`、初始化运行时设置、导出环境变量和配置日志。`MATHCRAFT_HOME` 可在导入后、启动前确定；配置默认目录由路径服务解析，已有实例继续绑定其原目录。启动顺序与异常边界见 [模型配置来源与普通知识库流程](../docs/design/模型配置来源与普通知识库流程.md)。

## 隔离文档提取

本次补齐基线缺失的 `MathCraft/runtime/worker_process.py` 与 `worker_tasks.py`，恢复 `extract_text_from_path_isolated()` 和 `TextOnlyParser.parse()` 的既有调用链；不增加依赖，单租户边界保持有效。2026-10-31 在 Windows / Python 3.14 上完成真实子进程及完整后端验证。

- `isolated_worker.py` 使用当前 Python 解释器执行固定命令 `python -m MathCraft.runtime.worker_process <request_path> <result_path>`，不通过 shell；继续管理临时目录、超时、并发限制，以及异步取消后的终止和等待回收。
- `worker_process.py` 读取 pickle 请求 `{callable_path, args, kwargs}`，按 `module:callable` 定位同步函数。成功写入 `{ok: True, result: ...}`；失败写入 `{ok: False, message, module, type, traceback, attrs}`。`attrs` 至少保留异常的 `filename`，忽略不可序列化属性，避免属性序列化失败掩盖原错误。该协议只用于父进程创建的可信临时文件，不是 HTTP 接口。
- `worker_tasks.py` 在任务执行时惰性调用 `MathCraft.utils.document_extractor.extract_text_from_path`。`extract_document_text` 透传 `filename_hint`、`max_bytes`、`max_chars` 并返回字符串；`extract_document_to_markdown` 先完成提取，再创建目标父目录、以 UTF-8 写入 `.md`，返回 `None`。提取失败不提前创建输出目录或文件。
- 远程失败先由父进程包装为 `IsolatedWorkerError`；公开提取入口继续恢复文档异常及 `filename`，并将既有内置文件异常映射为 `OSError`。`TextOnlyParser` 继续将既有 worker/文件错误包装为 `ParserError`。超时、取消、无结果或损坏结果沿用父进程原有异常边界，不转换为成功或静默回退。
- HTTP 文本预览沿用 `GET /api/knowledge-bases/{kb_name}/file-preview-text/{filename:path}`：成功返回纯文本，文档提取失败返回 422，文件缺失返回 404；请求字段与响应格式不变。traceback 和内部属性不增加为 HTTP 响应字段。

验收入口为 `.venv\Scripts\python.exe -m pytest backend/tests/test_isolated_document_extraction.py -q`，要求真实子进程覆盖文本/PDF 成功、Markdown 输出、HTTP 预览成功、错误传回、超时与取消，并完成后端回归。验收细项及实际结果记录入口见[后端包统一与接口对齐第 10 节](../docs/design/后端包统一与接口对齐.md#10-隔离文档解析恢复方案与验收)。新增回归 25 项通过、既有解析相关测试 9 项通过，完整后端套件 322 项通过、1 项跳过；仅有既有 PyMuPDF 弃用提示。

## 教师个人资料

`GET/PUT /api/user-profile` 独立读取与保存昵称、任教学段及年级，教师身份只读。`POST /api/user-profile/avatar` 上传经内容校验的位图，`GET /api/user-profile/avatar` 读取已保存头像；没有头像时返回 404。PNG、JPEG、WebP 上限 5 MiB，服务端拒绝非法路径、伪造格式、损坏或过大图片，失败保留旧头像。

统一应用装配资料路由，所有公开入口导出或启动同一个 app。个人资料和头像位于运行时数据根，不进入模型 catalog/draft、配置导出或 Git。资料和头像接口独立持久化；前端先预览，用户确认后顺序提交，部分失败分别反馈，不提供跨请求事务。具体字段及错误状态见 [API 文档](../docs/api.md)，实现范围见[功能规格](../docs/design/个人中心与应用设置功能规格.md)，验证结果见[实施记录](../docs/design/个人中心与应用设置实施记录.md)。

## 模型草稿与凭据历史回归

历史[模型与服务页面优化](../docs/design/模型与服务页面优化功能规格.md)使用原设置接口；当前模型入口已采用下文直接配置方案。独立 Profile 明确清空凭据时，运行时必须保持为空，不能借用同提供方其他 Profile 的密钥；缺省凭据仍沿用已有继承行为。回归用例通过隔离设置路由、本地 HTTP 假服务与公共运行时配置读取验证暂存、无请求体应用、脱敏凭据和失败重试，执行结果见[实施记录](../docs/design/模型与服务页面优化实施记录.md)。

## 模型直接配置

每个模型以 `direct_config` 保存独立提供方、地址、凭据和高级连接参数，原 Profile/模型 ID 保持稳定。目录迁移原子、幂等，旧任务引用复制原目标，重名按稳定规则调整；纯结构迁移保留已有嵌入签名和索引绑定。损坏文件或迁移失败时保留原文件并返回安全错误，不使用环境值覆盖故障文件。

`POST /api/settings/direct-model` 在锁内合并当前项，默认、删除和任务模式分别使用对应端点。名称统一去首尾空白并按大小写敏感规则全局校验；所有保留的旧写入入口同样校验，旧共享字段不覆盖已有独立模型。普通保存及发现只从同 ID 正式项恢复掩码；明确恢复草稿时还校验草稿版本。`GET /api/settings/direct-model/draft` 只生成安全迁移预览，不写入或启用草稿。

两条保留的模型发现通路返回一致业务状态、模型列表、原因代码及存在的上游 HTTP 状态。请求只执行模型列表发现，不进行推理或嵌入，不回传上游错误正文。接口以[机器契约](../openapi.json)及[生成 API 文档](../docs/api.md)为准，行为范围见[功能规格](../docs/design/模型直接配置功能规格.md)。

独立模型实现入口：`MathCraft/services/config/direct_model_config.py` 负责正式配置迁移和名称约束；`MathCraft/services/settings/direct_model_edit.py` 负责当前模型合并及默认操作。知识库兼容验证通过设置接口、公开运行时解析和本地假嵌入索引进行，详见[模型直接配置实施记录](../docs/design/模型直接配置实施记录.md)。

## 对话出题必填检查

`/api/chat` 累积教师要求，在题型、每种题型数量、范围、来源和难度齐备后才调用生成；数量缺失时按题型追问，每种题型数量为 1–20 道，不使用默认数量。设计与边界见 [对话出题必填信息检查](../docs/design/对话出题必填信息检查.md)。

## 收藏功能边界

收藏页沿用前端内存 mock，刷新后重置；收藏与收藏夹尚未接入后端持久化。本轮统一包与审计前端调用不新增收藏后端接口或存储。
