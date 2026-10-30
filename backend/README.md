# backend 目录说明

`backend/` 包含统一的 MathCraft Python 后端，知识库、模型配置和出题路由运行在同一个 FastAPI 进程中。

## 目录结构

```text
backend/
├── MathCraft/          # 对外 Python 模块与启动入口（python -m MathCraft）
│   ├── app.py          # 统一 FastAPI 应用装配
│   └── api/            # 对外 FastAPI 应用导出
├── math_q_agent/       # DeepTutor 兼容实现包，保留原有 import 路径
│   ├── api/            # FastAPI 应用装配、路由与请求工具
│   │   └── routers/profile.py # 教师资料与头像 HTTP 能力
│   ├── capabilities/   # 外部能力与 MarginNote4 连接器
│   ├── config/         # 进程配置
│   ├── core/           # 跨层协议、工具和流事件
│   ├── knowledge/      # 知识库管理、索引与进度事件
│   │   └── model_references.py # 嵌入绑定查询，异常注册表阻止删除
│   ├── logging/        # 日志与调用统计
│   ├── multi_user/     # 上游多用户兼容模块（当前由单租户替身驱动）
│   ├── runtime/        # 数据根、运行模式与隔离 worker
│   ├── services/       # LLM、嵌入、RAG、解析、设置等业务服务
│   │   ├── config/direct_model_config.py # 独立配置迁移、名称与有效参数快照
│   │   ├── settings/direct_model_edit.py # 当前项锁内合并、默认与任务模式
│   │   └── profile/    # 单租户资料与头像独立存储
│   ├── tools/          # RAG 检索、网页抓取等工具入口
│   └── utils/          # 通用文件、JSON、网络与校验工具
├── api/                # 出题编排路由：generate、chat
├── services/           # 出题业务与正式知识库/LLM 适配器
│   ├── knowledge.py    # 正式知识库目录与文档访问
│   ├── retrieval.py    # RAGService 检索适配器
│   └── llm.py          # 正式 LLM 配置适配器
├── schemas/            # 出题服务与个人资料的请求／响应契约
│   └── profile.py      # 资料字段、只读身份与学段年级校验
├── scripts/            # 出题和对话联测脚本（使用正式知识库）
├── tests/              # 后端测试套件
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
- `math_q_agent/` 作为 DeepTutor 正式实现包保留，出题服务通过薄适配器调用其中的 RAGService、LLM 和知识库访问层。
- `MathCraft.app` 装配正式知识库、模型配置和出题编排服务。`python -m MathCraft` 启动时加载根目录 `.env`；监听地址按 `--host`、`BACKEND_HOST`、默认值 `127.0.0.1` 的优先级确定，端口按 `--port`、`BACKEND_PORT`、已保存系统设置、默认值 `8000` 的优先级确定。shell 中同名变量优先于 `.env`；默认前端端口为 `5173`。统一应用与兼容应用均在启动后读取 `CORS_ORIGIN` / `CORS_ORIGINS`，默认无认证模式保持跨域放行。
- 运行数据、索引和本地配置不放入代码目录，统一按根 README 的约定写入运行时数据目录。

前后端端口统一由根 `.env` 配置时，后端使用 `python -m MathCraft` 启动。直接运行 Uvicorn 并指定 `--port` 会使用其命令行端口；应用 lifespan 加载 `.env` 无法修改已经解析的监听参数，可能导致 Vite 按 `.env` 转发到没有监听的端口。

应用模块导入仅装配路由，ASGI lifespan 负责加载 `.env`、初始化运行时设置、导出环境变量和配置日志。`MATH_Q_HOME` 可在导入后、启动前确定；配置默认目录由路径服务解析，已有实例继续绑定其原目录。启动顺序与异常边界见 [模型配置来源与普通知识库流程](../docs/design/模型配置来源与普通知识库流程.md)。

## 教师个人资料

`GET/PUT /api/user-profile` 独立读取与保存昵称、任教学段及年级，教师身份只读。`POST /api/user-profile/avatar` 上传经内容校验的位图，`GET /api/user-profile/avatar` 读取已保存头像；没有头像时返回 404。PNG、JPEG、WebP 上限 5 MiB，服务端拒绝非法路径、伪造格式、损坏或过大图片，失败保留旧头像。

统一入口和兼容入口都装配资料路由。个人资料和头像位于运行时数据根，不进入模型 catalog/draft、配置导出或 Git。资料和头像接口独立持久化；前端先预览，用户确认后顺序提交，部分失败分别反馈，不提供跨请求事务。具体字段及错误状态见 [API 文档](../docs/api.md)，实现范围见[功能规格](../docs/design/个人中心与应用设置功能规格.md)，验证结果见[实施记录](../docs/design/个人中心与应用设置实施记录.md)。

## 模型草稿与凭据历史回归

历史[模型与服务页面优化](../docs/design/模型与服务页面优化功能规格.md)使用原设置接口；当前模型入口已采用下文直接配置方案。独立 Profile 明确清空凭据时，运行时必须保持为空，不能借用同提供方其他 Profile 的密钥；缺省凭据仍沿用已有继承行为。回归用例通过隔离设置路由、本地 HTTP 假服务与公共运行时配置读取验证暂存、无请求体应用、脱敏凭据和失败重试，执行结果见[实施记录](../docs/design/模型与服务页面优化实施记录.md)。

## 模型直接配置

每个模型以 `direct_config` 保存独立提供方、地址、凭据和高级连接参数，原 Profile/模型 ID 保持稳定。目录迁移原子、幂等，旧任务引用复制原目标，重名按稳定规则调整；纯结构迁移保留已有嵌入签名和索引绑定。损坏文件或迁移失败时保留原文件并返回安全错误，不使用环境值覆盖故障文件。

`POST /api/settings/direct-model` 在锁内合并当前项，默认、删除和任务模式分别使用对应端点。名称统一去首尾空白并按大小写敏感规则全局校验；所有保留的旧写入入口同样校验，旧共享字段不覆盖已有独立模型。普通保存及发现只从同 ID 正式项恢复掩码；明确恢复草稿时还校验草稿版本。`GET /api/settings/direct-model/draft` 只生成安全迁移预览，不写入或启用草稿。

两条保留的模型发现通路返回一致业务状态、模型列表、原因代码及存在的上游 HTTP 状态。请求只执行模型列表发现，不进行推理或嵌入，不回传上游错误正文。接口以[机器契约](../openapi.json)及[生成 API 文档](../docs/api.md)为准，行为范围见[功能规格](../docs/design/模型直接配置功能规格.md)。

独立模型实现入口：`math_q_agent/services/config/direct_model_config.py` 负责正式配置迁移和名称约束；`math_q_agent/services/settings/direct_model_edit.py` 负责当前模型合并及默认操作。知识库兼容验证通过设置接口、公开运行时解析和本地假嵌入索引进行，详见[模型直接配置实施记录](../docs/design/模型直接配置实施记录.md)。
