# MathCraft — 知识库与模型配置后端

MathCraft 是一个独立的 FastAPI 服务，只对外提供两件事：知识库（创建、上传、解析、索引、检索、索引进度）与模型配置（提供方、模型、嵌入/重排角色、任务分配、连通性测试、解析引擎设置）。发行包名称为 `MathCraft`；为保持现有调用兼容，Python 导入名和 CLI 模块名仍为 `math_q_agent`。
它从 [DeepTutor](https://github.com/landing-ai/DeepTutor) 的 `a31d8262` 提交裁剪而来，缩减为单租户快照，不跟踪上游，运行时数据全部落在 `$MATH_Q_HOME/data`。

## 目录结构

```
MathCraft/                        # 仓库根：工程配置、跨端契约与文档
├── README.md                     # 当前项目说明、目录结构、启动方式和文档入口
├── AGENTS.md                     # 协作约定：文档同步、密钥红线、中文约定式提交
├── LICENSE                       # Apache-2.0 许可全文（含上游版权声明）
├── THIRD_PARTY_NOTICES.md        # 第三方来源说明与许可证正文
├── STUBS.md                      # 单租户替身模块清单，含原实现行为对比
├── pyproject.toml                # 包元数据、依赖与 extras；包体位于 backend/
├── openapi.json                  # 导出的 OpenAPI 契约快照（后端生成、前端消费）
├── .env.example                  # 环境变量样例（仅占位，不含真实值）
├── .gitignore                    # 忽略虚拟环境、运行时数据、缓存与 .env
├── backend/                      # 后端部署单元
│   ├── math_q_agent/             # 服务主包（import 名保持不变）
│   │   ├── __main__.py           # python -m math_q_agent 入口（--host/--port/--reload）
│   │   ├── api/                  # FastAPI 装配层
│   │   │   ├── main.py           # 应用工厂：CORS、lifespan、路由挂载、/healthz
│   │   │   ├── security_guard.py # 可选的请求筛查中间件（默认关闭）
│   │   │   ├── routers/          # auth / knowledge / settings / system 四组路由
│   │   │   └── utils/            # 索引进度广播、任务日志流、任务 ID、HTTP 头
│   │   ├── capabilities/
│   │   │   └── marginnote4/      # MarginNote4 笔记库连接器（store + 中英文提示词）
│   │   ├── config/               # pydantic-settings 进程配置（LLM 重试等）
│   │   ├── core/                 # 跨层协议契约：工具、能力、流事件、追踪
│   │   ├── knowledge/            # 知识库领域层：manager、manifest、索引运行、进度事件
│   │   ├── logging/              # loguru 日志装配与调用统计
│   │   ├── multi_user/           # 上游多用户与权限模型（本仓库由单租户替身驱动）
│   │   ├── runtime/              # 数据根解析、运行模式、隔离 worker、agentic 兼容壳
│   │   ├── services/             # 业务服务实现（按领域分包）
│   │   │   ├── config/           # 运行时设置、模型目录、设置草稿与就绪检查
│   │   │   ├── llm/              # 各厂商 LLM 客户端与 wire protocol
│   │   │   ├── embedding/        # 嵌入客户端
│   │   │   ├── rag/              # 8 条 RAG 流水线、检索服务、索引版本管理
│   │   │   ├── parsing/          # 7 种文档解析引擎与隔离 worker
│   │   │   ├── web_source/       # 网页抓取接入
│   │   │   ├── github_source/    # GitHub 仓库接入
│   │   │   ├── settings/         # 设置写入、provider 探测与编辑
│   │   │   ├── search/           # 搜索服务
│   │   │   ├── voice/ imagegen/ videogen/                    # 语音与生成类支撑服务（HTTP 面未暴露）
│   │   │   ├── session/ prompt/ mcp/ setup/ model_selection/ # 其它支撑模块
│   │   │   ├── partners/ workspace/  # 单租户替身，详见 STUBS.md
│   │   │   └── *.py              # 连接器、凭证、密钥池、provider 注册表、文件 IO
│   │   ├── tools/                # 工具层入口（RAG 检索、网页抓取）
│   │   └── utils/                # 通用工具：文档抽取/校验、JSON、密钥文件、网络
│   ├── api/                      # 出题服务路由：kb（上传/检索）/ generate（参数出题）/ chat（对话出题）
│   ├── services/                 # 出题服务：解析、切片、Chroma 检索、DeepSeek 出题、对话槽位状态机
│   ├── schemas/                  # 与前端对齐的 Question 模型
│   ├── main.py config.py         # 出题服务入口与配置（独立进程，与 math_q_agent 平级）
│   │   ├── api/                  # kb（上传/清单/检索）/ generate（参数出题）/ chat（对话出题）路由
│   │   ├── services/             # 多格式解析、按题号切片、Chroma 检索、DeepSeek 出题、对话槽位状态机
│   │   └── schemas/              # 与前端对齐的 Question 模型（公式为 $...$ LaTeX）
│   ├── scripts/                  # 出题服务命令行工具：入库 / 检索 / 出题 / 对话联测
│   ├── tests/                    # pytest 套件：真实 ASGI 应用 + 假嵌入端点
│   │   ├── conftest.py           # 独立数据根、假 /embeddings 服务、TestClient
│   │   └── test_*.py             # 契约、引擎、解析、连接器、进度等用例
├── docs/
│   └── api.md                    # HTTP API 参考：端点表、参数与 curl 示例
├── frontend/                     # 出题智能体前端（React 19 + Vite + Tailwind v4）
│   └── src/                      # 页面组件、api 适配层（httpAdapter/mock 可切换）、全局状态
└── tools/                        # 仓库维护脚本
    ├── closure.py                # 静态导入闭包与悬空引用分析
    └── gen_api_docs.py           # 由 openapi.json 生成 docs/api.md
```

`.venv/`、`data/`、`.pytest_cache/` 等本地生成物已在 `.gitignore` 中忽略，不属于仓库内容。

## 启动方法

### 0. 环境要求

- Python 3.11 – 3.14（`pyproject.toml`：`requires-python = ">=3.11,<3.15"`）。
- [uv](https://github.com/astral-sh/uv) 可选；本仓库现有的 `.venv` 里没有 pip（uv 创建的虚拟环境默认如此）。
- 首次索引前需要配置模型，见下文「首次使用」。

### 1. 创建虚拟环境并安装

方式 A：uv（推荐，本仓库开发环境即此方式）

```powershell
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -e .
```

方式 B：标准库 venv（自带 pip）

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e .
```

macOS / Linux 把解释器路径换成 `.venv/bin/python` 即可。

> 已有 `.venv` 却提示 `No module named pip`，说明这个环境里没装 pip：改用 `uv pip install`，或执行 `.venv\Scripts\python.exe -m ensurepip` 补装 pip。

可选 extras 按需安装（下例用 uv；用 pip 时把 `uv pip install --python .venv/Scripts/python.exe` 换成 `.venv\Scripts\python.exe -m pip install`）：

```powershell
uv pip install --python .venv/Scripts/python.exe -e ".[parse]"     # 全部文档解析引擎
uv pip install --python .venv/Scripts/python.exe -e ".[graphrag]"  # GraphRAG（需 Python < 3.14）
uv pip install --python .venv/Scripts/python.exe -e ".[engines]"   # 全部可选 RAG 引擎
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"       # 测试依赖
```

### 2. 启动服务

```powershell
.venv\Scripts\python.exe -m math_q_agent --port 8001
```

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` | `127.0.0.1` | 绑定地址；只对本机提供服务 |
| `--port` | `8001` | 绑定端口 |
| `--reload` | 关闭 | 源码变更后自动重启，仅开发时使用 |
| `--log-level` | `info` | uvicorn 日志级别 |

等价的 uvicorn 写法（便于接入进程管理器）：

```powershell
.venv\Scripts\python.exe -m uvicorn math_q_agent.api.main:app --host 127.0.0.1 --port 8001
```

### 3. 环境变量（可选）

服务**不会**自动读取 `.env` 文件（运行时设置加载器明确忽略它），变量需要在启动前由 shell 提供；`.env.example` 仅作变量清单参考，`.env` 已被 `.gitignore` 忽略。

| 变量 | 说明 |
| --- | --- |
| `MATH_Q_HOME` | 数据根，默认仓库根目录；运行时数据落在 `<MATH_Q_HOME>/data` |
| `MATH_Q_MODE` | 运行模式，本服务只使用 `server` |
| `CORS_ORIGIN` | 额外允许的浏览器来源，逗号分隔 |
| `BACKEND_PORT` | 后端端口设置项；用 `python -m math_q_agent` 启动时请改用 `--port` |

### 4. 验证

```powershell
curl.exe http://127.0.0.1:8001/healthz
# {"status":"ok","service":"math_q_agent"}

curl.exe http://127.0.0.1:8001/api/auth/status
# {"auth_enabled":false,"single_user":true,"user":{...}}
```

| 入口 | 作用 |
| --- | --- |
| `GET /healthz` | 存活探针，与引擎/凭证配置无关 |
| `GET /docs` | Swagger 交互式文档 |
| `GET /openapi.json` | OpenAPI 契约（仓库根的 `openapi.json` 是同一份快照） |
| `GET /api/settings` | 模型目录、提供方、解析等设置 |
| `GET /api/knowledge-bases` | 知识库列表 |

示例：创建一个知识库并上传文档。

```powershell
curl.exe -X POST http://127.0.0.1:8001/api/knowledge-bases -F name=demo -F files=@notes.pdf
curl.exe http://127.0.0.1:8001/api/knowledge-bases
```

### 5. 首次使用：配置模型

模型与解析配置**不**放在 `.env`，而是通过 `/api/settings` 写入
`<MATH_Q_HOME>/data/user/settings/model_catalog.json` 与 `document_parsing.json`：

1. 在 `/api/settings` 至少登记一个对话模型与一个嵌入模型（默认 `llamaindex` 流水线依赖嵌入）。
2. 用 `/api/settings/test-provider`，或 `/api/system/test/llm`、`/api/system/test/embeddings` 验证提供方可达。
3. 之后即可建库、上传并索引；进度通过 `/ws/knowledge-bases/*` 推送。

### 6. 出题智能体前端与服务

`backend/` 下的 `api/`、`services/`、`schemas/`、`main.py`、`config.py` 是独立于 math_q_agent 的出题服务（RAG 检索 + DeepSeek 出题，默认端口 8000，与 `math_q_agent` 平级共存），`frontend/` 是配套前端（React 19 + Vite + Tailwind v4，构建产物可部署到 GitHub Pages）。

```powershell
# 1) 安装出题服务依赖（向量检索走本地 Ollama + Chroma）
uv pip install --python .venv\Scripts\python.exe -e ".[question]"

# 2) 配置环境变量：复制 .env.example 为 .env（仓库根），填写 DEEPSEEK_API_KEY 等
#    出题服务通过 pydantic-settings 读取仓库根 .env，与 math_q_agent 互不影响

# 3) 上传文档并入库（支持文字版 PDF / docx / xlsx / md，扫描版 PDF 需接入 OCR 引擎）
.venv\Scripts\python.exe backend\scripts\upload.py 导数与微分_50题练习卷.pdf --kb kb-math

# 4) 启动出题服务（在 backend 目录下运行，接口文档 http://127.0.0.1:8000/docs）
cd backend
..\.venv\Scripts\python.exe -m uvicorn main:app --port 8000

# 5) 前端开发服务（另开终端，/api 代理到 8000）
cd frontend
npm install
npm run dev
```

前端生产构建 `npm run build` 产出 `frontend/dist`；`.github/workflows/deploy.yml` 提供手动触发的 GitHub Pages 部署，仓库在 Settings → Pages 启用后即可使用。检索与出题的命令行测试脚本位于 `backend/scripts/`（脚本已把 `backend/` 加入 import 路径）。出题服务使用的 DeepSeek 密钥只写入根目录 `.env`，严禁提交。

## 数据目录

服务持久化的全部内容位于 `$MATH_Q_HOME/data`：

```
data/
├── knowledge_bases/
│   ├── kb_config.json          # 全部知识库的注册表
│   └── <kb>/
│       ├── raw/                # 上传的原始文件
│       ├── metadata.json
│       ├── .progress.json      # 可恢复的索引进度
│       ├── version-N/          # 索引产物 + meta.json
│       └── visual_assets/
├── parse_cache/<hash>/<parser>/ # 解析结果缓存
└── user/settings/*.json        # 模型目录、解析、引擎等设置
```

`MATH_Q_HOME` 默认为仓库根目录。真实部署时应指向独立挂载的卷，并保证该目录可写、不进版本库。

## RAG 引擎

与上游一致，接入 8 条引擎：

| 引擎 | 默认安装 | 说明 |
| --- | --- | --- |
| `llamaindex` | 是 | 默认引擎，全文 + 向量 + 可选 BM25 |
| `pageindex` | 是（`pageindex` 包） | reasoning-as-retrieval |
| `graphrag` | 否 | `pip install -e ".[graphrag]"`，需 Python < 3.14 |
| `lightrag` | 否 | `pip install -e ".[rag-lightrag]"` |
| `lightrag_server` | 否 | 连接外部 LightRAG 服务 |
| `ima` | 否 | 连接外部 IMA 部署 |
| `kiwix` | 否 | 连接外部 Kiwix 服务 |
| `weknora` | 否 | 连接外部 WeKnora 部署 |

可选引擎惰性导入：缺少依赖时在引擎列表与预检中报告 *unavailable*，其配置端点仍可正常使用，服务启动不受影响。交叉编码器重排是 `.[rag-rerank]` extra。

文档解析接入 7 个引擎（`text_only`、`pymupdf4llm`、`markitdown`、`liteparse`、`docling`、`mineru`、`tika`），除 `text_only` 外均为可选，通过 `parse-*` extras 安装；MinerU 与 Tika 也可以走外部 CLI/服务。

## 认证

没有认证。所有请求都以本地管理员身份处理，`/api/auth/status` 返回 `single_user: true`，CORS 默认放行。请绑定回环地址，或把它放在自建网关之后。

## 测试

```powershell
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"
.venv\Scripts\python.exe -m pytest -q
```

`pyproject.toml` 的 `testpaths` 已指向 `backend/tests`，直接运行即可。套件通过 `TestClient` 驱动真实 ASGI 应用，数据根指向一次性的 `backend/tests/.data-home`；它会启动一个假的 OpenAI 兼容 `/embeddings` 端点，因此默认 LlamaIndex 流水线无需任何外部凭证即可完成索引与检索。端到端用例会建库、上传文档、等待索引完成并断言召回片段。

## 已知限制

以下是环境或范围事实，不是待修复的缺陷。

1. **依赖网络的连接器路径未验证。** GitHub 源、网页源，以及远程 Kiwix / IMA / WeKnora / LightRAG-server 连接器均已实现，失败路径有测试覆盖（拒绝连接时必须快速返回可读错误，且不能注册出“看起来能用”的知识库）；正常路径需要外网或外部服务，裁剪环境不具备。
2. **只有默认引擎做过端到端索引。** 测试用 LlamaIndex 对着假嵌入端点建索引。每个引擎都能解析到各自的流水线类，安装对应 extra 后会从 `configured: false` 变为 `true`，但真实的 GraphRAG / LightRAG / PageIndex 索引没有在这里构建过。
3. **隔离文档解析需要真实临时目录。** PDF 解析通过 worker 子进程完成；在禁止子进程管道的沙箱中，解析器会报失败而不是静默降级。PDF 入库请在普通环境运行服务。
4. **按设计没有认证。** 请绑定回环地址或用网关前置。

## 上游遗留的怪癖

这些是有意保留的行为（裁剪时选择保真而非重构），读代码时每一处都是真陷阱。

1. 运行时设置文件在 `math_q_agent.api.main` **导入时**创建，并导出到 `os.environ`。
2. `CATALOG_PATH` 与 `PROJECT_ROOT` 只在导入时解析一次；导入后再改 `MATH_Q_HOME` 不生效。
3. 模型目录写入会重置 LLM/嵌入客户端单例；空写入则不会。
4. 模型目录**没有**环境变量覆盖层，这一点由上游测试固定，予以保留。
5. `services/config/loader.py` 仍会读取 `main.yaml` / `agents.yaml` 里的对话 Agent 参数，本服务只用其中的解析/嵌入/模型路径。

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [docs/api.md](docs/api.md) | HTTP API 参考：端点、参数、curl 示例、WebSocket 契约 |
| [openapi.json](openapi.json) | 机器可读的 OpenAPI 契约快照 |
| [STUBS.md](STUBS.md) | 每个被替换为单租户替身的模块及其原行为 |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | 第三方来源与许可证正文 |
| [AGENTS.md](AGENTS.md) | 本仓库的协作约定（文档同步、密钥红线、提交规范） |

改动接口后请同步契约与文档：

```powershell
.venv\Scripts\python.exe -c "import json, math_q_agent.api.main as m; open('openapi.json','w',encoding='utf-8').write(json.dumps(m.app.openapi(), indent=2, ensure_ascii=False))"
.venv\Scripts\python.exe tools\gen_api_docs.py
```

## 许可证

本项目以 **Apache-2.0** 发布，全文见 [LICENSE](LICENSE)，`pyproject.toml` 中同步声明 `license = {text = "Apache-2.0"}`。`LICENSE` 中的版权行为上游项目（Copyright 2025 Data Intelligence Lab, The University of Hong Kong），裁剪时原样保留。

代码取自 DeepTutor（该项目同样为 Apache-2.0）；第三方来源与对应的 MIT 等许可证正文见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
