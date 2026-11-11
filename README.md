# MathCraft — 数学智能教学平台

MathCraft 面向教师与学生，提供题库协作、文档解析与检索、智能出题、组卷发布、学生作答和 AI 批卷。后端使用 FastAPI，前端使用 React 19 + TypeScript + Vite，数据存储采用 SQLite、Redis 与 Chroma。

- 教师：管理题库与学习空间，上传教学资料，出题、组卷、发布试卷和催交。
- 学生：加入学习空间，作答、查看获准公开的解析，收藏题目。
- 管理员：开通与管理账号，维护平台模型、检索配置和索引重建。

文档支持 PDF、DOCX、XLSX、Markdown 和 TXT；扫描件通过 MinerU OCR 解析，检索采用向量与全文混合召回、重排，出题与批卷使用 DeepSeek。

## 目录结构

以下列出主要源码、配置与文档入口：

```text
MathCraft/
├── backend/                  # FastAPI 后端与独立 uv 依赖环境
│   ├── app/
│   │   ├── main.py           # 应用入口 app.main:app
│   │   ├── config.py         # 配置定义，读取 backend/.env
│   │   ├── api/              # HTTP 与 WebSocket 接口
│   │   ├── models/           # 数据库模型
│   │   ├── schemas/          # 请求与响应契约
│   │   └── services/         # 认证、文档、RAG、出题等业务服务
│   ├── alembic/              # 数据库迁移
│   ├── scripts/              # 认证密钥、管理员与开发账号初始化
│   ├── tests/                # 后端测试
│   ├── .env.example          # 本机开发配置模板
│   └── README.md             # 后端配置、迁移与故障处理
├── frontend/                 # React 前端
│   ├── src/                  # 页面、组件、API 与状态管理
│   │   ├── api/              # 认证及业务 API 请求
│   │   │   ├── adminOps.ts   # 运维 v1 真实请求适配；五个后端接口待实现
│   │   │   └── adminOpsDemo.ts # 仅 DEV 显式启用的合成演示
│   │   ├── components/
│   │   │   └── admin/        # 七入口管理面板与既有管理操作
│   │   │       ├── AdminPanel.tsx
│   │   │       ├── LegacyOverview.tsx # 原平台资源与历史批次真实统计
│   │   │       └── ops/      # 运维页面、通知及共用展示／查询
│   │   │           ├── OpsPages.tsx
│   │   │           ├── RunDrawer.tsx
│   │   │           ├── AdminNotifications.tsx
│   │   │           ├── OpsShared.tsx
│   │   │           └── useOpsQuery.ts
│   │   └── types/
│   │       └── ops.ts        # 运维 v1 前端类型，不代表新增 OpenAPI
│   ├── ops-panel-regression.mjs # 运维面板离线浏览器回归
│   ├── package.json          # 前端依赖与命令
│   └── README.md             # 前端开发说明
├── docs/
│   ├── api.md                # API 文档
│   └── design/               # 功能设计、实施记录与待实现方案
│       ├── 运维后台升级方案.md # 运维方案、前端先行例外与验收记录
│       ├── 运维后台接口与联调契约.md   # 拟新增接口、状态和联调样例
│       ├── 运维后台模块说明.md     # 模块职责、依赖与验收要点
│       └── 运维后台系统方案说明.md # 面向方案评审的系统说明
├── apps/desktop/             # 桌面客户端预留目录
├── packages/contracts/       # 共享契约预留目录
├── tools/                    # API 文档生成等维护脚本
├── compose.yaml              # 本地 Redis 容器
├── pyproject.toml            # 仓库级依赖与检查配置
├── openapi.json              # 当前接口契约
├── AGENTS.md                 # 协作约定
├── GLOSSARY.md               # 领域术语
└── STUBS.md                  # 当前 DEV 演示边界与历史替身说明
```

## 启动方法

以下命令以 PowerShell 为例。先在终端进入仓库根目录，即包含 `compose.yaml`、`backend/` 和 `frontend/` 的目录；Redis、后端、前端按顺序启动。

### 1. 准备环境

安装 Python 3.11 及以上、uv、Node.js 22.13 及以上的 22.x 版本或 Node.js 24 及以上（含 npm），以及 Docker 与 Compose v2。Windows 使用 Docker Desktop 的 Linux 容器引擎，并先启动 Docker Desktop；已有 Redis 7 及以上服务时可直接使用。

```powershell
python --version
uv --version
node --version
npm --version
docker compose version
```

模型出题、向量检索与 OCR 需要访问相应外部服务，并配置凭据。

### 2. 启动 Redis

在仓库根目录执行：

```powershell
docker compose config --quiet
docker compose up -d --wait redis
docker compose exec redis redis-cli ping
```

最后一条命令应返回 `PONG`。默认监听 `127.0.0.1:6379`，数据保存到 Docker 命名卷。若端口已被现有 Redis 占用，直接使用该服务，并在下一步配置对应的 `REDIS_URL`。

### 3. 安装后端依赖并初始化配置

在同一终端进入 `backend/`：

```powershell
cd backend
uv sync
uv run python scripts/init_auth_secrets.py
if (-not (Test-Path app/local_secrets.py)) {
    Copy-Item app/local_secrets.example.py app/local_secrets.py
}
```

初始化脚本在缺少 `backend/.env` 时从 `.env.example` 创建，生成两项独立的认证密钥；已有合法密钥会保留，且不会打印。随后用编辑器打开 `backend/.env`，确认以下配置：

| 配置 | 本机开发填写方式 |
| --- | --- |
| `APP_ENV` | `development` |
| `TURNSTILE_ENABLED` | `false`，仅实际回环请求可跳过人机验证 |
| `DATABASE_URL` | 默认 `sqlite:///./data/mathcraft.db` |
| `REDIS_URL` | 默认 `redis://127.0.0.1:6379/0`，与上一步的服务一致 |
| `AUTH_JWT_SECRET`、`AUTH_CODE_SECRET` | 由初始化脚本生成，保留生成值 |
| `DEEPSEEK_API_KEY` | 可填部署默认 Key，也可登录后在“设置 → 模型与服务”保存个人 Key |
| `SMTP_*` | 使用邮箱验证码登录、找回密码或绑定邮箱时配置 |

上述复制命令仅在缺少 `app/local_secrets.py` 时创建占位配置，已有文件保留。首次账号密码登录无需真实模型凭据，使用模型功能前再配置对应服务。

已有 `.env` 不会被模板覆盖，需手动核对开发开关。配置来源以 [backend/app/config.py](backend/app/config.py) 为准，环境变量优先于 `.env`；修改后需重启后端。

### 4. 迁移数据库并创建首个管理员

继续在 `backend/` 执行：

```powershell
New-Item -ItemType Directory -Path data -Force | Out-Null
uv run alembic upgrade head
uv run python scripts/create_admin.py
```

按提示输入登录账号、显示名称和两次密码。账号可使用英文字母、数字、下划线、点和连字符；密码为 8–64 字符，UTF-8 不超过 72 字节，输入时隐藏。管理员只需首次创建，已有管理员时跳过最后一条命令；脚本不会覆盖已有账号。

已有数据的环境应先备份再迁移。自定义 SQLite 路径时，先创建对应父目录；备份需包含 WAL 已提交数据，可使用 SQLite backup API，具体见 [后端说明](backend/README.md)。

### 5. 启动后端

仍在 `backend/` 执行，并保持该终端运行：

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
```

启动后可访问：

- 健康检查：`http://127.0.0.1:8000/api/health`
- Swagger 接口文档：`http://127.0.0.1:8000/docs`

索引重建使用进程内任务，当前按单进程部署，保留 `--workers 1`。

### 6. 启动前端并登录

新开一个终端，从仓库根目录执行：

```powershell
cd frontend
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`，使用刚创建的管理员账号选择“密码登录”。前端将 `/api` 和 `/media` 请求代理到后端的 8000 端口。

管理员登录后在管理面板开通教师、学生账号。教师创建题库并上传资料，随后可检索、出题和组卷。模型配置分为两处：

- “设置 → 模型与服务”：个人 DeepSeek Key、MinerU Token，个人配置优先于部署默认值。
- 管理员“模型与检索”：平台嵌入、重排模型与凭据；修改嵌入模型或服务地址后，需显式重建索引才能应用。

部署默认的硅基流动与 MinerU 凭据配置方式见 [模型配置说明](docs/design/模型配置来源与普通知识库流程.md)，占位格式见 [local_secrets.example.py](backend/app/local_secrets.example.py)。

### 7. 日常启动与停止

首次初始化完成后，只需启动 Redis，并分别在 `backend/`、`frontend/` 运行上述服务命令。依赖变更后重新安装，数据库结构变更后重新执行迁移。

前后端各在对应终端按 `Ctrl+C` 停止。Redis 在仓库根目录管理：

```powershell
docker compose stop redis       # 暂停
docker compose up -d --wait redis # 恢复
docker compose down             # 移除容器，保留数据卷
```

默认运行数据位于 `backend/data/`，包括 SQLite、上传原件、OCR 结果、头像与 Chroma 索引；Redis 数据另存在 Docker 卷中。日常停止不要给 `down` 添加 `-v`，该参数会删除数据卷。

### 常见启动问题

- 登录按钮显示“认证配置不可用”：确认认证密钥已初始化，开发配置为 `APP_ENV=development`、`TURNSTILE_ENABLED=false`，按上述回环地址与 `--no-proxy-headers` 启动，然后重启后端、刷新页面。检查启动环境变量是否覆盖 `.env`。
- 前端请求失败：确认后端 8000 端口和 Redis 均已启动；邮件、向量、OCR 等依赖的状态可从健康检查查看。
- Chroma 在 Windows 报 `code 14`：核对启动进程的 `TEMP/TMP` 是否可写，处理步骤见 [后端说明](backend/README.md)。

生产部署需设置 `APP_ENV=production`、`TURNSTILE_ENABLED=true` 并配置 Cloudflare 站点信息，关闭开发账号能力，配置持久化路径与备份。服务器通过 SSH 连接，部署前按 [后端迁移说明](backend/README.md#迁移与验证) 完成备份、迁移与审计。

## 开发检查

后端在 `backend/` 执行；测试使用临时 SQLite、进程内 fakeredis 和外部服务替身：

```powershell
uv sync --group dev
uv run pytest -q
```

前端在 `frontend/` 执行：

```powershell
npm run typecheck
npm run lint
npm run build
```

## 文档入口

- [后端说明](backend/README.md)、[前端说明](frontend/README.md)：各端开发、配置与排错。
- [API 文档](docs/api.md)、[OpenAPI 契约](openapi.json)：接口与数据字段。
- [账号与权限设计](docs/design/账号系统整合与审查修复.md)、[模型配置说明](docs/design/模型配置来源与普通知识库流程.md)、[知识库说明](docs/design/知识库模块说明.md)：业务规则与能力边界。
- [运维后台系统方案说明](docs/design/运维后台系统方案说明.md)：面向方案评审与协作沟通，介绍系统目标、使用场景、功能模块和建设边界；文末列明代码实施必须参考的三份约定文档。
- [运维后台扩展方案](docs/design/运维后台升级方案.md)：用户授权按 v1 契约在 G0 前先行实现七入口与管理员通知前端，前端与合成交互已验收；五个 ops 后端接口仍待实现，G0 真实追踪、G1 后端契约冻结、G3 贯通均未通过。DEV 中管理员登录后可显式勾选合成演示，默认真实；旧平台资源统计、账号、模型与安全仍使用真实接口，真实请求失败不自动切换演示，生产无演示入口与 demo 模块。配套[接口与联调契约](docs/design/运维后台接口与联调契约.md)、[模块说明](docs/design/运维后台模块说明.md)和[演示边界](STUBS.md)说明实现范围；追踪、本地 Phoenix 及告警后端仍按方案建设。
- [协作约定](AGENTS.md)、[领域术语](GLOSSARY.md)：开发约定与术语定义。

当前实现以 `backend/app/`、`frontend/src/` 与根 `openapi.json` 为准；设计文档中的历史记录仅供参考。

## 许可证

项目以 [Apache-2.0](LICENSE) 发布，最初从 DeepTutor 裁剪而来；第三方来源与许可证正文见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
