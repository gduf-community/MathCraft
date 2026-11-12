# 扫描 PDF 云端 OCR 策略

> 本文记录当前 `backend/app/` 与根 [openapi.json](../../openapi.json) 的 MinerU 云 OCR、知识点简化及简化稿索引。2026-11-10 的个人 DeepSeek Key 修复及其隔离回归作为历史记录保留在第 8 节；当前 MinerU 修复与真实重解析结果见第 8.1 节。通用权限、文档和检索契约见 [知识库模块说明](知识库模块说明.md)。

> 2026-11-13 更新：MinerU 探测成功判定、安全 OCR 诊断和个人设置页提示已修复；原失败 PDF 已保留缓存各重解析一次，均再次失败在云端解析。上册失败分片的单片复现返回 `parsing failed, please try again later`，没有业务码。实现与验收见第 1.1、3.4、6.1、8.1 节；本结果不代表 OCR 或后续模型链路已通过。

## 1. 目标、范围与历史边界

扫描 PDF 通过题库文档上传进入后台任务后，先调用 MinerU 云端取得 Markdown，再尝试生成知识点简化文档，供 SQL/FTS5/Chroma 检索与单文档出题使用。当前不提供本地 MinerU、LiteParse、Docling 切换入口。

实际入口为 `services/documents.py:run_ingestion`、`services/mineru.py` 和 `services/knowledge_simplify.py`。旧 `backend/src/MathCraft/services/parsing/ParseService`、LlamaIndex provider、统一解析 IR、`document_parsing.json`、`MINERU_MODE` 云/本地切换及历史 `/api/settings` 均不是当前契约。旧文档中的 `scanned_pdf_mineru_cloud_not_configured/scanned_pdf_mineru_cloud_failed` 也不是当前实现的稳定错误码。

普通 PDF、DOCX、XLSX、MD、TXT 使用当前格式解析器；本策略仅在入库文档 format 为 PDF 且扫描检测命中时执行。不能将 parsing/base.py 的 OCR 占位协议描述为当前题库扫描件尚未接入 OCR：题库入库在调用普通 PDF parser 前已经分流至 MinerU。

### 1.1 本次修复设计范围（2026-11-13）

目标是消除 MinerU 配置测试的假成功，并让实际 OCR 失败能在不泄露上游内容的前提下定位阶段、错误码及分片。覆盖 MinerU 客户端、文档入库错误出口、连接测试接口和个人设置页提示。

- 探测使用合法全零 UUID `00000000-0000-0000-0000-000000000000` 作为不存在的批次 ID，只读取批次结果，不创建或上传解析任务。通过条件见第 3.4 节。
- 个人设置页将 MinerU 成功提示与 DeepSeek 分开，使用“鉴权通过，实际解析仍受额度和任务结果影响”，并明确测试只验证连接／鉴权，不保证任务解析、额度或内容可用。
- 后端增加 `operation/provider_code/http_status/part_index` 安全结构化 OCR 错误，由既有文档错误文本显示阶段、码和片号，不新增公开接口字段或前端接口类型，详见第 6.1 节。
- 沿用操作者个人凭据优先、部署默认兜底，以及顶层 `full.md`、分片 `part_XX/full.md` 和简化稿的既有缓存复用条件；不增加强制刷新、缓存失效或数据库迁移。用户授权的真实重解析与假服务自动化测试分开记录。

验收区分静态检查、假服务隔离回归和真实重解析，具体标准与证据边界见第 8.1 节；尚无结果的项目不得标记通过。

## 2. 扫描检测与参数

`mineru.detect_scanned_pdf` 用 PyMuPDF 提取每页文字并去两端空白，计算：

~~~text
page_count == 0       → 非扫描，返回 (False, 0)
total_chars < 50      → 扫描
total_chars / page_count < 30 → 扫描
其他                 → 普通文字层 PDF
~~~

不检查页面图像、不要求全文文字完全为空。只有少量文字的文件、短篇文字 PDF 或空白但有页数的文件也可能命中；没有 OCR 质量评分、乱码检测或按页混合解析保障。

普通 `PdfParser` 自身保留平均每页少于 20 字符时调用 OCR 占位引擎的逻辑；常规题库路径先用更高的扫描阈值分流，不能将两个阈值合并成一个检测契约。

MinerU 客户端使用代码固定的 API v4 基址 `https://mineru.net/api/v4`、`model_version=vlm`，申请上传链接时发送：

~~~json
{
  "enable_formula": true,
  "enable_table": true,
  "language": "ch",
  "model_version": "vlm",
  "files": [{"name": "<文件名>", "is_ocr": true}]
}
~~~

`is_ocr=true` 直接属于请求载荷，没有读取/回写全局解析器设置，也没有普通 MinerU 与强制 OCR 的配置签名分流机制。

## 3. 权限、配置来源与接口字段

### 3.1 权限与上传入口

平台教师可通过 `POST /api/banks/with-document`（multipart name、单个 file）新建题库并上传首文档，201 返回 bank/document。已有题库通过 `POST /api/banks/{bank_id}/documents`（multipart 单个 file）上传，须 creator/editor，202 返回：

~~~text
document_id, name, status, stage, progress, eta_minutes
~~~

readonly 可以查看状态、下载和检索/出题，不能上传或重解析。平台管理员被教学资源鉴权排除，不能借管理员身份调用文档能力；非成员返回 404。组合创建先提交题库，上传失败不保证回滚空题库。

支持 PDF/DOCX/XLSX/MD（含 .markdown）/TXT；默认上传上限 200 MiB。上层上传限制与 MinerU 客户端的 200 MiB 检查分开；`mineru_limits.max_pages=200` 是接口展示值，当前客户端对超过 200 页的扫描 PDF 会尝试分片，而非直接按整本文档页数拒绝。

### 3.2 配置优先级与本轮简化修复

| 阶段 | 当前来源与边界 |
| --- | --- |
| OCR Token | 上传/重解析按本次操作者解析 UserModelSetting.mineru_token，无个人值取系统 MINERU_DEFAULT_TOKEN，传给后台任务；并非固定使用原上传者 |
| 简化知识点 LLM | 在请求受理时解析本次操作者的个人 DeepSeek Key，无个人值取服务端 settings.deepseek_api_key；显式传入 run_ingestion 及 knowledge_simplify 各阶段 |
| 简化模型和地址 | settings.deepseek_model/deepseek_base_url，默认 deepseek-flash；不是逐用户模型选择 |
| 简化后嵌入与检索重排 | 管理员维护的平台活动配置优先于部署默认模型、地址与凭据；沿用活动／待应用配置及索引重建切换规则 |
| 后续参数出题/HyDE | 使用出题者个人 DeepSeek Key 优先、服务端 Key 兜底；本轮将扫描简化对齐到本次操作者个人 Key 优先的规则 |

修复前，简化调用未传操作者 Key，只使用服务端 DeepSeek Key；该缺陷已修复。最新要求已替代先前访谈 Q2 的“取消服务端兜底”决策：个人 DeepSeek／MinerU 配置优先、部署默认兜底，管理员嵌入／重排活动配置优先、部署默认兜底。个人连接测试成功仍不能代替扫描入库的完整行为验收。

本轮覆盖新建题库并上传、已有题库上传和重解析三个入口。各入口在受理时按本次通过鉴权的操作者解析有效 DeepSeek Key，传给后台 `run_ingestion`，再显式传入 `knowledge_simplify` 的目录提取、线程池分批概括和缺失小节补写，直到最终模型调用。共享资料不借用原上传者或创建者的个人 Key；受理后修改设置不改写本次已传入的值。

修复仅涉及内部传参，保留 OCR／简化缓存复用与现有异常处理，HTTP 请求响应结构、状态码和鉴权边界保持不变；不新增页面字段、迁移、强制刷新接口或真实服务调用。无个人 Key 时可使用部署默认；个人 Key 调用失败不等于自动改用部署 Key 重试，凭据和错误均沿用既有脱敏边界。

个人入口为 `GET/PUT /api/users/me/model-settings`。PUT 字段 `deepseek_api_key/mineru_token` 各最长 128；省略/null 保留，空串或纯空白清除个人值，返回 saved=true。GET 仅提供配置状态、掩码、模型标识、系统内置模型及 MinerU 限制，不能从 configured/using_default 推定有效凭据存在。

`POST /api/users/me/model-settings/test-mineru` 调用有效 Token 的探测，`POST /api/users/me/model-settings/test-deepseek` 使用个人优先的有效 Key；两者均会外呼，本次未执行。配置来源只从调用代码确认，未读取 .env 或 local_secrets.py 的真实值。

### 3.3 轮询、重解析和下载

| 方法与路径 | 当前行为 |
| --- | --- |
| `GET /api/banks/{bank_id}/documents` | 文档数组，按创建时间倒序 |
| `GET /api/banks/{bank_id}/documents/{document_id}` | 单文档 SQL 状态轮询 |
| `POST /api/banks/{bank_id}/documents/{document_id}/reprocess` | creator/editor，无请求体，仅 ready/failed 可用，202；其他状态 400 BAD_STATE |
| `GET /api/banks/{bank_id}/documents/{document_id}/download` | 读当前 storage_path；inline 默认 false；MD inline 为纯文本 |
| `DELETE /api/banks/{bank_id}/documents/{document_id}` | creator/editor，204；删除不等于完整回收所有 OCR/原件派生产物 |

列表/详情字段为 `id/bank_id/name/format/size_bytes/page_count/is_scanned/status/stage/progress/chunk_count/ocr_status/error_message/created_at`。内部 ocr_error/ocr_task_id/ocr_result_path/text_source 不在该公开载荷中。OpenAPI 的多处成功响应尚未细化 schema，字段需结合当前路由读取。

### 3.4 MinerU 连接／鉴权探测修复契约

修复前的 `ping_token` 使用非 UUID 批次 ID，并将除 HTTP 401 外的响应视为成功，可能误报权限不足、限流或服务异常。目标改为请求 `GET /extract-results/batch/00000000-0000-0000-0000-000000000000`，使用本次操作者已保存的有效 Token，不提交待保存输入。

响应必须为合法 JSON 对象，且满足以下任一条件才允许通过：

1. HTTP 为 2xx，`code` 为整数 `0`，且 `data` 为 JSON 对象。
2. HTTP 必须为 200，`code` 为官方 `-60012`（整数或字符串），对应“找不到任务”的不存在批次响应；该分支不要求成功结果的 `data` 对象。其他 HTTP 状态不能由此放行。

`code=0` 必须严格判断整数类型，不能把布尔值、字符串 `"0"` 或浮点数当作成功；找不到任务仅允许精确匹配官方 `-60012`，不能按任意错误文案放行。HTTP 401／403／429／5xx 及其他非 2xx、其他业务码、缺失 code、非法 JSON、非对象顶层 JSON、`code=0` 但 `data` 缺失或为非对象，以及网络异常、超时均失败，不能由响应文案或 `data` 存在推定成功。

通过只表示本次探测的连接／鉴权检查通过，不能保证上传、任务解析、额度、结果完整性或内容可用。设置页保留 DeepSeek 的连接测试提示，MinerU 独立显示“鉴权通过，实际解析仍受额度和任务结果影响”；默认 Token 状态也不得写成实际解析可用。接口仍使用既有 `ok/limits` 成功响应及既有失败契约，不增加请求／响应字段或前端类型。

## 4. 核心流程、分片与缓存

1. 保存源文件和 uploaded 文档行，向 FastAPI BackgroundTasks 传入 document_id、有效 MinerU Token，以及请求受理时按操作者解析的有效 DeepSeek Key。
2. 后台确认文件存在，先调用 Chroma 删除旧向量，成功后再删旧 SQL chunks、FTS 并提交；之后才进入 parsing 和扫描检测。Chroma 清理失败时保留 SQL／FTS，但不承诺外部向量操作原子回滚。
3. 扫描命中则记录 page_count/is_scanned，进入 ocr、ocr_status=running。
4. 先检查有效 Token；为空则 failed，提示“未配置 MinerU Token，无法解析扫描版 PDF”，内部 ocr_error 为 token missing。即使存在 full.md，也先经过 Token 检查。
5. 如果 `settings.ocr_path()/{document_id}/full.md` 已存在，直接复用；否则向 MinerU 申请上传 URL、PUT 文件、轮询结果、下载 ZIP，提取 full.md。
6. OCR 完成后尝试复用或生成知识点简化稿，按 Markdown 章节解析为 ParsedBlock；生成时将已传入的有效 DeepSeek Key 显式传至目录提取、线程池概括与补写，命中简化缓存仍可跳过 LLM。
7. 切片与 jieba 分词，写 SQL/FTS5 并提交；调用 bge-m3 写 Chroma，完成后才 ready，发送入库通知。

单文件云流程轮询间隔 5 秒，上限 600 秒。超过 200 页时当前代码先拆 PDF：首片前 15 页用来提目录，其余按 `max(30, ceil((页数-15)/15))` 页切片，计划总片数最多 16；同批申请、上传并轮询，按顺序合并为顶层 full.md。分片轮询上限为 `min(3600, max(600, 240×待识别片数))` 秒；上传和结果下载有局部重试，不能据此宣称完整任务自动重试。极大页数时分片公式也不保证每片均不超过 200 页。

分片可复用 `part_XX/full.md`，但不是可靠持久化任务队列或完整检查点系统。单文件结果 ZIP 若含子目录，客户端可递归找到 full.md，但上层缓存复用只检查顶层 full.md，不能保证所有成功 OCR 结果都再次命中缓存。

缓存只按文档 ID 路径或文件内容标记复用，没有源 PDF 哈希、OCR 参数、模型/提示词指纹验证，也没有 HTTP 强制刷新参数。`doc.ocr_task_id="local"` 是当前成功落库值，不是云任务 ID。客户端将最近一次申请成功的批次编号写入对应 OCR 目录的 `last_batch_id.txt`，便于失败后只读核查；只保存受限格式的编号，不保存 Token、签名 URL 或整份响应，不据此自动恢复云任务。

## 5. 简化 MD 替换与原件预览缺口

`knowledge_simplify.build_simplified_markdown` 清洗 OCR 文本，提取目录，定位章节，分批概括，再按章组装；产物目标是保留核心公式、排除例题习题的知识点文档。生成步骤可能补写缺失小节，但不能承诺内容完整性、公式准确度或原 PDF 页码映射。

成功时：

- 简化稿写 `uploads/{bank_id}/{document_id}_simplified.md`；
- 保持相同 Document ID，name 改 `<原名>_知识点简化版.md`、format 改 MD、storage_path 和 size_bytes 指向简化稿；
- 原 PDF 仍通常保留在 `uploads/{bank_id}/{document_id}.pdf`，没有另建公开文档记录；
- 后续入库、FTS、向量和出题参考均使用简化稿，而非同时索引原 PDF。

简化缓存仅检查文件是否以 `# 《` 开头且前 300 字含“知识点简化版”；符合时跳过本轮 LLM，回退 OCR 全文产物通常不符合此标记。不能将“重新解析”等同于重新调用 OCR 或重新生成简化稿。

下载/查看只读取当前 storage_path，所以简化成功后返回 MD；`inline=true` 使用 `text/plain; charset=utf-8`。当前没有 original/simplified 切换参数或独立原 PDF 预览接口，不能把“物理保留 PDF”写成“用户可预览原件”。

重解析通过 MD 格式、名称后缀和固定 PDF 路径寻找原件；存在时还原 PDF 属性后重跑并可能复用缓存。如果原件不存在，按当前 MD 处理，不保证提示原件丢失，也不会自动重建原 PDF。

## 6. 异常、后台任务与一致性边界

| 情况 | 当前结果 |
| --- | --- |
| 无有效 OCR Token | 文档 failed，error_message 为缺少 Token，内部 ocr_error=token missing；没有历史 scanned_pdf_* 稳定码 |
| MinerUError（如云端失败、超时、缺产物） | `_ocr_failure` 保持安全分类，failed，内部记录安全 ocr_error；增加阶段、业务码与片号的诊断见第 6.1 节 |
| HTTP/ZIP/解析等其他异常 | 沿用外层失败处理；不能保证都归类为 MinerUError，OCR 结构化包装与脱敏验收要求见第 6.1 节 |
| 简化服务错误 SimplifyServiceError | failed，提示简化生成失败；不回退原文 |
| 简化目录/内容类一般异常 | 写临时 Markdown 为 OCR 全文并用于索引，保留原 PDF 名称、格式和下载路径；后续仍可能因嵌入等失败 |
| 解析结果/切片为空 | failed，不发布 ready |
| 嵌入/Chroma 失败 | failed，SQL/FTS 可能已经提交，没有完整回滚 |

当前 `_fail` 会把 running 的 ocr_status 改为 failed；OCR 已 done 后的简化或嵌入失败仍可保留 done。progress=100 也可表示失败。应组合 status、stage、error_message 判断，不能只看 OCR 子状态或百分比。

入库使用进程内 BackgroundTasks，进度写 SQL 与 Redis `ingest:task:{document_id}`（默认 7200 秒），详情从 SQL 读取。重启时只将 parsing/ocr/chunking/embedding 改 failed，要求重新解析；不会自动续跑、同步 Redis 或处理 uploaded。当前无完整入库互斥、取消和任务版本防旧写保障。

解析前先调用 Chroma 清理旧向量，成功后才删除并提交旧 SQL chunks／FTS；因此 Chroma 初始化或清理失败仍可在扫描检测前阻断流程，但此时尚未删除 SQL／FTS。清理成功后的后续失败没有旧索引恢复；新 SQL／FTS 与向量写入也不是同一事务。不能宣称重解析失败始终保留旧可用版本。

删除接口只沿当前 storage_path 清理文件，不能保证原 PDF、OCR/分片目录、临时稿、Redis 记录全部同步回收。此处记录当前边界，不在本次文档任务中修改代码。

### 6.1 安全结构化 OCR 错误

由 MinerU 客户端在申请上传链接、上传文件、轮询结果、云端解析、下载结果、解压／读取产物等边界包装错误，单文件和分片路径使用同一内部错误契约；入库服务只读取经过校验的字段生成错误文本，不分析或拼接原始异常字符串。阶段值使用固定枚举 `submit/upload/poll/parse/download/result`，并保留 `request/probe` 表示通用请求与连接测试，展示时映射为中文阶段。

| 内部字段 | 约束与展示 |
| --- | --- |
| `operation` | 固定阶段枚举，展示“申请上传链接／上传文件／查询任务／云端解析／下载解析结果／读取解析结果”等；不能接受上游任意字符串作为阶段 |
| `provider_code` | 从响应提取并严格限制格式和长度的业务码，兼容整数码及 `A0202` 等短码；若任务仅在 `err_msg` 中携带已知码，只允许提取白名单码并使用本地固定说明，正文一律丢弃；未知或不存在时省略，不虚构 `0` |
| `http_status` | 已取得响应时记录真实 HTTP 状态整数；连接失败等无响应情况省略，不能将状态码当成业务码 |
| `part_index` | 已知具体分片时携带原始零基索引，以 `part_XX` 显示片号并对应既有缓存目录，如索引 1 显示 `part_01`；单文件或整批错误不虚构片号 |

例如展示“OCR 解析失败：查询任务；业务码 -60012；HTTP 200；分片 part_01”（仅为格式示例，不是本次真实失败记录）。HTTP 403／429／5xx、业务失败、任务 `state=failed`、非法 JSON、结构缺失、超时及 ZIP／产物错误都应产生安全失败信息；没有业务码的错误仍可展示已知阶段、HTTP 状态及片号，不把所有任务失败归因于 Token。

公开 `stage/error_message`、内部 `ocr_error`、通知和日志只使用安全字段及固定说明；禁止回显任意上游 `err_msg/msg`、完整响应／任务对象、签名上传／下载 URL、Authorization、Token 或 Key，也不能因保留异常因果链而打印含敏感 URL 的原始堆栈。已知通用消息 `parsing failed, please try again later` 只在完整字面量匹配时翻译为固定中文重试建议，仍按失败处理，不增加自动重试。辅助批次编号文件写入遇到锁定、只读等 `OSError` 时，仅记录固定告警和异常类型，不阻断 OCR。此设计不扩展公开响应类型，缓存命中与已有分片重试边界保持不变。

## 7. 待实现目标

1. 为原 PDF、OCR 全文、简化稿建立显式关联，分别授权预览/下载并标明来源。
2. 使用持久化任务队列，覆盖 uploaded 等所有中断状态，支持互斥、取消、重试和任务版本校验。
3. 新索引完成后切换，失败保留旧版本，提供 SQL/FTS/Chroma 一致性修复。
4. 以源文件哈希、解析/模型配置和产物完整性校验缓存，提供显式强制刷新与统一结果目录。
5. 提供扫描/混合 PDF 质量门禁、公式与章节完整性验收、页码溯源和派生文件完整回收。

操作者个人 DeepSeek Key 优先、服务端兜底的简化修复已完成，验收记录见第 8 节；以上目标仍待实现。

## 8. 验收标准与记录口径

以下为整体行为验收标准；本轮个人 Key 修复的隔离回归结果单独记录在表后，不将其等同于真实云端全流程验收：

| 场景 | 应验证的结果 |
| --- | --- |
| 扫描阈值 | 总字符少于 50 或平均每页少于 30 命中，零页非扫描；不依赖页面图像 |
| 权限 | creator/editor 可上传/重解析，readonly 不可写但可读；平台管理员无教学权限，非成员 404 |
| Token 与缓存 | 使用操作者有效 Token；无 Token 时即使有 OCR 缓存仍失败；有顶层 full.md 时可跳过云调用 |
| 云端请求 | 固定 v4/vlm、formula/table/language/is_ocr 载荷正确；普通文字层 PDF 不走该云分支 |
| 大文档 | 超 200 页按现行计划分片、复用已完成片、按页序合并，超限与失败信息符合客户端行为 |
| 三个入口与操作者 | 新建并上传、已有库上传、重解析均在受理时选取本次操作者的有效 DeepSeek Key 并传给 run_ingestion；共享资料不取原上传者或创建者的个人 Key |
| 个人优先与服务端兜底 | 个人和部署默认同时存在时用个人 Key；仅个人 Key 存在且无简化缓存时能完成假模型简化；无个人值或清除后沿用部署默认，两者皆无时沿用缺配置处理 |
| 简化全阶段传参 | 目录提取、线程池概括、缺失小节补写及最终模型调用收到同一有效 Key；受理后修改设置不改写在途任务的已传入值 |
| 缓存与兼容 | 既有 OCR／简化缓存继续复用，简化命中可跳过 LLM；普通文档不新增简化调用；请求响应、权限及管理员配置规则不变，无页面新字段或迁移 |
| 简化成功 | 同一文档 ID 替换为 MD，索引引用简化稿；下载/inline 返回 MD，原 PDF 预览缺口明确 |
| 简化失败 | 服务错误 failed；内容错误回退 OCR 全文且保留 PDF 条目，不能混为同一策略 |
| 重解析与重启 | ready/failed 才能重解析；恢复原件依赖固定路径；处理中重启变 failed，uploaded 缺口明确 |
| 一致性 | Chroma 前置清理失败可能阻断 OCR，此时 SQL／FTS 尚未删除；清理后的重建失败不承诺恢复旧索引，不将百分比 100 视为成功 |

自动化回归只使用假模型、假凭据和隔离数据。当前 [conftest.py](../../backend/tests/conftest.py) 使用每测试独立 `fakeredis.FakeRedis` 替换 cache.get_redis，不需要连接或清空本机 Redis 15 号库。

本轮已完成三个入口及简化各阶段的个人 Key 传递。既有定向回归 79 passed（116.19 秒）；新增隔离回归另批 10 passed（22.59 秒），覆盖个人值覆盖默认值、仅个人值、部署默认兜底、另一 editor 使用自己的配置重解析并复用 OCR、并发任务不串 Key 和缺失小节补写。独立审查未发现本次新增问题，补充假值探针覆盖 JSON 修复、参数兼容重发及简化缓存。命令、静态检查、全量结果和限制统一记录在 [扫描件简化个人 Key 修复](模型配置来源与普通知识库流程.md#扫描件简化个人-key-修复2026-11-10)。未执行迁移、真实模型／MinerU 调用或原失败 PDF 重解析。

以下为既有历史记录，不作为本修复已通过的证据：

主线合并已有记录为 **304 passed、79 subtests passed、22 failed**（844.09 秒）：1 项组合上传测试状态码期望按非成员 404 约定修正后单项复核通过，其余 **21 项**关联 Chroma 原生绑定/tenant 初始化与文档入库失败链路。相关前置失败可让扫描检测/OCR 或后续权限断言没有实际执行，不能据此宣称 OCR 已通过。

2026-11-10 本机另批为 **291 passed、79 subtests passed、21 failed**，其中 20 项 Chroma 相关、1 项迁移子进程超时；迁移单项复跑 1 passed。不得与主线批次混算，也不得用单项复跑改写全量结果；上述历史诊断的当前状态以本轮修复记录中的完整批次结果为准。记录依据为 [账号系统整合与审查修复](账号系统整合与审查修复.md) 与 [用户系统实施规格](用户系统实施规格.md)。

### 8.1 本次修复验收与记录（2026-11-13）

以下是本次新增验收要求，不能用第 8 节的个人 Key 历史回归代替：

| 范围 | 验收标准 | 本次证据状态 |
| --- | --- | --- |
| 探测请求 | 假服务确认请求全零 UUID 的不存在批次，无任务创建、文件上传或未保存凭据参与 | `test_model_settings.py` 真实客户端／HTTP 假传输覆盖 |
| 探测允许条件 | 2xx 且整数 `code=0`／对象 `data`，或仅 HTTP 200 且官方 `code=-60012` 可通过 | 整数／字符串找不到任务码与正常成功响应分别覆盖 |
| 探测拒绝条件 | 401／403／429／5xx、其他业务码、非法 JSON、缺字段、错误类型、网络异常和超时均失败 | 假响应覆盖；非 ASCII、空白和控制字符 Token 在构造请求头前安全拒绝 |
| 设置页提示 | DeepSeek 保留连接测试语义；MinerU 成功 toast 和页内 notice 均提示“鉴权通过，实际解析仍受额度和任务结果影响”；测试前说明仅连接／鉴权，不保证解析、额度或内容可用 | 前端实现与静态检查结果另记；未做浏览器交互验收 |
| 安全诊断 | 校验 operation、业务码、HTTP 状态和原始 part_XX 编号；未知字段不虚构 | HTTP 与业务码同时保留；单文件成功、分片失败和真实上传到通知出口分别覆盖 |
| 脱敏 | 在响应与异常中植入假敏感标记，状态、通知、日志均不得泄漏 | `test_mineru.py` 及既有失败恢复测试覆盖；特定通用失败原文仅精确匹配后翻译为固定提示 |
| 缓存兼容 | 已完成分片不再上传，新旧结果按原页序合并，再调用完全命中缓存 | 201／322 页真实假 PDF 与 HTTP 假服务覆盖；最近批次文件只含编号 |
| 真实重解析 | 依用户授权复用缓存各重跑一次，区分鉴权和实际任务状态 | 两本均再次云端失败；单片最小复现亦失败，详见下表 |

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

## 9. 当前实现入口

- [文档入库服务](../../backend/app/services/documents.py)：上传、状态、OCR/简化分支、索引先删后建。
- [MinerU 客户端](../../backend/app/services/mineru.py)：检测、v4 云请求、分片、轮询与缓存。
- [知识点简化](../../backend/app/services/knowledge_simplify.py)、[LLM 客户端](../../backend/app/services/rag/llm.py)：本轮有效 DeepSeek Key 的显式传递目标、模型调用与简化产物。
- [文档路由](../../backend/app/api/documents.py)、[题库依赖](../../backend/app/deps.py)：权限、轮询、重解析和当前文件下载。
- [模型设置](../../backend/app/services/model_settings.py)、[个人接口](../../backend/app/api/users.py)：操作者个人配置及部署兜底解析。
- [检索实现](../../backend/app/services/rag/retrieval.py)、[启动处理](../../backend/app/main.py)：简化稿消费与重启中断状态。
