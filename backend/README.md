# backend 目录说明

`backend/` 包含 MathCraft 的 Python 后端代码，分为现有知识库与模型配置服务，以及出题服务两部分。

## 目录结构

```text
backend/
├── math_q_agent/       # 知识库、模型配置与系统能力主包，import 名保持为 math_q_agent
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
├── main.py             # 出题服务入口
└── config.py           # 出题服务配置
```

## 运行边界

- `math_q_agent/` 的 Python 导入名和命令行入口保持不变。
- 根目录的 `main.py` 启动出题服务；对应配置位于 `config.py`，端口和地址读取根目录 `.env` 的 `QUESTION_BACKEND_HOST` / `QUESTION_BACKEND_PORT`。
- `math_q_agent` 的启动入口会加载同一份根目录 `.env`，其中 `BACKEND_HOST` / `BACKEND_PORT` 控制知识库与模型配置服务。
- 运行数据、索引和本地配置不放入代码目录，统一按根 README 的约定写入运行时数据目录。
