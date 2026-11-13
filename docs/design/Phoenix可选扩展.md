# Phoenix 可选扩展

状态：**已实现独立可选扩展；台账基础已提供，实际入口与后台查询后续接入。**

## 接入方式

实现位于 `backend/app/services/phoenix_tracing.py`，使用私有 OpenTelemetry provider、有界队列和手工 OTLP/HTTP protobuf 导出。`MetadataClient` 继承普通 OpenAI SDK 的默认 HTTP 客户端，保留代理、重定向和连接配置，观察公开 `send` 调用；不引入 Agent SDK，也不读取、复制或发送请求／响应正文。

`@trace_run` 覆盖对话消息、同步参数化出题和后台参数化任务；`TracingThreadPoolExecutor` 向生成及审核线程传递上下文。采集限于入口、关联标识、模型标识、时间、耗时、HTTP 状态和安全错误类别，不采集对话、题干、答案、解析、提示词、模型输入输出、工具正文、凭据或异常全文。

## 运行标识与结果含义

`ops_runs` 模型、迁移和写入模块已提供，实际入口尚未接入。`trace_run` 内部生成 `run_` 标识，`RunLedger.accept` 可通过 `current_run_id()` 在同一执行上下文复用 ID；未启用追踪时独立生成，也支持显式 ID。本批不改装饰器，`/start` 的预分配 ID 到后台追踪的绑定仍待后续接入，见 [运行台账基础](运维后台运行台账基础.md)。

**根 span 的 OK 仅表示被装饰函数正常返回，不证明生成批次已保存或业务成功。** 函数可能返回业务错误而没有抛出异常；LLM 调用错误独立记录，不能通过根 span 推导后台的 `completed`、`failed` 或 `unknown`。

HTTP 流在完整读至 EOF 时结束；读取异常记录安全错误类别。SDK 正常收到 SSE 结束标记也可能提前关闭 HTTP 流，因此仅观察到关闭时记录 `mathcraft.stream.end=closed`、状态 `UNSET`，不推断成功、取消或失败。

## 依赖与配置

仓库根和 `backend/pyproject.toml` 均提供 `phoenix` 可选 extra，固定 `opentelemetry-sdk==1.45.2` 和 `opentelemetry-exporter-otlp-proto-http==1.45.2`。在所使用的环境目录执行 `uv sync --extra phoenix`；不启用时无需安装。

配置沿用 `backend/app/config.py` 和 `backend/.env.example`：

| 字段 | 默认值 |
| --- | --- |
| `PHOENIX_ENABLED` | `false` |
| `PHOENIX_ENDPOINT` | `http://127.0.0.1:6017/v1/traces` |
| `PHOENIX_PROJECT` | `mathcraft` |
| `PHOENIX_API_KEY` | 空；配置类型为 `SecretStr` |
| `PHOENIX_QUEUE_SIZE` | `128` |
| `PHOENIX_TIMEOUT_SECONDS` | `0.5` |

开关关闭、可选依赖缺失或扩展配置无效时，业务仍可启动。导出超时、队列满或 Phoenix 不可用时丢弃对应元数据并记录安全日志；队列不持久化，不承诺补发。追踪故障不改变模型请求结果，也不决定后台状态。

## 独立 Docker 部署

根 `compose.phoenix.yaml` 固定 `arizephoenix/phoenix:version-21.0.0` 与 digest `sha256:b5bcec3455bd5c431f52737fc62046c081752b483e3fff40c63f40783736bcad`，仅发布 `127.0.0.1:6017:6006`，使用 `phoenix_data` 持久命名卷。

在仓库根执行：

```powershell
docker compose -f compose.phoenix.yaml up -d --wait phoenix
docker compose -f compose.phoenix.yaml stop phoenix
```

访问入口为 `http://127.0.0.1:6017`。Compose 显式设置 `PHOENIX_ENABLE_AUTH=false`，仅用于单机可信访问；远程部署须使用 HTTPS、独立认证和 API key，不可直接把无认证端口公开。停止容器保留卷，不使用 `down -v` 清除追踪数据。

启用时先启动独立容器，在后端环境安装 extra，再将 `PHOENIX_ENABLED` 改为 `true` 并重启后端。停用时改回 `false` 并重启；Phoenix 服务与 MathCraft 可独立运行。

## 验收边界

使用假模型和合成数据覆盖两条业务入口、LLM 错误、线程关联、关闭开关、缺少可选依赖及导出故障；确认存储中只有元数据。导出受理不等于记录已持久可查，应读取 Phoenix 核对关联。Phoenix 结果不能替代后台台账或业务成功判断。

旧 `tools/ops_g0` 的 Agent SDK harness、正文采集和清理脚本不属于当前实现或验收流程。

## 验证结果（2026-11-13）

- Phoenix 专项 25 项通过，覆盖普通 OpenAI SDK、SSE 关闭、并发线程关联、代理路由、配置错误及导出故障隔离。
- 独立容器通过健康检查；假模型并发运行后实际读回 6 条 span（2 条根、4 条模型调用），关联正确，无业务正文或凭据，无真实模型调用。
- OpenAPI 与根契约一致；两个 uv 锁文件校验通过；修改文件 Ruff 通过。全库原有 Ruff 1 条、Pyright 15 条诊断未新增。
- 全量回归为 789 项通过、31 项失败：23 项涉及 Chroma 原生存储 `code 14`，8 项为旧 G0 本机网络测试与公共禁网夹具冲突。HEAD 隔离副本已分别复现两类根因；不计作 Phoenix 验收通过项。
- 单独组合追踪、流式与审核测试时为 60 项通过、4 项失败；4 项因 `rag_settings` 未建表而失败，在上述全量回归中通过。此组合仍存在测试初始化顺序限制。
