# Redis 容器启动设计

状态：已提供配置；本机 Docker 引擎不可用，容器运行验收待完成。

## 目标与范围

为本地开发补充 Redis Docker Compose 启动选项。Compose 只定义 Redis，后端和前端继续按当前本地命令启动。原有 WSL 或本机 Redis 仍可按需使用，同一时间只使用一个占用 6379 端口的实例。

## 配置与数据契约

- 根目录 `compose.yaml`：项目名 `mathcraft`，服务名 `redis`，使用 `redis:7-alpine` 镜像。
- 宿主机仅通过 `127.0.0.1:6379` 访问，容器内部端口为 6379。后端仍使用 `REDIS_URL=redis://127.0.0.1:6379/0`，不使用 Docker 内部服务名作为本地后端主机名。
- 命名卷 `redis_data` 挂载 `/data`，启用 AOF；停止或执行普通 `docker compose down` 时保留数据卷。
- 使用 `redis-cli ping` 健康检查，健康后启动命令返回成功；`unless-stopped` 用于容器重启策略。
- 不增加应用账号、环境凭据或 HTTP 接口；初始化账号仍保存到原 SQLite 数据库。

## 核心流程

1. 启动 Docker 引擎；若本机或 WSL Redis 已占用 6379，先停止对应 Redis 实例。
2. 在仓库根目录执行 `docker compose up -d --wait redis`。
3. 执行 `docker compose exec redis redis-cli ping`，确认得到 `PONG`。
4. 从后端运行环境执行现有 Redis 探测命令，随后按 README 启动后端和前端并登录。
5. 使用 `docker compose stop redis` 暂停，或使用 `docker compose down` 移除容器和网络并保留数据卷。

## 异常与切换边界

- Docker 引擎未运行时无法启动容器，必须先启动引擎。
- 端口冲突时停止旧 Redis，不自动修改端口或后端地址。
- 首次切换到容器使用独立数据卷，不自动导入原 Redis 会话、任务或缓存；使用者重新登录，旧实例未完成的任务需重新发起。账号和业务数据库不受切换影响。
- 删除命名卷会丢失其中的 Redis 数据；日常停止不删除卷。
- 本方案面向本机开发，端口不绑定公网地址，不扩展其他服务的容器部署。

## 验收标准

- `docker compose --env-file backend/.env.example config --quiet` 成功，渲染后只有 `redis` 服务，端口、AOF、健康检查与卷挂载符合上述契约。
- Docker 引擎可用时，`docker compose up -d --wait redis` 成功，容器健康，`redis-cli ping` 返回 `PONG`。
- Windows 本地后端连接到配置地址的 Redis，三类初始化账号仍可登录。
- Redis 写入临时标记后停止并重建容器，标记仍可从相同命名卷读取，验收后删除该临时标记。
- 根 README 与后端 README 给出一致的工作目录、启动、验证、停止和实例切换说明。
