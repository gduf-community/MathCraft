# MathCraft 后端

> 2026-11-10 实际 SQL 迁移、Chroma 原路径与运行设置服务已核验，完整后端全量基线已通过，后续修复的末轮定向验证与独立审查也已完成。本机 Chroma 1.5.9 的 code 14 通过仅覆盖进程可写 `TEMP/TMP` 解决，未升级或清库；原 PDF 仍 failed、chunks=0，不能将存储恢复写成资料入库成功。下文旧测试数字属于历史批次，保留且不累计。

## 远端 main 整合（2026-11-10）

本次提交将本地账号管理、可选邮箱及人机验证开关与远端 `main` 的知识库、出题审核和通知功能合并。保留双方提交历史，普通快进推送，不重写远端历史。新建题库并上传文档的组合入口沿用教师创建权限；下载内联预览仍校验题库成员，聊天仍校验资源归属。

两侧已有 Alembic head 分别为 `f2b3c4d5e678` 和 `e3b7c1d94a62`，新增纯版本合并节点 `h3c4d5e6f789`，`down_revision` 同时引用两个 head，升级执行两侧尚未完成的迁移。该合并节点不修改业务数据、不轮换账号或密码，也不重写已有迁移标识。原有“本轮不新增字段或迁移”仅指登录/邮箱规则和人机验证开关本身，不包含此次远端分支集成。发布仍须在备份副本上完成迁移和只读审计。

OpenAPI 与 API 文档已从合并后的应用、使用隔离测试配置重新生成，覆盖 104 个 HTTP 操作。根 `uv.lock` 同步仓库级 PyJWT 和 fakeredis 依赖，后端仍使用自己的 `backend/uv.lock`。合并后的后端完整 pytest 为 304 passed、79 subtests passed、22 failed（844.09 秒），不宣称全量通过。失败快照包含 1 项新增组合上传测试的状态码期望错误，修正为既有非成员 404 隐私约定后单项复核通过；其余 21 项关联 Chroma 原生绑定或 tenant 初始化及文档入库失败链路（题库 1、对话 5、文档 7、全流程 1、出题 6、健康 1）。认证、邮箱、Turnstile、迁移及审计没有失败；文档前置失败阻断的对话权限断言不算完成。补充验证另计：资源隔离与出题审核 16 项通过；从两个已发布 head 升级到统一 head 1 项及 2 个子测试通过。Ruff 全范围保留 2 项在合并前 HEAD 已存在的诊断；Pyright 26 项（5 项因隔离目录缺少个人 local_secrets、3 项远端既有回调类型、其余 18 项既有函数或未改文件，未另跑历史基线），认证文件没有诊断。本次合并修改的后端文件定向 Ruff 通过。前端最终 typecheck、lint（0 错误、15 条既有警告）和 build 均通过；auth-session、logout-session、isolation-session、admin-panel 四个 Node 回归通过，merge-frontend-regression 四组离线浏览器检查全部通过且无 pageerror，覆盖组合上传权限、预览、通知及暂停重发。构建保留主 JS 体积提示；完整 e2e-auth 沿用前一轮已通过记录，本轮未重复执行。

当前后端以 `app.main:app` 为入口，使用 FastAPI、SQLAlchemy、Alembic、SQLite、Redis 与 Chroma。历史 `/api/kb`、Ollama 和单租户入口不代表当前实现。

## 模型配置与知识库说明（2026-11-10）

设置拆分与平台检索配置已实现，验证记录见文末。普通应用设置仅保留“模型与服务”，个人中心仅保留资料与安全。个人模型配置通过 `/api/users/me/model-settings` 保存在 `UserModelSetting`，只支持 DeepSeek Key 与 MinerU Token。出题／对话／批卷的 Key 优先取当前用户，OCR Token 优先取上传／重解析操作者，均保留部署默认兜底；向量与重排读取管理员平台活动配置，未覆盖时沿用部署默认，个人只读。清除个人凭据后仍可能使用系统默认；没有当前多提供方 catalog 或逐库模型绑定接口。

扫描件简化已接入个人 Key：新建并上传、已有库上传和重解析在受理时按本次操作者解析有效 DeepSeek Key（个人优先、服务端兜底），传入 `run_ingestion`，再显式传入 `knowledge_simplify` 的目录提取、线程池概括与补写。保留缓存复用及 API 请求响应结构，不新增页面字段或数据库迁移。全量后端 502 passed、81 subtests passed；既有定向 79 项、新增回归 10 项另批分别通过，独立审查未发现新增问题；完整结果及验证边界见[修复记录](../docs/design/模型配置来源与普通知识库流程.md#扫描件简化个人-key-修复2026-11-10)。本机后端已重启，未自动重解析原失败文档，未调用真实模型或 MinerU 服务。

管理员后台以左侧导航切换、右侧展示“模型与检索”等内容，可分别编辑嵌入与重排的模型标识、HTTP(S) 服务 URL、凭据，Chroma 类型、路径与 heartbeat 状态只读。`RagSetting` 单行保存活动／待应用配置、generation、重建进度与 revision；未覆盖时沿用默认模型、部署地址和既有凭据兜底。响应仅返回凭据状态与掩码，不含明文；省略、null、空串或纯空白保留已有凭据，无管理员清除接口。

| 管理员接口 | 行为 |
| --- | --- |
| `GET /api/admin/rag-settings` | 读取 `active/pending/vector_store/rebuild/revision` |
| `PUT /api/admin/rag-settings` | 携带 revision 保存模型、URL 与可选凭据，200 返回最新状态；过期版本为 `409 RAG_SETTINGS_CONFLICT` |
| `POST /api/admin/rag-settings/test` | 测试 embedding／rerank 当前草稿及相应已保存凭据／兜底，不保存，错误脱敏 |
| `POST /api/admin/rag-settings/rebuild` | 携带 revision 显式提交待应用配置的重建，返回 202；任务终态须继续读取 |

嵌入模型或 URL 变更仅保存为 pending，同次输入的嵌入凭据跟随 pending；管理员确认重建后才应用。仅更新活动嵌入凭据或重排模型／URL／凭据对后续请求生效。重建使用活动题库中 ready 文档的 SQL chunks，无需重新解析或 OCR，写入新 generation 集合；旧库继续查询和出题，上传、重解析、文档删除、整库删除及配置写入暂停（409 `RAG_REBUILD_BUSY`）。有未完成资料入库时拒绝重建（409 `RAG_INGESTION_BUSY`）。全部成功后一次提交活动配置与索引指针，失败保留旧版本与 pending 供重试；在途检索沿用已固定快照。

知识库资料由 `/api/banks` 及其 documents／search 接口管理。教师创建，创建者／可编辑／只读三档授权；只读成员可检索和出题，资料权限不共享个人记录或凭据。组合建库上传通过 `create_bank(commit=False)`，由 `queue_upload` 同一 SQL 事务提交题库、成员和首文档，并与重建门禁串行化；文件写入与后续后台入库不构成跨存储全流程事务。扫描件简化 MD 替换当前文档记录、单文档重解析先删旧切片、进程内后台任务中断、多资料和解析版本缺口仍需按实际边界理解，平台模型重建的回退不等于单文档重解析也可回退。既有完整验收仍受上述 Chroma／入库失败阻塞，本轮验证记录见文末。

配置优先级、接口和流程见 [模型配置来源与普通知识库流程](../docs/design/模型配置来源与普通知识库流程.md)；设置拆分、保存／生效、错误、迁移和验收标准见 [设置拆分与保存反馈设计](../docs/design/设置拆分与保存反馈设计.md)。领域模型、权限、完成情况及验收见 [知识库模块说明](../docs/design/知识库模块说明.md) 和 [扫描 PDF 策略](../docs/design/扫描PDF云端OCR策略.md)，HTTP 入口见 [API 文档](../docs/api.md)。早期直接模型目录的通过记录仅作历史证据。

## 文档入库、重解析与错误边界增量

上传支持 `.pdf/.docx/.xlsx/.md/.markdown/.txt`，由 `queue_upload` 校验扩展名、空内容和 `settings.max_upload_mb`（默认 200 MiB）；不支持格式／空文件为 400 `UNSUPPORTED_FORMAT/EMPTY_FILE`，超限为 422 `DOCUMENT_TOO_LARGE`。组合建库上传仍在同一 SQL 事务提交题库、成员及首文档。前端一次选择／拖放多个文件是串行发出单文件请求；首请求拒绝保草稿，部分成功保留 `bankId`、只重试未受理文件，不新增后端批量或哈希去重接口。

重解析调用 `requeue_document`：可找到简化稿对应原 PDF 时恢复文件属性，并将 SQL／Redis 状态重置为 uploaded／0，清空旧错误、OCR 状态／任务引用、切片数量、页数、扫描与文本来源字段；磁盘 OCR 缓存仍可复用。入库先执行向量清理，再清理 SQL chunks／FTS；向量清理失败时保留尚未清理的 SQL／FTS。清理已成功后再遇解析／OCR／嵌入错误，不承诺旧索引回滚。

| 边界 | 当前行为 |
| --- | --- |
| 嵌入请求 | `EmbeddingError` 分类为 authentication、rate_limit、timeout、connection、server、request、invalid_response；检查 HTTP、响应数量／下标、有限数值及维度一致性，以安全中文错误代替上游响应正文 |
| Chroma | `VectorStoreError` 按 init、access、write、query、read、delete、health 归类；仅原生 NotFound 表示集合不存在，其他错误上抛，不将写／删失败静默当作成功。日志仅记操作／类型／数值原生码 |
| 检索与删除 | 文档路由捕获存储故障返回 503 `VECTOR_STORE_UNAVAILABLE`；检索直接暴露的嵌入异常为 503 `EMBEDDING_UNAVAILABLE`，混合检索内部降级按现有实现。后台入库将嵌入／向量存储的安全失败消息写入 `error_message` |
| 下载／预览 | `/download` 返回当前 storage_path，PDF 为 application/pdf、MD／TXT 为 UTF-8 text/plain，Office 返回各自媒体类型。2 MiB 文本上限、40 块／2 万字符分页、60 秒文本／180 秒 PDF 与下载超时均为前端预览边界，不是后台上传／OCR 限制 |
| 删除事务 | `purge_document/purge_bank` 在 SQL 事务内执行清理，活动向量／collection 删除成功后才 commit，最后删除当前 storage_path 文件。向量失败 rollback，保留 SQL／文件供重试；向量成功后 commit 失败仍需重新解析恢复向量，unlink 失败可能遗留文件。跨存储仍非原子，不保证回收 OCR／Redis／全部派生文件 |
| 删除后前端缓存 | 编辑／查看弹窗删除成功后调用 `onChanged(documentId)`，BankTab 先经 `invalidateDocument` 移除当前 docs 中的文档、清空对应选择并递增请求版本，再异步刷新题库／docs；刷新失败或删除前的旧请求不能恢复已删除项。上传／重新解析仍通过 `onChanged()` 刷新 |

文档失败详情仍通过现有列表／状态接口的 `error_message/stage/ocr_status` 返回，前端可展开并选择复制；只读成员无重解析权限，creator/editor 重新排队仍返回 202。完整实现与异常边界见 [知识库模块说明](../docs/design/知识库模块说明.md#5-上传解析存储与进度)。

末轮修复中，`_set_stage` 已在提交 SQL 后捕获 Redis 进度写入的 `RedisError`，只记录异常类型及 `PROGRESS_CACHE_UNAVAILABLE`，缓存故障不再阻断后续调度／处理；排队边界四项定向验证通过。OCR／未知异常已采用结构化分类和固定安全文案，脱敏及重试回归通过，不能计入此前全量基线。进程内 BackgroundTasks 仍不是持久化队列。

## 模块结构

```text
backend/
├── app/
│   ├── main.py              # 应用装配与路由注册
│   ├── auth_validators.py   # HTTP 与离线审计共用的纯标识校验
│   ├── config.py            # backend/.env 配置
│   ├── db.py                # SQLite WAL、SQLAlchemy 会话和 FTS
│   ├── deps.py              # 登录用户及角色依赖
│   ├── api/                 # auth/admin/users、题库/文档、出题/空间/试卷等
│   │   └── admin_rag.py     # 管理员配置读写、草稿测试与显式重建
│   ├── models/              # 业务数据与认证会话/消费凭证
│   │   └── rag_setting.py   # 平台活动／待应用配置及索引版本
│   ├── schemas/             # 请求、响应与外部契约
│   │   └── rag_settings.py  # 管理员配置、凭据掩码与重建契约
│   └── services/
│       ├── auth.py          # 密码、JWT、数据库会话、刷新与撤销
│       ├── auth_codes.py    # 验证码、限流和数据库消费凭证
│       ├── auth_delivery.py # SMTP 与 Turnstile 边界
│       ├── rag_settings.py  # 平台配置、写入门禁与重建切换
│       ├── rag_runtime.py   # 模型与索引版本快照
│       └── rag/             # 向量、检索、出题及对话编排
├── alembic/                 # 数据库版本迁移
│   └── versions/i4d5e6f7a890_platform_rag_settings.py # 平台检索配置表
├── scripts/                 # 开发初始化与只读迁移审计
│   └── init_auth_secrets.py  # 手动补齐本地认证密钥，不输出秘密值
├── tests/                   # HTTP、事务、迁移与命令测试
├── .env.example             # 空凭据配置模板
├── pyproject.toml
└── uv.lock
```

## 启动与配置

先启动 Redis。在仓库根目录执行本地 Docker Compose 命令，确认最后返回 `PONG` 后再进入 `backend/`：

Compose 默认读取根目录 `.env`；若其中的格式或 `COMPOSE_*` 配置导致报错，请检查该文件，后端配置仍放在 `backend/.env`，当前 Redis 服务不依赖其中的变量。

```powershell
docker compose up -d --wait redis
docker compose exec redis redis-cli ping
```

Docker 引擎须已启动，6379 端口须空闲；默认 `REDIS_URL=redis://127.0.0.1:6379/0`。日常在仓库根执行 `docker compose stop redis` 暂停，`docker compose up -d --wait redis` 恢复；`docker compose down` 移除容器与网络但保留 AOF 命名卷，不添加 `-v`。已有原生 Redis 可继续使用，同一时间只运行一个占用 6379 的实例。完整命令及切换边界见 [根 README](../README.md#1-启动-redis) 与 [Redis 容器设计](../docs/design/Redis容器启动设计.md)。

```powershell
cd backend
uv sync
uv run python scripts/init_auth_secrets.py
# 缺少 .env 时脚本从 .env.example 创建；按根 README 配置清单补齐其余配置后再继续
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
```

部署前必须执行 `uv run alembic upgrade head`，包含 `h3c4d5e6f789 → i4d5e6f7a890`：创建 `rag_settings` 并初始化单行，空覆盖和空 generation 沿用原 `kb_*` 集合，不复制本地秘密。先备份 SQL 与 Chroma 并在受控副本核对；线上部署仍须独立完成迁移。当前必须保持单 worker 进程（`--workers 1`），重建使用进程内 BackgroundTasks，启动时将中断的 queued／running 标记 failed，保留旧活动版本和 pending，由管理员重试，不自动续跑。

启动收尾也包含 uploaded/parsing/ocr/chunking/embedding 文档，将其标记 failed 后由用户重新解析，避免排队资料永久阻塞平台重建；SQL 收尾不等于重写 Redis。重建向量保留已有 SQL chunk ID、chunk_index、章节与类型，跨批次不重置 chunk_index。

旧索引和失败重建的部分集合均保留并额外占用磁盘，当前无自动回收／清理接口，需要运维清理。清理前必须核对活动 generation、在建 generation 及仍被在途检索快照使用的旧集合，禁止误删活动／在途索引。已切换 generation 或正在重建时迁移 downgrade 会拒绝，须先恢复兼容旧模型与索引。

配置以 [app/config.py](app/config.py) 和 [.env.example](.env.example) 为准，环境变量可覆盖固定位置的 `backend/.env`。完整字段、默认值、用途和获取来源集中在根 [生产配置清单](../README.md#生产配置清单) 与 [数据、缓存与模型配置](../README.md#数据缓存与模型配置)，部署时逐项填写。`config.py` 默认 `APP_ENV=production`，模板则为 `development`；生产须显式设为 `production`，`DEV_ACCOUNTS_ENABLED=false`，并清空教师/学生各自的 `EMAIL`、`USER_NO`、`PASSWORD`、`DISPLAY_NAME` 八个开发字段。Redis 存储验证码、限流和业务任务；认证会话在数据库中。缺少必要配置时相关认证操作拒绝或返回不可用。真实配置、数据库和上传文件不入库。

### 本机 SQLite 备份与 Chroma 临时目录恢复（2026-11-10，已核验）

迁移或恢复前先停止后端及其他 SQL 写入者，确认实际数据库／上传／OCR／Chroma 位置，并完整备份。SQLite 为 WAL 模式：不能只复制 `.db` 而漏掉未 checkpoint 的已提交数据。文件级备份须保证同一快照，包含主库和仍存在的 `-wal`，同步保存 `-shm` 供核对；也可通过 SQLite backup API 生成已包含提交 WAL 内容的完整快照。恢复、迁移副本和原库不得混用不同时点的文件。Chroma 与上传／OCR 目录另行保护，不能把 SQL 备份当作所有存储的完整备份。

本次排查使用实际 `backend/.venv` 的 Chroma **1.5.9**。默认系统 `TEMP/TMP` 所指目录不可写时，原生 PersistentClient 报 `code 14`；换新建、相对或 POSIX 格式的 Chroma 路径仍复现。仅将启动该 Python 进程的 `TEMP/TMP` 改成可写目录后，原生 probe 已成功。这不是需要升级版本、重置 Chroma、清空数据库或更换向量存储目录的证据。

下列为以后受控启动时的进程环境示例；本次文档同步不执行命令、不修改真实 `.env` 或全局用户／系统环境。先完成备份和已批准的实际库迁移，再在 `backend/` 启动；新启动终端或服务进程须重新显式设置此覆盖，服务账号须对所选目录有写权限：

```powershell
$mathcraftTemp = Join-Path $env:LOCALAPPDATA 'MathCraft\Temp'
New-Item -ItemType Directory -Path $mathcraftTemp -Force | Out-Null
$env:TEMP = $mathcraftTemp
$env:TMP = $mathcraftTemp
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
```

仅修改父 PowerShell 进程及其后续子进程环境；已经运行的 Python 不会自动取得覆盖，必须按恢复方案启动新进程。不在此更改锁文件、Chroma 版本、`CHROMA_DIR` 或删除旧索引；此前 esbuild 的 TEMP 清理权限记录属于另一历史构建问题，不与本次原生 Chroma 诊断混为同一验收结果。

以下为主代理已确认的实际恢复结果。证据目录为仓库根 `output/implementation/documents-recovery-20261110/`；该目录含运行材料，不作为源码提交，本文仅记录必要汇总，不读取或披露真实配置、凭据和用户内容。

| 证据／环节 | 已确认结果与边界 |
| --- | --- |
| `backup-20261110-155735/` | 备份包含 WAL，另补充迁移前 SQLite backup 完整快照 `consistent-before-migration.db`；副本迁移已通过，实际迁移另有独立记录 |
| `migration-actual.json` | 实际库从 `h3c4d5e6f789` 升至 `i4d5e6f7a890`；users=3、banks=1、documents=1、chunks=0 均保持不变，`quick_check=ok` |
| `chroma-copy-verified.json` | 原副本 collections=[]、records=0；原生 Chroma 1.5.9 使用假向量完成 add/get/query 验证，随后清理 probe 集合，不接入真实嵌入服务 |
| `chroma-actual-verified.json` | 实际原路径 heartbeat／list 成功、collection=0。旧失败发生在首次初始化，没有历史索引记录；未清空或迁移旧集合来取得成功 |
| `runtime-verified.json` | 实际 settings service 读取成功，`vector_store.available=true`、`pending=false`、`rebuild=idle`；原 PDF 仍 `failed`、chunks=0、原件存在。存储恢复没有自动重新解析或补齐资料索引 |
| 管理员会话与契约 | 当前无可复用的活动管理员会话，未伪造或创建会话。运行实例 OpenAPI 已确认管理员检索配置 GET／PUT、草稿测试 POST、重建 POST 四个操作；契约存在不等于管理员已认证 HTTP／UI 验收完成 |

恢复保持现有版本、原数据与向量路径，仅覆盖启动进程的可写临时目录。实际迁移、原生存储及运行设置服务检查已完成；真实模型／OCR、原失败 PDF 的重解析和全量业务验收不在上述成功结论内。完整后端全量基线已通过，后续修复的末轮定向验证与独立审查由主代理补充最终结果，本文不据恢复证据改写历史失败数字。

### 本机 Turnstile 临时开关与恢复（2026-11-09，已实现并在本机启用）

`TURNSTILE_ENABLED` 的代码默认值为 `true`；[.env.example](.env.example) 面向本机开发，显式设为 `false` 并配合 `APP_ENV=development`。首次初始化从模板创建 `backend/.env`，已有配置需手动编辑这两项，初始化命令不会覆盖它们。仅配置为 `false`、`APP_ENV` 属于 `development/test`，且请求实际 ASGI peer 为回环 IP（如 `127.0.0.1` 或 `::1`）时跳过人机验证；不信任 Host、Origin 或转发头来扩展该范围。非本机 peer 即使在该配置下仍执行完整 Turnstile。production 必须设为 `true` 并补齐真实站点配置，配置 `false` 时在启动校验阶段拒绝，不能启动。

`AuthConfig.turnstile_enabled` 为必填 boolean，由 GET `/api/auth/config` 按当前请求计算有效值。有效值为 `false` 时不调用 Cloudflare；有效值为 `true` 时保留票据、站点配置、action、hostname 等完整验证，空票据仍拒绝。`POST /api/auth/email-code` 与 `POST /api/auth/login/account` 的 `turnstile_token` 可缺省或为空字符串，但仅有效禁用请求可跳过其验证。前端据有效状态决定脚本加载与提交条件。

2026-11-09 曾仅以启动进程环境 `TURNSTILE_ENABLED=false` 临时重启本机后端；该覆盖不会随普通重启保留。2026-11-10 排查确认本机重启后回到 `APP_ENV=production`、`TURNSTILE_ENABLED=true`，且未配置 Turnstile 站点，导致认证配置不可用、密码登录按钮禁用。本次将 `APP_ENV=development`、`TURNSTILE_ENABLED=false` 保存到已被 Git 忽略的本机 `backend/.env`，继续绑定回环地址并使用 `--no-proxy-headers`。需要恢复人机验证时，将本机配置改为 `TURNSTILE_ENABLED=true` 并补齐站点配置；配置变更后重启后端并刷新页面。环境变量仍优先于文件，须同时核对启动环境中的覆盖值。

账号密码、JWT/SQL 会话及撤销、Origin/CSRF、邮箱验证码、限流、proof 消费、角色与资源权限保留，SMTP 不可用仍不能完成邮件流程。新增 7 项后端针对性测试、前端检查及完整浏览器回归已通过；本机关闭已确认生效，后端全量 291 passed、79 subtests passed、21 failed（20 项 Chroma 相关失败、1 项迁移子进程超时）；迁移超时用例单独复跑通过，见下方验收说明。本轮验收完成于 2026-11-10；迁移用例复跑耗时 7.51 秒，未修改代码。Ruff 10 项、Pyright 19 项既有诊断，本次文件无新增。本文其他原有数量保留为开关调整前记录。验收矩阵见 [实施规格](../docs/design/用户系统实施规格.md)。

### 认证密钥本地初始化与保存

安装依赖后手动执行 `uv run python scripts/init_auth_secrets.py`，再迁移数据库并启动后端。脚本不接受参数，从脚本路径定位固定的 `backend/.env`，不随执行目录变化；缺少文件时从 `backend/.env.example` 创建。在仓库根目录已有 `.venv` 依赖环境时，也可执行：

```powershell
.venv\Scripts\python.exe backend\scripts\init_auth_secrets.py
```

脚本分别用 `secrets.token_urlsafe(48)` 生成 `AUTH_JWT_SECRET` 与 `AUTH_CODE_SECRET`，只填缺项或空值（包括 `''`、`""`）；已有非空合法值保留，重复执行不变。非空值不足 32 个 UTF-8 字节、两项密钥相同、认证键重复、目标认证键的值含变量插值或 dotenv 语法错误时，拒绝修改并返回非零，只输出固定脱敏错误提示。原有配置与注释保留，采用原子写入，写入失败保持原文件。完整契约见 [认证密钥本地初始化设计](../docs/design/认证密钥本地初始化设计.md)。

脚本不打印密钥，不导入应用，不连接数据库、Redis 或网络，不生成 SMTP、Turnstile 或模型服务凭据，也不会随服务启动自动执行。运行期间不要同时用编辑器或其他程序保存 `.env`。环境变量仍覆盖文件值，修改配置后须重启后端。生产也可通过部署平台的秘密管理服务或经批准的密码管理器，独立生成两项高熵密钥（各至少 32 字节，建议 48 随机字节），使用受控秘密注入配置。避免秘密值进入 stdout、CI/共享日志、截图或聊天；真实 `backend/.env` 不提交，并限制为部署账号可访问。SMTP、Cloudflare Turnstile 与模型凭据须从各自服务商获取。

同一部署所有后端进程与实例保持相同密钥和 issuer/audience，不要每次启动重新生成。轮换 JWT 密钥使旧访问 JWT 验签失败，轮换验证码密钥使旧邮件码校验失败；数据库中刷新会话的摘要、状态与用户认证版本独立管理，不能把换 JWT 密钥视为必然撤销 refresh。需要撤销时使用现有会话撤销流程。详见根 [密钥生成与轮换说明](../README.md#生产认证密钥生成与保存)。

生产 `CORS_ORIGINS` 使用精确 HTTPS Origin，例如 `https://learn.example.com`；`TURNSTILE_ALLOWED_HOSTNAMES` 对应填写 `learn.example.com`，与 Cloudflare widget 的 hostname 配置一致。前者包含协议及必要端口，后者不含协议、端口或路径；二者都不是 URL 路径白名单。

SQLite 默认相对文件路径按启动工作目录解析，从本目录启动对应 `backend/data/mathcraft.db`；`CHROMA_DIR`、`UPLOAD_DIR`、`OCR_DIR`、`AVATAR_DIR` 的相对路径以 `backend/` 为基准。生产改用部署者提供的持久卷绝对路径和受控 `REDIS_URL`，保留既有用户、模型设置、上传及索引的迁移与备份。个人模型配置经 `/api/users/me/model-settings` 保存在 `UserModelSetting`，优先于环境兜底模型密钥；认证脚本不生成模型服务凭据。本文说明部署准备，不代表已配置真实服务、执行生产迁移或完成上线。

开发账号仅在 `APP_ENV=development` 且 `DEV_ACCOUNTS_ENABLED=true` 时显式运行 `uv run python scripts/seed.py`；教师与学生配置均需完整，重复执行不改已有密码、角色及归属。开发凭据接口只用于受控本机环境，前端按钮仅填充；生产禁止此能力及开发凭据配置。

## 认证与接口

状态（2026-11-09）：方案已实现，前端、浏览器、契约与 127 项认证相关回归已通过；完整后端验收受 Chroma 初始化失败阻塞，详见实施规格。

账号由管理员开通，首个管理员用 create_admin.py 交互创建；公开注册、学工号登录及 purpose=register 删除。登录页仅“密码登录”“邮箱登录”，默认密码模式，无身份选择；服务端识别 admin/teacher/student。POST /api/auth/login/account 继续接收 {account,password,turnstile_token}，其中 turnstile_token 可缺省或为空，有效启用时仍拒绝空票据；按 account 精确匹配，邮箱缺失/未验证/已验证均可密码登录。POST /api/auth/login/email 接收 {email,challenge_id,code}，无 role，仅已验证邮箱可用。GET /api/auth/config 的 methods 为 [account_password,email_code]，新增请求级布尔字段 turnstile_enabled；开发填充返回 account、password、role，role 仅选样例，填充 account。

UserPayload 新增必填布尔字段 email_verified，沿用既有模型，无新增数据库迁移。学工号及 PUT /api/users/me/user-no 继续作为资料维护，需当前密码；普通资料不能改邮箱、学工号或身份。

| 邮箱安全接口 | 请求与前置条件 | 结果 |
| --- | --- | --- |
| POST /api/auth/email-code | email、purpose=email_bind；turnstile_token 可缺省或为空，有效启用时仍需有效票据；需 Bearer，仅无已验证邮箱；绑定 user_id、auth_version、原邮箱快照与目标邮箱 | 同步投递，成功 202，失败 503；失败不清限额 |
| PUT /api/users/me/email-binding | Bearer；{email,current_password,challenge_id,code}；仅无已验证邮箱，含历史未验证邮箱 | 当前密码、专用 proof、版本/快照和唯一性通过后绑定，204 |
| POST /api/users/me/email-change；PUT /api/users/me/email | Bearer；沿用已验证旧邮箱与新邮箱双码契约 | 双 proof、事务快照和版本复核，换绑 204 |
| DELETE /api/users/me/email | Bearer；JSON {current_password} | 清空 email/email_normalized/email_verified_at，email_verified=false，204 |

三类邮箱变更均同事务递增认证版本、撤销全部会话，清目标用户 Cookie，返回默认密码登录页，不自动创建会话。错误密码、邮箱冲突、错码/过期/重放、跨用户/用途、版本或原邮箱快照变化不改邮箱。管理员在管理面板自身安全区域使用同一自助契约，不替其他用户操作。

公开 login/reset_password 发码在有效启用时经 Turnstile、始终经限流后统一 202、响应后投递；失败不激活码，202 不表示送达。安全复核正在补齐挑战绑定：用途＋规范化邮箱＋用户 ID＋认证版本，发码/邮箱登录/重置三处一致。邮箱解绑转给他人、相同版本下旧 login/reset 码不得作用新账号；部署后旧未消费挑战需重发，无数据库迁移。绑定/换绑仍为已认证同步投递，失败 503。

Access 仅驻留前端内存，刷新凭据由 HttpOnly Cookie 管理，摘要与撤销状态在 SQL。refresh/logout 校验可信 Origin、JSON、CSRF；普通退出按 Bearer 的 sid 仅撤销当前设备。改密、重置、邮箱变更及管理员重置/禁用撤销全部旧会话。浏览器跨标签锁与目标用户 Cookie 清理沿用。

完整接口见根 [openapi.json](../openapi.json) 与 [API 索引](../docs/api.md)，业务、契约与验收见 [整合设计](../docs/design/账号系统整合与审查修复.md)、[功能规格](../docs/design/用户系统功能规格.md)、[实施规格](../docs/design/用户系统实施规格.md)。旧 create_user.py 固定退出 2，不解析凭据或访问数据库；开发 seed 只限 development＋显式开关，生产不初始化开发账号。

## 迁移与验证

迁移前先备份，将该进程的 `DATABASE_URL` 显式指向受控副本并确认路径，再执行 `uv run alembic upgrade head`，随后审计升级后的同一副本；确认通过后在维护窗口升级目标库并复核。不要让副本验收命令继续使用目标库地址。审计会检查当前 head 及实际结构，未升级的副本不能通过。脚本路径参数使用实际受控副本路径：

```powershell
uv run python scripts/auth_migration.py audit --operator-confirmed --database <受控副本路径>
```

该命令不修复数据，不输出邮箱或密码。邮箱缺失/未验证仅为信息项，不阻断发布或启用账号的 account 密码登录；禁用状态仍阻断登录。缺失认证表/列/约束、错误 head、重复标识、角色身份、规范化异常和开发种子来源等独立门禁继续生效。保留历史 account、密码哈希、用户 ID 和资源归属，不合并、认领或自动验证旧邮箱；此前认证调整未新增模型迁移，旧 Redis token 不再接受。本轮平台配置新增 `i4d5e6f7a890`，部署要求以上述启动说明为准，验证记录见文末。

后端测试使用每测试独立 fakeredis 和临时 SQLite，SMTP、Turnstile、模型均为假服务，不连接或清空本机 Redis：

```powershell
uv run pytest -q
uv run ruff check app tests
```

本次前端与浏览器检查已通过，后端用户 ID 绑定修复及 127 项相关回归已通过，完整 pytest 为 285 通过、79 个子用例通过、20 项 Chroma 相关失败；实施规格区分本轮验证和历史数量。不要为运行测试读取个人 `.env` 或 `app/local_secrets.py`。

### 历史记录｜PR #8 安全与契约修复

以下保留当时修复背景，其中注册与邮箱审计门禁按历史阅读，以本轮认证和迁移规则为准。

- `/api/auth/logout` 使用 Authorization 中签名有效（允许已到期）的 access 绑定 sid；仍校验 Origin 与 CSRF。不得通过共享 Cookie 选定撤销对象，Cookie 只在同 sid 时删除，重复注销幂等。
- 注册、登录、重置密码发码统一返回 202，再通过响应后任务发送邮件，避免 SMTP 慢响应或超时泄露邮箱是否存在；只有发送成功的最新挑战才激活。后台投递不是持久队列，进程退出可能丢失待发邮件，用户须等待冷却后重发。已认证邮箱换绑仍同步发送，失败返回 503，日志不含地址或供应商错误内容。
- 历史账号审计复用认证的格式、长度及控制字符规则（含学工号 Unicode 空白、C1 控制字符和邮箱空域名标签），并保持只读、仅数量输出及发布阻断。
- 认证与个人资料接口有显式响应模型，空值资料字段保持 null；OpenAPI 中 422 为实际 `{detail:{code,message}}`，刷新及退出声明 Cookie、Origin、CSRF 和 Bearer 要求。

`backend/app/auth_validators.py` 是不加载应用配置的邮箱／学工号校验模块，认证服务保留原导出接口并复用它，离线审计直接依赖此纯模块。

## main 账号整合说明

认证、管理员开通、随机空间加入码迁移与发布审计参见 [整合设计](../docs/design/账号系统整合与审查修复.md)。首次运维管理员通过 `uv run python scripts/create_admin.py` 在受控终端交互创建；密码仅隐藏输入。`ADMIN_CONTACT` 是公开联系指引。部署须按实际状态升级既有 Alembic head，再执行只读审计；未验证邮箱不自动标记可信，但不阻断启用账号密码登录。数据库中的开发种子账号必须经数据拥有者处置后才能发布。

测试使用临时 SQLite、进程内 fakeredis 和假 SMTP/Turnstile/模型服务，并显式禁用环境文件；不清理本机 Redis。仓库根执行 `.venv\Scripts\python.exe -m pytest -q`。测试配置不能用于生产。

## 本次实施验证（2026-11-09）

本次已通过前端 typecheck；lint 为 0 错误、15 条原有警告。build 在独立 TEMP 重试成功，首次失败为 esbuild 默认 TEMP 清理权限问题。OpenAPI 与 docs/api.md 已在测试隔离环境重新生成并核对注册/学工号登录路由删除、绑定/解绑存在、EmailLogin 无 role、UserPayload.email_verified 为必填字段。

本次已通过 auth-session-regression、logout-session-regression、isolation-session-regression、admin-panel-regression、e2e-auth 五个脚本，五个脚本 ESLint 为 0 错误、0 警告。浏览器无异常或意外外网请求；桌面与 375px 截图已完成视觉检查，产物在 output/playwright/auth-account/，包含 login-desktop/mobile 及安全区 8 张截图。本次七份文档的相对本地链接检查 missing_local_links=0。后端用户 ID 绑定修复后的 127 项认证相关测试已通过。Ruff（含 scripts）保留 11 项既有诊断、Pyright 保留 19 项既有诊断，新增诊断均为 0，本次修改文件的 Ruff 通过。后端完整 pytest 已执行：285 passed、79 subtests passed、20 failed，耗时 16 分 26 秒。20 项失败集中于文档、聊天、出题和健康检查，底层 Chroma PersistentClient 报 `InternalError: (code: 14) unable to open database file`；独立新目录初始化同样复现，无需经过认证或业务 API。扫描 PDF 用例也在扫描检测前的向量清理处中断。本次认证用例没有失败，但完整后端验收未通过，不能将本轮记录为全量通过。

## 本轮设置拆分验证记录（2026-11-10）

以下为设置拆分阶段的历史结果；后续实际迁移和运行恢复结果已单列于上方，完整后端全量基线已通过，末轮定向验证与独立审查已完成，不改写或累计本段数字。

根 `.venv` 完整后端结果为 **373 passed、81 subtests passed、21 failed**，约 1002 秒，21 项均为既有 Chroma bindings 初始化／入库后续链路范围，完整验收未通过。`backend/app` 与新增测试 Ruff 通过；全范围仅留 `test_banks.py:73` 的既有 unused `student_id`。Pyright 隔离 HEAD 基线 26 errors、当前 21 errors，新增 0；新增接口与重建测试最终一轮 102 passed（backend/.venv）；使用假模型及本文件局部 Chroma 替身。详细结果与验收边界见[设置拆分设计的本轮验证记录](../docs/design/设置拆分与保存反馈设计.md#验证记录)，不与历史批次混算。

### 上传／预览／恢复增量结果（2026-11-10，已完成）

本轮完整后端全量基线（主代理提供，2026-11-10）：仓库根 `.venv` 在可写进程 `TEMP/TMP` 下运行完整 pytest，**479 passed、81 subtests passed、无失败，耗时 1329.22 秒**，日志 `pytest-full.log`。该基线早于随后追加的 Redis 排队／错误脱敏修复，不能作为这些后续修改的最终全量快照。验证记录统一采用“全量基线＋末轮定向”，末轮后端定向 81 项通过，独立审查的三项新发现均已修复并复核关闭；各批次数量不累计。

重解析 SQL／Redis 状态重置、向量清理异常保留旧 SQL／FTS、嵌入和存储错误分类与脱敏、删除跨存储异常属于本次功能检查范围。实际库迁移、完整备份、Chroma 副本假向量 probe、原路径与运行设置服务结果已在上方单列。标准前端 `npm run build` 仅将进程 TEMP／TMP 指向 `backend/data/tmp` 后成功，无需历史 manualChunks 临时分包；typecheck 通过，lint 为 0 errors、3 条既有 warnings，无新增。末轮定向验证、独立审查及其余检查均已完成；本文档同步不运行真实模型、OCR 或读取真实用户内容。前端独立用例入口见 [上传与预览离线回归](../frontend/README.md#上传与预览离线回归)。

#### 末轮收尾记录（2026-11-10）

后续补丁定向运行 `backend/tests/test_document_failure_recovery.py` 与现有文档接口测试：**81 passed**。覆盖原生 Chroma 假向量读写、Redis 进度缓存失效后仍能调度及重试、OCR／简化／兜底异常脱敏、删除失败保留 SQL 与原件、全局安全 503、下载媒体类型。此结果与前述 479 项全量基线分别记录，不相加，也不称为后续补丁的再次全量执行。

前端最终 typecheck、lint 和标准 build 通过；lint 为 **0 errors、3 条既有 warnings**，build 保留既有大包体积提示，构建进程使用可写 TEMP／TMP。预览 **23 项**、上传 **10 组**、整合 **24 组**回归通过，auth／logout／isolation 会话回归及管理员面板回归通过。整合用例包括删除立即失效、同名上传按 ID 选择、通知与上传交错、切库期间题库列表同步；题库列表和文档列表使用独立版本，待选上传 ID 由最后有效文档结果消费，手动选择、切库和删除清理旧意图。

最终 Ruff 的本轮实现及新增测试通过；全范围仍有 `backend/tests/test_banks.py:73` 的既有 F841。Pyright 为 **16 项既有诊断，无本轮新增**，没有把两项全范围静态检查记为零诊断通过。根 OpenAPI 已重新生成并核对 **108 个 HTTP 操作**，下载声明五种文件媒体类型及二进制 schema，API 索引同步生成。

两名未参与实现的独立审查员覆盖前端 20 个、后端 11 个增量文件：三项新发现（Redis 排队卡死、上传选择被通知刷新吞掉、切库丢弃全局题库列表）已修复并复核关闭，末轮无未关闭发现。OCR 异常脱敏也已独立复核。限定审查及复核记录在 `output/implementation/documents-recovery-20261110/`，备份与证据为忽略的本机运行产物，不提交。

本机后端已用最终源码、原持久化路径、可写进程 TEMP／TMP 和单 worker 再次启动，运行 OpenAPI 四项管理员配置操作及下载媒体类型一致，运行 settings service 的向量存储可用。当前没有可复用的活动管理员会话，未伪造或创建会话，因此未将真实管理员已认证 HTTP／UI 登录流程列为已验收。真实 PDF 保持 failed、chunks=0 且原件保留，由用户主动“重新解析”触发后续处理；本轮没有真实 OCR、嵌入或付费模型验收，也没有清库或升级 Chroma。
