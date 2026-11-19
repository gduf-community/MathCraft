# MathCraft 前端

React 19 + TypeScript strict + Vite + Tailwind CSS，提供教师与学生共用工作台，以及独立的管理员面板。账号由管理员开通，通过后端 HTTP API 认证。

组卷记录及已有学习空间页面支持试卷关闭与恢复；关闭后禁止开始作答和交卷，删除要求关闭，整卷删除还要求各空间停止作答。历史复盘沿用原作答题目和总分，详见 [数据一致性与故障恢复设计](../docs/design/数据一致性与故障恢复设计.md)。

学习空间提供“从本空间移除”操作：先停止该空间作答，且本空间没有任何作答记录时才能移除；已有作答请保留停止状态，以便继续复盘和统计。整卷删除与移除组卷记录仍是独立操作，对话的数据删除确认会说明影响范围。作答创建后若题目快照发生变化，页面暂停交卷并要求重新核对答案；进度轮询遇到短暂断线会继续查询原出题任务。

题库和资料删除失败时保留原操作的重试入口。题库列表显示“删除中／继续清理”，资料 SQL 已清但文件尚未清理时仍显示待清记录；处理中禁用重复提交，确认框等请求成功后关闭，失败在原框内显示原因。

题目预览的“一键清空”只删除预览题目及对应收藏，保留当前会话与对话记录。题目每批最多删除 200 条，全部批次成功后才清理本地题目与勾选；部分批次失败时保留本地原数据和确认框，重试可安全覆盖服务端已删除的题目。聊天、历史加载、数据操作确认或后台恢复正在处理时禁止清空，确认框处理中禁止重复提交及关闭。会话消息与题目预览分别维护请求版本，清空、切换会话或文档、退出登录后，迟到响应不能恢复旧题目或覆盖新会话。

历史快速出题任务的请求 UUID、无凭据参数及待清理 ID 继续按账号保存在本机，刷新后恢复原任务等待或已保存的清理意图；不再提供快速出题面板。恢复仍按原 UUID 幂等查询或补发，并以服务端执行退出与存活题目 ID 为准；清理批次最多 200 条，失败保留剩余 ID，可从标签栏“继续清理历史任务”重试。损坏或缺少补发参数的记录提供显式重置入口，账号变化后停止原账号回填。

清理聊天会话时，仅 `404 / CHAT_SESSION_NOT_FOUND` 视为已删除，覆盖删除成功但响应丢失后的重试；网络失败和其他错误继续保留原会话 ID。

## 目录与模块

| 路径 | 用途 |
| --- | --- |
| `src/api/` | 认证会话、业务请求、题库、文档预览与模型配置接口 |
| `src/api/exportDocx.ts` | 通过现有认证会话请求 Word 导出并下载 Blob |
| `src/api/adminOps.ts` | 管理员 V2 三个只读查询、运行时响应校验和安全错误映射 |
| `src/components/auth/` | 恢复历史视觉的登录页、学生／教师手动身份选择、邮箱验证码与 Turnstile |
| `src/components/auth/AuthDialog.tsx` | 复用 `ConfigurationDialog`，提供邮箱登录、绑定引导及两种密码找回方式 |
| `src/components/auth/LoginEmailBindingDialog.tsx` | 从邮箱登录切换到临时账号认证与邮箱绑定；可返回邮箱登录，撤销失败可重试 |
| `src/components/auth/EmailCodeFields.tsx` | 邮箱发码、验证码和 Turnstile；通过 `onBusyChange` 防止弹窗在发码期间关闭 |
| `src/components/layout/`、`src/components/tabs/` | 工作台布局与出题、预览、题库、收藏等页面 |
| `src/components/layout/HistorySidebar.tsx` | 可折叠历史侧栏，选择题库文档、打开与删除会话 |
| `src/components/tabs/GenerateTab/` | agent 对话布局、模式选择、图片附件、输入框审批、消息操作和生成进度 |
| `src/components/tabs/PreviewTab/ExportModal.tsx` | 已选题目的 Word 导出设置、题型顺序与请求反馈 |
| `src/components/settings/`、`src/components/admin/` | 个人模型设置与管理员面板 |
| `src/components/admin/LegacyOverview.tsx` | 原平台资源与历史批次统计，独立读取真实接口 |
| `src/components/admin/ops/` | V2 运行概览、筛选与 offset 分页、基本详情及共用只读查询 |
| `src/components/ui/` | 提示、确认框等共用控件 |
| `src/components/ui/ConfirmDialog.tsx`、`src/components/ui/SegmentedControl.tsx` | 异步确认弹窗与模式选择 |
| `src/components/ui/Toast.tsx` | 全站共享柔和浅色提示，保留错误／状态播报与会话隔离 |
| `src/store/`、`src/types/` | 认证与业务状态、共用类型 |
| `src/store/ToastContext.tsx` | 按 identity 保持 Provider 挂载，避免退出重试弹窗丢失；提示继续按 generation 隔离 |
| `merge-frontend-regression.mjs`、`merge-session-cases.mjs` | 离线 React 夹具、聊天与历史乱序、清空事务和任务生命周期回归 |
| `src/types/ops.ts` | 对齐正式后端 schema 的 V2 摘要、六状态与 nullable 字段 |
| `src/styles/`、`src/assets/`、`src/lib/` | 样式、静态资源与工具函数 |
| `vite.config.ts` | 开发代理、环境文件隔离与构建配置 |
| `run-regressions.mjs`、`regression-resources.mjs` | 回归顺序、构建、超时与资源清理 |
| `*-regression.mjs`、`e2e-auth.mjs` | 会话、组件与浏览器回归；ops-panel 为离线页面边界，ops-ledger 为正式临时台账联调 |

## 启动

先按[后端说明](../backend/README.md)启动后端及其依赖，再在仓库根目录执行：

```powershell
cd frontend
npm ci
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort
```

访问 `http://127.0.0.1:5173`；端口被占用时命令退出，不自动切换端口。当前环境的 npm wrapper 会错误解析附加启动参数，统一使用 Node 直接执行本地 Vite 入口，保留现有 package scripts。开发服务器仅绑定 `127.0.0.1`，`/api` 和 `/media` 代理到 `http://127.0.0.1:8000`。本机开发时后端也应绑定回环地址，避免通过公共代理或隧道暴露开发账号接口。

### 历史前端对照已结束（5174）

5174 临时对照已于 **2026-11-12 结束并停服**，旧登录与合成页面预览不再作为可用入口。`.scratch/frontend-0b5d4b4/`（含历史预览、依赖与产物）的删除被自动审批审查拒绝，目录尚待清理，仍被 Git 忽略。

历史记录保留：提交 `0b5d4b44a9abe356f9a006a4a3edf4206ebe56ef` 的 82 个受控源文件曾逐个核验一致；附加合成预览曾通过两角色 16 页、16 个深链、4 个详情及请求隔离检查。这些结果不表示旧认证兼容当前后端。原验收范围与清理状态见[恢复设计](../docs/implementation/登录视觉恢复与历史前端对照.md)，合成行为边界见 [STUBS](../STUBS.md#本地历史前端隔离预览2026-11-12)。

## 构建与检查

登录主卡仅提供邮箱登录和忘记密码入口；邮箱登录弹窗固定显示“尚未绑定邮箱？先绑定”。绑定弹窗一次填写账号、当前密码和新邮箱，点击“发送验证码”时自动校验账号密码与角色，再发送邮箱验证码；发送成功才出现验证码框与绑定按钮，并至少等待 60 秒才能重发，修改邮箱也不重置冷却。账号验证成功后清空密码并显示已验证摘要，支持撤销临时会话后返回邮箱登录。个人中心账号安全采用最大约 600px 的纵向表单，依次为学工号、邮箱、修改密码；无已验证邮箱时绑定不再输入密码，解绑独立校验当前密码，修改密码继续使用弹窗。

以下命令均在 `frontend/` 执行：

```powershell
npm run typecheck  # TypeScript 检查
npm run lint       # ESLint 检查
npm run build      # 类型检查并生成 dist/
node node_modules/vite/bin/vite.js preview --host 127.0.0.1  # 本机预览构建产物
```

`vite.config.ts` 使用空临时目录作为 `envDir`，隔离项目环境文件；仓库根 `.env`、`frontend/.env` 及它们的 `.local`、模式变体均不读取。API 公开地址通过 Vite 开发或构建进程的 `VITE_API_BASE_URL` 注入，留空时使用当前站点的同源路径。构建时的地址会写入浏览器产物；构建完成后，仅改变 `vite preview` 进程的环境变量不会重写产物，需要重新构建才能更新地址。`VITE_*` 会进入浏览器代码，不得放入密钥；临时目录权限错误时检查进程 `TEMP`／`TMP` 是否可写。

`VITE_WS_BASE_URL` 同样通过开发或构建进程注入，目前仅供 `src/api/urls.ts` 的 `wsUrl()` 工具函数使用，当前前端没有调用该函数或建立 WebSocket 连接。工具函数的地址回退顺序为 `VITE_WS_BASE_URL`、`VITE_API_BASE_URL`、当前页面来源。

当前 Vite 开发服务器将 `/api` 和 `/media` 固定代理到 `http://127.0.0.1:8000`；`vite preview` 默认继承 `server.proxy`，因此本机构建预览也使用这两条固定代理。部署到普通静态托管时不包含 Vite 代理，需要另行配置 API 与媒体文件访问。

### 可复现离线回归与 CI

使用 Node.js 22（至少 22.13）与 npm，依赖版本由 `package-lock.json` 固定。`playwright-core`、`esbuild` 均为显式开发依赖；浏览器默认使用与本地 Playwright 版本配套的 Chromium，不依赖临时工具目录、NODE_PATH 或系统浏览器路径。已有特定浏览器时可用 `AUTH_BROWSER` 显式指定可执行文件。

Ubuntu + Node 22 的 CI 在仓库根目录执行以下完整命令：

```bash
cd frontend
npm ci
npx --no-install playwright-core install chromium
npm run lint
npm test
```

CI 使用 Ubuntu 24.04 runner 预装的 Chromium 系统库。精简 Linux 环境可用 `npx --no-install playwright-core install --with-deps chromium` 补装系统依赖。Windows 本地安装使用上面的命令。首次安装 npm 依赖与 Chromium 需要网络；安装完成后回归使用内存 API 和假 Turnstile，无需后端、Redis、真实账号、模型或个人环境文件。

`npm test` 与 `npm run test:regression` 都会先执行 TypeScript 检查和一次生产构建，再按以下固定顺序逐个运行脚本：

1. `auth-session-regression.mjs`：HTTP、刷新与 XHR 上传的会话边界。
2. `logout-session-regression.mjs`：退出、失败重试与身份清理。
3. `isolation-session-regression.mjs`：标签、恢复、下载与环境文件隔离。
4. `document-upload-regression.mjs`：真实上传组件、校验与部分失败重试。
5. `document-preview-regression.mjs`：预览传输、渲染、取消与下载。
6. `admin-panel-regression.mjs`：管理员面板、账号操作与模型配置。
7. `merge-frontend-regression.mjs`：主线整合、会话竞态、聊天与通知。
8. `ops-panel-regression.mjs`：V2 页面、筛选分页、错误、竞态、窄屏与生产产物。
9. `e2e-auth.mjs`：完整认证页面与多标签流程，自动启动并关闭本地隔离 Vite。

仅验证聊天、历史、清空事务及后台任务恢复边界时，执行 `node merge-frontend-regression.mjs --chat-only`；旧参数 `--generation-only` 作为同一范围的兼容入口。`merge-session-cases.mjs` 复用离线浏览器夹具，直接验证保留的任务生命周期 Hook，不依赖已移除的快速面板。

运行器固定工作目录为 `frontend/`，保留子进程输出；构建、断言、清理失败或超时均非零退出，并停止后续脚本。类型检查、构建及普通回归各限时 180 秒，完整认证回归限时 300 秒；超时或中断会结束子进程树。浏览器与 Vite 在初始化或测试失败后也会关闭。运维页面测试使用回环端口 5182，认证测试使用回环端口 5178；端口占用时明确失败，都不会复用外部运行的前端。

CI 无需额外执行 `npm run typecheck` 或 `npm run build`。若同一 job 已成功构建当前代码，可执行 `npm run test:regression -- --skip-build`，复用该次 `dist/`。单个回归可用 `node <脚本名>.mjs` 定向运行；单独执行 ops-panel 前需先运行 `npm run build`。完整认证也可用 `npm run test:auth` 单独执行。

截图和运维检查结果默认保存在已忽略的 `frontend/.test-results/`，可作为 CI artifact 收集；`OPS_TEST_OUTPUT` 可显式覆盖运维结果路径。

### 运维台账隔离联调

`npm run test:ops-ledger` 单独运行 `ops-ledger-regression.mjs`，不纳入默认离线回归。它需要先用 `backend/tests/ops_browser_server.py` 启动经过正式迁移的独立临时库后端，并将其生成的种子文件路径通过 `OPS_LEDGER_SEED` 传入；缺少种子文件时立即失败。脚本会发出真实 HTTP 请求，仅供隔离联调 job 使用。配置方法与验收边界见[前端 V2 与联调](../docs/implementation/运维后台前端V2适配与联调.md)。

## 代理和认证配置注意

- 登录支持账号密码和已验证邮箱验证码；用户手动选择学生／教师，登录结果以服务端角色为准，不匹配时退出并提示选择对应身份。管理员可直接进入管理面板。认证可用状态与配置来自 `GET /api/auth/config`，后端配置入口见[根 README](../README.md)。
- 后端允许的 Origin 须包含实际前端来源（协议、主机和端口）。刷新和退出依赖 Cookie、CSRF 与可信来源；生产使用 HTTPS。访问令牌仅保存在内存，刷新凭据由 HttpOnly Cookie 管理；浏览器需支持 Web Locks。
- Turnstile 由认证配置的请求级 `turnstile_enabled` 控制，不使用前端环境变量推断。后端 `TURNSTILE_ENABLED=false` 仅允许在 development/test 环境对实际回环请求生效，生产必须启用验证。
- 开发账号填充仅在 Vite 开发模式、浏览器地址为 `127.0.0.1` 且后端允许时显示；按钮只填充，不自动登录，前端不内置账号或密码。

## 功能要点

- 个人凭据在“个人中心 → API 配置”保存：留空保留，保存后仅显示掩码，眼睛图标可回显本机浏览器保存的完整 Key（在其他电脑配置的 Key 只显示掩码）；连接测试使用已保存配置，未配置 DeepSeek Key 时智能出题禁止发送。管理员在“模型与检索”维护平台模型与索引重建，嵌入模型变更需重建后生效。
- 题库支持 PDF、DOCX、XLSX、MD／markdown、TXT 批量上传；校验格式、空文件及名称／大小／修改时间重复项，部分失败可只重试未受理文件。上传受理后仍需等待后台处理完成，列表可查看失败详情。
- MD／TXT 提供分页文本预览，文本读取上限为 2 MiB；PDF 通过认证请求获取 Blob 后打开窗口，DOCX／XLSX 提供下载。关闭或切换文档时取消预览请求。
- 当前出题界面采用 agent 布局：右侧保留可折叠历史侧栏，选择题库与文档、打开或删除历史会话；“新建对话”保留历史记录，快速面板和快捷提问已移除。保留创新命题、知识答疑、数据管理、图片和操作确认。历史加载期间禁止发送、重试及编辑，Context 入口也同步校验；详情接口必传当前 `mode`，续聊与重试沿用服务端模式，避免误切到快速出题并重置已有上下文。恢复有消息的会话时收起模式控制器，空会话仍显示并选中服务端模式。会话删除等待服务端成功后移出列表，失败保留列表与确认框。消息编辑或回退重发、模式切换与数据操作沿用忙碌保护。

历史视觉记录：此前以 `5155f8a22ac75d2d67a9647e907dc18fedf5162b`（`bca8fb9^1`）为基准恢复旧欢迎区、四个快捷提问与快速面板的阶段已由当前 agent 布局替代。该阶段记录仍见[四模式说明](../docs/design/对话四模式与主线整合.md)与[恢复设计](../docs/implementation/登录视觉恢复与历史前端对照.md)，仅用于追溯。

历史消息回退只裁切前端显示的消息序列，编辑将原消息及附件放回草稿，重发沿用当前会话；现有服务端聊天 API 没有历史截断接口。因此不能保证服务端上下文回到该历史节点，也不能把该入口描述为服务端撤销或新建对话分支。

### 题目导出与公式显示

题目预览页勾选题目后启用“导出”，弹窗支持文档名称（前端最多 80 字符）、独立选择答案与解析、每题下方或文末集中、按题型模块上移／下移。导出池取当前预览题目与已选 ID 的交集，成功通过 `POST /api/export/docx` 下载 Word；失败显示后端错误或默认提示，提交中禁用导出按钮。该入口不创建组卷记录，收藏页的历史 Word／CSV 演示按钮不因此变为真实导出。

后端流式生成只改变模型接收与校验方式，前端仍发送普通聊天请求，并每 1.5 秒轮询进度，完成后接收审核后的题目。全局 KaTeX 字号为 `1em`；只有助手消息的 `.chat-answer` 区域为长公式提供限宽横向滚动，题目预览未套用该滚动规则。题目进入 `Question` 契约时统一常见公式定界符；前端 `Latex` 同时兼容 `$...$`、`$$...$$`、`\(...\)`、`\[...\]`。Word 使用独立的 OMML 转换，支持范围和失败保留文本见 [导出与公式说明](../docs/design/题目Word导出与公式呈现.md)。

### 登录视觉恢复与安全会话

主登录以 `0b5d4b44a9abe356f9a006a4a3edf4206ebe56ef` 为视觉参考，恢复浅蓝背景、左上品牌、桌面左侧宣传与右侧玻璃卡片、粒子和表单视觉。保留动态视觉视口、`auth-stage` 的 `env(safe-area-inset-*)` 安全区留白与卡片内部滚动。375×480 浏览器短视口下重置长表单提交按钮可达检查已通过；手机真机安全区与真实软键盘仍未验证。

主卡进一步对齐历史快照的紧凑密码登录布局，邮箱验证码登录和忘记密码放入独立弹窗。忘记密码先选择联系管理员或已绑定邮箱验证码重置；公开 `admin_contact` 含有效邮箱时显示邮箱及 `mailto:`，仅打开邮件客户端，无有效邮箱时隐藏邮箱行与发邮件入口，保留一般联系指引。本轮不新增管理员邮箱配置功能。弹窗复用 `ConfigurationDialog`，发码或提交期间禁止关闭、Esc 返回及步骤切换，关闭或切换步骤清除验证码与新密码。

学生／教师为可操作的身份单选项，实际权限取自服务端；密码或邮箱登录成功后先匹配角色，不匹配则退出并提示重新选择，服务端撤销失败保留重试退出入口，admin 可直接进入管理员面板。保留 Cookie／CSRF、内存访问令牌与跨标签隔离；绑定接口请求已同步为 `EmailProof`，不再包含 `current_password`。

“绑定邮箱”从邮箱登录弹窗内进入，切换时只显示一个弹窗。先验证现有账号密码、Turnstile 及服务端角色，不调用 `signIn` 或进入工作台。无已验证邮箱的账号（含历史未验证邮箱）可使用 `email_bind` 验证码及 `bindEmail` 完成绑定；认证后即清除密码，不重复提交。成功返回密码登录，返回邮箱登录或关闭前撤销临时会话，撤销失败保留弹窗和退出重试。绑定失败保留邮箱及验证码输入，发码期间不能关闭；已验证邮箱和错选角色按现有规则撤销会话。`ToastProvider` 仅按 identity 设置挂载 key，退出错误更新不会重挂登录页并丢失弹窗，提示仍按 generation 隔离。

此前视觉恢复阶段的 build、typecheck、lint、59 组整合回归及两项会话回归已通过，旧版完整认证 e2e 为 28 次 refresh、0 次意外请求及浏览器异常。后续账号安全布局与免密码绑定采用更新后的认证回归，结果见[登录视觉恢复与历史前端对照](../docs/implementation/登录视觉恢复与历史前端对照.md)的后续优化与验证记录；历史预览另行保留独立验收。

### 全站 Toast

全站 Toast 采用 agent 的柔和浅色样式：信息为浅蓝、成功为浅绿、错误为浅红，顶部居中显示并自动消失，不提供关闭按钮。真实提示由 `ToastContext` 共享，保留会话隔离；错误使用 `role="alert"` 与 assertive 播报，信息／成功使用 `role="status"` 与 polite 播报，两类区域均为 atomic。上传离线回归同时检查真实可见提示的浅色变体与播报语义。

此前按 `0b5d4b44a9abe356f9a006a4a3edf4206ebe56ef` 恢复深色底白字及关闭按钮的说明属于历史记录，已由当前 agent 样式替代；阶段记录见[恢复设计](../docs/implementation/登录视觉恢复与历史前端对照.md)。

### 工作台窄屏布局

小于 768px 时导航改为四列，主内容与历史侧栏纵向排列，账号操作允许换行；历史侧栏可展开或折叠。

### 运维后台 V2

管理员保留平台概览、出题运行、账号管理、模型与检索和账号安全。依赖状态、异常中心、管理员告警、质量统计、自监控和追踪访问演示已从当前前端删除。

前端只消费正式 V2 概览、运行列表和基本详情。使用 status/canceled、limit/offset 和 has_more；数量 null 显示未知、0 显示零，批次已保存不表示质量通过。字段以根 OpenAPI 为准，见[前端 V2 与联调](../docs/implementation/运维后台前端V2适配与联调.md)。

DEV 与生产均只使用真实运维适配器，没有产品内演示开关。有效空结果、无权限、记录不存在及数据不可用分别处理；刷新失败明确标注旧数据。平台资源、账号、模型和安全继续使用既有真实接口。

Phoenix 由后端独立接入，不新增前端必需跳转或正文查看；其可用性不决定业务运行状态，见[独立设计](../docs/design/Phoenix可选扩展.md)。

## 相关文档

- [API 文档](../docs/api.md)：请求与响应契约。
- [Word 导出与公式呈现](../docs/design/题目Word导出与公式呈现.md)：预览导出入口、请求限制、公式转换与样式边界。
- [登录视觉恢复与历史前端对照](../docs/implementation/登录视觉恢复与历史前端对照.md)：历史基准、身份匹配、保留的认证／聊天能力、双端口启动及验收边界。
- [管理员与账号开通设计](../docs/design/管理员与账号开通设计.md)、[账号系统整合与审查修复](../docs/implementation/账号系统整合与审查修复.md)：账号、认证与安全设置。
- [设置拆分与保存反馈设计](../docs/design/设置拆分与保存反馈设计.md)、[模型配置功能规格](../docs/design/模型直接配置功能规格.md)、[配置来源与知识库流程](../docs/design/模型配置来源与普通知识库流程.md)：个人及平台模型配置。
- [知识库模块说明](../docs/design/知识库模块说明.md)、[题目收藏页面设计](../docs/design/题目收藏页面设计.md)：题库、上传预览与收藏。
- 运维方案：[系统方案说明](../docs/design/运维后台系统方案说明.md)、[模块说明](../docs/design/运维后台模块说明.md)、[三人分工](../docs/implementation/运维后台三人实施分工方案.md)、[运行手册](../docs/operations/运维后台运行手册.md)和[Phoenix 可选扩展](../docs/design/Phoenix可选扩展.md)；当前演示边界见 [STUBS](../STUBS.md)。
- [运维代码审查与精简](../docs/implementation/运维后台代码审查与精简.md)：独立双轴审查、冗余删除依据及回归结果。
