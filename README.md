# MathCraft — 数学智能教学平台

MathCraft 面向教师与学生，提供题库协作、文档解析与检索、智能出题、组卷发布、学生作答和 AI 批卷。后端使用 FastAPI，前端使用 React 19 + TypeScript + Vite，数据存储采用 SQLite、Redis 与 Chroma。

- 教师：管理题库与学习空间，上传教学资料，出题、组卷、发布试卷和催交。
- 学生：加入学习空间，作答、查看获准公开的解析，收藏题目。
- 管理员：开通与管理账号，维护平台模型、检索配置和索引重建。

文档支持 PDF、DOCX、XLSX、Markdown 和 TXT；扫描件通过 MinerU OCR 解析，检索采用向量与全文混合召回、重排，出题与批卷使用 DeepSeek。

对话提供快速出题、创新命题、知识答疑和数据管理四模式。生成阶段在后端流式解析并校验题目，界面通过进度轮询等待审核后的结果；题目预览中勾选题目后可导出 Word，设置题型顺序、答案和解析的位置。

## 目录结构

以下列出主要源码、配置与文档入口：

```text
MathCraft/
├── backend/                  # FastAPI 后端
│   ├── app/                  # 接口、数据模型与业务服务
│   ├── alembic/              # 数据库迁移
│   ├── scripts/              # 配置初始化与账号管理
│   ├── tests/                # 后端测试
│   └── README.md             # 后端配置、迁移与排错
├── frontend/                 # React + TypeScript 前端
│   ├── src/                  # 页面、组件、API 与状态管理
│   └── README.md             # 前端开发说明
├── docs/                     # API 文档与设计说明
│   ├── api.md                # API 索引
│   └── design/               # 设计、实施与验证记录
├── tools/                    # 文档生成与维护工具
├── apps/desktop/             # 桌面客户端预留目录
├── packages/contracts/       # 共享契约预留目录
├── compose.yaml              # 本地 Redis 容器
├── compose.phoenix.yaml      # 可选 Phoenix 追踪服务
├── pyproject.toml            # 仓库级依赖与检查配置
├── openapi.json              # 接口契约
├── AGENTS.md                 # 协作约定
├── GLOSSARY.md               # 领域术语
└── STUBS.md                  # 开发演示与历史替身说明
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

出题 JSON 修复依赖 `json-repair`，Word 导出依赖 `python-docx`、`latex2mathml` 和 `mathml2omml`，由上述 `uv sync` 安装。升级时需重新同步依赖；仓库根环境与后端独立环境分别由各自的 `pyproject.toml`、`uv.lock` 管理，使用哪个环境就同步哪个环境。导出在本地生成文档，无需模型调用或安装 Microsoft Word。

OpenAI 兼容客户端使用 `openai<3`：当前追踪适配基于 `httpx`，不兼容 OpenAI SDK 3.x 的 `httpx2`。已有环境更新后执行 `uv sync` 并重启后端，避免个人模型连接测试在请求发出前报客户端兼容错误。

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

已有 `.env` 不会被模板覆盖，需手动核对开发开关。后端环境配置以 [backend/app/config.py](backend/app/config.py) 为准，进程环境变量优先于固定位置的 `backend/.env`；修改后需重启后端。唯一可复制的后端环境模板为 [backend/.env.example](backend/.env.example)，根 [.env.example](.env.example) 仅作配置入口指引，当前前后端均不读取根 `.env`。

MinerU Token 在“设置 → 模型与服务”保存，个人配置优先；部署默认 Token 使用 `app/local_secrets.py` 的 `MINERU_DEFAULT_TOKEN`。旧 `MINERU_MODE`、`MINERU_API_BASE_URL`、`MINERU_API_TOKEN` 不生效，已有本机文件不会自动迁移。嵌入和重排模型仍由管理员“模型与检索”维护。

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
$mathcraftTemp = (New-Item -ItemType Directory -Path data/tmp -Force).FullName
$env:TEMP = $mathcraftTemp
$env:TMP = $mathcraftTemp
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
```

上述 PowerShell 启动方式为当前终端及后端子进程指定本地临时目录，避免 Windows 默认临时目录不可写时导致 Chroma 初始化或向量写入失败。Chroma 使用进程内本地持久存储，无需另外启动向量数据库服务；临时目录不替代 `CHROMA_DIR` 中的正式索引。

启动后可访问：

- 健康检查：`http://127.0.0.1:8000/api/health`
- Swagger 接口文档：`http://127.0.0.1:8000/docs`

索引重建使用进程内任务，当前按单进程部署，保留 `--workers 1`。

### 6. 启动前端并登录

新开一个终端，从仓库根目录执行：

```powershell
cd frontend
npm install
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort
```

打开 `http://127.0.0.1:5173`，使用刚创建的管理员账号选择“密码登录”。前端将 `/api` 和 `/media` 请求代理到后端的 8000 端口；端口占用时退出，不自动换端口。

前端隔离项目环境文件，根 `.env` 和 `frontend/.env` 均不会被 Vite 加载；自定义公开 API 地址需在开发启动或构建前通过进程环境变量 `VITE_API_BASE_URL` 注入。监听地址与端口使用上述命令行参数，开发代理目标由 `frontend/vite.config.ts` 定义；`VITE_*` 会进入浏览器代码，不得放入凭据。详见[前端配置说明](frontend/README.md#构建与检查)。

教师、学生账号由管理员开通。个人 DeepSeek Key 和 MinerU Token 在“设置 → 模型与服务”配置；平台嵌入、重排模型由管理员在“模型与检索”配置。嵌入模型或服务地址变更后，需重建索引才能应用。

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
- 删除资料提示 `DATABASE_BUSY`：短暂写锁会自动有限重试；持续占锁时保留资料与原件，请稍后重试并检查其他写入进程。不要根据失败状态或零切片计数跳过索引清理，见 [删除与锁竞争说明](docs/design/知识库模块说明.md#删除写锁竞争修复2026-11-12)。
- 删除资料的全文索引清理出现 `SQLITE_CANTOPEN / 14`：更新后重启后端以应用 SQLite 内存临时存储配置；数据库与 WAL 仍保存在磁盘。该错误与写锁竞争分别处理，见 [后端排错说明](backend/README.md#常见问题)。

生产部署需设置 `APP_ENV=production`、`TURNSTILE_ENABLED=true` 并配置 Cloudflare 站点信息，关闭开发账号能力，配置持久化路径与备份。服务器通过 SSH 连接，部署前按 [后端迁移说明](backend/README.md#迁移与验证) 完成备份、迁移与审计。

### 可选 Phoenix

默认关闭。需要时在 `backend/` 执行 `uv sync --extra phoenix`，在仓库根执行 `docker compose -f compose.phoenix.yaml up -d --wait phoenix`；设置 `PHOENIX_ENABLED=true` 并重启后端。使用根环境时也在根目录安装同名 extra。

默认 OTLP 地址为 `http://127.0.0.1:6017/v1/traces`，查看入口为 `http://127.0.0.1:6017`。容器固定 Phoenix 21 镜像 digest，数据保存到 `phoenix_data` 命名卷。此本机部署默认无认证，仅限可信单机；远程访问须独立配置 HTTPS、认证和 API key。

默认配置：`PHOENIX_ENABLED=false`、`PHOENIX_PROJECT=mathcraft`、`PHOENIX_API_KEY=`（`SecretStr`）、`PHOENIX_QUEUE_SIZE=128`、`PHOENIX_TIMEOUT_SECONDS=0.5`。根与后端 extra 均固定 `opentelemetry-sdk==1.45.2`、`opentelemetry-exporter-otlp-proto-http==1.45.2`，仅追踪元数据。停用时关闭开关并重启后端；容器可独立 `docker compose -f compose.phoenix.yaml stop phoenix`，保留数据卷。

详细配置与排错见 [Phoenix 可选扩展](docs/design/Phoenix可选扩展.md)。

## 开发检查

后端在 `backend/` 执行；测试使用临时 SQLite、进程内 fakeredis 和外部服务替身，夹具禁止外部网络，不连接或清空本机 Redis：

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

- [后端说明](backend/README.md)、[前端说明](frontend/README.md)：开发、配置与排错。
- [API 文档](docs/api.md)、[OpenAPI 契约](openapi.json)：接口与数据字段。
- [账号与权限](docs/design/账号系统整合与审查修复.md)、[认证与账号安全](docs/design/登录视觉恢复与历史前端对照.md)。
- [模型配置](docs/design/模型配置来源与普通知识库流程.md)、[知识库](docs/design/知识库模块说明.md)。
- [四模式对话](docs/design/对话四模式与主线整合.md)、[出题审核](docs/design/出题审核中间件设计与实施记录.md)、[Word 导出](docs/design/题目Word导出与公式呈现.md)。
- [运维后台](docs/design/运维后台模块说明.md)、[运行手册](docs/design/运维后台运行手册.md)、[可选追踪](docs/design/Phoenix可选扩展.md)。
- [协作约定](AGENTS.md)、[领域术语](GLOSSARY.md)。

## 许可证

项目以 [Apache-2.0](LICENSE) 发布，最初从 DeepTutor 裁剪而来；第三方来源与许可证正文见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

出题运行台账及生命周期见 [台账基础](docs/design/运维后台运行台账基础.md)与[入口接入](docs/design/运维后台出题入口接入.md)。
