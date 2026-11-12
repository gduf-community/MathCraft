# A0 / G0 独立准备工具

仅供甲在实际 SDK 业务路径交接前做源码核验、隔离部署和合成试接入。不由应用导入，不新增运维 SQL、周期心跳、统计服务、告警或 ops API。**独立 harness 成功不等于实际业务 G0 通过。**

本轮状态和证据索引见 [独立准备记录](../../docs/design/运维后台A0与G0独立准备记录.md)，官方资料见 [技术核验](../../docs/design/运维后台G0技术核验.md)。

## 文件

| 文件 | 用途 |
| --- | --- |
| `pyproject.toml`、`uv.lock` | 独立固定依赖，不改变应用环境 |
| `audit.py` | 对本地 main / agent 的已跟踪后端源码做 AST 核验，不导入应用配置 |
| `environment.py`、`compose.yaml` | 新建并保留独立 Phoenix 凭据、数据和固定镜像 |
| `redaction.py`、`transport.py` | 入缓冲前脱敏、回环出口、有界队列／重试／退出 |
| `harness.py` | SDK 假模型／假工具、并发与线程关联，内存执行事实 |
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
& $g0python -X utf8 -m unittest discover -s backend/tests -p test_ops_g0_preparation.py -v
```

`audit` 使用本地 ref，不自动 fetch；记录 SHA 后再解释结果。`harness` 输出 `sdk-evidence.json` 与脱敏 `.otlp`，`verify` 独立输出 `phoenix-verification.json`、`persisted-spans.json`。后者通过才算持久可查；SDK 文件里的 `phoenix_persistence_verified:false` 表示导出脚本本身不作存储判断，以独立 verification 为准。出口、脱敏或正常导出缺失会让 harness 报错并保留已生成证据。

`retention` **只操作新建的 `ops-g0-retention-<label>` 合成项目**：写入四天前及当前的根／子 spans，先读取两组，再禁用原生到期规则，经公开 REST 删除三天前窗口，复读并重复删除。结果在 `retention-<label>.json`。禁止把它改成业务项目名或用它操作 Phoenix 私有表。

唯一清理选择为应用经公开接口调度。`retention.POLICY` 记录正文 3 天、每日一次、24 小时窗口、每次最多 8 窗口；本工具没有注册 scheduler。G0 后乙/M8 负责实际周期调度、持久游标、失败恢复和记录；不能再启用 Phoenix 原生过期规则并行清理。隔离验收样例之外的正文保留尚未接线。

## 停止与数据

```powershell
docker compose -f tools/ops_g0/compose.yaml --env-file .scratch/ops-g0-20261112/phoenix.env stop phoenix
# 恢复使用上面的 up -d --wait
```

停止保留数据。不要删除数据目录、快照或以清理工作区为由运行 `git clean`。新凭据、SQLite、运行证据及快照均留在被忽略的独立目录；本轮原 RAG 验收目录未参与上述命令。

## 限制

脱敏器只验证已列出的合成凭据形式，不能当作任意文本的完整 DLP。真实业务接入前须明确正文白名单，并补实际 SDK 模型、工具、异常和嵌套字段样例。导出队列及单 payload 有界，不代表 SDK 自身所有活跃 trace 状态或业务输入均有界。HTTP 客户端不读取导出响应正文；关闭有截止时间，未完成如实记录，不能宣称故障样本可重放。

当前测试通过 unittest 运行，不导入应用 `conftest.py`，不连接或清空 Redis，不使用应用 SQLite。实际入口、取消、最终交付版本及审核证据仍等外部交接，完整 G0 由原方案验收负责人确认。
