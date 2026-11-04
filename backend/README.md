# MathCraft 后端

当前后端以 `app.main:app` 为入口，使用 FastAPI、SQLAlchemy、Alembic、SQLite、Redis 与 Chroma。历史 `/api/kb`、Ollama 和单租户入口不代表当前实现。

## 模块结构

```text
backend/
├── app/
│   ├── main.py              # 应用装配与路由注册
│   ├── config.py            # backend/.env 配置
│   ├── db.py                # SQLite WAL、SQLAlchemy 会话和 FTS
│   ├── deps.py              # 登录用户及角色依赖
│   ├── api/                 # auth/users、题库/文档、出题/空间/试卷等
│   ├── models/              # 业务数据与认证会话/消费凭证
│   ├── schemas/             # 请求、响应与外部契约
│   └── services/
│       ├── auth.py          # 密码、JWT、数据库会话、刷新与撤销
│       ├── auth_codes.py    # 验证码、限流和数据库消费凭证
│       ├── auth_delivery.py # SMTP 与 Turnstile 边界
│       └── rag/             # 向量、检索、出题及对话编排
├── alembic/                 # 数据库版本迁移
├── scripts/                 # 认证密钥生成、开发初始化与只读迁移审计
│   └── generate_auth_secrets.py # 标准库脚本，不读写 .env
├── tests/                   # HTTP、事务、迁移与命令测试
├── .env.example             # 空凭据配置模板
├── pyproject.toml
└── uv.lock
```

## 启动与配置

```powershell
cd backend
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
# 按根 README 生产配置清单或受控开发要求编辑 .env，再继续
uv sync --group dev
uv run alembic upgrade head
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
```

配置以 [app/config.py](app/config.py) 和 [.env.example](.env.example) 为准，环境变量可覆盖固定位置的 `backend/.env`。完整字段、默认值、用途和获取来源集中在根 [生产配置清单](../README.md#生产配置清单) 与 [数据、缓存与模型配置](../README.md#数据缓存与模型配置)，部署时逐项填写。`config.py` 默认 `APP_ENV=production`，模板则为 `development`；生产须显式设为 `production`，`DEV_ACCOUNTS_ENABLED=false`，并清空教师/学生各自的 `EMAIL`、`USER_NO`、`PASSWORD`、`DISPLAY_NAME` 八个开发字段。Redis 存储验证码、限流和业务任务；认证会话在数据库中。缺少必要配置时相关认证操作拒绝或返回不可用。真实配置、数据库和上传文件不入库。

### 手工生成认证密钥

从本 `backend/` 目录执行：

```powershell
python scripts/generate_auth_secrets.py
```

若在仓库根目录，则执行 `python backend/scripts/generate_auth_secrets.py`。无需 uv 或项目依赖，脚本只用 Python 标准库；不加载应用、连接数据库或读写 `.env`。每次手工运行独立生成两个 `secrets.token_urlsafe(48)` 值，输出 `AUTH_JWT_SECRET`、`AUTH_CODE_SECRET` 两行及保存提示；加 `--help` 仅显示帮助，不生成。将这两行人工粘贴进 `backend/.env` 的同名配置项，已有配置不得整份覆盖；不要把输出重定向到 `.env`，不要提交或记录到共享日志。SMTP 的主机、账号、授权密码、发件人和 TLS 参数须向邮件服务商获取；Turnstile 的 site key、secret key 和站点配置须从 Cloudflare 获取，脚本不能伪造第三方凭据。

同一部署所有后端进程与实例保持相同密钥和 issuer/audience，不要每次启动重新生成。轮换 JWT 密钥使旧访问 JWT 验签失败，轮换验证码密钥使旧邮件码校验失败；数据库中刷新会话的摘要、状态与用户认证版本独立管理，不能把换 JWT 密钥视为必然撤销 refresh。需要撤销时使用现有会话撤销流程。详见根 [密钥生成与轮换说明](../README.md#生产认证密钥生成与保存)。

生产 `CORS_ORIGINS` 使用精确 HTTPS Origin，例如 `https://learn.example.com`；`TURNSTILE_ALLOWED_HOSTNAMES` 对应填写 `learn.example.com`，与 Cloudflare widget 的 hostname 配置一致。前者包含协议及必要端口，后者不含协议、端口或路径；二者都不是 URL 路径白名单。

SQLite 默认相对文件路径按启动工作目录解析，从本目录启动对应 `backend/data/mathcraft.db`；`CHROMA_DIR`、`UPLOAD_DIR`、`OCR_DIR`、`AVATAR_DIR` 的相对路径以 `backend/` 为基准。生产改用部署者提供的持久卷绝对路径和受控 `REDIS_URL`，保留既有用户、模型设置、上传及索引的迁移与备份。个人模型配置经 `/api/users/me/model-settings` 保存在 `UserModelSetting`，优先于环境兜底模型密钥；认证脚本不生成模型服务凭据。本文说明部署准备，不代表已配置真实服务、执行生产迁移或完成上线。

开发账号仅在 `APP_ENV=development` 且 `DEV_ACCOUNTS_ENABLED=true` 时显式运行 `uv run python scripts/seed.py`；教师与学生配置均需完整，重复执行不改已有密码、角色及归属。开发凭据接口只用于受控本机环境，前端按钮仅填充；生产禁止此能力及开发凭据配置。

## 认证与接口

邮箱验证注册可不填学工号；注册自动登录。登录支持邮箱验证码或学工号密码，不支持邮箱密码及旧用户名登录。访问令牌仅驻留前端内存；刷新凭据由 HttpOnly Cookie 管理。刷新和退出需要精确可信 Origin、JSON 请求及 CSRF Token。修改/重置密码、换绑邮箱撤销全部设备；退出仅撤销当前设备。学工号变更需要当前密码。

完整接口见根 [openapi.json](../openapi.json) 与 [API 索引](../docs/api.md)，业务及错误边界见 [认证设计](../docs/design/用户系统功能规格.md) 和 [实施规格](../docs/design/用户系统实施规格.md)。

旧版 `scripts/create_user.py` 已停用：包括帮助参数在内固定退出 2，不解析凭据、不加载配置、不访问数据库。真实用户通过公开注册验证邮箱，开发账号仅使用上述受控初始化命令。

## 迁移与验证

迁移前保留只读备份；对受控副本运行：

```powershell
uv run python scripts/auth_migration.py audit --operator-confirmed --database <受控副本路径>
```

该命令不修复数据，不输出邮箱或密码。缺失/未验证邮箱、重复标识及其他异常阻断发布；不能静默合并、认领或自动验证历史用户。迁移必须保留用户 ID 和资源归属，旧会话不得继续使用。

后端测试使用每测试独立 fakeredis 和临时 SQLite，SMTP、Turnstile、模型均为假服务，不连接或清空本机 Redis：

```powershell
uv run pytest -q
uv run ruff check app tests
```

测试结果、认证竞争与生产构建检查记录在实施规格中。不要为运行测试读取个人 `.env` 或 `app/local_secrets.py`。
