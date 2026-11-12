# SDK Agent 接入与实际业务 G0 验收

日期：2026-11-13。开发目标分支为长期 `agent`，修改前基线为 `05cc44d65d456f12733a0e8a7dccb3b24f3c35ff`；原本地 `main` 为 `4fa87d7490ea359cf1be4dba743f3419db04ebf7`。只有完成独立审查及实际 G0 后才集成到本地 main，不推送。

## 目标、范围和验收标准

保留固定检索、出题、审核、修补、重出及最终求解，只替换已受理出题中的单次模型执行。SDK 执行、业务编排及安全观测分别由 `agent_sdk.py`、原 RAG/审核模块和 `generation_observation.py` / `agent_tracing.py` 承担。接口及扩展方法见 [Agent 开发指南](Agent开发指南.md)。

`GENERATION_LLM_BACKEND=sdk|legacy` 在受理时固定。SDK 使用 Agent → Runner → OpenAIChatCompletionsModel，单轮、无工具/handoff/session，HTTP 和 SDK 重试均为零；原业务允许的 JSON 修复、预算升级及 thinking 参数回退仍由原调用位置决定。缺执行依赖为安全 503；追踪缺配置、导出失败或满队列均不得改变业务结果。

事件只由注入的内存收集器保留，不在应用中积累生产事件列表。每个 run 固定账号、入口、会话/任务和 SDK trace ID；逐工作项传播上下文。异步受理先记录 accepted，后台执行记录 started/ended。题目事务成功后产生 batch 及逐题版本事实，助手回复事务及关联单独记录。取消请求不构造权威终态；审核异常放行仍为 unknown。

本轮不增加五个 ops 路由、运维 SQL、持久事件幂等、周期心跳、告警及清理调度。G1 冻结这些模块的契约，G2 实现，G3 负责贯通验收。

G0 必须由真实 HTTP 入口、实际 SDK/业务事务和真实本地 Phoenix 的独立读取共同支持。模型提供方底层使用 HTTPX MockTransport；检索/嵌入允许合成替身，不请求真实模型。还须核对正文排除、单一本地出口、并发归属、模型失败、审核降级、取消、两次事务、导出故障/恢复、缓冲满和真实公开删除能力。

## 运行环境与安全证据

- SDK `0.20.0`、OpenInference adapter `2.7.0`、OTel `1.45.2`、OpenAI `2.54.0`、HTTPX `0.28.1`；根/后端 `sdk-agent` 可选组及锁文件同步。
- 独立 Phoenix `21.0.0`，镜像 digest `sha256:b5bcec3455bd5c431f52737fc62046c081752b483e3fff40c63f40783736bcad`。
- 本轮专用容器 `mathcraft-ops-business-g0-20261113`，仅宿主回环 `127.0.0.1:6026`，限制 2 CPU、2 GiB，运行时抽样约 471.4 MiB / 3.90% CPU；抽样不是峰值承诺。
- 忽略目录 `D:/vscode project/math_agent/deeptutor_and_mathcraft/MathCraft/.scratch/ops-business-g0-20261113/` 保存独立凭据、数据及安全证据，报告不得复制凭据值。旧 6016 实例和他人数据不参与本轮操作。
- 生产导出先按安全属性白名单排除任意正文、事件正文和原异常，再复用已审查的脱敏/有界传输。仅允许数值回环 HTTP `/v1/traces`。初始化只执行一次，首 trace 前替换默认处理器链。

正文保留采用已选定的公开 REST 时间窗删除机制，目标 3 天、每日一次、24 小时窗口、每次最多 8 个窗口。隔离 `ops-g0-retention-sdk20261113a` 项目实际删除两条四天前根/子 span，保留两条当前对照，重复删除安全；证据为上述目录的 `retention-sdk20261113a.json`。原生到期设为 maxDays=0，避免双调度。本轮只验证能力，正式调度、持久游标、迟到 span 和活动摘要保护由乙/M8 在 G2/G3 落地。

## 检查记录

测试环境使用临时 SQLite、每测试独立进程内 FakeRedis，禁止外部模型网络并注入假秘密模块。Windows 默认临时目录不可写会造成 Chroma code 14；本轮仅对测试进程设置 TEMP/TMP/SQLITE_TMPDIR 到 D 盘 `.scratch/sdk-g0-tmp`，没有修改机器 ACL、真实配置或业务数据。

| 范围 | 已取得结果 |
| --- | --- |
| 原生成/对话/审核/模式/权限基线 | 80 passed；此前 11 项环境失败在可写 TEMP 下全部消失 |
| SDK 单次执行及资源清理 | 56 passed，实际原生 SDK + 假 HTTP transport |
| 联合兼容回归 | 158 passed；包含 SDK、tracing、观测及原业务，最后受理字段修正另有 29 passed 覆盖 |
| 最后受理/事件/原生成接口 | 29 passed，其中观测 21 项、生成 8 项 |
| 独立 G0 工具 | 40 passed，无跳过；实际 HTTP harness 安全测试另 3 passed |
| 前端 | typecheck/lint/build 通过；0 错误、3 条原有 lint 警告和原有大分包提示；59 组整合、2 组管理面板、23 组 ops 浏览器回归通过；ops 内含 174 项扩展断言、28 次页面/宽度溢出检查，0 意外请求及未处理异常 |
| Ruff | 新增/修改范围通过；全库仅既有 `test_banks.py:73 F841` |
| Pyright | 相同工作区布局下干净 agent 基线 42、当前 42，未新增诊断；不把原 main 目录的 15 项与隔离 agent 环境直接相减 |
| 完整后端 | 769 passed、115 subtests passed，1176.10 秒；随后 close/submit 修复的受影响 tracing/transport/verifier 三模块 38 passed、21 subtests passed |
| 实际业务 Phoenix | 最终矩阵 13/13 场景、432 个持久 span、563 条安全事件、62 次假模型 HTTP 请求，0 真实模型及未授权网络 |
| 独立审查 | Standards / Spec 原范围及追加启动边界均通过；具体整改与独立复现见下节 |

完整后端命令为 `.venv/Scripts/python.exe -B -m pytest -q -p no:cacheprovider`，静态检查为 `ruff check --no-cache backend/app backend/tests tools/ops_g0` 及前端 Pyright。首轮全量曾有 9 项失败（8 项独立工具回环端口被统一禁网拒绝、1 项事件版本字段切换时的旧收集函数），定位后定向通过，最终完整重跑取得上述结果。最后停机竞态变更只复核受影响范围，不无理由重复整套。独立工具另用 unittest discovery；实际业务运行器不执行 pytest 自动模型替换。

## 实际业务与故障证据索引

实际入口命令为 `.venv/Scripts/python.exe -B -X utf8 -m tools.ops_g0.business --home <隔离目录> --base-url http://127.0.0.1:6026 --label ops-g0-business-final`。在 HTTPX 的模型 transport 层打桩，实际经过 HTTP 登录、生成/对话接口、原生 SDK、审核/修补/重出/求解及 SQLite commit；检索、embedding、rerank 为假服务，就绪文档由夹具预置，不把文档入库纳入本轮声明。

最终项目 `ops-g0-business-final-33173f4b` 有 13 个根、56 个非根执行 AGENT、56 个 LLM，全部 LLM 父链经过非根执行 AGENT。192 个业务阶段、3 次重出尝试的事件配对、持久 span 锚点及继承元数据核对通过。两名教师各自通过 HTTP 登录并发生成，provider barrier 确认重叠，账号、run、root、batch 均分别不同；同一真实会话两条连续消息的 run/root/batch 不同，两次助手回复关联提交均核对通过。

矩阵还覆盖同步/异步、模型失败、审核异常放行、快速/创新命题、修补重出求解、执行确认取消、第一次成果 commit 成功而第二次回复关联 commit 失败，以及恢复后的新样本。accepted=exported=独立读取 span 数=432，failed/dropped/boundary_errors/rejected_responses/pending 均为零。安全 verifier 的 6 项反例测试通过，拒绝把根 AGENT 算成执行 Agent、LLM 绕过执行 Agent，以及 stage/attempt 元数据缺失或错配。

同一生产 buffer 的停机/满队列/恢复另行验收：before/outage/recovery 三次同步 HTTP 均 200 且批次成功；停机样本耗时 0.226 秒（假模型条件）。1024 个合成压力 span 令队列达到上限 64；停机后累计 failed=115、dropped=942、pending=0，恢复后累计 exported 从 37 增至 69，前后 69 个 control span 独立可读。没有重建 buffer，没有增加模型重试；13 次模型请求均为假 transport。

Phoenix 授权实测无凭据 401、无效假 key 401、独立授权 200，没有复用 MathCraft Cookie。公开清理的过期/未过期与重复对照见上节；逐 trace 访问授权审计尚待 G2，真实前端正文入口仍关闭。

安全报告留在被忽略目录，提交中仅保存索引和 SHA-256，不纳入临时账号、配置、SQLite、追踪数据或凭据：

| 证据文件（相对原工作区） | SHA-256 |
| --- | --- |
| `.scratch/sdk-g0-tmp/business-evidence/ops-g0-business-final-33173f4b.safe.json` | `65e69494088d17d90083d1c5f2065f83e4a908b76f4836ac5a16c16917d1de68` |
| `.scratch/ops-business-g0-20261113/export-faults-c.safe.json` | `101de34db0152c5964e05471955e6a0b32d738a72fe39f33f6f5e34df139d8c0` |
| `.scratch/ops-business-g0-20261113/authorization.safe.json` | `e884a39771fe7cfff1fdd6eeaeb840676dc5fd27847098f5159dde2a0c2059f1` |
| `.scratch/ops-business-g0-20261113/retention-sdk20261113a.json` | `ed4063be6a7f8c2f677d93f9dd7188d5638168a49903c722b4fb01311f12eea9` |

前端仅修正回归脚本的两个历史登录按钮 locator，产品界面及请求契约保持原结构。runtime OpenAPI 新增三处安全 unavailable 503 声明；完整重新生成同时补齐旧静态契约遗漏、但运行时已经存在的 Word 导出等 schema，没有引入对应新功能。五个 ops 路径仍未注册。

## 门禁与集成状态

**G0 与 agent 独立审查通过。** 实际 SDK HTTP 业务、Phoenix 持久读取、上下文/版本/两次事务、脱敏、本地单出口、导出故障恢复、独立授权及公开清理能力证据齐全；原业务与前端无新增回归。agent 通过后集成到本地 main；具体合并 SHA 及 G1 状态由后续冻结交接记录登记。G2/G3 未实现、未验收。

## 独立审查整改

使用仓库 code-review 技能，由没有附带编写上下文的 Laplace（Standards）和 Beauvoir（Spec）分别审查基线 `05cc44d` 到候选 `069cbd4` 的 53 文件，并独立复核后续修复。两轴结论分别记录，不用一轴通过掩盖另一轴问题。

| 审查轴 | 发现及修复 |
| --- | --- |
| Standards | lifespan 的 finally 覆盖启动恢复失败；端口在线程创建前校验，意外发送错误结清队列；工具测试只放行自行绑定的数值回环端口；客户端构造/enter/exit 失败关闭准入并报告 unavailable；正常 close 与 submit 共用锁，防止空队列 worker 退出后接受孤立项目 |
| Spec | OI 2.7 不转发 custom_span.data，改用上下文 metadata 继承 stage/attempt；审核异常放行保持业务原行为，但事实标 unknown 且不计 passed；G0 要求非根执行 AGENT 及所有 LLM 父链；并发与同会话多 run 改由真实 HTTP 登录和出题驱动 |

最后 close/submit 修复在候选后新增，传输文件 SHA-256 为 `fbc78c42e1cbf75bc513177dc4238585bf77d7f1d4e1fc60e8fe4de29260e106`。Standards 的五项问题均已独立关闭；审查者在旧竞态暂停点重复 10 轮，放行后均 accepted=exported=1、pending=0，反向先关闭顺序也拒绝入队且无遗留线程。Spec 原四项均独立关闭。没有通过修改测试 Redis、添加真实模型调用或放宽外部网络来取得通过。

Spec 追加发现 SDK 默认 provider 首次准备会构造云端 HTTPX 客户端，无效 `SSL_CERT_FILE` 会令追踪关闭时也启动失败。应用改为先直接安装空 `DefaultTraceProvider`，避免该惰性默认客户端；异常及退出清理只操作已保存引用。新进程实际 lifespan 在无效 CA 且禁止默认导出器构造的条件下验证启动/退出；provider 准备失败也不逃出 lifespan，SDK 受理前安全 unavailable。本地 exporter 故障仍不影响已可执行 SDK 的业务。

该修复后重新执行完整实际 HTTP/Phoenix 矩阵，项目 `ops-g0-business-provider-final` 再次 PASSED：13 场景、432 span、563 安全事件、62 假请求、0 真实模型、0 失败/丢弃。最新安全报告 `.scratch/sdk-g0-tmp/business-evidence/ops-g0-business-provider-final.safe.json` 的 SHA-256 为 `6b61e7bbccc0a9c71ebdfa5f52872e24c09199cece8b629394df8cd7d628d314`；前述首次矩阵及故障/授权/清理报告保留作补充，不覆盖失败的历史尝试。

最后 provider 修复由全新 Avicenna 复核 Standards，由 Beauvoir 独立验证 Spec：无效 CA 的实际 lifespan 连续启动/关闭两次；provider 构造或安装失败不逃出启动且受理前 503、无 accepted 事件，legacy 可用；OTLP 初始化或导出客户端失败仍各执行一次原生 SDK 假模型请求；正常路径仍有非根 Agent/LLM 且不导出正文。默认处理器构造次数均为零，两轴无剩余阻塞。修复后五模块 118 passed、21 subtests passed，随后新增的受理前 provider 不可用测试 1 passed；Pyright 仍为同布局基线 42 项，无新增。

主线集成还发现 11 项普通字符串迭代器兼容失败：资源关闭逻辑原先直接要求 `.close()`，与 `Iterator[str]` 边界不符。修复先在 agent 开发：对提供 close 的 SDK/legacy generator 注册退出回调，普通迭代器保持原解析行为。新增边界回归，保留原 SDK 提前解析失败/取消/流关闭的清理测试；复核后重新集成，结果在 G1 交接记录登记。
