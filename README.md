# MathCraft — 数学智能教学平台

## 项目说明

MathCraft 是一个面向教师与学生的数学教学平台，由 FastAPI 后端和 React 前端组成。

后端提供账号与角色、题库协作、文档上传与解析、RAG 检索、智能出题、题目收藏、学习空间、组卷发布、学生作答、AI 批卷、催交通知和个人中心等能力。前端提供对应页面，所有业务数据都来自真实接口，不再使用前端 mock。

仓库最初从 DeepTutor 裁剪而来，当前后端已经替换为独立的 FastAPI 实现，目录结构以本 README 为准。`docs/` 下保留社区早期的设计与流程资料，其中部分内容描述的是旧实现，阅读时以当前代码和根 `openapi.json` 为准。

## 目录结构

```
MathCraft/
├── README.md                     # 项目说明、目录结构与启动方式
├── AGENTS.md                     # 协作约定：文档同步、密钥红线、中文约定式提交
├── GLOSSARY.md                   # 领域术语表
├── STUBS.md                      # 历史单租户替身模块说明
├── LICENSE                       # Apache-2.0 许可全文
├── THIRD_PARTY_NOTICES.md        # 第三方来源与许可证正文
├── pyproject.toml                # 仓库级依赖、包路径、pytest/Ruff/Pyright 配置
├── openapi.json                  # 当前 FastAPI 应用的 OpenAPI 契约快照
├── .env.example                  # 社区历史环境变量样例
├── backend/                      # FastAPI 后端
│   ├── app/
│   │   ├── main.py               # 应用装配、路由注册、/media 静态目录
│   │   ├── config.py             # backend/.env 配置
│   │   ├── db.py                 # SQLite engine、WAL、FTS5 建表语句
│   │   ├── deps.py               # 登录用户与权限依赖
│   │   ├── errors.py             # 统一错误响应
│   │   ├── local_secrets.py      # 硅基流动与 MinerU 密钥，已被 .gitignore 忽略
│   │   ├── local_secrets.example.py
│   │   ├── api/                  # auth、banks、documents、generate、questions、
│   │   │                         # favourites、chat、spaces、papers、attempts、
│   │   │                         # urges、users 等路由
│   │   ├── models/               # 21 张 SQLAlchemy 表
│   │   ├── schemas/              # Pydantic 请求与响应模型
│   │   └── services/
│   │       ├── rag/              # 向量、重排、HyDE、混合检索、出题与对话编排
│   │       ├── auth.py           # bcrypt 与 Redis 会话
│   │       ├── documents.py      # 解析、OCR、切片、入库状态机
│   │       ├── banks.py          # 题库与成员权限
│   │       ├── spaces.py         # 学习空间
│   │       ├── papers.py         # 组卷、发布、催交
│   │       ├── attempts.py       # 作答、交卷、复盘
│   │       └── grading.py        # 客观题判分与主观题 AI 批卷
│   ├── alembic/                  # 数据库迁移
│   ├── scripts/                  # seed、create_user、检索与真实链路冒烟
│   ├── tests/                    # 103 项后端接口测试
│   ├── data/                     # 运行时数据，已被 .gitignore 忽略
│   ├── alembic.ini
│   ├── pyproject.toml            # 后端独立依赖与运行配置
│   └── uv.lock
├── frontend/                     # React 19 + Vite + TypeScript + Tailwind v4
│   ├── src/api/                  # 真实接口层与字段映射
│   ├── src/components/           # 登录、导航、题库、出题、收藏、空间、组卷、个人中心
│   │   └── settings/             # 社区保留的「设置」界面
│   ├── src/store/                # 登录态与全局业务状态
│   ├── src/styles/
│   ├── vite.config.ts            # /api 与 /media 代理到后端
│   └── package.json
├── docs/                         # 当前方案及社区历史设计、API 与流程资料
│   ├── design/用户系统功能规格.md # 已接受的邮箱认证、JWT 与开发账号设计
│   └── design/用户系统实施规格.md # 用户故事、实施决策与验收规格（待实现）
├── apps/desktop/                 # 跨端客户端预留目录
├── packages/contracts/           # 跨端契约预留目录
└── tools/                        # 仓库维护脚本
```

`backend/data/`、`.venv/`、`node_modules/`、`dist/`、`.env` 等都是本地生成物，不进入版本库。

用户系统已对齐的业务需求与拟议实现见 [用户系统功能规格与认证设计](docs/design/用户系统功能规格.md)，覆盖邮箱验证码、学工号密码、Turnstile、JWT 会话及 `.env` 开发账号；设计已获接受，实施范围及验收见 [用户系统实施规格](docs/design/用户系统实施规格.md)；功能待实现，配置项与接口尚未生效。

## 技术栈

| 层 | 选型 |
| --- | --- |
| Web 框架 | FastAPI + Uvicorn |
| ORM 与迁移 | SQLAlchemy 2.x + Alembic |
| 数据库 | SQLite，开启 WAL 与 FTS5 全文索引 |
| 会话与任务 | Redis，保存登录会话、出题任务、文档入库进度与对话槽位 |
| 向量库 | Chroma，按题库持久化 |
| 向量模型 | 硅基流动 `BAAI/bge-m3`，1024 维 |
| 重排模型 | 硅基流动 `BAAI/bge-reranker-v2-m3` |
| 大模型 | DeepSeek `deepseek-flash`，OpenAI 兼容接口 |
| OCR | MinerU 云端 API，用于扫描件 |
| 前端 | React 19、Vite、TypeScript、Tailwind CSS v4 |

后端没有引入 LangChain。检索链路由项目自行实现，避免为一条固定的检索流程增加额外抽象。

## 启动方法

### 环境要求

- Python 3.11 及以上，推荐使用 uv 管理依赖。
- Node.js 18 及以上。
- Redis 7 及以上。Windows 可使用 Redis 的 Windows 构建版本，Linux 与 macOS 直接启动 `redis-server`。
- 可访问 DeepSeek、硅基流动与 MinerU 的网络环境。

### 1. 启动 Redis

Redis 是后端的硬依赖，登录会话、出题任务与文档入库进度都存放在这里。默认地址为 `redis://127.0.0.1:6379/0`。

```powershell
# Windows 示例，在 Redis 所在目录执行
.\redis-server.exe .\redis.conf

# Linux / macOS
redis-server
```

### 2. 启动后端

```powershell
cd backend
Copy-Item .env.example .env
uv sync
uv run alembic upgrade head
uv run python scripts/seed.py
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

`seed.py` 会创建三个测试账号，密码均为 `123123`：

| 账号 | 角色 |
| --- | --- |
| `teacher` | 教师 |
| `student` | 学生 |
| `student2` | 学生 |

需要额外账号时可执行 `uv run python scripts/create_user.py`。

后端启动后：

- 健康检查：`http://127.0.0.1:8000/api/health`
- Swagger 文档：`http://127.0.0.1:8000/docs`
- OpenAPI 契约：`http://127.0.0.1:8000/openapi.json`
- 上传文件与头像静态目录：`http://127.0.0.1:8000/media/...`

健康检查会逐项返回 database、redis、embedding、reranker、mineru、chroma 的状态。

### 3. 启动前端

```powershell
cd frontend
npm install
npm run dev
```

浏览器访问 `http://localhost:5173`。前端通过 Vite 代理把 `/api` 和 `/media` 转发到 `127.0.0.1:8000`，不需要在浏览器里单独配置后端地址。

### 4. 重新导出 OpenAPI 快照

接口变更后，在 `backend` 目录执行：

```powershell
uv run python -c "import json, sys; sys.path.insert(0,'.'); from app.main import app; open('../openapi.json','w',encoding='utf-8').write(json.dumps(app.openapi(), indent=2, ensure_ascii=False))"
```

根 `openapi.json` 必须与当前应用保持一致。

## 配置说明

后端配置从 `backend/.env` 读取，模板见 `backend/.env.example`。

| 变量 | 说明 |
| --- | --- |
| `DATABASE_URL` | SQLite 地址，默认 `sqlite:///./data/mathcraft.db` |
| `REDIS_URL` | Redis 地址，默认 `redis://127.0.0.1:6379/0` |
| `DEEPSEEK_API_KEY` | DeepSeek 兜底密钥；用户在个人中心配置后优先使用个人密钥 |
| `DEEPSEEK_BASE_URL` | DeepSeek 接口地址，默认 `https://api.deepseek.com` |
| `CHROMA_DIR` | Chroma 持久化目录，默认 `data/chroma` |
| `UPLOAD_DIR` | 原始文档目录，默认 `data/uploads` |
| `OCR_DIR` | OCR 临时目录，默认 `data/ocr` |
| `CORS_ORIGINS` | 允许的前端来源，默认包含 `127.0.0.1:5173` 与 `localhost:5173` |

硅基流动与 MinerU 的密钥写在 `backend/app/local_secrets.py`，可参考 `local_secrets.example.py` 创建。该文件已被 `.gitignore` 忽略，禁止提交到仓库。DeepSeek 密钥也可以在个人中心按用户配置，环境变量只作为缺省兜底。

检索与切片参数在 `app/config.py` 中，包括 `top_k`、`dense_top_k`、`sparse_top_k`、`fused_top_k`、`rerank_top_k`、`rrf_k`、`chunk_size` 与 `chunk_overlap`。

## 核心实现

### 账号与权限

登录使用 bcrypt 校验密码，会话 token 存在 Redis，默认有效期 7 天；修改密码或退出登录会销毁对应会话。

平台角色只有教师和学生。题库内部还有创建者、超级管理员、管理员和普通成员；学习空间区分创建者与成员。前端按角色和权限下发按钮，后端在每个接口上再次校验。

### 题库与文档

教师和学生都可以创建题库、上传文档、管理成员与转让题库。支持 PDF、DOCX、XLSX、MD、TXT。

文档入库流程为解析、扫描件 OCR、切片、写入 FTS5、生成向量并写入 Chroma，状态通过 Redis 进度供前端轮询。扫描件会调用 MinerU 云端 OCR。

### RAG 检索

查询优化使用 HyDE，先生成假设性文档再检索。检索采用混合策略：

1. 硅基流动 `bge-m3` 稠密向量召回
2. jieba 分词后走 SQLite FTS5 BM25 稀疏召回
3. RRF 融合两路结果
4. `bge-reranker-v2-m3` 重排并截断

### 智能出题

出题有两种入口：右侧参数面板的快速出题，以及 AI 对话框中的 Agent 出题。两者都把任务写入 Redis 并异步执行，前端轮询进度；生成结果合并到题目预览，互不覆盖。

### 组卷、作答与批卷

组卷会保存题目快照，发布到学习空间后学生才能作答。教师可以停止或恢复作答、催交、删除发布。组卷时可以选择交卷后的操作：

- 允许交卷后查看答案和解析
- 允许修改答案并重新提交

学生交卷后，客观题按标准答案判分，主观题调用 DeepSeek 评分。未允许查看解析时，交卷响应与复盘接口都不会下发答案。催交通知按时间正序展示，学生可单条已读或删除。

### 个人中心

个人中心维护昵称、头像和密码。模型配置支持按用户填写 DeepSeek 密钥并测试连通性，MinerU Token 也在同一页面配置。

## 数据目录

运行数据全部位于 `backend/data/`：

```
data/
├── mathcraft.db          # SQLite 主库，含 FTS5 虚拟表
├── chroma/               # Chroma 向量库
├── uploads/              # 原始文档
├── ocr/                  # OCR 中间文件
└── avatars/              # 用户头像
```

该目录已被 `.gitignore` 忽略。迁移或部署时直接复制或挂载整个 `data/` 即可。

## 测试

后端测试位于 `backend/tests`，覆盖认证、题库、文档、出题、收藏、空间、组卷、作答、批卷、催交通知与个人资料。测试会使用临时 SQLite 与 Redis 15 号库，外部模型调用全部打桩，不需要真实密钥。

```powershell
cd backend
uv run pytest -q
```

前端类型检查与构建：

```powershell
cd frontend
npm run typecheck
npm run build
```

## 当前边界

1. 后端以 SQLite 单机部署为目标，没有做多节点写入与分布式锁。
2. Redis 不可用时，登录、出题和文档入库都无法工作。
3. DeepSeek、硅基流动与 MinerU 依赖外网，离线环境只能运行不涉及模型的部分。
4. `docs/` 中的设计与流程文档来自社区早期版本，可能与当前实现不一致，接口以根 `openapi.json` 为准。
5. `docs/api.md` 及 `tools/` 下的文档生成脚本仍保留社区旧逻辑，重新生成前需要按当前路由更新脚本分组。

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 协作约定、文档同步要求、密钥红线与提交规范 |
| [GLOSSARY.md](GLOSSARY.md) | 学习空间、题库、个人中心等领域术语 |
| [STUBS.md](STUBS.md) | 历史替身模块清单 |
| [openapi.json](openapi.json) | 当前接口契约快照 |
| [docs/](docs/) | 社区历史设计、流程与 API 资料 |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | 第三方来源与许可证正文 |

## 许可证

本项目以 Apache-2.0 发布，全文见 [LICENSE](LICENSE)，`pyproject.toml` 中同步声明 `license = {text = "Apache-2.0"}`。

仓库最初从 DeepTutor 裁剪而来，`LICENSE` 中的版权行原样保留。第三方来源与对应的许可证正文见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
