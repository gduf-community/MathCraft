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
│   ├── capabilities/   # 外部能力与 MarginNote4 连接器
│   ├── config/         # 进程配置
│   ├── core/           # 跨层协议、工具和流事件
│   ├── knowledge/      # 知识库管理、索引与进度事件
│   ├── logging/        # 日志与调用统计
│   ├── multi_user/     # 上游多用户兼容模块（当前由单租户替身驱动）
│   ├── runtime/        # 数据根、运行模式与隔离 worker
│   ├── services/       # LLM、嵌入、RAG、解析、设置等业务服务
│   ├── tools/          # RAG 检索、网页抓取等工具入口
│   └── utils/          # 通用文件、JSON、网络与校验工具
├── api/                # 出题服务的 kb、generate、chat 路由
├── services/           # 出题服务的解析、切片、检索与出题逻辑
│   └── parsing/        # 文档格式解析器
├── schemas/            # 出题服务请求与响应模型
├── scripts/            # 入库、检索、出题和对话联测脚本
├── tests/              # 后端测试套件
├── main.py             # 统一应用兼容入口
└── config.py           # 出题服务配置
```

## 运行边界

- 使用 `python -m MathCraft` 启动统一后端；`MathCraft.api.main:app` 是对外 ASGI 入口，包含知识库、模型配置和出题路由。
- `math_q_agent/` 作为 DeepTutor 兼容实现包保留，已有导入路径和内部模块无需迁移。
- `MathCraft.app` 装配知识库、模型配置和出题服务；端口和地址读取根目录 `.env` 的 `BACKEND_HOST` / `BACKEND_PORT`。
- `MathCraft` 的启动入口会加载同一份根目录 `.env`，其中 `BACKEND_HOST` / `BACKEND_PORT` 控制知识库与模型配置服务。
- 运行数据、索引和本地配置不放入代码目录，统一按根 README 的约定写入运行时数据目录。
