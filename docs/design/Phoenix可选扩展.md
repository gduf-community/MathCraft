# Phoenix 可选扩展

状态：**独立可选扩展、台账实际入口及 V2 查询已实现并在本地整合，前端 V2 已隔离联调，部署待验收。**

## 接入方式

实现位于 `backend/app/services/phoenix_tracing.py`，使用私有 OpenTelemetry provider、有界队列和手工 OTLP/HTTP protobuf 导出。`MetadataClient` 继承普通 OpenAI SDK 的默认 HTTP 客户端，保留代理、重定向和连接配置，观察公开 `send` 调用；不引入 Agent SDK，也不读取、复制或发送请求／响应正文。

`@trace_run` 覆盖对话消息、同步参数化出题和后台参数化任务；`TracingThreadPoolExecutor` 向生成及审核线程传递上下文。采集限于入口、关联标识、模型标识、时间、耗时、HTTP 状态、安全错误类别、阶段决策和分组计数，不采集对话、题干、答案、解析、提示词、模型输入输出、工具正文、凭据或异常全文。

## 运行标识与结果含义

实际出题入口已写入 `ops_runs`。`trace_run` 内部生成 `run_` 标识，`RunLedger.accept` 通过 `current_run_id()` 复用；未启用追踪时独立生成。`/start` 在受理时分配 ID，通过后台参数 `run_id` 传递；后台装饰器的 `run_id_kwarg` 复用该 ID 建立根 span，不采集其余参数。非出题对话仍可只有追踪而没有台账，见 [入口接入](运维后台出题入口接入.md)。

**根 span 的 OK 仅表示被装饰函数正常返回，不证明生成批次已保存或业务成功。** 函数可能返回业务错误而没有抛出异常；LLM 调用错误独立记录，不能通过根 span 推导后台的 `completed`、`failed` 或 `unknown`。

HTTP 流在完整读至 EOF 时结束；读取异常记录安全错误类别。SDK 正常收到 SSE 结束标记也可能提前关闭 HTTP 流，因此仅观察到关闭时记录 `mathcraft.stream.end=closed`、状态 `UNSET`，不推断成功、取消或失败。

## 出题阶段追踪设计

对话、同步参数化与后台参数化出题共用命题、审核和补题追踪。按 `mathcraft.run_id` 筛选同一次运行，按 `mathcraft.candidate_id` 查找候选的判定历史。命题每次尝试独立建 span，产出的候选和本次模型调用共享父节点。后续模型调用挂到求解、解析补全、修题或成品验收阶段下。修订沿用候选 ID，`mathcraft.revision` 为 0 或 1。首轮 `mathcraft.refill_round` 为 0，缺额补题为 1 至 3。

生成分组用 `mathcraft.candidates.requested` 和 `mathcraft.candidates.produced` 记录本轮要求和返回的候选数，局部失败时同时保留模型错误原因。阶段通过 `mathcraft.stage`、`mathcraft.decision` 和可选的 `mathcraft.reason_code` 表示业务判定。HTTP 200 也可能产生 `false_proposition`，模型传输超时则在模型 span 标记 `error.type=TIMEOUT`。命题阶段因题型、原题选项、重复或配额跳过的候选显示为 `skipped`，教师的候选拦截计数从审核开始累计。进入修题或复审的中间判定用于追踪过程，最终拦截以审核或交付阶段的决策为准。

业务结果提交后才为各题型和目标档位生成 `mathcraft.question.summary`，复用教师端请求数、交付数、缺额、审核拦截和生成事件计数。零交付但教师结果已提交时也记录缺额。运行取消、需要来源确认、事务失败或提交结果未知时，没有已提交的交付汇总。追踪网络故障仍由有界队列隔离，教师结果与台账保留各自的业务语义。

2026 年 11 月 23 日使用本机 Phoenix 21.0.0 和假模型完成三入口回读，合计 82 条 span。同步参数化足量交付为 `run_d8c441e48c8b4c4c88f2cebbf4c2ed30`，后台参数化修题后交付为 `run_48767330079b5305`，对话地狱档简答缺额为 `run_2e7bc216d82547968f74f46ca4657fe4`。缺额场景核对了三道命题为假及第三轮一次模型超时。

本地验收可用 `MATHCRAFT_PHOENIX_ACCEPTANCE=1` 运行 `backend/tests/test_phoenix_question_acceptance.py`，从固定镜像对应的本机 Phoenix 查询已持久化的 span。

## 配置与降级

安装、配置和部署见 [运维后台运行手册](../operations/运维后台运行手册.md#phoenix-启停)。

开关关闭、可选依赖缺失或扩展配置无效时，业务仍可启动。导出超时、队列满或 Phoenix 不可用时丢弃对应元数据并记录安全日志；队列不持久化，不承诺补发。追踪故障不改变模型请求结果，也不决定后台状态。

## 验收边界

使用假模型和合成数据覆盖两条业务入口、LLM 错误、线程关联、关闭开关、缺少可选依赖及导出故障；确认存储中只有元数据。导出受理不等于记录已持久可查，应读取 Phoenix 核对关联。Phoenix 结果不能替代后台台账或业务成功判断。

旧 `tools/ops_g0` 的 Agent SDK harness、正文采集和清理脚本不属于当前实现或验收流程。

实施与历史验证见[运维后台本地整合验收](../implementation/运维后台本地整合验收.md)。
