# Redis 容器启动设计

状态：配置与本地 main 启动文档已同步；2026-11-09 已通过 Compose 静态渲染与配置核对，本轮未启动容器，运行及持久化验收待完成。

## 目标与范围

为本地开发补充 Redis Docker Compose 启动选项。Compose 只定义 Redis，后端和前端继续按当前本地命令启动。原有 WSL 或本机 Redis 仍可按需使用，同一时间只使用一个占用 6379 端口的实例。

## 配置与数据契约

- 根目录 `compose.yaml`：项目名 `mathcraft`，服务名 `redis`，使用 `redis:7-alpine` 镜像。
- 宿主机仅通过 `127.0.0.1:6379` 访问，容器内部端口为 6379。后端仍使用 `REDIS_URL=redis://127.0.0.1:6379/0`，不使用 Docker 内部服务名作为本地后端主机名。
- 命名卷 `redis_data` 挂载 `/data`，默认实际名称为 `mathcraft_redis_data`，启用 AOF；停止或执行普通 `docker compose down` 时保留数据卷。
- 使用 `redis-cli ping` 健康检查，健康后启动命令返回成功；`unless-stopped` 用于容器重启策略。
- 所有命令从仓库根目录直接执行；Compose 默认读取根目录 `.env`，若其中的格式或 `COMPOSE_*` 配置导致报错，请检查该文件，后端配置仍放在 `backend/.env`，当前 Redis 服务不依赖其中的变量。
- 不增加应用账号、环境凭据或 HTTP 接口；用户、密码与认证会话保存到 SQLite。当前 main 不使用 Redis token 登录，管理员通过受控交互脚本初始化，教师/学生的开发 seed 仅供开发环境。

## 核心流程

1. 启动 Docker 引擎；若本机或 WSL Redis 已占用 6379，先停止对应 Redis 实例。
2. 在仓库根目录执行 `docker compose config --quiet`，再执行 `docker compose up -d --wait redis`。
3. 执行 `docker compose exec redis redis-cli ping`，确认得到 `PONG`。
4. 按 README 启动本机后端和前端；后端使用 `REDIS_URL=redis://127.0.0.1:6379/0`。登录配置仍需满足 SMTP、Turnstile 和认证密钥要求，Redis 健康不代表所有认证配置已完成。
5. 使用 `docker compose stop redis` 暂停，`docker compose up -d --wait redis` 恢复；或使用 `docker compose down` 移除容器和网络并保留数据卷。

## 异常与切换边界

- Docker 引擎未运行时无法启动容器，必须先启动引擎。
- 端口冲突时停止旧 Redis，不自动修改端口或后端地址。
- 首次切换到容器使用独立数据卷，不自动导入原 Redis 验证码、限流和任务缓存；旧验证码失效，旧实例未完成的任务需按实际状态重新发起。账号、认证会话和业务数据库不受切换影响；单纯切换 Redis 不会撤销数据库中的刷新会话。
- 删除命名卷会丢失其中的 Redis 数据；日常停止不删除卷。
- 本方案面向本机开发，端口不绑定公网地址，不扩展其他服务的容器部署。

## 验收标准

- `docker compose config --quiet` 成功，渲染后只有 `redis` 服务，端口、AOF、健康检查与卷挂载符合上述契约。
- Docker 引擎可用时，`docker compose up -d --wait redis` 成功，容器健康，`docker compose exec redis redis-cli ping` 返回 `PONG`。
- Windows 本地后端连接到配置地址的 Redis，专用测试账号可经当前 main 的 account 密码登录或已验证邮箱验证码登录，不把旧的三类 `.env` 初始化方案当作现行流程。
- Redis 写入临时标记后停止并重建容器，标记仍可从相同命名卷读取，验收后删除该临时标记。
- 根 README 与后端 README 给出一致的工作目录、启动、验证、停止和实例切换说明。
