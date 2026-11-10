# MathCraft 后端

基于 FastAPI、SQLAlchemy、Alembic、SQLite、Redis 和 Chroma，提供账号与权限、题库文档、混合检索、出题、组卷、作答及批卷接口。ASGI 入口为 `app.main:app`。

## 目录结构

```text
backend/
├── app/
│   ├── main.py          # 应用入口
│   ├── config.py        # 配置定义与 backend/.env 加载
│   ├── api/             # HTTP 与 WebSocket 路由
│   ├── models/          # 数据库模型
│   ├── schemas/         # 请求与响应契约
│   └── services/        # 认证、文档、RAG 与教学业务
├── alembic/             # 数据库迁移
├── scripts/             # 认证密钥、管理员及迁移审计工具
├── tests/               # 后端测试与外部服务替身
├── .env.example         # 本机开发配置模板
├── pyproject.toml       # 后端依赖
└── uv.lock              # 依赖锁文件
```

## 启动与配置

需要 Python 3.11 及以上、uv、Redis 7 及以上。以下使用 PowerShell；完整前后端启动说明见 [根 README](../README.md#启动方法)。

### 1. 启动 Redis

先启动 Docker 引擎，再从仓库根目录执行：

```powershell
docker compose up -d --wait redis
docker compose exec redis redis-cli ping
```

最后应返回 `PONG`。已有 Redis 服务时可直接使用，在下一步填写对应的 `REDIS_URL`。

### 2. 安装依赖与初始化配置

从仓库根目录进入 `backend/`，后续后端命令均在此目录执行：

```powershell
cd backend
uv sync
uv run python scripts/init_auth_secrets.py
if (-not (Test-Path app/local_secrets.py)) {
    Copy-Item app/local_secrets.example.py app/local_secrets.py
}
```

认证初始化脚本在缺少 `.env` 时从 [.env.example](.env.example) 创建，补齐 `AUTH_JWT_SECRET` 和 `AUTH_CODE_SECRET`，保留已有合法值且不打印。占位模型配置只在文件缺失时复制；账号密码登录无需真实模型凭据。

用编辑器检查 `.env`：

| 配置 | 本机开发说明 |
| --- | --- |
| `APP_ENV`、`TURNSTILE_ENABLED` | `development`、`false`，仅回环请求可跳过人机验证 |
| `DATABASE_URL` | 默认 `sqlite:///./data/mathcraft.db` |
| `REDIS_URL` | 默认 `redis://127.0.0.1:6379/0` |
| `DEEPSEEK_API_KEY` | 可选部署默认 Key；用户也可登录后保存个人配置 |
| `SMTP_*` | 使用邮箱验证码、找回密码或绑定邮箱时填写 |
| `CHROMA_DIR`、`UPLOAD_DIR`、`OCR_DIR`、`AVATAR_DIR` | 默认位于 `backend/data/`，可改为持久化绝对路径 |

配置以 [app/config.py](app/config.py) 为准，环境变量优先于固定位置的 `backend/.env`。SQLite 相对路径按启动工作目录解析，其他存储目录相对路径以 `backend/` 为基准。修改配置后重启服务。

DeepSeek 与 MinerU 个人凭据在应用“设置 → 模型与服务”保存；嵌入、重排模型与凭据由管理员在“模型与检索”维护。部署默认值及优先级见 [模型配置说明](../docs/design/模型配置来源与普通知识库流程.md)。

### 3. 迁移与创建管理员

```powershell
New-Item -ItemType Directory -Path data -Force | Out-Null
uv run alembic upgrade head
uv run python scripts/create_admin.py
```

已有数据时先按下方迁移说明备份。自定义 SQLite 路径时先创建父目录。首个管理员通过终端交互创建，账号允许英文字母、数字、下划线、点和连字符，密码为 8–64 字符且 UTF-8 不超过 72 字节；密码隐藏输入两次。已有管理员时跳过创建命令，其他账号由管理员面板开通。

### 4. 启动服务

```powershell
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
```

保持终端运行，按 `Ctrl+C` 停止。

- 健康检查：`http://127.0.0.1:8000/api/health`
- Swagger：`http://127.0.0.1:8000/docs`
- OpenAPI：`http://127.0.0.1:8000/openapi.json`

平台索引重建依赖进程内任务，当前使用单 worker。重启中断的资料入库或索引重建需由用户重新解析、管理员重新发起。

## 迁移与验证

已有部署升级前备份 SQLite、Chroma 与文件目录，先在受控副本迁移并审计，再在维护窗口升级目标库。SQLite 备份需包含已提交的 WAL 数据，可使用 backup API；SQL 备份不包含向量、上传原件、OCR、头像或 Redis。

以下示例在独立 PowerShell 终端、`backend/` 目录执行。将示例绝对路径替换为实际副本路径，确认环境变量指向副本后再执行迁移：

```powershell
$env:DATABASE_URL = 'sqlite:///C:/mathcraft-backup/mathcraft.db'
uv run alembic upgrade head
uv run python scripts/auth_migration.py audit --operator-confirmed --database 'C:/mathcraft-backup/mathcraft.db'
```

审计为只读，检查版本、结构和账号约束。完成后关闭该终端，避免副本地址影响正常启动；详细边界见 [账号与迁移设计](../docs/design/账号系统整合与审查修复.md)。

生产需设置 `APP_ENV=production`、`TURNSTILE_ENABLED=true`，补齐 Cloudflare 站点配置，关闭开发账号并清空开发账号字段。服务器通过 SSH 连接；同一部署保持认证密钥一致，不在每次启动时重新生成。

## 常见问题

- **认证配置不可用**：确认两项认证密钥已初始化。本机使用 `APP_ENV=development`、`TURNSTILE_ENABLED=false` 并按上述回环地址启动；生产需要完整 Turnstile 配置。环境变量可覆盖 `.env`。
- **邮箱功能不可用**：配置 SMTP；人机验证开关不替代邮件验证码或邮件服务。
- **Chroma 报 `code 14`**：除数据路径权限外，检查启动进程的 `TEMP/TMP` 是否可写。Windows 可在启动前为当前终端指定可写目录：

```powershell
$mathcraftTemp = Join-Path $env:LOCALAPPDATA 'MathCraft/Temp'
New-Item -ItemType Directory -Path $mathcraftTemp -Force | Out-Null
$env:TEMP = $mathcraftTemp
$env:TMP = $mathcraftTemp
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --no-proxy-headers
```

覆盖仅影响当前终端及随后启动的子进程。旧索引与失败重建集合不会自动回收，清理前核对活动、在建及仍在使用的索引版本，具体见 [设置与索引设计](../docs/design/设置拆分与保存反馈设计.md)。

## 开发检查

在 `backend/` 执行：

```powershell
uv sync --group dev
uv run pytest -q
uv run ruff check app tests
```

测试使用临时 SQLite、每测试独立 fakeredis 和假 SMTP、Turnstile、模型服务，不连接或清空本机 Redis。接口变更后同步根 `openapi.json` 和 [API 文档](../docs/api.md)，生成命令见 [协作约定](../AGENTS.md)。

## 相关文档

- [根 README](../README.md)、[前端说明](../frontend/README.md)：项目介绍与前后端启动。
- [API 文档](../docs/api.md)、[OpenAPI 契约](../openapi.json)：完整接口。
- [账号与权限](../docs/design/账号系统整合与审查修复.md)、[知识库说明](../docs/design/知识库模块说明.md)、[模型配置](../docs/design/模型配置来源与普通知识库流程.md)：功能与配置边界。
- 待实现方案：[系统方案说明](../docs/design/运维后台系统方案说明.md)、[运维后台](../docs/design/运维后台升级方案.md)、[接口与联调契约](../docs/design/运维后台接口与联调契约.md)、[模块说明](../docs/design/运维后台模块说明.md)。
