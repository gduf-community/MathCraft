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
├── .scratch/frontend-0b5d4b4/ # 已结束的本地历史对照残留，删除受阻，待清理
├── backend/                  # FastAPI 后端与独立 uv 依赖环境
│   ├── app/
│   │   ├── main.py           # 应用入口 app.main:app
│   │   ├── config.py         # 配置定义，读取 backend/.env
│   │   ├── api/              # HTTP 与 WebSocket 接口
│   │   │   └── export.py     # 登录用户提交题目并导出 Word
│   │   ├── models/           # 数据库模型
│   │   ├── schemas/          # 请求与响应契约
│   │   └── services/         # 认证、文档、RAG、出题等业务服务
│   │       ├── export_docx.py # Word 排版与 LaTeX → MathML → OMML 公式转换
│   │       └── rag/          # 检索、出题及四模式对话
│   │           ├── skills.py # 显式模式的技能注册与执行上下文
│   │           └── question_gen.py # 流式接收、滚动解析与题目校验
│   ├── alembic/              # 数据库迁移
│   ├── scripts/              # 认证密钥、管理员与开发账号初始化
│   ├── tests/                # 后端测试
│   ├── .env.example          # 本机开发配置模板
│   └── README.md             # 后端配置、迁移与故障处理
├── frontend/                 # React 前端
│   ├── src/                  # 页面、组件、API 与状态管理
│   │   ├── api/              # 认证及业务 API 请求
│   │   │   ├── adminOps.ts   # 运维 v1 真实请求适配；五个后端接口待实现
│   │   │   ├── adminOpsDemo.ts # 仅 DEV 显式启用的合成演示
│   │   │   └── exportDocx.ts # 认证请求与 Word 文件下载
│   │   ├── components/
│   │   │   ├── auth/         # 历史登录视觉、手动身份选择与当前安全认证
│   │   │   │   ├── AuthDialog.tsx # 邮箱登录与两种密码找回方式的独立弹窗
│   │   │   │   └── LoginEmailBindingDialog.tsx # 临时认证后绑定邮箱，退出失败可重试
│   │   │   ├── tabs/GenerateTab/ # 历史视觉恢复，保留四模式、图片与确认
│   │   │   │   └── QuickPrompts.tsx # 恢复历史快捷提问，点击填入草稿
│   │   │   ├── tabs/PreviewTab/ExportModal.tsx # 已选题目的 Word 导出设置
│   │   │   ├── ui/ConfirmCard.tsx # 数据操作影响预览与确认
│   │   │   ├── ui/SegmentedControl.tsx # 对话模式选择
│   │   │   ├── ui/Toast.tsx # 全站共享提示；本轮仅恢复历史外观
│   │   │   └── admin/        # 七入口管理面板与既有管理操作
│   │   │       ├── AdminPanel.tsx
│   │   │       ├── LegacyOverview.tsx # 原平台资源与历史批次真实统计
│   │   │       └── ops/      # 运维页面、通知及共用展示／查询
│   │   │           ├── OpsPages.tsx
│   │   │           ├── RunDrawer.tsx
│   │   │           ├── AdminNotifications.tsx
│   │   │           ├── OpsShared.tsx
│   │   │           ├── OpsExtensions.tsx # 自监控、配置、版本／范围及只读指引
│   │   │           ├── useOpsQuery.ts
│   │   │           └── useOpsClock.ts # 服务端快照加页面经过时间复核新鲜度
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
│       ├── 运维后台系统方案说明.md # 面向方案评审的系统说明
│       ├── 运维后台三人实施分工方案.md # 三人职责、接口归属与交接顺序
│       ├── 运维后台运行手册.md # 部署、值守、故障恢复与审计方案
│       ├── 对话四模式与主线整合.md # 对话流程、确认范围与合并边界
│       ├── 题目Word导出与公式呈现.md # 导出契约、公式转换与显示边界
│       ├── 登录视觉恢复与历史前端对照.md # 登录、agent 视觉基准与历史对照验收记录
│       ├── 运维后台A0与G0独立准备记录.md # 甲的本地核验、合成证据与待交接边界
│       └── 运维后台G0技术核验.md # 固定版本、Phoenix 认证及清理依据
├── apps/desktop/             # 桌面客户端预留目录
├── packages/contracts/       # 共享契约预留目录
├── tools/                    # API 文档生成等维护脚本
│   └── ops_g0/               # 独立 SDK/Phoenix 验证；显式授权后可做限额真实模型验收
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

出题 JSON 修复依赖 `json-repair`，Word 导出依赖 `python-docx`、`latex2mathml` 和 `mathml2omml`，由上述 `uv sync` 安装。升级时需重新同步依赖；仓库根环境与后端独立环境分别由各自的 `pyproject.toml`、`uv.lock` 管理，使用哪个环境就同步哪个环境。导出在本地生成文档，无需模型调用或安装 Microsoft Word。

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
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort
```

打开 `http://127.0.0.1:5173`，使用刚创建的管理员账号选择“密码登录”。前端将 `/api` 和 `/media` 请求代理到后端的 8000 端口；端口占用时退出，不自动换端口。当前环境的 npm wrapper 会错误解析附加启动参数，因此直接用 Node 执行本地 Vite 入口。

前端隔离项目环境文件，根 `.env` 和 `frontend/.env` 均不会被 Vite 加载；自定义公开 API 地址需在开发启动或构建前通过进程环境变量 `VITE_API_BASE_URL` 注入。监听地址与端口使用上述命令行参数，开发代理目标由 `frontend/vite.config.ts` 定义；`VITE_*` 会进入浏览器代码，不得放入凭据。详见[前端配置说明](frontend/README.md#构建与检查)。

主登录页按 `0b5d4b4` 恢复历史视觉，学生、教师可手动选择身份；认证角色以服务端响应为准，不匹配时退出并提示重新选择，管理员可直接进入管理面板。当前密码、邮箱验证码、重置密码、Turnstile 与安全会话流程保留，现有接口不变。

紧凑主卡以密码登录为主，提供“邮箱登录”和“忘记密码？”两个入口。邮箱登录弹窗内通过“尚未绑定邮箱？先绑定”切换到绑定流程，并可返回邮箱登录。未登录绑定一次填写账号、密码和邮箱，点击“发送验证码”后先验证账号，再发码并显示验证码框，成功发码后至少等待 60 秒才能重发；已登录个人页面绑定无需重复密码。绑定不进入工作台，成功返回登录，返回或关闭时撤销临时会话，退出失败可重试。找回密码可联系管理员或验证已绑定邮箱；未配置有效联系邮箱时隐藏邮件入口。

个人中心账号安全按学工号、邮箱、修改密码纵向排列；修改密码仍用弹窗。登录后首次绑定或重新绑定未验证邮箱只需邮箱验证码，换绑已验证邮箱需旧、新邮箱双验证码，解绑需当前密码；邮箱变更成功后全部设备退出。

5174 临时历史对照已于 **2026-11-12 结束并停服**，不再提供旧登录或隔离预览入口。`.scratch/frontend-0b5d4b4/` 的递归删除被自动审批审查拒绝，目录及其历史预览、依赖尚待清理；它们仍被 Git 忽略，不属于当前启动流程。历史核验与清理状态见[恢复设计](docs/design/登录视觉恢复与历史前端对照.md#2026-11-12-临时对照结束与清理状态)。

agent 视觉基准为 `5155f8a`（`bca8fb9^1`，前端树与 `bca8fb9` 相同），用户已明确确认恢复旧视觉并保留当前四模式、图片和数据确认。历史用户消息可编辑或回退后重发，但服务端没有历史截断接口，回退只裁切前端消息，不能保证服务端上下文同步回退。恢复文件、交互及验收见[登录视觉恢复与历史前端对照](docs/design/登录视觉恢复与历史前端对照.md)。

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
- 删除资料提示 `DATABASE_BUSY`：短暂写锁会自动有限重试；持续占锁时保留资料与原件，请稍后重试并检查其他写入进程。不要根据失败状态或零切片计数跳过索引清理，见 [删除与锁竞争说明](docs/design/知识库模块说明.md#删除写锁竞争修复2026-11-12)。
- 删除资料的全文索引清理出现 `SQLITE_CANTOPEN / 14`：更新后重启后端以应用 SQLite 内存临时存储配置；数据库与 WAL 仍保存在磁盘。该错误与写锁竞争分别处理，见 [后端排错说明](backend/README.md#常见问题)。

生产部署需设置 `APP_ENV=production`、`TURNSTILE_ENABLED=true` 并配置 Cloudflare 站点信息，关闭开发账号能力，配置持久化路径与备份。服务器通过 SSH 连接，部署前按 [后端迁移说明](backend/README.md#迁移与验证) 完成备份、迁移与审计。

## 开发检查

运维 A0/G0 独立准备使用单独环境与本机 Phoenix 6016 端口，不随应用启动，默认只用假模型；安装、认证配置生成、合成复现及显式授权的限额真实模型验收见 [工具说明](tools/ops_g0/README.md)。独立验证通过不代表实际业务 G0 通过。

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

- [后端说明](backend/README.md)、[前端说明](frontend/README.md)：各端开发、配置与排错。
- [API 文档](docs/api.md)、[OpenAPI 契约](openapi.json)：接口与数据字段。
- [四模式对话](docs/design/对话四模式与主线整合.md)：快速出题、创新命题、知识答疑和数据管理，包含图片及数据操作确认边界。
- [出题审核](docs/design/出题审核中间件设计与实施记录.md)：后端流式生成、滚动校验、JSON 修复与审核边界。
- [Word 导出与公式呈现](docs/design/题目Word导出与公式呈现.md)：预览页导出入口、`POST /api/export/docx`、公式转换及样式范围。
- [登录视觉恢复与历史前端对照](docs/design/登录视觉恢复与历史前端对照.md)：紧凑主卡、独立认证弹窗、登录页绑定邮箱及历史对照；保留四模式／图片／确认，Toast 恢复旧样式。最终 build／typecheck、lint（0 错误／3 条既有警告）、完整认证 e2e、59 组整合及两项会话回归均通过。历史隔离预览独立验收记录保留，5174 对照已于 2026-11-12 结束停服，目录删除受阻；真机安全区与软键盘未验证。
- [账号与权限设计](docs/design/账号系统整合与审查修复.md)、[模型配置说明](docs/design/模型配置来源与普通知识库流程.md)、[知识库说明](docs/design/知识库模块说明.md)：业务规则与能力边界。
- [运维后台系统方案说明](docs/design/运维后台系统方案说明.md)：面向方案评审与协作沟通，介绍系统目标、使用场景、功能模块和建设边界；文末列明代码实施必须参考的三份约定文档。
- [A0 与 G0 独立准备记录](docs/design/运维后台A0与G0独立准备记录.md)、[技术核验](docs/design/运维后台G0技术核验.md)：甲的源码接点盘点、固定环境、合成追踪／故障／真实删除证据及外部 SDK 交接清单；完整业务 G0 保持待验收。
- [运维后台三人实施分工方案](docs/design/运维后台三人实施分工方案.md)：本人负责前端、联调及审查，两位同事分别负责追踪／运行／质量与依赖／告警／清理调度；明确五接口归属及 G0～G3 交接。
- [运维后台运行手册](docs/design/运维后台运行手册.md)：补充 Phoenix 部署、容量保护、日常巡检、故障处理、清理验证和访问审计方案；当前为待实现手册。
- [运维后台扩展方案](docs/design/运维后台升级方案.md)：七入口保持不变，新增前端及合成交互已完成，含自监控、每题最终版本／审核范围、只读配置与排障指引；2026-11-11 历史验收不覆盖本次补全，新增前端检查及独立复审已通过。真实授权审计和后端联调待完成，五个 ops 后端接口仍待实现，G0／G1／G3 均未通过，真实追踪正文入口固定关闭。DEV 中管理员登录后可显式启用原五场景及四种访问结果模拟，默认真实，真实错误不自动转演示；旧平台资源、账号、模型与安全始终真实，生产排除 demo。配套[接口与联调契约](docs/design/运维后台接口与联调契约.md)、[模块说明](docs/design/运维后台模块说明.md)和[演示边界](STUBS.md)记录可选扩展与待 G1 边界；本次不新增后端或审计 API，不改 OpenAPI。
- [协作约定](AGENTS.md)、[领域术语](GLOSSARY.md)：开发约定与术语定义。

当前实现以 `backend/app/`、`frontend/src/` 与根 `openapi.json` 为准；设计文档中的历史记录仅供参考。

## 许可证

项目以 [Apache-2.0](LICENSE) 发布，最初从 DeepTutor 裁剪而来；第三方来源与许可证正文见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
