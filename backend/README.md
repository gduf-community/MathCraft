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
│   ├── logging/        # 日志与调用统计
│   ├── multi_user/     # 上游多用户兼容模块（当前由单租户替身驱动）
│   ├── runtime/        # 数据根、运行模式与隔离 worker
│   ├── services/       # LLM、嵌入、RAG、解析、设置等业务服务
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
└── main.py             # 统一应用兼容入口
```

## 运行边界

- 使用 `python -m MathCraft` 启动统一后端；`MathCraft.api.main:app` 是对外 ASGI 入口，包含知识库、模型配置和出题路由。
- `math_q_agent/` 作为 DeepTutor 正式实现包保留，出题服务通过薄适配器调用其中的 RAGService、LLM 和知识库访问层。
- `MathCraft.app` 装配正式知识库、模型配置和出题编排服务；端口和地址读取根目录 `.env` 的 `BACKEND_HOST` / `BACKEND_PORT`。
- `MathCraft` 的启动入口会加载同一份根目录 `.env`，其中 `BACKEND_HOST` / `BACKEND_PORT` 控制知识库与模型配置服务；没有 `BACKEND_PORT` 时使用已保存启动设置，显式 `--port` 优先。
- 运行数据、索引和本地配置不放入代码目录，统一按根 README 的约定写入运行时数据目录。

应用模块导入仅装配路由，ASGI lifespan 负责加载 `.env`、初始化运行时设置、导出环境变量和配置日志。`MATH_Q_HOME` 可在导入后、启动前确定；配置默认目录由路径服务解析，已有实例继续绑定其原目录。启动顺序与异常边界见 [模型配置来源与普通知识库流程](../docs/design/模型配置来源与普通知识库流程.md)。

## 教师个人资料

`GET/PUT /api/user-profile` 独立读取与保存昵称、任教学段及年级，教师身份只读。`POST /api/user-profile/avatar` 上传经内容校验的位图，`GET /api/user-profile/avatar` 读取已保存头像；没有头像时返回 404。PNG、JPEG、WebP 上限 5 MiB，服务端拒绝非法路径、伪造格式、损坏或过大图片，失败保留旧头像。

统一入口和兼容入口都装配资料路由。个人资料和头像位于运行时数据根，不进入模型 catalog/draft、配置导出或 Git。资料和头像接口独立持久化；前端先预览，用户确认后顺序提交，部分失败分别反馈，不提供跨请求事务。具体字段及错误状态见 [API 文档](../docs/api.md)，实现范围见[功能规格](../docs/design/个人中心与应用设置功能规格.md)，验证结果见[实施记录](../docs/design/个人中心与应用设置实施记录.md)。
