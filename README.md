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
│   │   ├── models/               # 业务用户与资源、认证会话及验证码消费凭证
│   │   ├── schemas/              # Pydantic 请求与响应模型
│   │   └── services/
│   │       ├── rag/              # 向量、重排、HyDE、混合检索、出题与对话编排
│   │       ├── auth.py           # bcrypt、JWT、数据库会话与撤销
│   │       ├── auth_codes.py     # Redis 验证码、限流与 SQL 消费凭证
│   │       ├── auth_delivery.py  # SMTP 与 Turnstile 适配
│   │       ├── documents.py      # 解析、OCR、切片、入库状态机
│   │       ├── banks.py          # 题库与成员权限
│   │       ├── spaces.py         # 学习空间
│   │       ├── papers.py         # 组卷、发布、催交
│   │       ├── attempts.py       # 作答、交卷、复盘
│   │       └── grading.py        # 客观题判分与主观题 AI 批卷
│   ├── alembic/                  # 数据库迁移
│   ├── scripts/                  # 认证密钥生成、seed、auth_migration 与冒烟
│   │   └── generate_auth_secrets.py # 标准库生成认证密钥，手工保存，不读写 .env
│   ├── app/api/auth_http.py       # 认证路由共享的 Cookie HTTP 辅助函数
│   ├── tests/                    # 隔离的认证与业务接口测试
│   ├── data/                     # 运行时数据，已被 .gitignore 忽略
│   ├── alembic.ini
│   ├── pyproject.toml            # 后端独立依赖与运行配置
│   └── uv.lock
├── frontend/                     # React 19 + Vite + TypeScript + Tailwind v4
│   ├── auth-session-regression.mjs # 会话身份、认证响应及异步竞争回归
│   ├── src/api/                  # 真实接口层与字段映射
│   ├── src/components/           # 登录、导航、题库、出题、收藏、空间、组卷、个人中心
│   │   └── settings/             # 社区保留的「设置」界面
│   ├── src/store/                # 登录态与全局业务状态
│   ├── src/styles/
│   ├── vite.config.ts            # /api 与 /media 代理到后端
│   └── package.json
├── docs/                         # 当前方案及社区历史设计、API 与流程资料
│   ├── design/用户系统功能规格.md # 已接受的邮箱认证、JWT 与开发账号设计
│   └── design/用户系统实施规格.md # 用户故事、实施决策与验收规格
├── apps/desktop/                 # 跨端客户端预留目录
├── packages/contracts/           # 跨端契约预留目录
└── tools/                        # 仓库维护脚本
```

`backend/data/`、`.venv/`、`node_modules/`、`dist/`、`.env` 等都是本地生成物，不进入版本库。

用户系统已对齐的业务需求与拟议实现见 [用户系统功能规格与认证设计](docs/design/用户系统功能规格.md)，覆盖邮箱验证码、学工号密码、Turnstile、JWT 会话及 `.env` 开发账号；设计已获接受，实施范围及验收见 [用户系统实施规格](docs/design/用户系统实施规格.md)；当前实施进度与验证证据见实施规格，未配置 SMTP/Turnstile 时拒绝相关认证操作。

## 技术栈

| 层 | 选型 |
| --- | --- |
| Web 框架 | FastAPI + Uvicorn |
| ORM 与迁移 | SQLAlchemy 2.x + Alembic |
| 数据库 | SQLite，开启 WAL 与 FTS5 全文索引 |
| 会话与任务 | Redis，保存邮箱验证码、限流、出题任务、文档入库进度与对话槽位；认证会话由数据库管理 |
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

Redis 是后端的硬依赖，邮箱验证码、限流、出题任务与文档入库进度存放在这里。默认地址为 `redis://127.0.0.1:6379/0`。

```powershell
# Windows 示例，在 Redis 所在目录执行
.\redis-server.exe .\redis.conf

# Linux / macOS
redis-server
```

### 2. 启动后端

```powershell
cd backend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 启动前按下方配置说明编辑 .env；已有文件不得覆盖
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

账号系统按 [用户系统实施规格](docs/design/用户系统实施规格.md)实施。开发默认账号不再硬编码：在 `backend/.env` 填写教师/学生的邮箱、学工号、密码、显示名，并显式开启 `DEV_ACCOUNTS_ENABLED`，再执行 `uv run python scripts/seed.py`。初始化只供开发环境使用，已有账号不重置密码，冲突会报错，生产禁止执行。开发登录按钮仅填充，仍需手动登录及人机验证；开发凭据不得复用个人或生产密码。

生产部署先按下方「生产认证密钥生成与保存」及「生产配置清单」准备 `backend/.env`，再安装依赖、完成迁移审计并启动服务。开发初始化还要求 `APP_ENV=development`；生产必须关闭开发能力并清空全部开发角色字段。
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

后端配置由 [app/config.py](backend/app/config.py) 定义，读取固定位置的 `backend/.env`；环境变量可覆盖文件值。模板见 [backend/.env.example](backend/.env.example)，根目录 `.env.example` 是历史样例。以下默认值以当前 `Settings` 为准，空字符串表示没有可用凭据。模板中的 `APP_ENV=development` 和本机域名不能直接用于生产。

### 生产认证密钥生成与保存

在受控终端手工执行一次，两个命令任选其一：

~~~powershell
# 从仓库根目录执行
python backend/scripts/generate_auth_secrets.py

# 或先进入 backend，再执行
python scripts/generate_auth_secrets.py
~~~

脚本仅依赖 Python 标准库，不需要 uv、安装项目依赖、加载应用或连接数据库；不读取、创建或写入任何 `.env`。每次显式执行分别调用 `secrets.token_urlsafe(48)`，生成两个独立的秘密值（每个来自 48 随机字节），输出 `AUTH_JWT_SECRET=...`、`AUTH_CODE_SECRET=...` 两行及人工保存提示。`python backend/scripts/generate_auth_secrets.py --help` 只显示帮助，不生成密钥。

仅首次初始化且文件不存在时才从模板创建 `backend/.env`；已有文件直接编辑同名配置项。把两行手工粘贴进去，不将整段输出重定向到 `.env`，不整份覆盖已有配置。不要把秘密值放进 Git、CI/共享日志、截图或聊天；脚本输出也应按凭据保护。同一部署的所有后端进程、实例使用同一组密钥并保持 issuer/audience 一致，不在每次启动时重新生成。此脚本只生成应用自己的两项秘密值，SMTP 账号/授权密码及 Cloudflare Turnstile 凭据必须从各自供应商获取，不能用随机字符串伪造。

轮换 `AUTH_JWT_SECRET` 会使旧签名的访问 JWT 无法验证；轮换 `AUTH_CODE_SECRET` 会使旧邮件验证码无法通过摘要校验。刷新令牌是不透明随机凭据，其摘要及会话状态在数据库中；更换 JWT 密钥本身不必然撤销 refresh 会话，符合条件的会话仍可能刷新得到新 JWT。如需撤销既有会话，应使用现有数据库会话/认证版本撤销流程；改密、重置密码、换绑邮箱撤销全部设备，普通退出撤销当前设备。轮换时协调所有实例更新配置并重启，不混用新旧密钥。

### 生产配置清单

以下参数在 `backend/.env` 或部署环境中设置。所有有效期、次数、限额和超时必须为正数；表中的默认值不是已完成生产配置的证明。

| 配置项 | 当前默认值 | 用途与生产值来源 |
| --- | --- | --- |
| `APP_ENV` | `production`（模板为 `development`） | 部署者显式设为 `production`，启用生产约束及安全 Cookie 行为 |
| `AUTH_JWT_SECRET` | 空 | HS256 访问 JWT 签名密钥；使用上述脚本生成，至少 32 字节 |
| `AUTH_CODE_SECRET` | 空 | 邮箱验证码及限流标识的 HMAC 密钥；独立生成，至少 32 字节，禁止与 JWT 密钥相同 |
| `AUTH_JWT_ISSUER` | `mathcraft` | JWT 的 iss；由部署约定指定非空发行方，签发与验证须一致 |
| `AUTH_JWT_AUDIENCE` | `mathcraft-web` | JWT 的 aud；由部署约定指定非空受众，签发与验证须一致 |
| `AUTH_ACCESS_TTL_SECONDS` | `900` | 访问 JWT 有效期，秒，默认 15 分钟；由部署者设置 |
| `AUTH_REFRESH_TTL_SECONDS` | `604800` | 数据库刷新会话绝对有效期，秒，默认 7 天；由部署者设置 |
| `AUTH_CODE_TTL_SECONDS` | `300` | 邮件验证码有效期，秒，默认 5 分钟 |
| `AUTH_CODE_MAX_ATTEMPTS` | `5` | 单个验证码允许的错误尝试次数 |
| `AUTH_CODE_RETRY_SECONDS` | `60` | 同邮箱、同用途的重发间隔，秒 |
| `AUTH_CODE_EMAIL_HOUR_LIMIT` | `5` | 同邮箱、同用途每小时发码上限 |
| `AUTH_CODE_IP_HOUR_LIMIT` | `30` | 同来源 IP 每小时发码上限；由部署者按访问规模设置 |
| `SMTP_HOST` | 空 | 邮件服务商提供的 SMTP 主机地址 |
| `SMTP_PORT` | `587` | 服务商规定的端口；须与其 TLS 模式匹配，范围 1–65535 |
| `SMTP_USERNAME` | 空 | 服务商提供的 SMTP 登录账号；当前发送器要求非空并执行登录 |
| `SMTP_PASSWORD` | 空 | 从邮件服务商取得的 SMTP 密码/专用授权码，不能由本脚本生成 |
| `SMTP_FROM` | 空 | 经服务商授权的发件人邮箱，应与该账号的发件权限匹配 |
| `SMTP_TLS_MODE` | `starttls` | 按服务商要求选择 `starttls`（连接后升级 TLS）或 `tls`（直接 TLS），不支持明文模式 |
| `SMTP_TIMEOUT_SECONDS` | `10` | SMTP 连接/操作超时，秒，由部署者设置 |
| `TURNSTILE_SITE_KEY` | 空 | 在 Cloudflare 控制台为生产站点创建 Turnstile widget 后取得的站点公钥，供前端渲染 |
| `TURNSTILE_SECRET_KEY` | 空 | 同一 widget 的服务端 Siteverify 密钥，仅后端保存；生产拒绝官方测试密钥 |
| `TURNSTILE_ALLOWED_HOSTNAMES` | 空（模板为 `localhost,127.0.0.1`） | 部署者填写逗号分隔的精确前端 hostname，并与 Cloudflare widget 的站点配置一致 |
| `TURNSTILE_TIMEOUT_SECONDS` | `10` | 后端向 Siteverify 验证人机令牌的超时，秒 |
| `CORS_ORIGINS` | `http://127.0.0.1:5173,http://localhost:5173` | 部署者替换为生产前端精确 HTTPS Origin 白名单，逗号分隔 |
| `DEV_ACCOUNTS_ENABLED` | `false` | 生产必须明确关闭，禁止开发初始化及凭据填充能力 |
| `DEV_TEACHER_EMAIL` / `DEV_TEACHER_USER_NO` / `DEV_TEACHER_PASSWORD` / `DEV_TEACHER_DISPLAY_NAME` | 均为空 | 生产全部清空；保留其中任一字段也会触发生产配置拒绝 |
| `DEV_STUDENT_EMAIL` / `DEV_STUDENT_USER_NO` / `DEV_STUDENT_PASSWORD` / `DEV_STUDENT_DISPLAY_NAME` | 均为空 | 生产全部清空；开发专用值不得复用生产或个人凭据 |

例如前端站点为 `https://learn.example.com` 时，`CORS_ORIGINS=https://learn.example.com`，`TURNSTILE_ALLOWED_HOSTNAMES=learn.example.com`。Origin 包含协议及非默认端口（如有），不得包含路径、尾斜杠、查询参数或通配符；hostname 只填主机名，不含协议、端口或路径。这里的域名是占位示例，应替换为实际浏览器访问前端的域名。生产由部署者配置 HTTPS；当前配置校验接受精确 HTTP/HTTPS Origin，不会代为申请证书或部署反向代理。缺少认证、SMTP 或 Turnstile 必要配置以及依赖故障时，相关认证操作拒绝或返回服务不可用，不绕过验证。

### 数据、缓存与模型配置

| 配置项 | 当前默认值 | 用途与部署路径来源 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./data/mathcraft.db` | 保存用户、角色、资源归属、个人模型设置与认证会话。SQLite 相对文件路径按进程工作目录解析，从 `backend/` 启动才对应 `backend/data/mathcraft.db`；生产由部署者指定受控持久卷的绝对数据库 URL，并先创建可写父目录 |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | 验证码、限流及业务任务缓存；使用部署者提供的受控 Redis 地址/逻辑库，各实例连接同一服务，与测试隔离 |
| `CHROMA_DIR` | `data/chroma` | 向量索引持久化目录 |
| `UPLOAD_DIR` | `data/uploads` | 原始上传文档目录 |
| `OCR_DIR` | `data/ocr` | OCR 工作文件目录 |
| `AVATAR_DIR` | `data/avatars` | 用户头像目录；示例配置未列出时使用此默认值 |
| `MAX_UPLOAD_MB` / `MAX_AVATAR_MB` | `200` / `5` | 文档/头像上传大小限制，MB，由部署者设置 |
| `GENERATE_TASK_TTL_SECONDS` | `1800` | Redis 出题任务缓存有效期，秒 |
| `CHAT_SESSION_TTL_SECONDS` / `INGEST_TASK_TTL_SECONDS` | `7200` / `7200` | Redis 对话槽位/文档入库任务缓存有效期，秒 |
| `SESSION_TTL_SECONDS` | `604800` | 保留的历史配置字段；当前认证会话有效期使用 `AUTH_REFRESH_TTL_SECONDS`，不用它调整登录时长 |
| `DEEPSEEK_API_KEY` | 空 | 从模型服务商取得的环境兜底密钥；用户个人中心的模型设置优先，不用于 JWT 或发码 |
| `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` / `DEEPSEEK_DISPLAY_NAME` | `https://api.deepseek.com` / `deepseek-flash` / `DeepSeek Flash` | 模型接口及默认模型信息，由供应商信息与部署约定确定 |
| `SILICONFLOW_BASE_URL` | `https://api.siliconflow.cn/v1` | 向量与重排服务接口；与认证密钥无关 |

四项存储目录的相对路径以 `backend/` 为基准，绝对路径则直接使用；生产应由部署者指定源码之外、后端进程可写的持久卷绝对路径，例如 Linux 的 `DATABASE_URL=sqlite:////srv/mathcraft/data/mathcraft.db`、`UPLOAD_DIR=/srv/mathcraft/uploads`（仅为路径示例，其余存储目录同样指定）；并安排数据库、上传、头像和索引的备份/恢复。迁移路径时显式搬迁现有数据库及目录、核对归属与索引，不能只改变量而丢弃用户数据；填写路径并不表示支持任意多实例共享 SQLite/Chroma 的部署方式。

用户个人模型设置经现有 `/api/users/me/model-settings` 保存到数据库 `UserModelSetting`，注册时与用户同事务初始化；认证配置完成不代表模型调用已配置。硅基流动与 MinerU 沿用 [local_secrets.example.py](backend/app/local_secrets.example.py) 所示的既有本地凭据配置边界，凭据由相应供应商取得；真实 `backend/app/local_secrets.py` 不提交、不打印，不作为本脚本的输入或输出。检索与切片参数仍见 `backend/app/config.py`。

配置文档和脚本只辅助部署准备，不表示已经配置真实服务、执行生产迁移或完成上线。迁移前先备份并在受控副本运行只读账号审计；缺失/未验证邮箱、标识冲突等问题未解决时阻断发布，具体门禁见 [后端迁移说明](backend/README.md#迁移与验证)。

## 核心实现

### 账号与权限

注册验证邮箱并自动登录；登录支持邮箱验证码或学工号密码，密码使用 bcrypt 校验。短期访问 JWT 仅保存在前端内存；刷新凭据通过 HttpOnly Cookie 管理，其摘要、会话状态及用户认证版本保存在数据库，默认刷新会话有效期 7 天。Redis 保存邮件验证码、限流和业务任务。修改/重置密码及换绑邮箱撤销全部设备会话，退出仅撤销当前设备。

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

个人中心维护昵称、头像和安全资料。修改密码验证旧密码；更换邮箱验证旧、新邮箱；添加、修改或移除学工号需当前密码。修改密码和换绑邮箱后所有设备下线，普通退出只影响当前设备。普通资料更新不能绕过安全接口修改邮箱或学工号。模型配置支持按用户填写 DeepSeek 密钥并测试连通性，MinerU Token 也在同一页面配置。

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

后端测试位于 `backend/tests`，覆盖认证、题库、文档、出题、收藏、空间、组卷、作答、批卷、催交通知与个人资料。测试使用临时 SQLite 与每测试独立的 fakeredis，绝不连接或清空本机 Redis；邮件、人机验证及外部模型全部打桩，不需要真实密钥。

```powershell
cd backend
uv sync --group dev
uv run pytest -q
```

前端类型检查与构建：

```powershell
cd frontend
npm run typecheck
npm run lint
npm run build
```

## 当前边界

1. 后端以 SQLite 单机部署为目标，没有做多节点写入与分布式锁。
2. Redis 不可用时，登录、出题和文档入库都无法工作。
3. DeepSeek、硅基流动与 MinerU 依赖外网，离线环境只能运行不涉及模型的部分。
4. `docs/` 中的设计与流程文档来自社区早期版本，可能与当前实现不一致，接口以根 `openapi.json` 为准。
5. `docs/api.md` 由 `tools/gen_api_docs.py` 按当前 OpenAPI 的全部 HTTP 操作生成；修改接口须同时更新契约及索引。

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

### 认证开发验证

后端测试使用临时 SQLite 与每测试独立的进程内 Redis（fakeredis），不连接或清空本机 Redis；SMTP、人机验证及外部模型使用假服务。先安装开发依赖，再在仓库根运行：

```powershell
uv sync --project backend --group dev
backend\.venv\Scripts\python.exe -m pytest -q
```

接口契约修改后重新生成根 OpenAPI 和完整 API 索引；生成器按当前全部接口标签输出，不再套用历史无鉴权目录。
