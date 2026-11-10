# MathCraft 前端

React 19 + TypeScript strict + Vite + Tailwind CSS，教师与学生共用工作台，管理员进入管理面板。账号由管理员开通，认证接入真实 HTTP API。主体方案与上传／预览增量已实现；实际 SQL 迁移／存储与运行设置服务已核验，标准 build／typecheck 通过，lint 仅 3 条既有 warnings。完整后端全量基线已通过，末轮定向验证与独立审查已完成；文末及旧章节数字均为各自历史批次，不能累计或视为当前全量通过。

## 启动与开发安全

运行 `npm install` 后执行 `npm run dev`，访问 http://127.0.0.1:5173。Vite 显式只绑定 127.0.0.1；/api 代理至 http://127.0.0.1:8000，后端也必须仅绑定 127.0.0.1。不要加 --host 0.0.0.0，不通过外部共享代理或隧道暴露开发账号接口。

开发填充仅在 Vite DEV、浏览器 hostname 为 127.0.0.1 且 config.development_accounts_enabled=true 时显示。按钮通过本机 POST /api/auth/development-account?role（JSON `{}`）获取 account、password、role，只填充 account 和密码，不提交登录；仍须手动登录，人机验证按 config.turnstile_enabled 的当前请求有效值执行。生产构建不显示按钮，不内置任何账号或密码；后端负责生产不挂载接口并校验来源、Host、代理头与环境。

## Turnstile 临时开关（2026-11-09，已实现并在本机启用）

后端 `TURNSTILE_ENABLED` 默认 `true`；配置 `false` 仅允许 `APP_ENV=development/test` 启动，且仅实际 ASGI peer 为回环 IP（如 `127.0.0.1` 或 `::1`）的请求可跳过。非本机 peer 仍需完整人机验证，Host/Origin/转发头不改变该判定；production 配置 `false` 拒绝启动。前端读取 GET `/api/auth/config` 的必填 boolean `turnstile_enabled`，其值按当前请求计算，不自行依据浏览器 hostname 或 `VITE_*` 推测。

有效值为 `false` 时，所有使用 Turnstile 的登录与发码入口均不挂载 widget、不加载 Cloudflare 脚本，不以票据或 site_key 缺失阻止提交；后端也不调用 Cloudflare。POST `/api/auth/email-code` 和 `/api/auth/login/account` 可省略 `turnstile_token` 或传空字符串。有效值为 `true` 时继续加载验证组件、要求有效票据；后端仍拒绝缺省/空票据及验证失败。账号密码、JWT/会话、CSRF、邮箱验证码及角色/资源权限均保留，关闭人机验证不使邮件验证码可跳过。

本次已向本机后台启动进程注入 `TURNSTILE_ENABLED=false` 后重启后端，不修改真实 `.env` 或密钥。恢复时将该启动进程环境改为 `true` 并重启后端，随后重新加载页面取得配置；若仅去掉覆盖，须保证其他受控配置为默认 `true`。不需要写入前端环境文件。

本机后端已通过启动进程环境 `APP_ENV=development`、`TURNSTILE_ENABLED=false` 重启，监听 127.0.0.1 并使用 `--no-proxy-headers`。8000 和 5173 返回 turnstile_enabled=false、available=true。新增 7 项后端针对性测试通过；前端 typecheck、lint（0 错误、15 条既有警告）、定向 ESLint、auth-session-regression、logout-session-regression 与完整 e2e-auth 均通过。真实 5173 的匿名浏览器检查确认零 Cloudflare 请求、登录按钮可用且无认证配置错误，未提交真实登录。OpenAPI/API 文档已重新生成并核对。2026-11-10 后端全量结果为 291 passed、79 subtests passed、21 failed：20 项对应本环境此前出现的 Chroma 数据库打开失败，另 1 项迁移建表子进程 30 秒超时；该迁移用例单独复跑 1 passed（7.51 秒），未修改代码，超时未再复现。Ruff 保留 10 项、Pyright 保留 19 项既有诊断，本次文件无新增。 其余原有数量保留为调整前记录。

## 认证流程与契约

- 登录页仅“密码登录”“邮箱登录”两种登录入口，默认密码登录；删除注册、学工号登录和身份选择，服务端识别 admin/teacher/student。密码恢复及 admin_contact 联系开户/恢复指引保留。
- 密码登录：POST /api/auth/login/account 发送 account、password，turnstile_token 可缺省或为空；邮箱缺失、未验证或已验证均可使用 account 密码登录。发码 action=email_code，密码登录 action=password_login；config.turnstile_enabled=true 时均须验证 Turnstile，false 时按上述本机边界跳过。
- 邮箱登录：POST /api/auth/login/email 仅 email、challenge_id、code，无 role；仅已验证邮箱可用，不创建用户。config.methods 固定为 [account_password,email_code]；开发填充使用返回的 account，开发接口 role 参数只选样例。
- 公开 POST /api/auth/register、POST /api/auth/login/password 与 purpose=register 删除。UserPayload 必含 email_verified，按其布尔值展示绑定或换绑；学工号保留为资料，当前密码验证其添加、修改、移除，不再用于登录。
- 无已验证邮箱（含历史未验证邮箱）：Bearer 申请 purpose=email_bind 的新邮箱码，再 PUT /api/users/me/email-binding 发送 {email,current_password,challenge_id,code}。挑战绑定 user_id、auth_version、原邮箱快照和目标邮箱，不能跨用户/版本/邮箱使用。
- 已验证邮箱换绑：POST email-change 返回 change_id，分别发送 email_change_old/email_change_new 码；PUT /api/users/me/email 发送 change_id、old_challenge_id、old_code、new_challenge_id、new_code。不能用 email_bind 代替双码。
- 解绑：DELETE /api/users/me/email 的 JSON 为 {current_password}；清空邮箱、规范化值、验证时间，email_verified=false。绑定、换绑、解绑均 204、撤销全部设备会话、清理目标用户状态并回默认“密码登录”；不自动登录或重放操作。
- 教师/学生在个人安全设置操作，管理员在管理面板自身安全区域自助配置邮箱。普通资料接口不发送邮箱、学工号、身份或认证状态。
- 密码恢复 purpose=reset_password，仅已验证邮箱可用，无已验证邮箱时联系管理员。错误验证码/网络错误保留两次新密码输入；成功、离开或重新选流程时清空。新密码 8–64 字符且 UTF-8 ≤72 字节。
- 公开 login/reset 挑战的安全修复绑定用途、邮箱、用户 ID、认证版本，发码/登录/重置一致；邮箱转给他人后旧码不能作用新账号。部署后旧未消费挑战需重发，无数据库迁移，后端最终验证待收尾。
- config 返回 site_key、csrf_token、请求级 boolean turnstile_enabled；认证返回 access_token/token_type/expires_in/user；me 返回 {user}，user-no 与普通资料返回直接 user。reset 发送 new_password、confirm_password；PUT password 发送 old_password、new_password、confirm_password；PUT user-no 发送 user_no（移除 null）、current_password。
- Access 仅存内存；refresh/logout 发送 JSON {}、credentials:include 和 X-CSRF-Token，刷新凭据为 HttpOnly Cookie，不读取或持久化。
- 单标签刷新单飞，Web Locks 跨标签串行登录、刷新、退出、config Cookie 更新及改密/重置/绑定/换绑/解绑响应；需要续期先在锁外完成，锁内不自动刷新或重放安全写请求。BroadcastChannel 按用户/会话/已验证目标邮箱传播失效，不广播 token；不支持安全协调时明确失败。
- 401 写请求仅在 ACCESS_TOKEN_EXPIRED 明确认证阶段未执行时最多重试一次；SESSION_REVOKED、TOKEN_EXPIRED 清理状态，不盲目重放。启动清理旧 mathcraft-auth/mc_token/mathcraft-token。

## 模型配置与知识库边界（2026-11-10）

本轮设置职责拆分、管理员模型与检索及统一保存反馈已实现，验证记录见文末，完整流程见 [设置拆分与保存反馈设计](../docs/design/设置拆分与保存反馈设计.md)。

应用设置仅展示“模型与服务”，由 `src/components/settings/PersonalModelSettings.tsx` 调用 `/api/users/me/model-settings` 保存个人 DeepSeek Key、MinerU Token。留空保留、勾选清除后保存；个人连接测试使用服务端已保存配置及兜底，有未保存输入或写后读回失败时禁用测试。向量／重排只读展示平台活动模型。个人中心仅保留资料和安全设置，不再展示模型编辑或模型状态摘要。

管理员页面采用左侧导航、右侧内容，保留平台概览、账号管理和账号安全，增加“模型与检索”。`RagSettingsPanel` 可分别编辑嵌入／重排的模型标识、服务 URL 和凭据，Chroma 类型、路径与状态只读。经 `src/api/adminRagSettings.ts` 调用 `GET/PUT /api/admin/rag-settings`、`POST .../test` 与 `POST .../rebuild`（202）；响应无明文凭据，密钥留空保留，管理员不提供清除入口。管理员连接测试使用当前草稿但不保存，与个人模型测试规则不同。

嵌入模型／URL 保存后显示“已保存，待重建应用”，同次嵌入凭据跟随 pending；活动嵌入凭据单独更新、重排模型／URL／凭据更新用于后续请求。确认重建后复用 ready 文档的 SQL chunks，无需重新 OCR；旧库继续查询与出题，上传、重解析和文档／整库删除暂时暂停。状态每 2 秒轮询，成功切换、失败保留旧配置和索引及 pending 并支持重试；保存与重建携带 revision，409 冲突时保留草稿，要求载入已保存配置后重新编辑。

`ToastProvider` 位于认证上下文内、业务上下文外，普通工作台和管理员共用顶部居中提示：成功绿色约 3 秒，错误红色约 6 秒，带图标、文字、手动关闭及辅助技术播报；字段错误仍就地保留。覆盖模型与服务、资料与安全操作、题库设置、管理员配置和模型测试，会话失效清除提示并拒绝旧请求迟到反馈。个人配置写入确认后读回失败明确提示“已保存，最新配置读取失败”，禁用测试直到重新读取。

普通设置与管理员模型配置均有草稿保护：未保存修改时内部导航通过 `window.confirm` 确认放弃，取消后保留页面与草稿；保存中阻止内部导航，未保存或操作进行中通过 `beforeunload` 保护关闭／刷新页面。

题库资料主流程继续通过 `/api/banks`，包含三档权限、上传、轮询、预览、重解析及单文档出题；应用设置已移除旧知识库连接、引擎与解析分区，题库配置从题库管理进入。扫描件简化后查看／下载返回当前 MD 产物，独立原 PDF 入口、多资料共同出题和解析版本选择仍有缺口。

当前配置范围及契约见 [模型配置功能规格](../docs/design/模型直接配置功能规格.md)、[配置来源和流程](../docs/design/模型配置来源与普通知识库流程.md) 及 [API 文档](../docs/api.md)；知识库完成情况、权限和验收边界见 [知识库模块说明](../docs/design/知识库模块说明.md)。后端部署前须完成 `i4d5e6f7a890` 的 `alembic upgrade head` 并保持单 worker，详见 [后端 README](../backend/README.md)。本轮验证记录见文末，历史通过记录不替代本轮验收。

## 上传、预览、失败详情与删除缓存

题库新建／编辑／查看共用格式、空文件和名称+`size`+`lastModified` 去重校验，支持 PDF、DOCX、XLSX、MD、markdown、TXT（扩展名不区分大小写，markdown 显示为 MD）。同名不同大小或修改时间允许加入；没有内容哈希／服务端去重保证，不另设前端上传大小上限。选择支持 multiple，虚线区接收全部拖放文件并串行处理，支持 Enter／空格及拖放／键盘焦点高亮；忙时再次加入明确显示红色提示。

新建首请求受理前保留名称与全部文件，首拒绝保留草稿；首成功后记录 `bankId`，后续只上传到该题库。部分成功时保留未受理文件，重试不重复建库或重传已成功文件。批量提交中禁止关闭；新建全部受理成功后才关闭并提示绿色，部分失败保留弹窗与红色详情。受理不等于后台 `ready`。列表将 `error_message/ocr_status` 映射为 `errorMessage/ocrStatus`，通过可访问按钮展开失败原因、处理阶段及 OCR 状态，文本可选择复制；有编辑权限时可重新解析，只读成员仅查看。重试成功表示重新排队，处理中使用信息色。

| 当前格式／边界 | 预览与失败处理 |
| --- | --- |
| MD、TXT | 传递 `docFormat`；严格 UTF-8 与媒体类型校验，最多 2 MiB，按声明长度和流式实际字节双重检查，60 秒超时。TXT 保留源文本，不解释 Markdown／公式 |
| 文本分页 | 每页最多 40 块／2 万 UTF-16 字符单位，只挂载当前页公式；MD 超长单块截断为纯文本并提示下载全文，TXT 连续切页保留全文，切分避免断开代理对 |
| PDF | 点击同步预开窗口，通过认证请求取 PDF Blob（不解码文本），校验 `application/pdf` 后用对象 URL 显示；180 秒超时，窗口内可重试或下载，弹窗被拦截明确提示 |
| DOCX、XLSX | 显示不支持内联预览并提供下载，不触发文本预览 |
| 取消与下载 | 关闭／切换文档／注销取消关联请求，抑制旧反馈，释放对象 URL；主动取消不显示错误。下载同样为 180 秒超时，不受 2 MiB 文本预览上限限制 |
| 错误分类 | 客户端区分 `DOCUMENT_TIMEOUT`、`DOCUMENT_HTTP_ERROR`、`DOCUMENT_CONTENT_TYPE`、`DOCUMENT_TOO_LARGE`、`DOCUMENT_POPUP_BLOCKED`；后台嵌入／向量存储失败使用安全中文消息，OCR／未知异常按结构化分类及固定文案脱敏；上传体积拒绝与文本预览上限按所在环节区分 |

上传受理和重新解析通过 `onChanged() → refreshKbs` 刷新题库与当前 docs 缓存。编辑／查看弹窗确认删除成功后先移除本地行，再调用 `onChanged(documentId)`；`BankTab/index.tsx` 先调用 `AppContext.invalidateDocument(bankId, documentId)`，立即移除当前题库 docs 中的该项、清空对应文档选择并递增请求版本，随后异步刷新。刷新失败时保持删除后的缓存状态，删除前的旧请求不能重新写回已删项。刷新另以会话、题库 ID 和请求版本防止旧响应覆盖，题库消失时清空题库／文档选择和 docs。刷新失败显示错误；客户端缓存失效不表示服务端 OCR／Redis 缓存或全部派生文件已清理。服务端先在事务内清理 SQL、向量成功后 commit、最后删除当前文件，向量失败会回滚 SQL 并保留文件；跨存储异常边界见 [知识库说明](../docs/design/知识库模块说明.md#9-数据布局删除与待实现目标)。

## 目录与模块

| 路径 | 职责 |
| --- | --- |
| src/api/session.ts | 内存会话、CSRF、Cookie、刷新协调、统一认证 HTTP |
| src/api/auth.ts | 严格认证与安全资料契约、密码规则 |
| src/api/backend.ts | 业务请求和 DTO 映射；共用会话传输 |
| src/api/banks.ts | 题库适配、权限与文档字段映射，保留失败详情和 OCR 状态 |
| src/api/documentPreview.ts | 认证预览／下载、2 MiB 文本读取、超时取消和 PDF Blob 窗口生命周期 |
| src/api/modelSettings.ts、adminRagSettings.ts、urls.ts | 个人凭据、管理员模型与重建接口及公开服务地址 |
| src/store/AuthContext.tsx | 会话恢复、登录门禁、退出 |
| src/store/AppContext.tsx | 业务状态与资料保存 |
| src/store/ToastContext.tsx、src/components/ui/Toast.tsx | 普通用户／管理员共用的顶部居中反馈、显示时间与会话隔离 |
| src/components/auth/ | LoginPage、EmailCodeFields、Turnstile |
| src/components/tabs/ProfileTab/ | 基本资料与 SecuritySettings |
| src/components/settings/ | SettingsPage、ModelSettings、PersonalModelSettings，普通设置仅模型与服务 |
| src/components/admin/AdminPanel.tsx、RagSettingsPanel.tsx | 左侧导航／右侧内容，系统模型编辑、只读 Chroma 与重建进度 |
| src/components/tabs/ | 出题、预览、题库、组卷记录、空间、收藏 |
| src/components/tabs/BankTab/BankCreateModal.tsx、BankEditModal.tsx、BankViewModal.tsx | 建库草稿／部分成功重试、批量上传、失败详情、权限与预览分流 |
| src/components/tabs/BankTab/uploadFiles.ts、useDocUpload.ts、shared.tsx | 共用格式／空文件／文件身份去重、串行受理、键盘与拖放上传区、错误展开 |
| src/components/tabs/BankTab/DocPreviewModal.tsx、documentPreviewBlocks.ts | MD／TXT 分页、超长块降级、当前页公式、重试与关闭取消 |
| src/styles/login.css | 既有品牌/背景/玻璃面板与两种登录入口响应式布局 |
| e2e-auth.mjs | 浏览器/HTTP 接缝合成认证回归 |
| merge-frontend-regression.mjs | 主线整合的题库权限、预览、通知及聊天并发离线浏览器回归 |
| document-upload-regression.mjs | 离线真实上传／列表组件、串行与失败草稿／重试、字段映射、权限及预览分流回归 |
| document-preview-regression.mjs | 真实预览传输与组件的有界读取、格式／UTF-8、分页、超时／取消及 PDF 窗口回归 |
| vite.auth-test.config.mjs | 仅回环绑定、独立空环境目录、不代理真实后端的测试服务器 |

## 检查与浏览器验证

`npm run typecheck`、`npm run lint`、`npm run build`。构建使用不读取 .env 的 Vite 配置；部署公开地址通过受控构建环境注入，禁止凭据进入 VITE_*。

本地无需真实邮箱、Cloudflare 或模型。浏览器回归在 HTTP 边界拦截所有 /api/，使用合成数据和假 Turnstile；不以组件内部函数替身断言。

1. 将 playwright-core 安装在临时工具目录（不加入项目依赖）：`npm install --prefix "$env:TEMP/mathcraft-auth-browser" playwright-core`。
2. 执行 `npx vite --config vite.auth-test.config.mjs`，默认 127.0.0.1:5178；可用 AUTH_TEST_URL 指向专用假服务入口。
3. 设置 AUTH_BROWSER 为已安装 Chromium 的绝对路径；未设置时使用本机 Playwright chromium-1217 路径。执行 `node e2e-auth.mjs`。
4. 按当前脚本验证默认密码/邮箱两入口、无注册及身份选择、三角色路由、旧存储清理、恢复/双标签轮换、安全区绑定/双码换绑/解绑、学工号资料及开发 account 填充；本次截图保存在 output/playwright/auth-account/，包含桌面、375px 登录及安全区域。

该验证不代替后端真实数据库、Cookie 安全属性、Redis 并发或 SMTP/Siteverify 测试。真实后端联调使用专用假服务和临时数据，不连接真实账号、生产数据库或未知 Redis。

Windows 若 esbuild 报系统临时目录 Access denied，可将当前进程 TEMP/TMP 指向本任务专用可写临时目录后重试构建；该目录与 dist、node_modules junction 均不得提交。

2026-11-10 本次标准 `npm run build` 已在仅将启动进程 TEMP／TMP 指向可写 `backend/data/tmp` 后成功，无需 manualChunks workaround，未修改仓库构建配置或依赖版本。typecheck 通过；lint 为 0 errors、3 条既有 warnings，无新增。该临时目录及产物不提交。

以下命令保留为此前设置拆分阶段的历史 workaround：当时曾临时分包并保留默认压缩和转译，不修改仓库 Vite 配置；当前标准构建已通过，不再把它作为本次构建的必要条件：

```powershell
node --input-type=module -e "import { build } from 'vite'; await build({ build: { rollupOptions: { output: { manualChunks(id) { if (id.includes('node_modules/katex')) return 'katex'; if (id.includes('node_modules')) return 'vendor'; } } } } });"
```


认证审查回归：在 frontend 目录运行 `node auth-session-regression.mjs`。该脚本通过真实会话模块的公开接口验证认证响应原子提交、跨标签身份切换不重放和旧刷新不清理新登录；仅替换浏览器协调与 HTTP，不访问真实服务。开发账号按钮使用 POST `/api/auth/development-account?role=...`（JSON `{}`），保持精确 Origin 来源校验。原 GET 仅为兼容入口。


### 上传与预览离线回归

本轮完整后端全量基线（主代理提供，2026-11-10）：仓库根 `.venv` 在可写进程 `TEMP/TMP` 下运行完整 pytest，**479 passed、81 subtests passed、无失败，耗时 1329.22 秒**，日志 `pytest-full.log`。该基线早于随后追加的 Redis 排队／错误脱敏修复，不能作为这些后续修改的最终全量快照。验证记录统一采用“全量基线＋末轮定向”，末轮后端定向 81 项通过，独立审查的三项新发现均已修复并复核关闭；各批次数量不累计。

在 `frontend/` 执行 `node document-upload-regression.mjs` 与 `node document-preview-regression.mjs`。脚本复用本机 `mathcraft-auth-browser` 测试工具目录中的 `playwright-core` 及已安装 Chromium，`AUTH_BROWSER` 可指定浏览器路径；不启动后端、无需真实账号或模型。运行前按脚本实际依赖准备测试工具，不将它们误写成已声明的生产依赖。

上传脚本挂载真实新建／编辑／查看弹窗、上传 hook、banks 字段映射和 Toast，替换请求／会话与预览边界，阻断外网。覆盖 multiple／全部拖放文件、串行、首拒绝保草稿、部分成功保留 `bankId` 且只重试未提交文件、busy 拒绝与关闭保护、格式／空文件／同批跨批去重、同名不同文件、失败详情与角色权限、上传／删除回调及 PDF／MD／TXT／Office 分流。它验证回调与预览契约，不据此宣称真实 AppContext 或完整预览实现已经验收。

预览脚本独立覆盖真实预览边界和组件的上限、严格 UTF-8、媒体类型、分页与长块、超时、取消／注销、对象 URL、PDF 窗口／重试／下载及渲染隔离；AppContext 当前文档缓存与选择同步由相应主线整合回归核对。最终预览 23 项、上传 10 组、整合 24 组通过，其余结果见下方「末轮收尾记录」，各批次数量不累计。

### 本次运行恢复与最终验收边界（2026-11-10）

主代理已确认实际库迁至 `i4d5e6f7a890`，业务行数量不变、quick_check=ok；Chroma 1.5.9 在进程可写 TEMP／TMP 下，副本假向量 probe 与原路径 heartbeat／list 通过，运行 settings service 返回 `vector_store.available=true`、pending=false、rebuild idle。原索引记录为 0，原 PDF 仍 failed、chunks=0、原件存在；这不是资料已重新入库或真实嵌入／OCR 已验收。当前没有可复用活动管理员会话，未伪造／创建会话；运行 OpenAPI 四个管理员配置操作存在不等于管理员已认证 HTTP／UI 已验收。备份和证据文件见 [后端恢复记录](../backend/README.md#本机-sqlite-备份与-chroma-临时目录恢复2026-11-10已核验)。末轮定向验证与独立审查结果已记录在下方「末轮收尾记录」。

### 工作台窄屏布局

小于 768px 时，工作台导航改为四列、主内容与快速出题面板纵向排列，顶部账号操作允许换行。页面自然纵向滚动，参数栏展开、折叠和全部操作仍可到达；不使用横向裁切隐藏控件。桌面参数栏宽度及拖拽行为不变。375px 验收应同时检查文档宽度、对话发送、标签切换与参数栏折叠/展开。

PR #8 修复回归：运行 `node auth-session-regression.mjs` 与 `node logout-session-regression.mjs`。前者覆盖真实 XHR 上传的预刷新、显式过期单次重试、撤销不重放、角色／账号变化和旧响应隔离；后者覆盖注销使用原 Bearer（不刷新）、无本地凭据不匿名注销、不广播清除其他账号及旧注销不清除新登录。退出依赖 Origin/CSRF 与当前标签 Authorization，允许 access 过期后安全撤销原 sid。

注销网络失败后，登录页显示失败说明和“重试退出”按钮，并保留仅用于撤销重试的内存凭据；点击按钮会真实重试原 sid，旧退出失败不会覆盖新登录状态；确认后清除，新显式登录成功后才丢弃它；登录网络、解析或映射失败仍保留原退出重试凭证。未确认期间拒绝刷新恢复；重新加载保留 sessionStorage 的非凭据退出阻断标记；内存中的撤销重试凭据会丢失，不保证网络不可达期间已完成服务端撤销。

## main 账号整合说明

账号由管理员开通，所有启用账号默认使用 account 密码登录；可选已验证邮箱登录，均由服务端识别三角色，页面不选身份。管理员安全区域支持自身邮箱配置，历史邮箱不自动验证，未验证邮箱不阻断密码登录。运维管理员进入管理面板，不能进入题库教学工作台。个人资料保存等待服务端成功，空手机号可清除；未填写性别不默认选择。个人模型凭据通过用户级接口保存或明确清除，连接测试只针对已保存凭据。当前支持的个人模型配置与认证边界见 [整合设计](../docs/design/账号系统整合与审查修复.md)。

会话回归：`node auth-session-regression.mjs`、`node logout-session-regression.mjs`、`node isolation-session-regression.mjs`。管理面板离线回归：`node admin-panel-regression.mjs`。`src/components/settings/PersonalModelSettings.tsx` 为当前设置页的个人模型编辑组件，个人中心不再挂载。Vite 使用启动时新建的空临时目录，隔离项目 `.env` 文件；进程显式注入的 `VITE_*` 仍属于公开前端配置。

## 主线整合验证（2026-11-10）

本轮以 `a9424fb` 为共同语义基线，对照账号分支 `937b83d` 与 `origin/main` 的 `4a89c2d`，检查有冲突及自动合并的全部重叠前端文件。题库保留仅教师可新建、创建者按登录账号添加成员、创建者／可编辑／只读三档权限和关闭凭题库编号加入；保留远端文档预览、后台入库与进度、通知、出题审核字段及对话暂停／编辑／重发。性别空值、两种登录入口、可选已验证邮箱及管理员工作台隔离保持现有账号契约。

新建并上传 `POST /api/banks/with-document` 使用 `authenticatedOperation`，校验响应结构并解析后端 `detail.code`；仅明确 `ACCESS_TOKEN_EXPIRED` 可续期后重试一次。撤销、未知 401、身份或角色变化均不重放。上传 API 保留 `eta_minutes`，映射为预计等待时间。预览 `GET /api/banks/{bankId}/documents/{docId}/download?inline=1` 统一经 `sessionFetch`，在 text/blob 正文读取完成后再次检查会话代次；旧账号内容不得显示或打开新标签。题库详情补全、后台批量上传与入库轮询同样绑定发起会话，首个题库创建失败即停止后续上传。

通知、聊天进度及暂停接口均经统一 `request`。通知仅刷新当前选中题库的文档；刷新返回时若已换库或换账号则丢弃。教师清除题库通知红点不会调用仅学生可用的催交接口。暂停立即释放当前聊天操作，旧结果和 finally 不得覆盖新对话或清理新轮询；退出／工作台卸载清理轮询并中止当前请求。文档状态、阶段及进度在 `KbDocument` 上显式声明，侧栏不依赖无依据断言。

本轮实际检查：`npm run typecheck` 通过；`npm run lint` 为 0 错误、15 条既有警告，位于 EngineParsingFields、LightRagRoleFields、RecordsTab 与 AuthContext，本轮无新增诊断。`npm run build` 通过；Windows 默认 TEMP 首次遇到 esbuild 清理权限错误，进程 TEMP/TMP 指向本任务专用目录后重跑成功。构建仍提示主包大于 500 kB，最终主 JS 约 780.46 kB（gzip 230.02 kB）。

三组会话 Node 回归 `auth-session-regression`、`logout-session-regression`、`isolation-session-regression` 与 `admin-panel-regression` 全部通过。前者新增真实创建并上传 XHR 的预续期、单次过期重试、撤销不重放、旧响应隔离及错误结构验证；隔离脚本新增延迟预览正文跨账号拒绝、当前会话预览成功和入库等待间隙换账号后停止旧文档轮询。

运行 `node merge-frontend-regression.mjs` 进行针对性离线浏览器回归：实际渲染 React 组件及题库适配层，业务服务使用合成数据，浏览器所有网络均阻断，不启动后端、不使用真实账号或读取个人环境文件。结果如下：

- 教师可创建、学生无创建弹窗；后台多文件队列成功，首个创建失败或切换账号后不发送后续上传。
- 创建者／可编辑／只读的成员管理、上传和删除控件符合权限，入库进度保留。
- 文档预览的成功、空内容、错误提示均通过；点击关闭或预览遮罩均不关闭父题库弹窗。
- 外部题库通知不替换当前题库文档，换库后的旧刷新被丢弃，账号变化后停止通知请求，教师清红点不误调学生接口。
- 暂停后发送新消息，旧结果不写入、旧 finally 不清理新请求，当前轮询保留；换账号后停止快速出题轮询；工作台卸载清除全部轮询。浏览器无 pageerror。

本轮按新增风险完成上述定向浏览器检查，未重复完整 `e2e-auth`；早期完整认证浏览器结果保留为历史记录。本节只记录前端结果，后端全量、Chroma 环境失败及静态诊断以主任务同步文档为准。检查与构建均未复制个人 `.env` 或读取 `local_secrets`；`node_modules` 使用原工作区依赖 junction，`dist` 与临时构建目录不提交。

## 本次实施验证（2026-11-09）

本次已通过前端 typecheck；lint 为 0 错误、15 条原有警告。build 在独立 TEMP 重试成功，首次失败为 esbuild 默认 TEMP 清理权限问题。OpenAPI 与 docs/api.md 已在测试隔离环境重新生成并核对注册/学工号登录路由删除、绑定/解绑存在、EmailLogin 无 role、UserPayload.email_verified 为必填字段。

本次已通过 auth-session-regression、logout-session-regression、isolation-session-regression、admin-panel-regression、e2e-auth 五个脚本，五个脚本 ESLint 为 0 错误、0 警告。浏览器无异常或意外外网请求；桌面与 375px 截图已完成视觉检查，产物在 output/playwright/auth-account/，包含 login-desktop/mobile 及安全区 8 张截图。本次七份文档的相对本地链接检查 missing_local_links=0。后端用户 ID 绑定修复后的 127 项认证相关测试已通过。Ruff（含 scripts）保留 11 项既有诊断、Pyright 保留 19 项既有诊断，新增诊断均为 0，本次修改文件的 Ruff 通过。后端完整 pytest 已执行：285 passed、79 subtests passed、20 failed，耗时 16 分 26 秒。20 项失败集中于文档、聊天、出题和健康检查，底层 Chroma PersistentClient 报 `InternalError: (code: 14) unable to open database file`；独立新目录初始化同样复现，无需经过认证或业务 API。扫描 PDF 用例也在扫描检测前的向量清理处中断。本次认证用例没有失败，但完整后端验收未通过，不能将本轮记录为全量通过。

## 本轮设置拆分验证记录（2026-11-10）

三组会话 Node 脚本和桌面／320px／375px 的 19 项隔离浏览器检查已通过，未访问真实服务。最终 `npm run typecheck` 通过，`npm run lint` 为 0 errors、3 条既有 warnings（旧孤立组件清理后由 15 条降至 3 条）。默认 `npm run build` 遇到 esbuild 输入临时文件删除 `Access denied`；保持仓库原构建配置，通过 Vite Node API 临时传入 katex／vendor 的 manualChunks 分包参数、保留默认 minify／target 后生产构建通过。admin-panel-regression 与 merge-frontend-regression 两组既有浏览器回归均通过，包含未保存确认与保存／读回期间导航保护。完整记录与验证边界见[设置拆分设计的本轮验证记录](../docs/design/设置拆分与保存反馈设计.md#验证记录)，历史批次不替代本轮结果。

#### 末轮收尾记录（2026-11-10）

后续补丁定向运行 `backend/tests/test_document_failure_recovery.py` 与现有文档接口测试：**81 passed**。覆盖原生 Chroma 假向量读写、Redis 进度缓存失效后仍能调度及重试、OCR／简化／兜底异常脱敏、删除失败保留 SQL 与原件、全局安全 503、下载媒体类型。此结果与前述 479 项全量基线分别记录，不相加，也不称为后续补丁的再次全量执行。

前端最终 typecheck、lint 和标准 build 通过；lint 为 **0 errors、3 条既有 warnings**，build 保留既有大包体积提示，构建进程使用可写 TEMP／TMP。预览 **23 项**、上传 **10 组**、整合 **24 组**回归通过，auth／logout／isolation 会话回归及管理员面板回归通过。整合用例包括删除立即失效、同名上传按 ID 选择、通知与上传交错、切库期间题库列表同步；题库列表和文档列表使用独立版本，待选上传 ID 由最后有效文档结果消费，手动选择、切库和删除清理旧意图。

最终 Ruff 的本轮实现及新增测试通过；全范围仍有 `backend/tests/test_banks.py:73` 的既有 F841。Pyright 为 **16 项既有诊断，无本轮新增**，没有把两项全范围静态检查记为零诊断通过。根 OpenAPI 已重新生成并核对 **108 个 HTTP 操作**，下载声明五种文件媒体类型及二进制 schema，API 索引同步生成。

两名未参与实现的独立审查员覆盖前端 20 个、后端 11 个增量文件：三项新发现（Redis 排队卡死、上传选择被通知刷新吞掉、切库丢弃全局题库列表）已修复并复核关闭，末轮无未关闭发现。OCR 异常脱敏也已独立复核。限定审查及复核记录在 `output/implementation/documents-recovery-20261110/`，备份与证据为忽略的本机运行产物，不提交。

本机后端已用最终源码、原持久化路径、可写进程 TEMP／TMP 和单 worker 再次启动，运行 OpenAPI 四项管理员配置操作及下载媒体类型一致，运行 settings service 的向量存储可用。当前没有可复用的活动管理员会话，未伪造或创建会话，因此未将真实管理员已认证 HTTP／UI 登录流程列为已验收。真实 PDF 保持 failed、chunks=0 且原件保留，由用户主动“重新解析”触发后续处理；本轮没有真实 OCR、嵌入或付费模型验收，也没有清库或升级 Chroma。
