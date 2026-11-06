# MathCraft 后端

MathCraft 后端以 `app.main:app` 为入口，提供管理员账号管理、教师与学生登录、题库协作、文档入库、RAG 检索与智能出题、题目收藏、学习空间、组卷发布、学生作答、批卷、催交通知及个人中心。业务数据通过 SQLAlchemy 持久化，登录会话和异步任务状态保存在 Redis。

当前行为以 [`app/`](app/)、根 [`openapi.json`](../openapi.json) 和实际路由为准。项目整体说明与前端启动方式见[根 README](../README.md)。

## 技术栈与运行条件

| 部分 | 当前实现 |
| --- | --- |
| 运行环境 | Python 3.11 及以上，使用 uv 安装和运行后端依赖 |
| HTTP 服务 | FastAPI、Uvicorn、Pydantic Settings |
| 数据库与迁移 | SQLite、SQLAlchemy 2.x、Alembic；SQLite 开启 WAL、外键和 FTS5 |
| 会话与任务缓存 | Redis 7 及以上；保存登录会话、出题任务、文档入库进度和对话槽位 |
| 密码校验 | bcrypt |
| 文档解析 | PyMuPDF、python-docx、openpyxl，以及 Markdown、TXT 解析器 |
| 向量与重排 | 硅基流动 `BAAI/bge-m3`（1024 维）与 `BAAI/bge-reranker-v2-m3` |
| 检索 | Chroma 持久化向量索引、jieba 分词、SQLite FTS5、RRF 融合与重排 |
| 生成与评分 | 通过 OpenAI 兼容客户端调用 DeepSeek，默认模型为 `deepseek-flash` |
| 扫描件 OCR | MinerU 云端 API，已接入文档入库流程 |

Redis 是硬依赖。即使 SQLite 中已有账号，登录仍需要把会话写入 Redis；Redis 不可用时，登录与依赖缓存的任务无法正常工作。Windows 可以通过下文的 [Docker Compose 选项](#redis-启动选项docker-compose)或 WSL 提供 Redis。WSL 的安装与前台启动命令见[根 README 的 Redis 启动说明](../README.md#1-启动-redis)，使用 WSL 前台运行时保持 Redis 终端开启。

仅验收登录与账号管理不需要配置真实模型密钥；文档向量化、检索、生成、主观题评分及 OCR 需要相应服务的凭据和网络。

## 目录结构

```text
backend/
├── app/
│   ├── main.py                  # 应用装配、路由注册、/media 头像静态目录
│   ├── config.py                # backend/.env 与环境变量配置
│   ├── db.py                    # SQLAlchemy 引擎、会话与 SQLite 配置
│   ├── deps.py                  # 登录用户、平台角色与资源归属校验
│   ├── errors.py                # 业务错误及统一响应
│   ├── local_secrets.example.py # 系统服务凭据的占位样例
│   ├── api/                     # auth、admin、users、banks、documents、generate、
│   │                            # questions、favorites、chat、spaces、papers、
│   │                            # urges、attempts、health 路由
│   ├── models/                  # 用户、题库、文档、题目、空间与试卷等 ORM 模型
│   ├── schemas/                 # Pydantic 请求与数据契约
│   └── services/
│       ├── auth.py              # 密码哈希与 Redis 会话
│       ├── bootstrap.py         # 显式初始化管理员、教师和学生账号
│       ├── cache.py             # Redis 客户端与缓存键
│       ├── model_settings.py    # 个人模型配置与凭据解析
│       ├── documents.py         # 解析、OCR、切片与入库编排
│       ├── banks.py             # 题库与成员权限
│       ├── generation.py        # 出题任务编排
│       ├── spaces.py            # 学习空间
│       ├── papers.py            # 组卷、发布与催交
│       ├── attempts.py          # 作答、交卷与复盘
│       ├── grading.py           # 客观题判分与主观题 AI 评分
│       ├── parsing/             # PDF、DOCX、XLSX、MD、TXT 解析
│       ├── mineru.py            # MinerU 云端 OCR 客户端
│       └── rag/                 # 切片、向量、检索、重排、出题与对话编排
├── alembic/                     # 环境与版本化数据库迁移
├── scripts/                     # 账号初始化、辅助建号和手动链路检查
├── tests/                       # 接口与服务测试、外部服务替身夹具
├── .env.example                 # 后端配置样例
├── alembic.ini                  # Alembic 配置
├── pyproject.toml               # 后端独立依赖与 uv 配置
├── uv.lock                      # 后端依赖锁文件
└── README.md
```

运行后默认产生 `data/`，包含 `mathcraft.db`、`chroma/`、`uploads/`、`ocr/` 和 `avatars/`。本地配置文件 `backend/.env`、`app/local_secrets.py` 与运行数据不进入版本库。

## 配置

配置入口为 [`app/config.py`](app/config.py)，dotenv 文件固定为 `backend/.env`，模板为 [`.env.example`](.env.example)。环境变量可以覆盖 dotenv 中的设置。后端运行、迁移与初始化命令均在 `backend/` 执行，以保证 SQLite 相对路径、迁移配置及脚本入口一致。

| 变量 | 默认值或用途 |
| --- | --- |
| `DATABASE_URL` | `sqlite:///./data/mathcraft.db`，相对当前工作目录 |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` |
| `SESSION_TTL_SECONDS` | 登录会话默认 604800 秒，即 7 天 |
| `DEEPSEEK_API_KEY` | DeepSeek 兜底密钥；个人中心配置优先 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com` |
| `DEEPSEEK_MODEL` | `deepseek-flash` |
| `CHROMA_DIR` | `data/chroma` |
| `UPLOAD_DIR` | `data/uploads` |
| `OCR_DIR` | `data/ocr` |
| `AVATAR_DIR` | `data/avatars` |
| `CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173`，逗号分隔 |
| `INITIAL_ADMIN_ACCOUNT` / `INITIAL_ADMIN_PASSWORD` | 显式初始化所需的管理员账号与密码 |
| `INITIAL_TEACHER_ACCOUNT` / `INITIAL_TEACHER_PASSWORD` | 显式初始化所需的教师账号与密码 |
| `INITIAL_STUDENT_ACCOUNT` / `INITIAL_STUDENT_PASSWORD` | 显式初始化所需的学生账号与密码 |
| `ADMIN_CONTACT` | 登录页公开展示的管理员联系说明，可留空 |

`CHROMA_DIR`、`UPLOAD_DIR`、`OCR_DIR`、`AVATAR_DIR` 的相对路径由配置方法基于 `backend/` 解析。迁移存储位置时，需要同时保留数据库、上传资料、OCR 文件、头像与向量索引，并更新对应配置，避免已有资源失联。

系统硅基流动密钥及 MinerU 默认 Token 使用 `app/local_secrets.py`，首次使用可从 `app/local_secrets.example.py` 复制。该文件需要存在；只验收登录时可保留样例中的空值或占位值。个人 DeepSeek 密钥与 MinerU Token 通过 `/api/users/me/model-settings` 保存到 `UserModelSetting`，调用时优先采用个人配置。环境变量、dotenv 或系统凭据文件变更后重新启动后端进程；个人模型配置通过接口保存后按请求读取。

## Redis 启动选项：Docker Compose

仓库根目录的 [`compose.yaml`](../compose.yaml) 仅提供 `redis` 服务，后端与前端仍在本地运行。启动前确认 Docker Desktop 的引擎正在运行，并先关闭旧的 WSL Redis，避免占用主机 `6379` 端口：前台运行的实例在对应终端按 `Ctrl+C` 停止，以服务方式运行的实例则在对应 WSL 发行版内停止该服务。

该服务使用 `redis:7-alpine` 镜像，端口映射为 `127.0.0.1:6379:6379`，仅绑定主机回环地址；命名卷 `redis_data:/data` 配合 `--appendonly yes` 持久化 Redis 数据，使用 `redis-cli ping` 进行健康检查，重启策略为 `unless-stopped`。

以下命令均在**仓库根目录**执行，启动并等待 Redis 健康检查通过后，检查连通性、状态与日志：

```powershell
docker compose up -d --wait redis
docker compose exec redis redis-cli ping
# 期望：PONG
docker compose ps
docker compose logs --tail 50 redis
```

本地后端继续使用 `REDIS_URL=redis://127.0.0.1:6379/0`，无需改为 `redis` 主机名。若需在当前 PowerShell 终端显式设置，可在启动后端前执行：

```powershell
$env:REDIS_URL = "redis://127.0.0.1:6379/0"
```

临时停止 Redis，或移除 Compose 容器和网络时，在仓库根目录选择执行：

```powershell
# 停止 Redis，保留容器与命名卷
docker compose stop redis

# 移除容器和网络，保留命名卷 redis_data
docker compose down
```

`docker compose down` 不加 `-v`，以保留命名卷中的数据。切换到 Docker Redis 不会自动迁移旧 WSL Redis 中的登录会话和任务状态，用户需要重新登录；账号及其他关系数据仍保存在原有数据库中，无需重新初始化账号。

## 首次准备与数据库迁移

先通过上述 Docker Compose 选项或 WSL 启动 Redis，并确认 `REDIS_URL` 指向的实例可访问。若本机已安装 Redis CLI，默认本地实例可检查：

```powershell
redis-cli -h 127.0.0.1 -p 6379 ping
# 期望：PONG
```

若 Redis 在 WSL 中运行，可在对应发行版内执行 `redis-cli ping`；后端仍须能够连接配置中的 Redis 地址。

在仓库根目录打开 PowerShell，准备后端依赖与配置；已有本地配置时保留原文件：

```powershell
cd backend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
if (-not (Test-Path app/local_secrets.py)) { Copy-Item app/local_secrets.example.py app/local_secrets.py }
uv sync
New-Item -ItemType Directory -Force data | Out-Null
```

在本地编辑 `backend/.env`，为管理员、教师和学生分别填写六个 `INITIAL_*` 字段。三个账号必须互不相同；账号可使用中文、字母、数字、下划线、点和连字符，最长 64 字符。密码不能为空；建议至少 6 位并为每个账号分别设置。

然后创建或升级数据库，再显式初始化账号：

```powershell
uv run alembic upgrade head
uv run python scripts/init_accounts.py
```

Alembic 从 `app.config.settings.database_url` 获取连接串，负责关系表及初始 FTS5 虚拟表迁移。使用自定义 SQLite 位置时，先创建数据库文件的父目录；升级已有数据前应先备份。

账号初始化入口为 [`scripts/init_accounts.py`](scripts/init_accounts.py)，调用 [`services/bootstrap.py`](app/services/bootstrap.py) 补建管理员、教师和学生及其模型设置记录。重复执行会跳过同名同角色的已有账号，保留其密码、资料和状态；同名账号的角色不匹配或配置不合法时会报错。修改 `INITIAL_*_PASSWORD` 后重复初始化不会重置已有密码。

日常启动不会自动建表、运行迁移或创建账号。初始化完成后，后续账号通过管理员面板或 `/api/admin/accounts` 管理。

## 日常启动

先启动 Redis，再从 `backend/` 执行：

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

拉取包含新迁移的代码后，启动前执行 `uv run alembic upgrade head`。需要补建配置中的初始账号时，再单独执行 `uv run python scripts/init_accounts.py`。

前端从仓库根目录另开终端启动：

```powershell
cd frontend
npm ci
npm run dev
```

访问 `http://localhost:5173`。Vite 将 `/api` 和 `/media` 代理至后端 `127.0.0.1:8000`；前端依赖已安装且锁文件未变化时，日常只需 `npm run dev`。

## 接口与文档入口

| 入口 | 说明 |
| --- | --- |
| `http://127.0.0.1:8000/docs` | 当前服务的交互式 Swagger 文档 |
| `http://127.0.0.1:8000/openapi.json` | 运行中服务的 OpenAPI 契约 |
| [根 openapi.json](../openapi.json) | 仓库中的接口契约快照 |
| [docs/api.md](../docs/api.md) | API 文档；维护时需核对生成脚本分组覆盖情况 |
| [docs/design/](../docs/design/) | 当前功能设计说明 |

常用路由如下；请求字段与完整路径以运行中 OpenAPI 为准。

| 路由 | 用途 |
| --- | --- |
| `GET /api/auth/config` | 登录页公开配置 |
| `POST /api/auth/login` | 使用 `account`、`password` 登录 |
| `GET /api/auth/me` | 校验当前会话并返回用户资料与角色 |
| `POST /api/auth/logout` | 销毁当前会话 |
| `/api/admin/accounts`、`GET /api/admin/overview` | 管理员账号管理与平台概况 |
| `/api/users/me`、`/api/users/me/model-settings` | 个人资料与个人模型配置 |
| `/api/banks`、`/api/banks/{bank_id}/documents` | 题库协作与文档管理 |
| `POST /api/banks/{bank_id}/search` | 题库内检索 |
| `POST /api/generate/start`、`GET /api/generate/progress/{task_id}` | 异步出题与进度查询 |
| `/api/chat/sessions` | 对话会话与消息 |
| `/api/questions`、`/api/favorites` | 题目维护与收藏 |
| `/api/spaces`、`/api/papers`、`/api/attempts/{attempt_id}/submit` | 学习空间、组卷发布与交卷 |
| `/api/urges` | 催交通知 |
| `GET /api/health` | 数据库、Redis、外部服务与 Chroma 探测 |
| `/media/...` | 头像静态资源 |

`/api/health` 返回 `database`、`redis`、`siliconflow_embedding`、`siliconflow_rerank`、`mineru_default_token` 和 `chroma`。该接口会实际调用硅基流动探测向量与重排；`mineru_default_token` 仅表示系统默认 Token 是否存在，不能证明 OCR 可用。HTTP 200 也不代表各组件全部通过，需检查字段值；登录验收可直接使用认证接口。

## 本地三角色登录验收

以下为人工验收方法；先完成数据库迁移、显式账号初始化和 Redis、后端、前端启动。

1. 打开登录页，确认只需填写登录账号和密码，管理员联系说明与 `ADMIN_CONTACT` 一致。
2. 分别使用配置中的管理员、教师、学生账号登录，每次退出后再验证下一角色。管理员应进入管理员面板，教师与学生进入各自工作台；浏览器刷新后仍应保留有效登录态。
3. 核对登录请求为 `POST /api/auth/login`，JSON 请求体为 `{"account":"<对应账号>","password":"<对应密码>"}`。成功响应应为 HTTP 200，包含 `token`、`expires_in` 和 `user`，其中 `user.role` 分别为 `admin`、`teacher`、`student`。
4. 使用本次登录返回的 Token 请求 `GET /api/auth/me`，请求头为 `Authorization: Bearer <token>`；应返回 HTTP 200，`user` 的账号与角色和登录响应一致。Token 只在本地使用，不粘贴到日志、文档或提交中。
5. 用管理员会话请求 `GET /api/admin/accounts` 应成功；用教师和学生会话请求相同接口应返回 HTTP 403。无 Token 请求 `GET /api/auth/me` 应返回 HTTP 401。
6. 对当前账号调用 `POST /api/auth/logout` 应返回 HTTP 204。继续使用原 Token 请求 `GET /api/auth/me` 应返回 HTTP 401，前端再次刷新也应回到登录页。
7. 使用错误密码登录应返回 HTTP 401；已禁用账号使用正确密码登录应返回 HTTP 403。禁用状态可在需要验收时通过管理员面板准备，恢复后再继续使用该账号。

若登录失败，先从实际运行后端的 Windows 环境验证 Redis 连通性：

```powershell
# 在 backend/ 目录执行，应输出 Redis: PONG
uv run python -c "from app.services.cache import get_redis; assert get_redis().ping(); print('Redis: PONG')"
```

仅在 WSL 内返回 `PONG` 不代表 Windows 后端已连通。Redis 未运行时，即使密码校验通过，创建会话仍会失败；恢复 Redis 后重试登录即可，无需重复初始化账号。随后核对是否在正确的 `DATABASE_URL` 上完成迁移和初始化，以及账号状态。外部模型未配置导致的健康检查失败，应按对应组件排查。

## 辅助脚本与检查边界

- `scripts/create_user.py`：命令行创建教师或学生，不支持创建管理员；日常账号管理使用管理员面板。
- `scripts/seed.py`：写入固定的演示教师、学生账号，仅用于本地演示，不能代替三角色初始化。
- `scripts/test_retrieval.py`、`scripts/smoke_live.py`、`scripts/smoke_paper_live.py`：检索或业务链路的手动检查脚本，使用前需核对脚本参数及其数据库、模型和服务配置，部分操作会访问真实外部服务。

自动化测试位于 `tests/`，外部模型由 `tests/conftest.py` 打桩。夹具会使用临时 SQLite 和本机 Redis 15 号库并调用 `flushdb()`；只有确认该实例与逻辑库专供测试后才运行后端测试。文档维护与人工登录验收不需要清空 Redis 或运行测试套件。
