# MathCraft — 数学智能体项目

## 项目说明

MathCraft 是一个包含 Python 后端与 React 前端的数学智能体项目。后端提供知识库管理、文档解析、索引检索、模型配置和出题服务；前端提供题目生成、题目预览、组卷和参数配置等交互界面。

项目包含一个统一的 `MathCraft` 后端：同一进程提供知识库、模型配置、文档入库、检索和题目生成 API；`frontend` 是配套的 React 应用。前后端按独立进程启动，详细目录职责见 [backend/README.md](backend/README.md) 和 [frontend/README.md](frontend/README.md)。

`MathCraft` 从 [DeepTutor](https://github.com/landing-ai/DeepTutor) 的 `a31d8262` 提交裁剪而来，缩减为单租户快照，不跟踪上游，运行时数据全部落在 `$MATH_Q_HOME/data`。内部 `math_q_agent` 包作为兼容层保留，新的启动命令和公共模块名统一为 `MathCraft`。

## 目录结构

```
MathCraft/                        # 仓库根：工程配置、跨端契约与文档
├── README.md                     # 项目说明、启动方式和文档入口
├── AGENTS.md                     # 协作约定：文档同步、密钥红线、中文约定式提交
├── LICENSE                       # Apache-2.0 许可全文
├── THIRD_PARTY_NOTICES.md        # 第三方来源说明与许可证正文
├── STUBS.md                      # 单租户替身模块清单
├── GLOSSARY.md                   # 学习空间、个人中心、设置与知识库领域术语
├── pyproject.toml                # 包元数据、依赖与 extras
├── openapi.json                  # 导出的 OpenAPI 契约快照
├── .env.example                  # 环境变量样例
├── .gitignore                    # 忽略虚拟环境、运行时数据、缓存与 .env
├── backend/                      # Python 后端，详细结构见 backend/README.md
│   ├── MathCraft/                # 对外 Python 模块与启动入口
│   ├── math_q_agent/             # DeepTutor 兼容实现包
│   │   ├── api/routers/profile.py # 单租户教师资料与头像接口
│   │   ├── services/profile/     # 资料校验与独立持久化
│   │   ├── knowledge/model_references.py # 知识库嵌入绑定查询与删除保护
│   │   ├── services/config/direct_model_config.py # 独立模型配置迁移与名称规则
│   │   └── services/settings/direct_model_edit.py # 单模型合并与独立默认操作
│   └── README.md                 # 后端目录结构与职责说明
├── docs/                         # API 文档、设计资料与项目流程文档
│   ├── api.md                    # HTTP API 参考
│   ├── 更详细的出题流程.md        # 给教师阅读的资料选择、出题修改、版本保存与组卷流程
│   ├── design/                   # 新功能与模块设计文档
│   │   ├── PRD-智能出题智能体.md  # 考研全范围、多选解析结果、逐题版本及指定版本组卷的总体需求
│   │   ├── 知识库模块说明.md       # 现有知识库架构、生命周期与接口分组
│   │   ├── 模型配置来源与普通知识库流程.md # 模型配置来源、启动与知识库主链路
│   │   ├── 扫描PDF云端OCR策略.md   # 扫描文档解析策略与异常处理
│   │   ├── 个人中心与模型配置页面设计.md # 已确认的页面方案与能力边界
│   │   ├── 个人中心与应用设置功能规格.md # 本地功能规格、用户故事与验收标准
│   │   ├── 个人中心与应用设置实施记录.md # 验收结果、审查及验证边界
│   │   ├── 模型与服务页面优化功能规格.md # 提供方与三种模型子页优化规格
│   │   ├── 模型与服务页面优化实施记录.md # 实施范围、验收映射与环境说明
│   │   ├── 模型直接配置功能规格.md # 三类直接配置及迁移契约
│   │   ├── 模型直接配置实施记录.md # 实现、接口与验收证据
│   │   ├── 对话出题必填信息检查.md # 多轮追问与各题型数量生成门槛
│   │   └── 临时配置弹出面板设计.md # 新建与绑定配置的弹层交互和验收
│   ├── deeptutor参考前端/         # 提供方与模型页面布局参考截图
│   ├── adr/                      # 架构决策记录
│   └── 智能体出题工作流程.docx  # 出题流程说明
├── frontend/                     # React 前端，详细结构见 frontend/README.md
│   ├── src/api/urls.ts          # 环境配置驱动的 HTTP 与 WebSocket 地址
│   ├── src/components/settings/ # 模型、引擎、解析及知识库入口
│   │   ├── model/DirectModelEditor.tsx # 完整模型表单与手动发现
│   │   └── model/directCatalog.ts # 单模型编辑合并与校验
│   ├── src/components/ui/ConfigurationDialog.tsx # 通用临时配置模态面板
│   ├── src/components/profile/  # 教师资料表单与头像上传
│   ├── src/components/tabs/FavoritesTab/ # 题目收藏页（mock 数据，前端演示）
│   └── README.md                 # 前端目录结构与开发命令
└── tools/                        # 仓库维护脚本
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

基础安装已经包含默认的 `llamaindex` RAG 引擎和内置 `text_only` 文档解析引擎，启动默认服务不需要安装下面的 extras。其他解析器、RAG 引擎和测试依赖按需安装（下例用 uv；用 pip 时把 `uv pip install --python .venv/Scripts/python.exe` 换成 `.venv\Scripts\python.exe -m pip install`）：

```powershell
uv pip install --python .venv/Scripts/python.exe -e ".[parse]"     # 可选：全部额外文档解析引擎
uv pip install --python .venv/Scripts/python.exe -e ".[graphrag]"  # 可选：GraphRAG（需 Python < 3.14）
uv pip install --python .venv/Scripts/python.exe -e ".[engines]"   # 可选：全部额外 RAG 引擎与重排依赖
uv pip install --python .venv/Scripts/python.exe -e ".[dev]"       # 可选：测试依赖
```

其中，`text_only` 不依赖额外解析器或模型，负责普通 PDF、Office 和文本类文件的基础文本提取；`llamaindex` 使用本地索引和向量检索，运行前仍需通过 `/api/settings` 配置可用的嵌入模型。扫描型 PDF 没有文字层时会强制使用 MinerU 云端 OCR，必须通过 `/api/settings` 或 `MINERU_MODE=cloud` 配置 MinerU，并提供 API Token；系统不会为扫描 PDF 启动本地 OCR、LiteParse 或 Docling 回退。其他格式或明确选择的解析器仍按对应依赖和外部服务配置运行。

### 2. 启动统一后端

```powershell
.venv\Scripts\python.exe -m MathCraft
```

应用导入不会加载 `.env` 或写入运行时设置。ASGI 启动时加载 `.env`、初始化设置和日志，再开始接收请求；初始化失败会直接终止启动。命令行入口会先读取 `.env` 和已保存的启动配置。端口优先级为 `--port` > shell / `.env` 中的 `BACKEND_PORT` > `system.json` > 内置默认值 `8000`，与 Vite 默认代理端口一致。监听地址按 `--host` > shell / `.env` 中的 `BACKEND_HOST` > `127.0.0.1` 确定。

Python 启动模块和公共 API 模块名统一为 `MathCraft`。知识库、模型配置和出题接口都由这个进程提供，内部 `math_q_agent` 代码已直接装配进统一应用。

知识库统一使用 DeepTutor 正式知识库模块，默认 RAG provider 为 `llamaindex`。出题服务只调用正式知识库的文件列表和 RAG 查询，不再提供独立的 Chroma/Ollama 入库链路。

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--host` | `127.0.0.1` | 绑定地址；只对本机提供服务 |
| `--port` | 启动配置（默认 `8000`） | 绑定端口；优先读取 `BACKEND_PORT`，其次为已保存系统设置 |
| `--reload` | 关闭 | 当前入口虽然接受此参数，但传给 Uvicorn 的是应用对象，无法启用热重载；开发时使用下方 Uvicorn 命令 |

日常启动和进程管理器均使用上面的 `python -m MathCraft`，由启动器在绑定端口前读取 `.env`。直接运行 `uvicorn MathCraft.api.main:app` 时，Uvicorn 自行决定监听地址；应用在 lifespan 中加载 `.env` 已经晚于监听参数解析，不能改变 Uvicorn 的端口。尤其不要保留 `--port 8000` 后再只修改 `.env`，否则前端代理与后端端口会不一致。

需要自行管理 Uvicorn（例如使用 `--reload --reload-dir backend` 或 `--log-level info`）时，必须由外部启动环境将有效地址与端口传给 Uvicorn，并与根 `.env` 保持一致；这些 Uvicorn 参数不属于项目启动器的配置读取逻辑。

### 3. 环境变量（可选）

统一后端和前端开发服务器都从仓库根目录的 `.env` 读取进程级环境变量：

| 服务 | `.env` 行为 | 配置位置 |
| --- | --- | --- |
| `MathCraft`（上述示例为 8000） | 启动时读取仓库根 `.env`；shell 中已有的同名变量优先 | 首次没有 `model_catalog.json` 时由 `LLM_*`、`TASK_*`、`EMBEDDING_*` 初始化；通过 `/api/settings` 保存的 catalog 优先；MinerU 支持用 `MINERU_*` 做部署级覆盖 |
| Vite（5173） | 通过指向仓库根的绝对 `envDir` 读取同一份 `.env` | `FRONTEND_*` 控制开发／预览服务器，`VITE_API_BASE_URL` / `VITE_WS_BASE_URL` 控制浏览器地址 |

首次运行可执行 `Copy-Item .env.example .env`；已有 `.env` 时直接补充所需变量，避免覆盖本地设置。前后端缺少变量时均使用下表默认值；shell 中同名变量优先，修改后重启相应进程。前端生产配置在构建时读取，变更后需重新构建。`.env.example` 提供默认值和空凭据占位，`.env` 已被 `.gitignore` 忽略。模型配置的来源优先级是：

```text
model_catalog.json > shell 环境变量 > .env > 内置默认值
```

模型环境变量只负责首次生成尚不存在的 `model_catalog.json`；初始化后的配置会出现在前端，凭据以掩码展示。正式目录一旦存在（包括有意清空的目录），就优先于环境变量；通过 `/api/settings` 保存后，后续重启不会被 `.env` 覆盖，也不会把修改写回 `.env`。MinerU 的 `MINERU_*` 是解析器的部署级覆盖，仍会在运行时覆盖 `document_parsing.json` 对应字段。

扫描型 PDF 建议配置：

```dotenv
MINERU_MODE=cloud
MINERU_API_BASE_URL=https://mineru.net
MINERU_API_TOKEN=
```

`MINERU_API_TOKEN` 必须填入本机或部署环境的真实 Token，不能写入 `.env.example`、代码、测试或提交记录。缺少 Token 时，扫描 PDF 会明确报“没有配置 MinerU 云端 OCR”，不会启动本地 OCR、LiteParse 或 Docling 回退。

| 变量 | 说明 |
| --- | --- |
| `MATH_Q_HOME` | 数据根，默认当前工作目录（在仓库根启动时即仓库根）；可在 shell 或 `.env` 中设置，须在 ASGI 启动前确定；运行时数据落在 `<MATH_Q_HOME>/data` |
| `MATH_Q_MODE` | 运行模式，本服务只使用 `server` |
| `CORS_ORIGIN` / `CORS_ORIGINS` | 默认空；两个应用均读取的额外浏览器来源，逗号分隔；当前无认证模式仍默认放行跨域 |
| `BACKEND_HOST` / `BACKEND_PORT` | 统一后端绑定地址和端口，默认 `127.0.0.1` / `8000`；同时供 Vite 推导代理目标 |
| `LLM_BINDING` / `LLM_MODEL` / `LLM_API_KEY` / `LLM_BASE_URL` | 首次启动时初始化主模型 Provider、模型、密钥和地址 |
| `TASK_BINDING` / `TASK_MODEL` / `TASK_API_KEY` / `TASK_BASE_URL` | 首次启动时初始化后台任务模型 |
| `TASK_MODE` | 任务模型模式：`inherit`、`profiles` 或 `reference`，默认 `profiles` |
| `EMBEDDING_BINDING` / `EMBEDDING_MODEL` / `EMBEDDING_API_KEY` / `EMBEDDING_BASE_URL` | 首次启动时初始化嵌入模型 |
| `EMBEDDING_DIMENSION` | 首次启动时初始化嵌入维度 |
| `FRONTEND_HOST` / `FRONTEND_PORT` | Vite 开发服务器绑定地址和端口，默认 `127.0.0.1` / `5173` |
| `FRONTEND_PREVIEW_PORT` | Vite 预览服务器端口，默认 `4173` |
| `FRONTEND_PROXY_TARGET` | 默认空；可单独指定开发／预览服务器内部代理目标，否则由绝对 `VITE_API_BASE_URL` 或 `BACKEND_*` 推导 |
| `VITE_API_BASE_URL` | 前端生产构建使用的绝对 API 地址；本地开发留空，使用 Vite `/api` 代理 |
| `VITE_WS_BASE_URL` | 默认空，跟随 API 地址或当前页面源；可单独设置浏览器 WebSocket 地址，HTTPS 自动使用 WSS |

### 4. 验证

```powershell
curl.exe http://127.0.0.1:8000/healthz
# {"status":"ok","service":"MathCraft"}

curl.exe http://127.0.0.1:8000/api/auth/status
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
curl.exe -X POST http://127.0.0.1:8000/api/knowledge-bases -F name=demo -F files=@notes.pdf
curl.exe http://127.0.0.1:8000/api/knowledge-bases
```

### 5. 首次使用：配置模型与知识库

1. 打开「设置 → 模型与服务」，进入语言模型或嵌入模型，点击「添加模型」，在同一表单填写唯一的配置名称、提供方、地址、凭据和模型标识。配置名称去除首尾空白后在三类模型中全局唯一，区分大小写；模型标识允许重复。
2. 点击「保存并启用」，只保存当前项。第一项自动成为该类默认，后续项可单独「设为默认」。不知道模型标识时，可先点击「获取模型列表」；失败后仍可手填并保存，保存不会自动发现或调用模型。任务模型默认跟随主语言模型，按需切换独立配置。环境初始化项会以相同形式展示；旧草稿只允许用户明确逐项恢复。
3. 选择 `text_only`、Docling 或 MinerU 作为全局文档解析引擎；普通知识库流程默认使用 LlamaIndex。
4. 通过知识库 API 创建知识库、上传文档并读取后台索引状态；出题服务选择正式知识库和其中的 raw 文档，`/api/generate`、`/api/chat` 仅负责编排。

### 6. 启动前端

`backend/` 下的 `api/`、`services/`、`schemas/`、`main.py` 提供出题编排能力，并已与 DeepTutor 正式知识库和模型配置 API 合并到同一 FastAPI 进程；`frontend/` 是配套前端（React 19 + Vite + Tailwind v4，构建产物可部署到 GitHub Pages）。

启动顺序是：启动统一后端，再启动前端开发服务器。

```powershell
# 1) 通过正式知识库 API 上传文档并启动索引
#    具体请求见 docs/api.md；模型和嵌入配置统一通过 /api/settings 管理

# 2) 前端开发服务（另开终端，/api 代理到 BACKEND_PORT）
cd frontend
npm install
npm run dev
```

设置中的「知识库连接」支持真实建库、文件上传与引擎配置；题库管理直接进入既有题库协作、文档上传和模拟进度演示，使用 `bankMock` 和定时器，不会触发真实索引。正式接口见 [docs/api.md](docs/api.md)。Vite 默认代理到 `127.0.0.1:8000`，不会读取后端保存的 `system.json`；如果后端改用其他端口，请同时在根目录 `.env` 设置 `BACKEND_PORT` 并重启前端开发服务器。

开发与预览服务器均代理 `/api` 和 `/ws`，监听通配地址 `0.0.0.0` / `::` 时代理转为连接回环地址。`FRONTEND_PROXY_TARGET` 用于指定内部代理，`VITE_*` 用于浏览器公开地址；凭据不得放入公开地址变量。具体地址前缀和 WebSocket 配置示例见 [frontend/README.md](frontend/README.md)。

前端生产构建 `npm run build` 产出 `frontend/dist`；`.github/workflows/deploy.yml` 提供手动触发的 GitHub Pages 部署，仓库在 Settings → Pages 启用后即可使用。检索与出题的命令行测试脚本位于 `backend/scripts/`（脚本已把 `backend/` 加入 import 路径）。模型密钥由 `/api/settings` 管理，严禁写入代码、文档或提交记录。

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

`MATH_Q_HOME` 默认使用进程启动时的当前工作目录；在仓库根目录启动时才对应仓库根目录。真实部署时应指向独立挂载的卷，并保证该目录可写、不进版本库。

## RAG 引擎

当前工厂注册 9 个 RAG provider，配置时使用下表中的精确标识符：

| 引擎 | 默认安装 | 说明 |
| --- | --- | --- |
| `llamaindex` | 是 | 默认引擎，全文 + 向量 + 可选 BM25 |
| `pageindex` | 是（`pageindex` 包） | PageIndex Cloud 云端服务，需配置专用 API Key |
| `pageindex-oss` | 是（`pageindex` 包） | PageIndex OSS 本地索引，使用当前激活的 LLM，支持 PDF |
| `graphrag` | 否 | `pip install -e ".[graphrag]"`，需 Python < 3.14 |
| `lightrag` | 否 | `pip install -e ".[rag-lightrag]"` |
| `lightrag-server` | 否 | 连接外部 LightRAG 服务 |
| `ima` | 否 | 连接外部 IMA 部署 |
| `kiwix` | 否 | 连接外部 Kiwix 服务 |
| `weknora` | 否 | 连接外部 WeKnora 部署 |

可选引擎惰性导入：缺少依赖时在引擎列表与预检中报告 *unavailable*，其配置端点仍可正常使用，服务启动不受影响。交叉编码器重排是 `.[rag-rerank]` extra。

文档解析接入 7 个引擎（`text_only`、`pymupdf4llm`、`markitdown`、`liteparse`、`docling`、`mineru`、`tika`），除 `text_only` 外均为可选。扫描型 PDF 的 OCR 主路径固定使用 MinerU 云端，要求在设置中配置 `mode=cloud` 和 API Token；MinerU 本地 CLI、LiteParse 和 Docling 不作为扫描 PDF 的隐式 OCR 回退。

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

## 配置初始化与兼容约定

1. 应用模块导入仅装配路由；运行时设置初始化、环境变量导出和日志配置在 ASGI lifespan 启动阶段完成。导出 OpenAPI 不会创建运行时设置或日志。
2. 配置默认路径通过当前路径服务解析，导入后、启动前设置 `MATH_Q_HOME` 仍然有效；显式路径注入继续受支持，已创建的服务实例仍绑定原目录。运行期间请通过设置 API 修改配置，切换数据根请重启进程。
3. 设置接口只有在模型目录内容实际改变时才重置 LLM/嵌入客户端；重复保存相同配置不会重置。
4. 模型环境变量负责首次初始化目录；已保存的有效目录（包括明确保存的空目录）优先，不会被环境变量再次覆盖。

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [docs/api.md](docs/api.md) | HTTP API 参考：端点、参数、curl 示例、WebSocket 契约 |
| [docs/更详细的出题流程.md](docs/更详细的出题流程.md) | 教师操作版：按上传资料、指定范围、逐题修改、手动保存版本和组卷的顺序说明操作 |
| [docs/design/PRD-智能出题智能体.md](docs/design/PRD-智能出题智能体.md) | 考研全章节总体需求：整份解析结果多选与原文预览、对话范围、手动版本保存与清理、待组卷及独立组卷页；含确认状态和待决策事项 |
| [docs/design/模型直接配置功能规格.md](docs/design/模型直接配置功能规格.md) | 三类直接配置、名称规则、手动发现、单项保存与迁移契约 |
| [docs/design/模型直接配置实施记录.md](docs/design/模型直接配置实施记录.md) | 直接配置实现、验收证据及验证边界 |
| [docs/design/模型与服务页面优化功能规格.md](docs/design/模型与服务页面优化功能规格.md) | 提供方优先导航、卡片与模型列表交互、48 条用户故事及 18 项验收 |
| [docs/design/模型与服务页面优化实施记录.md](docs/design/模型与服务页面优化实施记录.md) | 页面优化验收、凭据修复、审查与构建环境说明 |
| [docs/design/个人中心与模型配置页面设计.md](docs/design/个人中心与模型配置页面设计.md) | 五项教师资料、三种模型用途与连接管理、知识库引擎、文档解析及学习空间延期 |
| [docs/design/个人中心与应用设置功能规格.md](docs/design/个人中心与应用设置功能规格.md) | 本地规范：46 条用户故事、实现决策与 18 项行为验收 |
| [docs/design/个人中心与应用设置实施记录.md](docs/design/个人中心与应用设置实施记录.md) | 实际交付、18 项验收映射、双轴审查及本地验证边界 |
| [docs/design/知识库模块说明.md](docs/design/知识库模块说明.md) | 知识库模块架构、生命周期、数据布局和接口分组 |
| [docs/design/扫描PDF云端OCR策略.md](docs/design/扫描PDF云端OCR策略.md) | 扫描 PDF 的检测、MinerU 云端 OCR 契约和验收标准 |
| [docs/design/模型配置来源与普通知识库流程.md](docs/design/模型配置来源与普通知识库流程.md) | 模型目录优先级、Task 模式与普通知识库后端流程 |
| [docs/adr/0001-正式知识库作为唯一知识库入口.md](docs/adr/0001-正式知识库作为唯一知识库入口.md) | 正式知识库唯一入口的架构决策 |
| [GLOSSARY.md](GLOSSARY.md) | 学习空间、个人中心、应用设置、知识库、RAG 和出题编排术语 |
| [openapi.json](openapi.json) | 机器可读的 OpenAPI 契约快照 |
| [STUBS.md](STUBS.md) | 每个被替换为单租户替身的模块及其原行为 |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | 第三方来源与许可证正文 |
| [AGENTS.md](AGENTS.md) | 本仓库的协作约定（文档同步、密钥红线、提交规范） |

改动接口后请同步契约与文档：

```powershell
.venv\Scripts\python.exe -c "import json, MathCraft.app as m; open('openapi.json','w',encoding='utf-8').write(json.dumps(m.app.openapi(), indent=2, ensure_ascii=False))"
.venv\Scripts\python.exe tools\gen_api_docs.py
```

第一条命令从统一应用导出 OpenAPI 契约到根目录 `openapi.json`；第二条命令读取该快照并生成 `docs/api.md`。这两步用于开发维护，不是启动服务的必要步骤。端点表由契约生成，生成脚本中的检索说明和 WebSocket 示例仍需随行为变化人工维护。

## 个人中心与应用设置

左侧导航底部「设置」默认打开「模型与服务 → 语言模型」，并提供嵌入模型、任务模型三个类别。每项直接填写提供方、地址、凭据和模型标识，点击一次「保存并启用」只保存当前项；选中项与默认配置分离，任务默认跟随主模型。知识库连接、知识库引擎和文档解析保持各自入口及保存方式。

个人中心只维护头像、昵称、只读教师身份、任教学段及年级。使用独立的 `/api/user-profile` 接口持久化；头像选择后先预览，点击「保存资料」后先保存资料、再上传头像；两步分别反馈结果，失败保留可重试选择。支持经校验的 PNG、JPEG、WebP，最大 5 MiB。资料与模型目录互相独立。

设置中的「知识库连接」提供真实知识库与「配置引擎」入口，建库选择只作用于本次知识库。题库管理、组卷和学习空间仍保留明确的演示／未开放状态，不向学生真实发布。安装下载任务只观察当前后端进程；取消不回滚已完成内容。

规格：[个人中心与应用设置功能规格](docs/design/个人中心与应用设置功能规格.md)。实际验收：[实施记录](docs/design/个人中心与应用设置实施记录.md)。接口：[API 文档](docs/api.md)。

## 许可证

本项目以 **Apache-2.0** 发布，全文见 [LICENSE](LICENSE)，`pyproject.toml` 中同步声明 `license = {text = "Apache-2.0"}`。`LICENSE` 中的版权行为上游项目（Copyright 2025 Data Intelligence Lab, The University of Hong Kong），裁剪时原样保留。

代码取自 DeepTutor（该项目同样为 Apache-2.0）；第三方来源与对应的 MIT 等许可证正文见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

历史版本曾默认进入提供方，使用连接卡片、搜索与能力筛选，辅助任务提供三种来源模式；当前已由下述模型直接配置流程替代。历史设计依据见[独立功能规格](docs/design/模型与服务页面优化功能规格.md)，验证与环境说明见[实施记录](docs/design/模型与服务页面优化实施记录.md)。

### 模型直接配置

已知模型标识时，最少流程为「添加模型 → 在同一表单填写配置名称、提供方、地址、凭据和模型标识 → 保存并启用」。第一个配置自动成为该类默认项，后续备用项不替换默认；配置名称去首尾空白后全局唯一且区分大小写，模型标识可重复。

不知道标识时，可在未保存表单中手动点击「获取模型列表」。失败保留输入并显示原因及可用 HTTP 状态，仍可手填标识并保存；保存不自动发现、推理或嵌入。任务提供跟随主模型和独立配置两种模式，切换保留备用项。

旧正式连接与任务引用自动展开为独立模型，保留稳定 ID、默认和知识库嵌入绑定；历史重名的调整可在页面查看。旧草稿通过明确选项逐项恢复，不会因迁移、打开页面或保存另一项而被应用。共享字段在迁移后不再覆盖模型的独立配置。正式目录继续优先于环境初始化配置，前端不回写 `.env`；损坏或迁移失败的既有文件保留原样并报告错误。详细范围见[功能规格](docs/design/模型直接配置功能规格.md)，检查证据见[实施记录](docs/design/模型直接配置实施记录.md)。

临时配置入口采用居中弹出面板：新建知识库、更改引擎绑定和新增模型的交互、异常边界与验收见[临时配置弹出面板设计](docs/design/临时配置弹出面板设计.md)。现有 HTTP 字段与数据契约继续见 [API 文档](docs/api.md)。

## 对话出题的信息确认

`/api/chat` 在题型、各题型数量、范围、来源和难度齐备前持续追问。未提供数量时不再默认 5 道；每种题型数量沿用 1–20 道约束，已明确的要求在多轮对话中保留。详见 [对话出题必填信息检查](docs/design/对话出题必填信息检查.md)。
