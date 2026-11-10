# MathCraft — 数学智能教学平台

## 上传、预览与运行恢复增量（2026-11-10，恢复已核验）

当前实现已补齐共用上传校验、多文件串行提交与草稿重试、失败详情、认证 PDF／有界文本预览、删除后当前文档缓存同步及嵌入／存储错误分类。流程见下方[题库与文档](#题库与文档)、[知识库模块说明](docs/design/知识库模块说明.md) 和[设置拆分设计](docs/design/设置拆分与保存反馈设计.md)。实际 SQL 迁移、Chroma 原路径与运行设置服务已核验；标准 build／typecheck 通过、lint 仅 3 条既有 warnings。完整后端全量基线已通过，末轮定向验证与独立审查已完成，结果见本轮增量记录；以下历史测试数字分别保留，不累计为本次结果。

本机实际 `backend/.venv` 的 Chroma **1.5.9** 因默认系统 `TEMP/TMP` 不可写触发原生 `code 14`；仅进程临时目录改为可写后恢复，未升级版本、未清库、未更换向量目录。实际库已从 `h3c4d5e6f789` 迁至 `i4d5e6f7a890`，users=3／banks=1／documents=1／chunks=0 不变、quick_check=ok；原路径 heartbeat／list 及运行 settings service 已通过，vector_store.available=true、pending=false、rebuild idle。原 PDF 仍 failed、chunks=0、原件存在，原 collection=0（旧失败发生在首次初始化，没有历史索引记录），不能写成已恢复入库。含 WAL 的备份、补充完整快照及各证据文件见[后端恢复说明](backend/README.md#本机-sqlite-备份与-chroma-临时目录恢复2026-11-10已核验)。

## 远端 main 整合（2026-11-10）

本次提交将本地账号管理、可选邮箱及人机验证开关与远端 `main` 的知识库、出题审核和通知功能合并。保留双方提交历史，普通快进推送，不重写远端历史。新建题库并上传文档的组合入口沿用教师创建权限；下载内联预览仍校验题库成员，聊天仍校验资源归属。

两侧已有 Alembic head 分别为 `f2b3c4d5e678` 和 `e3b7c1d94a62`，新增纯版本合并节点 `h3c4d5e6f789`，`down_revision` 同时引用两个 head，升级执行两侧尚未完成的迁移。该合并节点不修改业务数据、不轮换账号或密码，也不重写已有迁移标识。原有“本轮不新增字段或迁移”仅指登录/邮箱规则和人机验证开关本身，不包含此次远端分支集成。发布仍须在备份副本上完成迁移和只读审计。

OpenAPI 与 API 文档已从合并后的应用、使用隔离测试配置重新生成，覆盖 104 个 HTTP 操作。根 `uv.lock` 同步仓库级 PyJWT 和 fakeredis 依赖，后端仍使用自己的 `backend/uv.lock`。合并后的后端完整 pytest 为 304 passed、79 subtests passed、22 failed（844.09 秒），不宣称全量通过。失败快照包含 1 项新增组合上传测试的状态码期望错误，修正为既有非成员 404 隐私约定后单项复核通过；其余 21 项关联 Chroma 原生绑定或 tenant 初始化及文档入库失败链路（题库 1、对话 5、文档 7、全流程 1、出题 6、健康 1）。认证、邮箱、Turnstile、迁移及审计没有失败；文档前置失败阻断的对话权限断言不算完成。补充验证另计：资源隔离与出题审核 16 项通过；从两个已发布 head 升级到统一 head 1 项及 2 个子测试通过。Ruff 全范围保留 2 项在合并前 HEAD 已存在的诊断；Pyright 26 项（5 项因隔离目录缺少个人 local_secrets、3 项远端既有回调类型、其余 18 项既有函数或未改文件，未另跑历史基线），认证文件没有诊断。本次合并修改的后端文件定向 Ruff 通过。前端最终 typecheck、lint（0 错误、15 条既有警告）和 build 均通过；auth-session、logout-session、isolation-session、admin-panel 四个 Node 回归通过，merge-frontend-regression 四组离线浏览器检查全部通过且无 pageerror，覆盖组合上传权限、预览、通知及暂停重发。构建保留主 JS 体积提示；完整 e2e-auth 沿用前一轮已通过记录，本轮未重复执行。

账号系统状态（2026-11-09）：主体方案已实现，前端与浏览器回归已通过；公开 login/reset 挑战用户 ID 绑定修复及 127 项认证相关回归已通过，后端全量结果为 285 通过、79 个子用例通过、20 项 Chroma 相关失败。当前规则与本次检查记录见下方账号说明和设计入口。

本机登录临时调整（2026-11-09，已实现并在本机启用）：本机后端已通过启动进程环境 `APP_ENV=development`、`TURNSTILE_ENABLED=false` 重启，监听 127.0.0.1 并使用 `--no-proxy-headers`。8000 和 5173 返回 turnstile_enabled=false、available=true。新增 7 项后端针对性测试通过；前端 typecheck、lint（0 错误、15 条既有警告）、定向 ESLint、auth-session-regression、logout-session-regression 与完整 e2e-auth 均通过。真实 5173 的匿名浏览器检查确认零 Cloudflare 请求、登录按钮可用且无认证配置错误，未提交真实登录。OpenAPI/API 文档已重新生成并核对。2026-11-10 后端全量结果为 291 passed、79 subtests passed、21 failed：20 项对应本环境此前出现的 Chroma 数据库打开失败，另 1 项迁移建表子进程 30 秒超时；该迁移用例单独复跑 1 passed（7.51 秒），未修改代码，超时未再复现。Ruff 保留 10 项、Pyright 保留 19 项既有诊断，本次文件无新增。

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
├── compose.yaml                  # 本地 Redis 容器、健康检查与 AOF 数据卷
├── openapi.json                  # 当前 FastAPI 应用的 OpenAPI 契约快照
├── .env.example                  # 社区历史环境变量样例
├── backend/                      # FastAPI 后端
│   ├── app/
│   │   ├── main.py               # 应用装配、路由注册、/media 静态目录
│   │   ├── config.py             # backend/.env 配置
│   │   ├── db.py                 # SQLite engine、WAL、FTS5 建表语句
│   │   ├── deps.py               # 登录用户与权限依赖
│   │   ├── errors.py             # 统一错误响应
│   │   ├── auth_validators.py    # HTTP 与离线审计共用的纯标识校验
│   │   ├── local_secrets.py      # 硅基流动与 MinerU 密钥，已被 .gitignore 忽略
│   │   ├── local_secrets.example.py
│   │   ├── api/                  # auth、admin、banks、documents、generate、questions、
│   │   │                         # favourites、chat、spaces、papers、attempts、
│   │   │                         # urges、notifications、users 等路由
│   │   │   └── admin_rag.py      # 管理员模型设置、草稿测试与显式索引重建
│   │   ├── models/               # 业务用户与资源、认证会话及验证码消费凭证
│   │   │   └── rag_setting.py    # 平台活动／待应用配置与索引版本状态
│   │   ├── schemas/              # Pydantic 请求与响应模型
│   │   │   └── rag_settings.py   # 管理员配置、掩码响应与重建契约
│   │   └── services/
│   │       ├── rag/              # 向量、重排、HyDE、混合检索、出题与对话编排
│   │       ├── rag_settings.py   # 平台配置保存、写入门禁与索引重建切换
│   │       ├── rag_runtime.py    # 一次检索的模型与索引版本快照
│   │       ├── auth.py           # bcrypt、JWT、数据库会话与撤销
│   │       ├── auth_codes.py     # Redis 验证码、限流与 SQL 消费凭证
│   │       ├── auth_delivery.py  # SMTP 与 Turnstile 适配
│   │       ├── question_review.py # 出题审核、盲评、重复检测与修补
│   │       ├── knowledge_simplify.py # 扫描件目录驱动简化入库
│   │       ├── documents.py      # 解析、OCR、切片、入库状态机
│   │       ├── banks.py          # 题库与成员权限
│   │       ├── spaces.py         # 学习空间
│   │       ├── papers.py         # 组卷、发布、催交
│   │       ├── attempts.py       # 作答、交卷、复盘
│   │       └── grading.py        # 客观题判分与主观题 AI 批卷
│   ├── alembic/                  # 数据库迁移
│   │   └── versions/i4d5e6f7a890_platform_rag_settings.py # 平台检索配置迁移
│   ├── scripts/                  # seed、auth_migration、create_admin 与冒烟
│   │   └── init_auth_secrets.py   # 手动补齐本地认证密钥，不输出秘密值
│   ├── app/api/auth_http.py       # 认证路由共享的 Cookie HTTP 辅助函数
│   ├── tests/                    # 隔离的认证与业务接口测试
│   ├── data/                     # 运行时数据，已被 .gitignore 忽略
│   ├── alembic.ini
│   ├── pyproject.toml            # 后端独立依赖与运行配置
│   └── uv.lock
├── frontend/                     # React 19 + Vite + TypeScript + Tailwind v4
│   ├── auth-session-regression.mjs # 会话身份、认证响应及 XHR 上传重试回归
│   ├── logout-session-regression.mjs # 注销 Bearer 绑定及跨标签隔离回归
│   ├── isolation-session-regression.mjs # 跨账号、重载退出、延迟下载回归
│   ├── admin-panel-regression.mjs # 管理面板离线交互回归
│   ├── merge-frontend-regression.mjs # 主线合并后的权限、通知、预览与聊天回归
│   ├── document-upload-regression.mjs # 真实上传／列表组件、批量草稿重试与权限离线回归
│   ├── document-preview-regression.mjs # 真实文本／PDF 预览、上限分页、超时与取消离线回归
│   ├── src/api/                  # 真实接口层与字段映射
│   │   ├── adminRagSettings.ts   # 管理员检索配置契约与请求校验
│   │   ├── banks.ts             # 题库与文档映射，保留错误详情和 OCR 状态
│   │   └── documentPreview.ts   # 认证文本／PDF／下载，有界读取、超时取消及 Blob 生命周期
│   ├── src/components/           # 登录、导航、题库、出题、收藏、空间、组卷、个人中心
│   │   ├── settings/             # 应用设置仅保留模型与服务
│   │   │   └── PersonalModelSettings.tsx # 个人 DeepSeek／MinerU 凭据编辑
│   │   ├── admin/RagSettingsPanel.tsx # 系统模型编辑、Chroma 状态与重建进度
│   │   ├── ui/Toast.tsx          # 顶部居中成功／错误提示
│   │   ├── tabs/BankTab/         # 题库信息、成员、批量上传、失败详情与文档预览
│   │   │   ├── BankCreateModal.tsx # 建库草稿、首请求受理及部分成功重试
│   │   │   ├── BankEditModal.tsx # 编辑题库、上传与文档操作
│   │   │   ├── BankViewModal.tsx # 按成员权限查看、上传和文档操作
│   │   │   ├── uploadFiles.ts   # 上传格式／空文件／名称大小修改时间去重校验
│   │   │   ├── useDocUpload.ts  # 串行上传、忙时明确拒绝及逐文档受理回调
│   │   │   ├── shared.tsx       # 键盘／拖放上传区、失败详情及题库共享控件
│   │   │   ├── DocPreviewModal.tsx # MD／TXT 分页、重试、下载和请求取消
│   │   │   └── documentPreviewBlocks.ts # 文本分块分页、超长块纯文本降级
│   │   └── tabs/ProfileTab/      # 个人资料与账号安全
│   ├── src/store/                # 登录态与全局业务状态
│   │   └── ToastContext.tsx      # 普通用户与管理员共用的会话隔离提示
│   ├── src/styles/
│   ├── vite.config.ts            # /api 与 /media 代理到后端
│   └── package.json
├── docs/                         # 当前方案及社区历史设计、API 与流程资料
│   ├── design/设置拆分与保存反馈设计.md # 已实现的设置拆分、管理员配置、索引重建与保存反馈
│   ├── design/用户系统功能规格.md # 管理员开户、双入口登录与可选邮箱规则
│   ├── design/用户系统实施规格.md # 当前认证契约、实施验收与历史记录
│   ├── design/管理员与账号开通设计.md # 管理员能力、开通流程与历史决策边界
│   ├── design/Redis容器启动设计.md # 本地 Redis Compose 启停与持久化边界
│   ├── design/认证密钥本地初始化设计.md # 本地认证密钥生成、保留与失败边界
│   ├── design/账号系统整合与审查修复.md # main 整合后的认证、资源权限与验收边界
│   ├── design/模型配置来源与普通知识库流程.md # 用户凭据、部署配置与当前入库链路
│   ├── design/模型直接配置功能规格.md # 当前个人模型配置范围与验收要求
│   ├── design/模型直接配置实施记录.md # 当前实现核对与历史目录配置验收
│   ├── design/知识库模块说明.md   # 题库资料权限、状态、检索与待完成项
│   ├── design/扫描PDF云端OCR策略.md # 当前扫描识别、简化产物及失败边界
│   └── design/出题审核中间件设计与实施记录.md # 查重、盲评、修补与解析流水线
├── apps/desktop/                 # 跨端客户端预留目录
├── packages/contracts/           # 跨端契约预留目录
└── tools/                        # 仓库维护脚本
```

`backend/data/`、`.venv/`、`node_modules/`、`dist/`、`.env` 等都是本地生成物，不进入版本库。

当前 main 的账号设计与验收以 [账号系统整合与审查修复](docs/design/账号系统整合与审查修复.md) 为准，包含管理员开户、默认 account 密码登录、可选邮箱自助配置、JWT + SQL 会话及资源权限。原 [功能规格](docs/design/用户系统功能规格.md)、[实施规格](docs/design/用户系统实施规格.md) 与 [管理员设计](docs/design/管理员与账号开通设计.md) 保留来源决策，并标明与当前规则的对应关系。SMTP 缺配置时邮件流程仍不可用；Turnstile 默认启用，缺配置或验证失败仍拒绝相关操作，仅下述显式本机开发/测试开关允许跳过人机验证。

出题审核中间件的目标、流程、数据契约、异常边界与验收结果见 [出题审核中间件设计与实施记录](docs/design/出题审核中间件设计与实施记录.md)。

## 技术栈

| 层 | 选型 |
| --- | --- |
| Web 框架 | FastAPI + Uvicorn |
| ORM 与迁移 | SQLAlchemy 2.x + Alembic |
| 数据库 | SQLite，开启 WAL 与 FTS5 全文索引 |
| 会话与任务 | Redis，保存邮箱验证码、限流、出题任务、文档入库进度与对话槽位；认证会话由数据库管理 |
| 向量库 | Chroma，按题库持久化 |
| 向量模型 | 默认 `BAAI/bge-m3`（1024 维）；管理员修改模型／URL 后重建应用 |
| 重排模型 | 默认 `BAAI/bge-reranker-v2-m3`；管理员修改后用于后续请求 |
| 大模型 | DeepSeek `deepseek-flash`，OpenAI 兼容接口 |
| OCR | MinerU 云端 API，用于扫描件 |
| 前端 | React 19、Vite、TypeScript、Tailwind CSS v4 |

后端没有引入 LangChain。检索链路由项目自行实现，避免为一条固定的检索流程增加额外抽象。

## 启动方法

### 环境要求

- Python 3.11 及以上，推荐使用 uv 管理依赖。
- Node.js 18 及以上。
- Redis 7 及以上。可使用下方 Docker Compose 方案；Windows 使用 Docker Desktop 的 Linux 容器引擎，其他环境使用带 Compose v2 的 Docker。已有原生 Redis 也可继续使用。
- 可访问 DeepSeek、硅基流动与 MinerU 的网络环境。

### 1. 启动 Redis

Redis 是后端的硬依赖，邮箱验证码、限流、出题任务与文档入库进度存放在这里。默认地址为 `redis://127.0.0.1:6379/0`。

**Docker Compose：**先启动 Docker 引擎，在仓库根目录执行以下命令。Compose 默认读取根目录 `.env`；若其中的格式或 `COMPOSE_*` 配置导致报错，请检查该文件，后端配置仍放在 `backend/.env`，当前 Redis 服务不依赖其中的变量。

```powershell
docker compose config --quiet
docker compose up -d --wait redis
docker compose exec redis redis-cli ping
```

最后一条命令应返回 `PONG`。根 `compose.yaml` 只启动 Redis，使用 `redis:7-alpine`、绑定 `127.0.0.1:6379`，并将 AOF 数据保存在命名卷 `mathcraft_redis_data`。后端仍在本机运行，`backend/.env` 中保持 `REDIS_URL=redis://127.0.0.1:6379/0`；如果 6379 已被原生 Redis 占用，先停止原实例再启动容器。

日常暂停、恢复或移除容器仍在仓库根目录执行：

```powershell
docker compose stop redis
docker compose up -d --wait redis
# 移除容器与网络，保留命名卷
docker compose down
```

普通 `down` 保留数据；不要在日常停止时添加 `-v`，否则会删除命名卷。首次切换到容器不会搬迁旧 Redis 的验证码、限流和任务缓存，旧任务需按实际状态重新发起；用户、密码和认证会话保存在 SQLite，切换 Redis 不会迁移或清除这些记录。此配置仅用于本机开发。详细边界见 [Redis 容器启动设计](docs/design/Redis容器启动设计.md)。

**原生 Redis：**已有服务可直接使用，无需同时启动容器。

```powershell
# Windows 示例，在 Redis 所在目录执行
.\redis-server.exe .\redis.conf

# Linux / macOS
redis-server
```

### 2. 启动后端

```powershell
cd backend
uv sync
uv run python scripts/init_auth_secrets.py
# 缺少 .env 时脚本从 .env.example 创建；按下方配置说明补齐其余配置后再继续
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
```

本轮设置拆分与平台检索配置已实现，验证记录见文末。部署前须先备份 SQL 与 Chroma，在受控副本核对后执行上述 `alembic upgrade head`，包含从 `h3c4d5e6f789` 到新迁移 `i4d5e6f7a890` 的平台配置表升级；线上部署仍须独立完成迁移。当前索引重建依赖进程内任务和启动收尾，必须使用单 worker 进程（`--workers 1`），不承诺多 worker 或多实例协调。

SQLite 备份必须包含已提交的 WAL 数据：停止写入后保持主库与仍存在的 `-wal` 为同一快照（`-shm` 同步保存供核对），或用 SQLite backup API 生成完整快照；仅复制 `.db` 不算完整。Windows 本机 Chroma 1.5.9 遇默认 `TEMP/TMP` 不可写的 code 14 时，在受控启动进程内覆盖到可写目录，再由新进程启动，保持现有版本和数据不变。具体恢复步骤和已确认的实际迁移／运行结果见[后端 README](backend/README.md#本机-sqlite-备份与-chroma-临时目录恢复2026-11-10已核验)；存储与设置服务恢复不替代真实资料入库、管理员已认证 HTTP／UI 或全量业务验收。

本机开发使用 [backend/.env.example](backend/.env.example)，模板默认 `APP_ENV=development`、`TURNSTILE_ENABLED=false`，无需配置 Cloudflare Turnstile 即可使用账号密码登录。首次运行上面的认证密钥初始化命令会从模板创建 `backend/.env`；已有文件不会被模板覆盖，需手动将其中这两个开关改为上述值，然后按上面的回环地址启动后端。

仅在某次启动进程中设置开关，后续普通重启会丢失该覆盖，重新要求人机验证；缺少站点配置时页面显示“认证配置不可用”，登录按钮禁用。将开关保存到 `backend/.env` 后，重启后端并刷新登录页，确认 `/api/auth/config` 返回 `turnstile_enabled=false`、`available=true`。启动环境变量优先于文件，根目录 `.env.example` 是历史样例，不用于当前后端配置。生产须设 `APP_ENV=production`、`TURNSTILE_ENABLED=true`，并补齐 Turnstile 站点配置。

账号系统按 [当前整合设计](docs/design/账号系统整合与审查修复.md)实施，正式账号由管理员开通，首个管理员使用下方交互命令。开发默认账号不再硬编码：在 `backend/.env` 填写教师/学生的邮箱、学工号、密码、显示名，并显式开启 `DEV_ACCOUNTS_ENABLED`，再执行 `uv run python scripts/seed.py`。初始化只供开发环境使用，已有账号不重置密码，冲突会报错，生产禁止执行。开发登录接口返回 account、password、role，按钮仅填充 account 和密码，仍需手动登录；人机验证按当前请求的有效开关执行。开发凭据不得复用个人或生产密码。

生产部署先安装依赖，按下方「生产认证密钥生成与保存」及「生产配置清单」准备 `backend/.env`，再完成迁移审计并启动服务。开发账号初始化还要求 `APP_ENV=development`；生产必须关闭开发能力并清空全部开发角色字段。
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

浏览器访问 `http://127.0.0.1:5173`。Vite 仅绑定 `127.0.0.1`，并把 `/api` 和 `/media` 转发到 `127.0.0.1:8000`；开发账号填充入口也仅允许此本机地址。

### 4. 重新导出 OpenAPI 快照

接口变更后，在 `backend` 目录执行：

```powershell
uv run python -c "import json, sys; sys.path.insert(0,'.'); from app.main import app; open('../openapi.json','w',encoding='utf-8').write(json.dumps(app.openapi(), indent=2, ensure_ascii=False))"
```

根 `openapi.json` 必须与当前应用保持一致。

## 配置说明

后端配置由 [app/config.py](backend/app/config.py) 定义，读取固定位置的 `backend/.env`；环境变量可覆盖文件值。模板见 [backend/.env.example](backend/.env.example)，根目录 `.env.example` 是历史样例。以下默认值以当前 `Settings` 为准，空字符串表示没有可用凭据。模板中的 `APP_ENV=development`、`TURNSTILE_ENABLED=false` 和本机域名不能直接用于生产。

### 本机临时关闭与恢复 Turnstile

`TURNSTILE_ENABLED` 默认 `true`。仅当它显式为 `false`、`APP_ENV` 为 `development` 或 `test`，且请求的实际 ASGI peer 为回环 IP（如 `127.0.0.1` 或 `::1`）时，跳过 Turnstile；不以 Host、Origin 或转发头替代实际 peer。非本机 peer 仍执行完整人机验证。`APP_ENV=production` 配合 `TURNSTILE_ENABLED=false` 在启动配置校验时拒绝，不能启动。

GET `/api/auth/config` 的 `AuthConfig` 新增布尔字段 `turnstile_enabled`，表示当前请求是否需要人机验证，而非原样返回环境变量。有效值为 `false` 时，后端不调用 Cloudflare，前端不加载 Turnstile 脚本、不因缺票据或站点公钥阻止提交。POST `/api/auth/email-code` 与 `/api/auth/login/account` 的 `turnstile_token` 可缺省或传空字符串；有效值为 `true` 时仍拒绝空票据，非空票据仍须完整验证。

`Settings` 的代码默认值仍为 `true`；本机开发模板显式设为 `false`，保存到 `backend/.env` 后可跨普通重启保留。2026-11-09 曾仅向后台启动进程注入临时覆盖，2026-11-10 已将本机开发开关保存到配置文件并验证。恢复人机验证时，在 `backend/.env` 中改为 `TURNSTILE_ENABLED=true`，补齐 `TURNSTILE_SITE_KEY`、`TURNSTILE_SECRET_KEY`、`TURNSTILE_ALLOWED_HOSTNAMES`，并核对启动环境是否仍有覆盖；随后重启后端并刷新页面。运行中的后端不会自动重载配置。

该开关仅控制人机验证。账号密码校验、启用状态、JWT/SQL 会话、Origin/CSRF、邮箱验证码及其限流与消费、角色与资源归属校验继续生效；关闭后不会生成邮件码或替代 SMTP。新增配置、验证器及三角色 HTTP 针对性测试已通过，禁用时零 Cloudflare 请求、前端可提交及恢复开启流程已通过浏览器回归，当前本机服务保持临时关闭；后端全量 291 passed、79 subtests passed、21 failed（20 项 Chroma 相关失败、1 项迁移子进程超时）；迁移超时用例单独复跑通过，见下方验收说明，详见 [实施规格](docs/design/用户系统实施规格.md)。

### 生产认证密钥生成与保存

本地配置可在 `backend/` 执行上述 `uv run python scripts/init_auth_secrets.py`，手动初始化 `AUTH_JWT_SECRET` 与 `AUTH_CODE_SECRET`。脚本不接受参数，始终从脚本路径定位固定的 `backend/.env`；文件不存在时从 `backend/.env.example` 创建。在仓库根目录已有 `.venv` 依赖环境时，也可执行：

```powershell
.venv\Scripts\python.exe backend\scripts\init_auth_secrets.py
```

脚本分别使用 `secrets.token_urlsafe(48)` 生成两项独立密钥，只填缺项或空值（包括 `''`、`""`）；已有非空合法值原样保留，重复执行不改变密钥。非空值不足 32 个 UTF-8 字节、两项密钥相同、认证键重复、目标认证键的值含变量插值或 dotenv 语法错误时，脚本拒绝修改并返回非零，只给出固定脱敏错误提示。原有配置与注释保留，采用原子写入，写入失败保持原文件。详见 [认证密钥本地初始化设计](docs/design/认证密钥本地初始化设计.md)。

该脚本不打印密钥，不导入应用，不连接数据库、Redis 或网络，不生成 SMTP、Turnstile 或模型服务凭据，也不会随服务启动自动执行。运行期间不要同时用编辑器或其他程序保存 `.env`。环境变量依旧覆盖文件值，修改文件或环境配置后须重启后端。生产也可通过部署平台的秘密管理服务或经批准的密码管理器，分别生成两个独立的高熵随机秘密值（各至少 32 字节，建议 48 随机字节），通过受控秘密注入配置。不要使用终端输出、CI 日志、截图或聊天传递秘密值。

仅首次初始化且文件不存在时才从模板创建 `backend/.env`；已有配置只编辑同名项，不整份覆盖、不将命令输出重定向到 `.env`。真实 `.env` 不提交到 Git，仅限部署账号访问。同一部署的所有后端进程、实例使用同一组密钥并保持 issuer/audience 一致，不在每次启动时重新生成。SMTP 账号/授权密码及 Cloudflare Turnstile 凭据必须从各自供应商获取，不能用随机字符串伪造。

轮换 `AUTH_JWT_SECRET` 会使旧签名的访问 JWT 无法验证；轮换 `AUTH_CODE_SECRET` 会使旧邮件验证码无法通过摘要校验。刷新令牌是不透明随机凭据，其摘要及会话状态在数据库中；更换 JWT 密钥本身不必然撤销 refresh 会话，符合条件的会话仍可能刷新得到新 JWT。如需撤销既有会话，应使用现有数据库会话/认证版本撤销流程；改密、重置密码及邮箱绑定、换绑、解绑撤销全部设备，普通退出撤销当前设备。轮换时协调所有实例更新配置并重启，不混用新旧密钥。

### 生产配置清单

以下参数在 `backend/.env` 或部署环境中设置。所有有效期、次数、限额和超时必须为正数；表中的默认值不是已完成生产配置的证明。

| 配置项 | 当前默认值 | 用途与生产值来源 |
| --- | --- | --- |
| `APP_ENV` | `production`（模板为 `development`） | 部署者显式设为 `production`，启用生产约束及安全 Cookie 行为 |
| `ADMIN_CONTACT` | 联系学校或平台管理员的提示文字 | 登录页公开展示的账号获取与问题联系指引，不填写密钥或私人凭据 |
| `AUTH_JWT_SECRET` | 空 | HS256 访问 JWT 签名密钥；通过受控秘密管理工具独立生成，至少 32 字节 |
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
| `TURNSTILE_ENABLED` | `true`（本机开发模板为 `false`） | `false` 仅允许 development/test 启动，且仅实际 ASGI peer 为回环 IP 的请求跳过人机验证；非本机仍验证，production 配置 false 拒绝启动 |
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
| `DEEPSEEK_API_KEY` | 空 | 从模型服务商取得的环境兜底密钥；应用设置中的个人模型配置优先，不用于 JWT 或发码 |
| `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` / `DEEPSEEK_DISPLAY_NAME` | `https://api.deepseek.com` / `deepseek-flash` / `DeepSeek Flash` | 模型接口及默认模型信息，由供应商信息与部署约定确定 |
| `LLM_TIMEOUT_SECONDS` | `300` | 单次模型调用超时，秒；客户端内部重试已关闭，避免一次超时被放大成十几分钟 |
| `REVIEW_SIMILARITY_THRESHOLD` / `REVIEW_MAX_REGEN_ROUNDS` / `REVIEW_CORPUS_LIMIT` | `0.92` / `1` / `300` | 出题中间件的语义查重阈值、换模板重出轮数与查重语料上限；重出轮数最多两轮，默认一轮以控制等待时间 |
| `SILICONFLOW_BASE_URL` | `https://api.siliconflow.cn/v1` | 平台未覆盖时的向量与重排默认服务地址；管理员分别维护的服务 URL 优先，与认证密钥无关 |

四项存储目录的相对路径以 `backend/` 为基准，绝对路径则直接使用；生产应由部署者指定源码之外、后端进程可写的持久卷绝对路径，例如 Linux 的 `DATABASE_URL=sqlite:////srv/mathcraft/data/mathcraft.db`、`UPLOAD_DIR=/srv/mathcraft/uploads`（仅为路径示例，其余存储目录同样指定）；并安排数据库、上传、头像和索引的备份/恢复。迁移路径时显式搬迁现有数据库及目录、核对归属与索引，不能只改变量而丢弃用户数据；填写路径并不表示支持任意多实例共享 SQLite/Chroma 的部署方式。

用户个人模型设置经现有 `/api/users/me/model-settings` 保存到数据库 `UserModelSetting`，管理员开户时与用户同事务初始化；认证配置完成不代表模型调用已配置。硅基流动与 MinerU 沿用 [local_secrets.example.py](backend/app/local_secrets.example.py) 所示的既有本地凭据配置边界，凭据由相应供应商取得；真实 `backend/app/local_secrets.py` 不提交、不打印，不作为本脚本的输入或输出。检索与切片参数仍见 `backend/app/config.py`。

平台嵌入与重排覆盖经 `/api/admin/rag-settings` 保存在 SQL `rag_settings`，优先于默认模型与部署地址／凭据兜底；它们与用户个人凭据分开管理。管理员响应只含配置状态和掩码，无明文凭据；密钥留空保留已有值，首版不提供管理员清除入口。

配置文档和脚本只辅助部署准备，不表示已经配置真实服务、执行生产迁移或完成上线。迁移前先备份并在受控副本运行只读账号审计；邮箱缺失/未验证仅作信息项，不阻断发布；结构、标识冲突、角色身份及开发种子来源等独立门禁仍需处理，具体门禁见 [后端迁移说明](backend/README.md#迁移与验证)。

## 核心实现

### 账号与权限

账号由管理员开通，首个管理员由运维交互创建。登录页仅“密码登录”“邮箱登录”两种入口，默认密码登录，不选择身份；服务端识别 admin/teacher/student 并进入对应页面。密码登录沿用 POST /api/auth/login/account 的 account、password；turnstile_token 可缺省或为空，但当前请求有效启用人机验证时仍拒绝空票据。按 account 精确匹配；邮箱缺失、未验证或已验证均可用原密码登录。邮箱码登录仅已验证邮箱可用，POST /api/auth/login/email 不再接收 role。config.methods 固定顺序 account_password、email_code，turnstile_enabled 返回当前请求的有效状态。

公开注册页面、POST /api/auth/register、POST /api/auth/login/password 和发码 purpose=register 删除。学工号保留为可维护资料，不能登录。邮箱是可选个人安全配置，UserPayload 必含 email_verified；三角色均能自助绑定、换绑或解绑，管理员在管理面板自身安全区域操作。

短期访问 JWT 仅保存在前端内存；HttpOnly 刷新 Cookie 的摘要、状态和认证版本在 SQL，刷新绝对有效期默认 7 天。Redis 保存验证码、限流和任务。改密、恢复、邮箱绑定/换绑/解绑与管理员重置/禁用撤销全部旧会话；普通退出仅撤销当前设备。

教师、学生和运维管理员的权限由服务端校验；管理员不因角色取得教学资源权限。题库区分创建者、可编辑、只读，空间区分创建者与成员；用户 ID 和历史资源归属保持稳定。

### 题库与文档

仅教师可创建题库。创建者独占成员管理、库设置、转让和整库删除；可编辑成员可上传和删除文档，只读成员可查看、下载、检索和出题。创建者按账号添加成员，编号自助加入已关闭；转让只接受启用教师，原创建者转为可编辑成员。历史学生创建的题库保留数据与归属，但学生不能新建。文档支持 PDF、DOCX、XLSX、MD、TXT。

文档入库流程为解析、扫描件 OCR、切片、写入 FTS5、生成向量并写入 Chroma；进度同时写入 SQL 与 Redis，前端文档状态轮询实际读取 SQL。扫描件会调用 MinerU 云端 OCR。

新建／编辑／查看上传入口共用格式、零字节、名称+大小+修改时间去重校验，支持 `.markdown` 并显示为 MD；同名不同文件允许加入，大小限制以服务端为准。multiple 选择或虚线区拖入的全部有效文件串行提交，支持键盘和拖入高亮；批量中再次加入明确报错并禁止关闭。新建首请求拒绝保留名称与文件，部分成功保存 `bankId`、只重试尚未受理文件，全成功才关闭并显示绿色；排队受理不等于解析完成。

失败文档支持可访问展开、选择复制错误正文及阶段／OCR 状态，有编辑权限时可重新解析。MD／TXT 为严格 UTF-8 有界预览：最多 2 MiB、60 秒，每页最多 40 块／2 万字符单位，当前页公式挂载，MD 超长单块降为带提示的截断纯文本；TXT 保留原文。PDF 点击同步开窗、经认证获取 Blob 显示，PDF 和下载为 180 秒超时；DOCX／XLSX 提示不支持内联并提供下载。关闭、切换文档或注销会取消关联预览，错误可重试，主动取消不报错。

上传与重解析的 `onChanged() → refreshKbs` 同步当前题库 docs。编辑／查看弹窗删除成功后调用 `onChanged(documentId)`，BankTab 先经 `AppContext.invalidateDocument` 移除当前 docs 中的该项、清空对应选择并递增请求版本，再异步刷新；刷新失败仍保留删除后的缓存状态，请求版本与会话／题库校验阻止旧响应恢复已删项，题库消失时清空失效选择及 docs。前端缓存同步不等于服务端 OCR／Redis／派生文件已回收。

文档／题库删除在 SQL 事务内清理记录，活动向量／collection 删除成功后才 commit，最后删除当前 storage_path 文件；向量失败会 rollback，保留 SQL／文件供重试。跨存储仍非原子：向量已删而 SQL commit 失败需重新解析恢复向量，文件 unlink 失败可能留下残留。嵌入错误区分鉴权、限流、超时、连接、服务端、请求与无效响应，Chroma 按操作归类；相关安全失败详情用于入库记录，检索／删除按边界返回 503，不能把存储故障当作空库或成功。

当前完成的是题库成员权限、文档管理、混合检索及单文档出题的基础实现，既有完整后端验收仍有 Chroma／入库失败，本轮验证记录见文末。扫描件简化成功后，文档记录改为简化 MD，查看／下载跟随该产物，缺少独立原 PDF 预览入口；单文档重解析仍先删除旧切片，失败不能保证旧索引继续可用。多资料共同出题、解析版本、精确页码过滤及外部连接器／多引擎仍未形成闭环，旧设置分区已从应用设置移除。平台模型重建的版本切换边界见下节；完整说明见 [知识库模块说明](docs/design/知识库模块说明.md) 和 [扫描 PDF 策略](docs/design/扫描PDF云端OCR策略.md)。

### RAG 检索

查询优化使用 HyDE，先生成假设性文档再检索。检索采用混合策略：

1. 活动嵌入模型稠密向量召回（默认 `BAAI/bge-m3`）
2. jieba 分词后走 SQLite FTS5 BM25 稀疏召回
3. RRF 融合两路结果
4. 活动重排模型重排并截断（默认 `BAAI/bge-reranker-v2-m3`）

管理员后台采用左侧导航、右侧内容，在“模型与检索”编辑嵌入／重排的模型标识、服务 URL 和凭据；本地 Chroma 的类型、路径与状态只读。`GET/PUT /api/admin/rag-settings` 读取／保存，`POST /api/admin/rag-settings/test` 测试当前草稿但不保存，`POST /api/admin/rag-settings/rebuild` 提交显式重建并返回 `202`。保存和重建携带 `revision`，过期版本返回 `409 RAG_SETTINGS_CONFLICT`；接口入口见 [API 文档](docs/api.md)，详细字段见 [设置拆分设计](docs/design/设置拆分与保存反馈设计.md)。

嵌入模型或 URL 变更保存为 `pending`，管理员确认重建后才应用；同次提交的嵌入凭据随 pending 生效。仅更新活动嵌入凭据或重排配置供后续请求使用。重建复用活动题库中 ready 文档的 SQL chunks，无需重新解析或 OCR；期间旧库继续查询和出题，暂停上传、重解析、文档删除和整库删除（`409 RAG_REBUILD_BUSY`），已有资料入库时拒绝启动重建。全部新集合完成后一次提交切换活动配置与索引，失败保留旧版本及 pending，支持重试；重启中断标记失败后由管理员重新发起。

组合建库上传在同一 SQL 事务提交题库、成员与首文档，并与重建门禁串行化；后续后台解析仍可能失败，不承诺文件、SQL 与向量全流程原子性。启动时将 `uploaded/parsing/ocr/chunking/embedding` 文档标记 `failed`，包含排队未开始的资料，避免重启遗留状态永久阻塞重建；需人工重新解析。平台重建保留 SQL chunk ID 和 chunk_index，跨批次不重置。

### 智能出题

出题有两种入口：右侧参数面板的快速出题，以及 AI 对话框中的 Agent 出题。两者都把任务写入 Redis 并异步执行，前端轮询进度；生成结果合并到题目预览，互不覆盖。

### 组卷、作答与批卷

组卷会保存题目快照，发布到学习空间后学生才能作答。教师可以停止或恢复作答、催交、删除发布。组卷时可以选择交卷后的操作：

- 允许交卷后查看答案和解析
- 允许修改答案并重新提交

学生交卷后，客观题按标准答案判分，主观题调用 DeepSeek 评分。未允许查看解析时，交卷响应与复盘接口都不会下发答案。催交通知按时间正序展示，学生可单条已读或删除。

### 个人中心

维护昵称、性别、手机号、学校与安全资料，保存等待服务端确认；性别/手机号可清空，未填性别不默认写入。头像当前显示昵称首字，后端保留受限上传接口。普通资料更新不能直接改邮箱、学工号、身份或密码；学工号专用维护仍需当前密码，仅作为资料。

无已验证邮箱时，申请 Bearer 认证的 purpose=email_bind 码，提交 PUT /api/users/me/email-binding 的 {email,current_password,challenge_id,code}，挑战绑定用户 ID、认证版本、原邮箱快照与目标邮箱；已有已验证邮箱沿用旧、新双码换绑。DELETE /api/users/me/email 以 {current_password} 解绑，清空邮箱、规范化值、验证时间，email_verified=false。三类变更均 204、撤销全部会话并返回默认“密码登录”；管理员在自身安全区域同样可配置。

个人中心只保留个人资料与安全设置，不再显示模型编辑或状态摘要。应用设置仅保留“模型与服务”，支持保存或显式清除个人 DeepSeek Key、MinerU Token；个人连接测试仅使用服务端已保存配置及其兜底，未保存输入或写后读回失败时禁用。

个人配置保存在 `UserModelSetting`，不使用历史 `model_catalog.json` 或 `/api/settings`。出题、对话和批卷优先使用当前用户 DeepSeek Key；OCR 优先使用上传／重解析操作者的 MinerU Token，均保留部署默认兜底。向量与重排使用管理员配置的当前活动值，未覆盖时沿用部署默认，个人只读。清除个人凭据也可能继续使用系统默认。完整优先级、字段和保存／测试规则见 [模型配置来源与普通知识库流程](docs/design/模型配置来源与普通知识库流程.md)。

扫描件简化已修复：新建并上传、已有库上传、重解析在受理时解析本次操作者的有效 DeepSeek Key（个人优先、服务端兜底），显式传给后台入库及目录提取、线程池概括和补写。保留缓存复用，API 请求响应结构不变，不新增页面字段或迁移。全量后端 502 passed、81 subtests passed；既有定向 79 项、新增回归 10 项另批分别通过，独立审查未发现新增问题；完整结果及验证边界见[修复记录](docs/design/模型配置来源与普通知识库流程.md#扫描件简化个人-key-修复2026-11-10)。本机后端已重启加载修复，未自动重解析原失败文档或调用真实模型／MinerU。

模型配置、个人资料、安全操作、题库设置、管理员配置和模型连接测试共用顶部居中 toast：成功绿色约 3 秒，错误红色约 6 秒，带图标、文字、关闭按钮和辅助技术播报；字段错误仍就地显示。提示依据服务端结果，写入已确认但读回失败时明确说明已保存、状态读取失败，不把旧状态当作可继续测试的配置。

## 数据目录

按文中默认配置从 `backend/` 启动时，SQLite、上传、OCR、头像和 Chroma 数据位于 `backend/data/`：

```
data/
├── mathcraft.db          # SQLite 主库，含 FTS5 虚拟表
├── chroma/               # Chroma 向量库
├── uploads/              # 原始文档
├── ocr/                  # OCR 中间文件
└── avatars/              # 用户头像
```

该目录已被 `.gitignore` 忽略。自定义存储目录可位于源码之外，迁移时按实际配置分别备份、搬迁并核对用户和资源归属。Docker Redis 数据独立位于上述命名卷，不包含在 `backend/data/` 中；备份数据库和文件目录时需另行考虑 Redis 中未完成任务的处理。

WAL 主库与日志属于同一 SQL 备份边界，不能只备份本目录树所示 `.db` 而忽略仍存在的 `mathcraft.db-wal`；SQLite backup 完整快照可替代原始文件组。Chroma、上传、OCR 与 Redis 均不由 SQL backup 自动覆盖，恢复应保留同一业务时点的对应数据，详细步骤见后端恢复说明。

平台重建使用带 generation 后缀的新 Chroma 集合；切换成功后的旧集合及失败残留集合不会自动删除，会额外占用磁盘，需要运维清理。清理前须核对 SQL 活动 generation、在建版本及仍被在途检索快照使用的旧版本，严禁误删活动／在途索引；当前没有自动垃圾回收或管理页清理接口。

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
2. Redis 保存验证码、限流与业务任务；不可用时发码、验证码消费及相关任务失败。JWT 会话及撤销保存在 SQL，不能把 Redis 描述为当前登录凭据的存储。
3. DeepSeek、硅基流动与 MinerU 依赖外网，离线环境只能运行不涉及模型的部分。
4. 账号及 Redis 启动的当前设计入口见下表；原账号功能分支规格保留历史章节，其他社区资料仅作历史参考，不能替代当前 `backend/app/`、`frontend/src/` 与根 `openapi.json`。
5. `docs/api.md` 由 `tools/gen_api_docs.py` 按当前 OpenAPI 的全部 HTTP 操作生成；修改接口须同时更新契约及索引。

## 文档入口

| 文档 | 内容 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 协作约定、文档同步要求、密钥红线与提交规范 |
| [GLOSSARY.md](GLOSSARY.md) | 学习空间、题库、个人中心等领域术语 |
| [设置拆分与保存反馈设计](docs/design/设置拆分与保存反馈设计.md) | 已实现的设置职责拆分、管理员配置、显式重建与保存反馈；验证记录见文末 |
| [STUBS.md](STUBS.md) | 历史替身模块清单 |
| [openapi.json](openapi.json) | 当前接口契约快照 |
| [账号系统整合与审查修复](docs/design/账号系统整合与审查修复.md) | 当前 main 的认证、管理员、资源权限、迁移及验收边界 |
| [管理员与账号开通设计](docs/design/管理员与账号开通设计.md) | 管理员开通与管理能力，以及来源方案的历史边界 |
| [Redis 容器启动设计](docs/design/Redis容器启动设计.md) | 本地 Compose 的启动、数据卷、停止与实例切换 |
| [认证密钥本地初始化设计](docs/design/认证密钥本地初始化设计.md) | 手动补齐认证密钥、已有值保留、脱敏错误与原子写入边界 |
| [模型配置来源与普通知识库流程](docs/design/模型配置来源与普通知识库流程.md) | 当前用户模型凭据、部署来源、入库流程与异常边界 |
| [模型配置功能规格](docs/design/模型直接配置功能规格.md) | 个人配置范围、保存／清除／连接测试契约与验收要求 |
| [模型配置实施记录](docs/design/模型直接配置实施记录.md) | 当前实现证据及明确标注的历史直接配置记录 |
| [知识库模块说明](docs/design/知识库模块说明.md) | 当前题库资料设计、权限、完成情况与待验收能力 |
| [扫描 PDF 云端 OCR 策略](docs/design/扫描PDF云端OCR策略.md) | 扫描判定、MinerU、知识点简化与原件预览缺口 |
| [docs/](docs/) | 当前设计、API 索引及社区历史资料 |
| [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) | 第三方来源与许可证正文 |

## 本轮设置拆分验证记录（2026-11-10）

以下保留设置拆分阶段的历史结果；上传／预览／运行恢复增量的本次最终结果见下方「末轮收尾记录」，各批次不累计。

根 `.venv` 完整后端结果为 **373 passed、81 subtests passed、21 failed**，约 1002 秒；失败均关联既有 Chroma bindings 初始化／入库后续链路，完整验收未通过。已确认三组会话 Node 回归和 19 项隔离浏览器检查通过，最终前端 typecheck 通过、lint 为 0 errors 和 3 条既有 warnings；新增管理员接口与重建测试 102 passed，admin-panel-regression 与 merge-frontend-regression 两组既有浏览器回归也已通过。Ruff、Pyright 基线对比及默认构建失败／临时分包构建通过的具体边界，统一见[设置拆分设计的本轮验证记录](docs/design/设置拆分与保存反馈设计.md#验证记录)。历史批次独立保留，隔离验证不代表真实模型服务或线上迁移已经完成。

### 上传／预览／运行恢复增量（2026-11-10，已完成）

本轮完整后端全量基线（主代理提供，2026-11-10）：仓库根 `.venv` 在可写进程 `TEMP/TMP` 下运行完整 pytest，**479 passed、81 subtests passed、无失败，耗时 1329.22 秒**，日志 `pytest-full.log`。该基线早于随后追加的 Redis 排队／错误脱敏修复，不能作为这些后续修改的最终全量快照。验证记录统一采用“全量基线＋末轮定向”，末轮后端定向 81 项通过，独立审查的三项新发现均已修复并复核关闭；各批次数量不累计。

离线前端入口为 `frontend/document-upload-regression.mjs`、`frontend/document-preview-regression.mjs`，分别验证真实上传／列表组件和真实预览传输／组件；主线整合回归补核对 AppContext 当前 docs 缓存。格式／空文件／去重、多文件串行与部分失败重试、busy 保护、失败详情及权限、文本上限／分页／超时／取消、PDF 生命周期、删除后选择失效、后端错误分类和迁移恢复为本次核验范围。具体脚本边界见[前端 README](frontend/README.md#上传与预览离线回归)。

本次已确认：实际库迁移、含 WAL 备份及补充一致性快照、Chroma 1.5.9 副本假向量 add/get/query（probe 集合已清理）、原路径 heartbeat／list、运行设置服务读取。原 PDF 仍 failed、chunks=0、原件存在；无可复用活动管理员会话，未伪造或创建会话，运行 OpenAPI 已确认四个管理员检索配置操作。标准 `npm run build` 仅进程 TEMP／TMP 指向 `backend/data/tmp` 后成功，无需此前 manualChunks workaround；typecheck 通过，lint 为 0 errors、3 条既有 warnings，无新增。末轮定向验证、独立审查与其余检查均已完成，详见下方收尾记录；不推定真实模型／OCR 或管理员已认证 HTTP／UI 验收完成，也不改写历史失败数字。

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

### 历史记录｜PR #8 认证审查修复（2026-11-05）

以下是当时修复记录；其中注册及邮箱门禁等旧规则按历史阅读，本轮契约以账号说明和实施规格为准。

退出必须携带当前标签的 Bearer 和 Origin/CSRF；服务端只撤销该 sid，Cookie 仅在属于同一会话时删除，已过期但签名有效的 access 仍可用于注销；网络失败保留仅撤销用的内存凭据供重试，不假报服务端已退出。XHR 文档上传仅在明确 `ACCESS_TOKEN_EXPIRED` 时刷新重试一次，撤销或身份变化不重放。登录／找回密码发码在 SMTP 故障时仍统一 202，不激活失败验证码；注册同样统一 202；已认证换邮箱仍明确 503。迁移审计必须使用与认证相同的邮箱及学工号校验。认证响应、Cookie/CSRF 输入和统一 422 错误结构以根 `openapi.json` 为准。

### 2026-11-09 账号实施与验证

本轮完成管理员开户、默认 account 密码与可选邮箱登录，删除公开注册、学工号登录和身份选择；沿用运维管理与资源授权。历史 account、密码哈希、用户 ID 和资源保留，旧邮箱不自动验证，邮箱缺失/未验证仅为审计信息；登录与邮箱规则调整本身不新增模型或迁移，远端整合新增纯版本合并节点，见上文。

安全复核要求公开 login/reset_password 挑战绑定用途、规范化邮箱、用户 ID、认证版本，发码、邮箱登录和重置三处保持一致，修复及认证专项回归已通过。邮箱解绑后转给他人、双方版本相同时，旧码也不能作用新账号；部署后旧未消费挑战需重发，无数据库迁移。

部署前备份并按实际状态升级既有 Alembic head、执行只读审计。空间顺序加入码经既有迁移轮换，原成员和资源 ID 不变，教师需重新分享；题库由创建者按账号授权。首次管理员在 backend 目录交互执行 create_admin.py，服务器用 SSH 连接；无默认密码或密码命令行参数。已有管理员通过面板开户，初始化不覆盖历史密码和状态。

本次已通过前端 typecheck；lint 为 0 错误、15 条原有警告。build 在独立 TEMP 重试成功，首次失败为 esbuild 默认 TEMP 清理权限问题。OpenAPI 与 docs/api.md 已在测试隔离环境重新生成并核对注册/学工号登录路由删除、绑定/解绑存在、EmailLogin 无 role、UserPayload.email_verified 为必填字段。

本次已通过 auth-session-regression、logout-session-regression、isolation-session-regression、admin-panel-regression、e2e-auth 五个脚本，五个脚本 ESLint 为 0 错误、0 警告。浏览器无异常或意外外网请求；桌面与 375px 截图已完成视觉检查，产物在 output/playwright/auth-account/，包含 login-desktop/mobile 及安全区 8 张截图。本次七份文档的相对本地链接检查 missing_local_links=0。后端用户 ID 绑定修复后的 127 项认证相关测试已通过。Ruff（含 scripts）保留 11 项既有诊断、Pyright 保留 19 项既有诊断，新增诊断均为 0，本次修改文件的 Ruff 通过。后端完整 pytest 已执行：285 passed、79 subtests passed、20 failed，耗时 16 分 26 秒。20 项失败集中于文档、聊天、出题和健康检查，底层 Chroma PersistentClient 报 `InternalError: (code: 14) unable to open database file`；独立新目录初始化同样复现，无需经过认证或业务 API。扫描 PDF 用例也在扫描检测前的向量清理处中断。本次认证用例没有失败，但完整后端验收未通过，不能将本轮记录为全量通过。

完整范围、行为和验证说明见 [账号系统整合与审查修复](docs/design/账号系统整合与审查修复.md)。本次实施未执行生产数据迁移或历史邮箱自动验证。

#### 末轮收尾记录（2026-11-10）

后续补丁定向运行 `backend/tests/test_document_failure_recovery.py` 与现有文档接口测试：**81 passed**。覆盖原生 Chroma 假向量读写、Redis 进度缓存失效后仍能调度及重试、OCR／简化／兜底异常脱敏、删除失败保留 SQL 与原件、全局安全 503、下载媒体类型。此结果与前述 479 项全量基线分别记录，不相加，也不称为后续补丁的再次全量执行。

前端最终 typecheck、lint 和标准 build 通过；lint 为 **0 errors、3 条既有 warnings**，build 保留既有大包体积提示，构建进程使用可写 TEMP／TMP。预览 **23 项**、上传 **10 组**、整合 **24 组**回归通过，auth／logout／isolation 会话回归及管理员面板回归通过。整合用例包括删除立即失效、同名上传按 ID 选择、通知与上传交错、切库期间题库列表同步；题库列表和文档列表使用独立版本，待选上传 ID 由最后有效文档结果消费，手动选择、切库和删除清理旧意图。

最终 Ruff 的本轮实现及新增测试通过；全范围仍有 `backend/tests/test_banks.py:73` 的既有 F841。Pyright 为 **16 项既有诊断，无本轮新增**，没有把两项全范围静态检查记为零诊断通过。根 OpenAPI 已重新生成并核对 **108 个 HTTP 操作**，下载声明五种文件媒体类型及二进制 schema，API 索引同步生成。

两名未参与实现的独立审查员覆盖前端 20 个、后端 11 个增量文件：三项新发现（Redis 排队卡死、上传选择被通知刷新吞掉、切库丢弃全局题库列表）已修复并复核关闭，末轮无未关闭发现。OCR 异常脱敏也已独立复核。限定审查及复核记录在 `output/implementation/documents-recovery-20261110/`，备份与证据为忽略的本机运行产物，不提交。

本机后端已用最终源码、原持久化路径、可写进程 TEMP／TMP 和单 worker 再次启动，运行 OpenAPI 四项管理员配置操作及下载媒体类型一致，运行 settings service 的向量存储可用。当前没有可复用的活动管理员会话，未伪造或创建会话，因此未将真实管理员已认证 HTTP／UI 登录流程列为已验收。真实 PDF 保持 failed、chunks=0 且原件保留，由用户主动“重新解析”触发后续处理；本轮没有真实 OCR、嵌入或付费模型验收，也没有清库或升级 Chroma。
