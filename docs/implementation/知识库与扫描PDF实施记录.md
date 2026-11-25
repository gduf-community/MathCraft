# 知识库与扫描 PDF 实施记录

现行行为见[知识库模块说明](../design/知识库模块说明.md)和[扫描 PDF 云端 OCR 策略](../design/扫描PDF云端OCR策略.md)。

## 章节定位回归（2026-11-25）

[Issue #27](https://github.com/gduf-community/MathCraft/issues/27) 的旧定位逻辑取最后一次章名匹配，导致第七章页眉前的六节漏掉原文。在隔离目录以假模型重跑简化，逐节检查传入的正文并生成新稿。

| 样本 | 旧定位有正文依据 | 修复后有正文依据 |
| --- | --- | --- |
| 《高等数学》第 8 版上册第七章，使用校验通过的 MinerU 缓存 | 4/10 | 10/10 |
| 同济大学《高等数学》第 7 版下册第八章开头两节，使用 Windows 中文 OCR 抽样 | 0/2 | 2/2 |

修复后的两份样本简化稿均无错误缺失占位。自动回归确认真正缺失的节保留提示，旧简化缓存触发一次重新生成，之后可复用新版。验收使用本地资料与假模型，并在隔离目录生成新稿。

## 知识库备份与本机恢复（2026-11-10）

据本次运行排查反馈，实际 `backend/.venv` 的 Chroma **1.5.9** 在默认系统 `TEMP/TMP` 指向不可写目录时出现原生 `code 14`；新建／相对／POSIX 形式的 Chroma 目录也曾复现。仅将启动该进程的 `TEMP/TMP` 指向可写目录后，原生 probe 已成功，未升级版本、未清空现有 Chroma，也未将改索引目录作为修复。启动进程的临时目录设置见 [后端排错说明](../../backend/README.md#常见问题)。

实际恢复已核验：`output/implementation/documents-recovery-20261110/backup-20261110-155735/` 包含 WAL，并补充 `consistent-before-migration.db` 完整快照。主代理确认 `migration-actual.json` 记录实际库 `h3c4d5e6f789 → i4d5e6f7a890`，users=3／banks=1／documents=1／chunks=0 不变，`quick_check=ok`。`chroma-copy-verified.json` 的原 collections=[]／records=0，Chroma 1.5.9 假向量 add/get/query 成功并清理 probe 集合；`chroma-actual-verified.json` 在原路径 heartbeat／list 成功、collection=0，旧失败位于首次初始化，没有历史索引记录。

`runtime-verified.json` 确认实际 settings service 可读，`vector_store.available=true`、`pending=false`、`rebuild=idle`；原 PDF 仍 failed、chunks=0、原件存在，没有自动重解析或恢复索引。当前无可复用活动管理员会话，未伪造或创建会话；运行 OpenAPI 已确认管理员检索配置的四个操作，不能代替管理员已认证 HTTP／UI 验收。末轮定向验证与独立审查已完成，不将存储恢复等同于真实 OCR／模型可用或完整后端验收，也不改写第 10 节历史失败数字。

## 知识库历史测试批次

### 10.2 既有验收记录（转述，不能累计）

依据 [账号系统整合与审查修复](账号系统整合与审查修复.md) 和 [用户系统实施规格](用户系统实施规格.md)，主线合并完整 pytest 为 **304 passed、79 subtests passed、22 failed**（844.09 秒）。其中 1 项为新增组合上传测试的非成员状态码期望，按既有 404 隐私约定修正后单项复核通过；其余 **21 项**关联 Chroma 原生绑定/tenant 初始化及文档入库失败链路：题库 1、对话 5、文档 7、全流程 1、出题 6、健康 1。文档前置失败阻断的对话权限断言不能视为完成。

2026-11-10 本机另一个批次为 **291 passed、79 subtests passed、21 failed**：20 项为该环境 Chroma 数据库打开失败，另 1 项为迁移建表子进程超时；迁移用例单独复跑 1 passed。两批不是同一次执行，单项复跑也不是全量复跑，不能换算、相加或写成全量通过。

### 10.3 本轮验证记录（2026-11-10）

设置拆分、管理员配置、平台重建与启动收尾的实现已完成；完整后端全量基线已通过，后续修复的末轮定向验证与独立审查已完成，见第 10.4 节。上述历史记录不代表当前完整链路已恢复；隔离测试结果不替代真实 OCR、模型服务或线上部署验收。

### 10.4 上传／预览／运行恢复增量（2026-11-10，已完成）

本轮完整后端全量基线（主代理提供，2026-11-10）：仓库根 `.venv` 在可写进程 `TEMP/TMP` 下运行完整 pytest，**479 passed、81 subtests passed、无失败，耗时 1329.22 秒**，日志 `pytest-full.log`。该基线早于随后追加的 Redis 排队／错误脱敏修复，不能作为这些后续修改的最终全量快照。验证记录统一采用“全量基线＋末轮定向”，末轮后端定向 81 项通过，独立审查的三项新发现均已修复并复核关闭；各批次数量不累计。

本次验收入口为前端 `document-upload-regression.mjs`、`document-preview-regression.mjs`，以及后端文档状态／向量错误边界相关隔离检查。应核对：多文件选择与拖放、首拒绝保草稿、部分成功只重试未提交文件、busy 拒绝与关闭保护、同名不同文件、错误详情与角色权限、文本上限／分页／编码／超时、PDF Blob 生命周期、删除后当前 docs 与选择同步、嵌入／存储错误分类。脚本覆盖及其具体边界见 [前端验证说明](../../frontend/README.md#可复现离线回归与-ci)。

已确认的增量：实际库迁移、Chroma 原路径与运行设置服务检查见第 9 节；仅将进程 TEMP／TMP 指向 `backend/data/tmp` 后标准 `npm run build` 成功，无需历史 manualChunks 分包，typecheck 通过、lint 为 0 errors／3 条既有 warnings，无新增。末轮定向验证与独立审查结果见下方收尾记录。第 10.2 节及设置拆分文档保留的既有数字属于独立历史批次，不能累计或据原生 probe 成功推导成全量通过。

#### 末轮收尾记录（2026-11-10）

后续补丁定向运行 `backend/tests/test_document_failure_recovery.py` 与现有文档接口测试：**81 passed**。覆盖原生 Chroma 假向量读写、Redis 进度缓存失效后仍能调度及重试、OCR／简化／兜底异常脱敏、删除失败保留 SQL 与原件、全局安全 503、下载媒体类型。此结果与前述 479 项全量基线分别记录，不相加，也不称为后续补丁的再次全量执行。

前端最终 typecheck、lint 和标准 build 通过；lint 为 **0 errors、3 条既有 warnings**，build 保留既有大包体积提示，构建进程使用可写 TEMP／TMP。预览 **23 项**、上传 **10 组**、整合 **24 组**回归通过，auth／logout／isolation 会话回归及管理员面板回归通过。整合用例包括删除立即失效、同名上传按 ID 选择、通知与上传交错、切库期间题库列表同步；题库列表和文档列表使用独立版本，待选上传 ID 由最后有效文档结果消费，手动选择、切库和删除清理旧意图。

最终 Ruff 的本轮实现及新增测试通过；全范围仍有 `backend/tests/test_banks.py:73` 的既有 F841。Pyright 为 **16 项既有诊断，无本轮新增**，没有把两项全范围静态检查记为零诊断通过。根 OpenAPI 已重新生成并核对 **108 个 HTTP 操作**，下载声明五种文件媒体类型及二进制 schema，API 索引同步生成。

两名未参与实现的独立审查员覆盖前端 20 个、后端 11 个增量文件：三项新发现（Redis 排队卡死、上传选择被通知刷新吞掉、切库丢弃全局题库列表）已修复并复核关闭，末轮无未关闭发现。OCR 异常脱敏也已独立复核。限定审查及复核记录在 `output/implementation/documents-recovery-20261110/`，备份与证据为忽略的本机运行产物，不提交。

本机后端已用最终源码、原持久化路径、可写进程 TEMP／TMP 和单 worker 再次启动，运行 OpenAPI 四项管理员配置操作及下载媒体类型一致，运行 settings service 的向量存储可用。当前没有可复用的活动管理员会话，未伪造或创建会话，因此未将真实管理员已认证 HTTP／UI 登录流程列为已验收。真实 PDF 保持 failed、chunks=0 且原件保留，由用户主动“重新解析”触发后续处理；本轮没有真实 OCR、嵌入或付费模型验收，也没有清库或升级 Chroma。

## 扫描 PDF 回归记录（2026-11-10）

本轮已完成三个入口及简化各阶段的个人 Key 传递。既有定向回归 79 passed（116.19 秒）；新增隔离回归另批 10 passed（22.59 秒），覆盖个人值覆盖默认值、仅个人值、部署默认兜底、另一 editor 使用自己的配置重解析并复用 OCR、并发任务不串 Key 和缺失小节补写。独立审查未发现本次新增问题，补充假值探针覆盖 JSON 修复、参数兼容重发及简化缓存。命令、静态检查、全量结果和限制统一记录在 [扫描件简化个人 Key 修复](../design/模型配置来源与普通知识库流程.md#扫描件简化个人-key-修复2026-11-10)。未执行迁移、真实模型／MinerU 调用或原失败 PDF 重解析。

以下为既有历史记录，不作为本修复已通过的证据：

主线合并已有记录为 **304 passed、79 subtests passed、22 failed**（844.09 秒）：1 项组合上传测试状态码期望按非成员 404 约定修正后单项复核通过，其余 **21 项**关联 Chroma 原生绑定/tenant 初始化与文档入库失败链路。相关前置失败可让扫描检测/OCR 或后续权限断言没有实际执行，不能据此宣称 OCR 已通过。

2026-11-10 本机另批为 **291 passed、79 subtests passed、21 failed**，其中 20 项 Chroma 相关、1 项迁移子进程超时；迁移单项复跑 1 passed。不得与主线批次混算，也不得用单项复跑改写全量结果；上述历史诊断的当前状态以本轮修复记录中的完整批次结果为准。记录依据为 [账号系统整合与审查修复](账号系统整合与审查修复.md) 与 [用户系统实施规格](用户系统实施规格.md)。

## MinerU 探测与重解析记录（2026-11-13）

本次隔离检查记录：

- 在 `frontend/` 执行 `npm run typecheck`，退出码 0，无 TypeScript 诊断。
- 在 `frontend/` 执行 `npm run lint`，退出码 0，0 errors、3 warnings；两项位于未修改的 `src/components/tabs/RecordsTab/index.tsx:376`（`react-hooks/exhaustive-deps`），一项位于未修改的 `src/store/AuthContext.tsx:43`（`react-refresh/only-export-components`），本次修改的设置组件无诊断。
- 原始 `main` 的 `ping_token` 通过内存模块和假 HTTP 响应对照：14 场景中 10 个误报成功、4 个符合预期。未覆盖工作区源码或读取真实凭据。
- 后端首轮相关三文件回归为 **157 passed、1 failed**（103.27 秒）；失败项为 `test_native_chroma_persists_queries_and_deletes_fake_vectors`，仍是此前已有的原生 Chroma `code 14 unable to open database file` 测试环境问题。此批次不能写成全通过；补充边界回归另行记录。
- 补充凭据格式、网络脱敏、状态码保留、通用失败翻译、单文件成功及辅助批次文件锁定用例后，末批执行 `python -m pytest -q backend/tests/test_model_settings.py backend/tests/test_mineru.py backend/tests/test_document_failure_recovery.py -k 'not test_native_chroma_persists_queries_and_deletes_fake_vectors'`：**172 passed、1 deselected**（105.01 秒）。唯一排除项就是上一批已确认失败的原生 Chroma 环境测试；未将其计作通过，未重跑仓库全量测试。
- 全范围 Ruff 仍有既有 `test_banks.py:73` 的 F841；修改文件无新增 Ruff 问题。Pyright 为 15 项既有诊断，较任务前 16 项减少 1 项结果下载响应可空诊断，没有新增诊断。
- OpenAPI 与 `docs/api.md` 已重新生成并核对 MinerU 路径的鉴权范围说明；`git diff --check` 通过。未执行浏览器交互验收。
- 独立审查指出的凭据请求头异常、HTTP／业务码同时保留、辅助诊断文件写入阻断 OCR 三项问题均已修复并加入回归；末次复核确认关闭。

真实运维复查与自动化测试独立执行，使用已有上传者配置；不变更活动／待应用 embedding 或 rerank 配置。有效 Token 的新鉴权探测通过，明确假 Token 的只读对照返回 HTTP 401 并被判失败。

| 文档 | 已有本地缓存 | 本轮提交与结果 | 本地最终状态 |
| --- | --- | --- | --- |
| 上册，322 页，`doc_f91f3f2413507515` | 12 片中的 `part_00..03` | 只提交缺失 8 片；43 秒后查询到 `part_05`（原 PDF 第 136–165 页）云端 failed，无结构化业务码 | failed／ocr failed，仍保留 4 片缓存，无顶层 full.md |
| 下册，342 页，`doc_891bb1687af8bb9c` | 12 片中的 `part_00..01` | 只提交缺失 10 片；48 秒后查询到 `part_08`（第 226–255 页）云端 failed，无结构化业务码 | failed／ocr failed，仍保留 2 片缓存，无顶层 full.md |

两次完整重解析均在首个已返回失败项处结束，不能据此断言同批其余所有云分片也失败。之后只对上册 `part_05` 做一次 30 页的最小复现，曾查询到 running、21／30 页进度，最终返回 `err_msg="parsing failed, please try again later"`，未提供 `err_code`。该任务编号保存在本地 OCR 运行目录供后续只读追查；原始供应商自由文本不进入用户状态或应用日志。

这证明当前阻塞点是 MinerU 云端解析结果；本轮已越过链接申请、上传、查询及前置向量清理，尚未进入 DeepSeek 简化或 embedding。没有证据指向 Token 无效、额度不足或本地锁冲突，也不能仅凭通用失败信息确定云端内部根因。后续应携任务编号向服务方核查，或另行确认解析模型／分片参数兼容性；本次不自动改变 OCR 模型、减少分片页数或发起更多重试。
