# A0 / G0 独立准备工具

包含独立准备工具及实际 HTTP 业务验收工具。应用只复用 `backend/app/services/agent_telemetry/` 中的脱敏与有界传输，不导入工具运行器；不新增运维 SQL、周期心跳、统计服务、告警或 ops API。**独立 harness 成功不等于实际业务 G0 通过。**

历史准备见 [独立准备记录](../../docs/design/运维后台A0与G0独立准备记录.md)，官方资料见 [技术核验](../../docs/design/运维后台G0技术核验.md)。本轮 SDK 实际业务入口、故障恢复和安全证据见 [SDK 接入与 G0 验收](../../docs/design/SDKAgent接入与G0验收.md)。

## 实际 HTTP 业务验收

`business.py` 从现有测试夹具导入隔离配置与临时 SQLite/FakeRedis，不执行替换整个模型函数的自动夹具。它保留实际 Agent/Runner/模型、审核、修补、重出、求解及业务事务，仅在模型 HTTP transport 和检索/嵌入边界提供假响应。导出至专用本地 Phoenix 后，独立读取并核对 run、账号、会话、阶段、尝试、批次和非根原生 Agent/LLM 父链。不同账号通过真实登录和 HTTP 生成并发，同一真实会话的连续生成分别分配运行与根 trace。

```powershell
$env:TEMP = Join-Path $PWD '.scratch/sdk-g0-tmp'
$env:TMP = $env:TEMP
$env:SQLITE_TMPDIR = $env:TEMP
& '.\.venv\Scripts\python.exe' -B -X utf8 -m tools.ops_g0.business --home '.scratch/ops-business-g0-20261113' --base-url 'http://127.0.0.1:6026' --label 'ops-g0-business-recheck'
```

先按专用环境记录准备该 Phoenix 及独立导出凭据；`--home` 不得指向真实业务配置，工具拒绝历史 6016 实例。报告只输出安全标识与计数，私有配置、数据库、会话和证据运行目录均不提交。该命令不调用真实模型。

## 文件

| 文件 | 用途 |
| --- | --- |
| `pyproject.toml`、`uv.lock` | 独立固定依赖，不改变应用环境 |
| `audit.py` | 对本地 main / agent 的已跟踪后端源码做 AST 核验，不导入应用配置 |
| `environment.py`、`compose.yaml` | 新建并保留独立 Phoenix 凭据、数据和固定镜像 |
| `redaction.py`、`transport.py` | 入缓冲前脱敏、回环出口、有界队列／重试／退出 |
| `harness.py` | SDK 假模型／假工具、并发与线程关联，内存执行事实 |
| `live_smoke.py` | 显式授权后的真实 DeepSeek 小样本验收，硬限 3 请求／每次 128 输出 tokens |
| `phoenix.py`、`verify.py` | 认证管理／读取，逐 span 核对真实存储及权限 |
| `retention.py` | 新合成项目的公开时间窗删除验证，不启动周期调度 |

## 环境与启动

在仓库根目录使用 PowerShell；需要 Python 3.11–3.14、uv、Docker Desktop Linux 引擎。固定 Phoenix 镜像为 amd64，其他架构需重新核验 digest。依赖安装及镜像下载需要联网；运行合成 SDK 时阻断非回环 socket 连接。

```powershell
uv sync --project tools/ops_g0 --frozen
$g0python = 'tools\ops_g0\.venv\Scripts\python.exe'
& $g0python -X utf8 -m tools.ops_g0.environment
docker compose -f tools/ops_g0/compose.yaml --env-file .scratch/ops-g0-20261112/phoenix.env up -d --wait
```

`uv sync` 在工具自己的 `.venv` 安装，不升级根目录或 backend 环境。本轮实际使用的等效独立环境位于 `.scratch/ops-g0-20261112/venv`，可把 `$g0python` 改为该环境的 `Scripts/python.exe` 复核已有证据。

仅发布 `127.0.0.1:6016`，服务开启 Phoenix 自身认证。Compose 的专用 bridge 是网络分组，不承诺服务端无外连；SDK 运行出口由 harness 的 socket 守卫核验。工作目录挂载至 `/mnt/data`，避免覆盖镜像程序目录 `/phoenix`。

独立配置位于 `.scratch/ops-g0-20261112/private.json` 和 `phoenix.env`。初始化保留已有文件，不显示凭据、不复用 MathCraft 配置；API 导出 key 由独立 admin secret 自动签发，期限 7 天。到期时仅轮换该隔离 key，不改变业务凭据。不要打印配置、运行会展开配置的 `docker compose config`，或提交 `.scratch` 文件。

## 复现

每次选用新 label 和新输出文件名，保留之前证据；下面的 label 只是示例。

```powershell
& $g0python -X utf8 -m tools.ops_g0.audit --output .scratch/ops-g0-20261112/a0-source-audit-recheck.json
& $g0python -X utf8 -m tools.ops_g0.harness --label recheck-01
& $g0python -X utf8 -m tools.ops_g0.verify evidence-recheck-01
& $g0python -X utf8 -m tools.ops_g0.retention --label recheck-01
& $g0python -X utf8 -m unittest discover -s backend/tests -p 'test_ops_g0_*.py' -v
```

`audit` 使用本地 ref，不自动 fetch；记录 SHA 后再解释结果。`harness` 输出 `sdk-evidence.json` 与脱敏 `.otlp`，`verify` 独立输出 `phoenix-verification.json`、`persisted-spans.json`。后者通过才算持久可查；SDK 文件里的 `phoenix_persistence_verified:false` 表示导出脚本本身不作存储判断，以独立 verification 为准。出口、脱敏或正常导出缺失会让 harness 报错并保留已生成证据。

`audit` 需要本地 `main`、`agent` 引用；仅有远端跟踪引用时，先通过 SSH 执行 `git fetch origin`，再用 `git branch --track agent origin/agent` 建立缺失的本地分支，无需切换工作区。已存在的分支不得覆盖。本次审查修复保持盘点脚本不变。

关联验收同时核对预期的 `batch_id`：已知批次错误或缺失均失败；尚未落库的运行允许没有批次，但不得携带另一批次。合成样例使用可区分的批次标识；通过检查仍不代表业务 G0 已通过。

`retention` **只操作新建的 `ops-g0-retention-<label>` 合成项目**：写入四天前及当前的根／子 spans，先读取两组，再禁用原生到期规则，经公开 REST 删除三天前窗口，复读并重复删除。结果在 `retention-<label>.json`。禁止把它改成业务项目名或用它操作 Phoenix 私有表。

唯一清理选择为应用经公开接口调度。`retention.POLICY` 记录正文 3 天、每日一次、24 小时窗口、每次最多 8 窗口；本工具没有注册 scheduler。G0 后乙/M8 负责实际周期调度、持久游标、失败恢复和记录；不能再启用 Phoenix 原生过期规则并行清理。隔离验收样例之外的正文保留尚未接线。

## 真实模型验收（显式请求时才运行）

日常测试仍只用假服务。用户明确要求真实模型验收后，在调用进程安全注入 `DEEPSEEK_API_KEY`；`DEEPSEEK_MODEL` 默认 `deepseek-flash`，`DEEPSEEK_BASE_URL` 仅允许 `https://api.deepseek.com` 或其 `/v1`。不在命令行填写凭据，不打印已有配置，也不读取 `local_secrets.py`。本轮凭据由忽略目录内的启动脚本从既有部署配置加载到子进程环境，未复制或归档其值。

```powershell
# 仅在凭据已经安全注入当前进程，且用户明确授权后执行
& $g0python -X utf8 -m tools.ops_g0.live_smoke --allow-real-model --label live-recheck-01
```

脚本只发送合成的 `17+25`：普通返回、真实模型调用本地加法工具、流式返回各一次；工具模式得到工具结果后直接结束，不追加回答请求。最多 3 个模型 POST、每次 `max_tokens<=128`、SDK 客户端不自动重试、总执行时限 120 秒；只允许官方 DeepSeek Chat Completions 端点及本地追踪读取。拒绝未经授权的主机、路径、模型替换和超额调用。错误只归档类型，provider 响应正文与凭据不进报告。

结果保存在 `evidence-<label>/real-model-report.json`，同时保存 SDK／本地 Phoenix 对照证据。真实调用完成后需单独复核存储；本脚本不会把独立模型烟测标为实际业务 G0 通过。历史独立准备曾执行 3 次付费烟测；本轮 SDK 实际业务验收不重复这些调用，也不新增真实模型请求。

## 停止与数据

```powershell
docker compose -f tools/ops_g0/compose.yaml --env-file .scratch/ops-g0-20261112/phoenix.env stop phoenix
# 恢复使用上面的 up -d --wait
```

停止保留数据。不要删除数据目录、快照或以清理工作区为由运行 `git clean`。新凭据、SQLite、运行证据及快照均留在被忽略的独立目录；本轮原 RAG 验收目录未参与上述命令。

## 限制

敏感路由判断统一识别路径字段和 `url.full`／`http.url` 的 URL 路径；认证、改密及个人模型设置的已知正文属性整体排除。排除状态在嵌套 JSON、编码后的 JSON 字符串、列表及 OTLP array／kvlist 中传递，并应用到关联事件和 links；普通出题请求的正文仍按原脱敏规则保留。此规则覆盖已知属性形态，不替代真实业务接入前的正文白名单。

脱敏器只验证已列出的合成凭据形式，不能当作任意文本的完整 DLP。结构化／转义字段被截断或无法解析时整体排除；真实业务接入前仍须明确正文白名单。导出队列及单 payload 有界，不代表 SDK 自身所有活跃 trace 状态或业务输入均有界。HTTP 2xx 导出回执最多读取 16 KiB 并按 OTLP protobuf 解析，拒收或非法回执计失败、不记录响应文字；部分拒收不重发整批。关闭有截止时间，未完成如实记录，不能宣称故障样本可重放。

合成出口守卫在锁定 HTTPX 0.28.1 的单跳请求分派处检查同步／异步及重定向，并辅以同步 socket 检查；不宣称覆盖任意库直接发起的原始 TCP。真实模型工具仅放行唯一有预算的模型客户端，其他 SDK HTTPX 出口仍限定本地。升级 HTTPX 后须重新核验该测试专用分派接点，不将其接入应用全局。

独立准备工具测试可通过 unittest 运行，不使用应用 SQLite/Redis；统一 pytest 下仅对测试自行绑定的数值回环 receiver 端口放行，其余服务网络继续禁用。实际业务 `business.py` 则使用隔离临时 SQLite 与进程内 FakeRedis，通过 HTTP 入口执行 SDK 和事务；两者证据边界及本轮结果见配套 SDK G0 记录。
