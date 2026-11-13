# MathCraft 前端

React 19 + TypeScript strict + Vite + Tailwind CSS，提供教师与学生共用工作台，以及独立的管理员面板。账号由管理员开通，通过后端 HTTP API 认证。

## 目录与模块

| 路径 | 用途 |
| --- | --- |
| `src/api/` | 认证会话、业务请求、题库、文档预览与模型配置接口 |
| `src/api/exportDocx.ts` | 通过现有认证会话请求 Word 导出并下载 Blob |
| `src/api/adminOps.ts`、`src/api/adminOpsDemo.ts` | 旧运维请求适配与 DEV 合成演示，待按新方案收缩；后台查询尚未实现 |
| `src/components/auth/` | 恢复历史视觉的登录页、学生／教师手动身份选择、邮箱验证码与 Turnstile |
| `src/components/auth/AuthDialog.tsx` | 复用 `ConfigurationDialog`，提供邮箱登录、绑定引导及两种密码找回方式 |
| `src/components/auth/LoginEmailBindingDialog.tsx` | 从邮箱登录切换到临时账号认证与邮箱绑定；可返回邮箱登录，撤销失败可重试 |
| `src/components/auth/EmailCodeFields.tsx` | 邮箱发码、验证码和 Turnstile；通过 `onBusyChange` 防止弹窗在发码期间关闭 |
| `src/components/layout/`、`src/components/tabs/` | 工作台布局与出题、预览、题库、收藏等页面 |
| `src/components/tabs/GenerateTab/` | 按 `5155f8a` 恢复历史视觉，保留四模式、图片附件、确认、消息操作和生成进度 |
| `src/components/tabs/GenerateTab/QuickPrompts.tsx` | 恢复历史四个快捷提问，点击仅填入草稿，由用户编辑并发送 |
| `src/components/tabs/PreviewTab/ExportModal.tsx` | 已选题目的 Word 导出设置、题型顺序与请求反馈 |
| `src/components/settings/`、`src/components/admin/` | 个人模型设置与管理员面板 |
| `src/components/admin/LegacyOverview.tsx` | 原平台资源与历史批次统计，独立读取真实接口 |
| `src/components/admin/ops/` | 运维概览、运行／依赖／异常页面、运行抽屉、管理员通知及共用查询与展示 |
| `src/components/admin/ops/OpsExtensions.tsx` | 运维自监控、配置、版本／审核范围证据及告警只读指引 |
| `src/components/admin/ops/useOpsClock.ts` | 使用服务端快照及页面经过时间复核观测有效期 |
| `src/components/ui/` | 提示、确认框等共用控件 |
| `src/components/ui/ConfirmCard.tsx`、`src/components/ui/SegmentedControl.tsx` | 数据操作预览确认与四模式选择 |
| `src/components/ui/Toast.tsx` | 全站共享提示；已恢复 `0b5d4b4` 历史外观，当前内容与触发逻辑保留 |
| `src/store/`、`src/types/` | 认证与业务状态、共用类型 |
| `src/store/ToastContext.tsx` | 按 identity 保持 Provider 挂载，避免退出重试弹窗丢失；提示继续按 generation 隔离 |
| `src/types/ops.ts` | 运维 v1 前端类型与客户端边界，不代表后端 schema 或 OpenAPI 已新增 |
| `src/styles/`、`src/assets/`、`src/lib/` | 样式、静态资源与工具函数 |
| `vite.config.ts` | 开发代理、环境文件隔离与构建配置 |
| `*-regression.mjs`、`e2e-auth.mjs` | 会话、组件与浏览器回归脚本 |

## 启动

先按[后端说明](../backend/README.md)启动后端及其依赖，再在仓库根目录执行：

```powershell
cd frontend
npm install
node node_modules/vite/bin/vite.js --host 127.0.0.1 --port 5173 --strictPort
```

访问 `http://127.0.0.1:5173`；端口被占用时命令退出，不自动切换端口。当前环境的 npm wrapper 会错误解析附加启动参数，统一使用 Node 直接执行本地 Vite 入口，保留现有 package scripts。开发服务器仅绑定 `127.0.0.1`，`/api` 和 `/media` 代理到 `http://127.0.0.1:8000`。本机开发时后端也应绑定回环地址，避免通过公共代理或隧道暴露开发账号接口。

### 历史前端对照已结束（5174）

5174 临时对照已于 **2026-11-12 结束并停服**，旧登录与合成页面预览不再作为可用入口。`.scratch/frontend-0b5d4b4/`（含历史预览、依赖与产物）的删除被自动审批审查拒绝，目录尚待清理，仍被 Git 忽略。

历史记录保留：提交 `0b5d4b44a9abe356f9a006a4a3edf4206ebe56ef` 的 82 个受控源文件曾逐个核验一致；附加合成预览曾通过两角色 16 页、16 个深链、4 个详情及请求隔离检查。这些结果不表示旧认证兼容当前后端。原验收范围与清理状态见[恢复设计](../docs/design/登录视觉恢复与历史前端对照.md)，合成行为边界见 [STUBS](../STUBS.md#本地历史前端隔离预览2026-11-12)。

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

### 上传与预览离线回归

```powershell
node document-upload-regression.mjs
node document-preview-regression.mjs
```

脚本依赖前端已安装依赖、系统临时目录下 `mathcraft-auth-browser` 工具目录中的 `playwright-core` 和已安装 Chromium；可通过 `AUTH_BROWSER` 指定浏览器路径。浏览器依赖不在当前 `package.json` 中声明，运行前需单独准备。脚本使用合成请求，无需后端、真实账号或模型，分别覆盖上传组件与预览传输／渲染边界。

其他定向检查可按需运行：

```powershell
node auth-session-regression.mjs
node logout-session-regression.mjs
node isolation-session-regression.mjs
node admin-panel-regression.mjs
node merge-frontend-regression.mjs
```

### 运维后台离线回归

`ops-panel-regression.mjs` 保留为旧页面的离线合成回归，覆盖待删除的依赖状态、异常中心与通知，不能作为新后台或 Phoenix 的验收依据。后续收缩页面时同步调整脚本；本次仅修改文档。

## 代理和认证配置注意

- 登录支持账号密码和已验证邮箱验证码；用户手动选择学生／教师，登录结果以服务端角色为准，不匹配时退出并提示选择对应身份。管理员可直接进入管理面板。认证可用状态与配置来自 `GET /api/auth/config`，后端配置入口见[根 README](../README.md)。
- 后端允许的 Origin 须包含实际前端来源（协议、主机和端口）。刷新和退出依赖 Cookie、CSRF 与可信来源；生产使用 HTTPS。访问令牌仅保存在内存，刷新凭据由 HttpOnly Cookie 管理；浏览器需支持 Web Locks。
- Turnstile 由认证配置的请求级 `turnstile_enabled` 控制，不使用前端环境变量推断。后端 `TURNSTILE_ENABLED=false` 仅允许在 development/test 环境对实际回环请求生效，生产必须启用验证。
- 开发账号填充仅在 Vite 开发模式、浏览器地址为 `127.0.0.1` 且后端允许时显示；按钮只填充，不自动登录，前端不内置账号或密码。

## 功能要点

- 个人凭据在“模型与服务”保存：留空保留，明确勾选后清除；连接测试使用已保存配置。管理员在“模型与检索”维护平台模型与索引重建，嵌入模型变更需重建后生效。
- 题库支持 PDF、DOCX、XLSX、MD／markdown、TXT 批量上传；校验格式、空文件及名称／大小／修改时间重复项，部分失败可只重试未受理文件。上传受理后仍需等待后台处理完成，列表可查看失败详情。
- MD／TXT 提供分页文本预览，文本读取上限为 2 MiB；PDF 通过认证请求获取 Blob 后打开窗口，DOCX／XLSX 提供下载。关闭或切换文档时取消预览请求。
- 出题界面以 `5155f8a22ac75d2d67a9647e907dc18fedf5162b`（`bca8fb9^1`，前端树与合并提交相同）为视觉基准。用户已明确确认恢复旧视觉并保留快速出题、创新命题、知识答疑、数据管理四模式及图片、确认能力。已恢复历史欢迎区、四个快捷提问、至少两行输入框与文档拖拽提示；快捷提问只填草稿。所有历史用户消息均可编辑或回退后重发，最新助手回复仍可重新生成；生成中、确认请求中或存在待确认操作时保留忙碌保护。即使消息为空，有待确认操作时也显示确认卡。图片用于出题要求抽取，数据删除／改名需先查看影响预览并确认；接口与异步隔离边界见[四模式说明](../docs/design/对话四模式与主线整合.md)，本轮范围见[恢复设计](../docs/design/登录视觉恢复与历史前端对照.md)。

历史消息回退只裁切前端显示的消息序列，编辑将原消息及附件放回草稿，重发沿用当前会话；现有服务端聊天 API 没有历史截断接口，`AppContext` 和接口均未因本轮恢复而修改。因此不能保证服务端上下文回到该历史节点，也不能把该入口描述为服务端撤销或新建对话分支。

### 题目导出与公式显示

题目预览页勾选题目后启用“导出”，弹窗支持文档名称（前端最多 80 字符）、独立选择答案与解析、每题下方或文末集中、按题型模块上移／下移。导出池取当前预览题目与已选 ID 的交集，成功通过 `POST /api/export/docx` 下载 Word；失败显示后端错误或默认提示，提交中禁用导出按钮。该入口不创建组卷记录，收藏页的历史 Word／CSV 演示按钮不因此变为真实导出。

后端流式生成只改变模型接收与校验方式，前端仍发送普通聊天请求，并每 1.5 秒轮询进度，完成后接收审核后的题目。全局 KaTeX 字号为 `1em`；只有助手消息的 `.chat-answer` 区域为长公式提供限宽横向滚动，题目预览未套用该滚动规则。题目进入 `Question` 契约时统一常见公式定界符；前端 `Latex` 同时兼容 `$...$`、`$$...$$`、`\(...\)`、`\[...\]`。Word 使用独立的 OMML 转换，支持范围和失败保留文本见 [导出与公式说明](../docs/design/题目Word导出与公式呈现.md)。

### 登录视觉恢复与安全会话

主登录以 `0b5d4b44a9abe356f9a006a4a3edf4206ebe56ef` 为视觉参考，恢复浅蓝背景、左上品牌、桌面左侧宣传与右侧玻璃卡片、粒子和表单视觉。保留动态视觉视口、`auth-stage` 的 `env(safe-area-inset-*)` 安全区留白与卡片内部滚动。375×480 浏览器短视口下重置长表单提交按钮可达检查已通过；手机真机安全区与真实软键盘仍未验证。

主卡进一步对齐历史快照的紧凑密码登录布局，邮箱验证码登录和忘记密码放入独立弹窗。忘记密码先选择联系管理员或已绑定邮箱验证码重置；公开 `admin_contact` 含有效邮箱时显示邮箱及 `mailto:`，仅打开邮件客户端，无有效邮箱时隐藏邮箱行与发邮件入口，保留一般联系指引。本轮不新增管理员邮箱配置功能。弹窗复用 `ConfigurationDialog`，发码或提交期间禁止关闭、Esc 返回及步骤切换，关闭或切换步骤清除验证码与新密码。

学生／教师为可操作的身份单选项，实际权限取自服务端；密码或邮箱登录成功后先匹配角色，不匹配则退出并提示重新选择，服务端撤销失败保留重试退出入口，admin 可直接进入管理员面板。保留 Cookie／CSRF、内存访问令牌与跨标签隔离；绑定接口请求已同步为 `EmailProof`，不再包含 `current_password`。

“绑定邮箱”从邮箱登录弹窗内进入，切换时只显示一个弹窗。先验证现有账号密码、Turnstile 及服务端角色，不调用 `signIn` 或进入工作台。无已验证邮箱的账号（含历史未验证邮箱）可使用 `email_bind` 验证码及 `bindEmail` 完成绑定；认证后即清除密码，不重复提交。成功返回密码登录，返回邮箱登录或关闭前撤销临时会话，撤销失败保留弹窗和退出重试。绑定失败保留邮箱及验证码输入，发码期间不能关闭；已验证邮箱和错选角色按现有规则撤销会话。`ToastProvider` 仅按 identity 设置挂载 key，退出错误更新不会重挂登录页并丢失弹窗，提示仍按 generation 隔离。

此前视觉恢复阶段的 build、typecheck、lint、59 组整合回归及两项会话回归已通过，旧版完整认证 e2e 为 28 次 refresh、0 次意外请求及浏览器异常。后续账号安全布局与免密码绑定采用更新后的认证回归，结果见[登录视觉恢复与历史前端对照](../docs/design/登录视觉恢复与历史前端对照.md)的后续优化与验证记录；历史预览另行保留独立验收。

### 全站 Toast 样式恢复

全站 Toast 已统一恢复 `0b5d4b44a9abe356f9a006a4a3edf4206ebe56ef` 的顶部居中深色底、白字、圆角、间距、阴影和入场视觉。三个 variant 使用 `bg-ink`（`#1f2937`）、白字和 `px-4 py-2.5 rounded-lg`，移除状态图标，保留关闭按钮与 aria。当前提示文案、业务触发点、成功／错误／信息语义、自动消失时长、手动关闭、无障碍播报及会话隔离保持不变；仍由 `ToastContext` 共享，管理员与教师／学生工作台均可使用。最终检查已通过，详见[恢复设计](../docs/design/登录视觉恢复与历史前端对照.md)。

### 工作台窄屏布局

小于 768px 时导航改为四列，主内容与快速出题面板纵向排列，账号操作允许换行；参数栏可展开或折叠。

### 运维后台前端先行

当前前端仍有依赖状态、异常中心、管理员告警通知，以及质量覆盖、自监控和追踪访问演示。**这些能力已从目标方案删除，本轮尚未删除前端代码。**

目标后台只新增概览中的运行摘要、运行列表和基本详情；既有账号管理、模型与检索、账号安全继续保留。后续由本人清理旧页面、演示、类型和请求适配，见[三人分工](../docs/design/运维后台三人实施分工方案.md)。`ops_runs` 和后台查询接口目前尚未实现。

DEV 合成演示仍需管理员真实登录并显式启用；旧平台资源、账号、模型和安全操作仍调用真实接口。请求出错不能自动切换演示，缺少证据不能显示正常或零失败。

Phoenix 由后端独立接入，不新增前端必需跳转或正文查看；其可用性不决定业务运行状态，见[独立设计](../docs/design/Phoenix可选扩展.md)。

## 相关文档

- [API 文档](../docs/api.md)：请求与响应契约。
- [Word 导出与公式呈现](../docs/design/题目Word导出与公式呈现.md)：预览导出入口、请求限制、公式转换与样式边界。
- [登录视觉恢复与历史前端对照](../docs/design/登录视觉恢复与历史前端对照.md)：历史基准、身份匹配、保留的认证／聊天能力、双端口启动及验收边界。
- [管理员与账号开通设计](../docs/design/管理员与账号开通设计.md)、[账号系统整合与审查修复](../docs/design/账号系统整合与审查修复.md)：账号、认证与安全设置。
- [设置拆分与保存反馈设计](../docs/design/设置拆分与保存反馈设计.md)、[模型配置功能规格](../docs/design/模型直接配置功能规格.md)、[配置来源与知识库流程](../docs/design/模型配置来源与普通知识库流程.md)：个人及平台模型配置。
- [知识库模块说明](../docs/design/知识库模块说明.md)、[题目收藏页面设计](../docs/design/题目收藏页面设计.md)：题库、上传预览与收藏。
- 运维方案：[系统方案说明](../docs/design/运维后台系统方案说明.md)、[模块说明](../docs/design/运维后台模块说明.md)、[三人分工](../docs/design/运维后台三人实施分工方案.md)、[运行手册](../docs/design/运维后台运行手册.md)和[Phoenix 可选扩展](../docs/design/Phoenix可选扩展.md)；当前演示边界见 [STUBS](../STUBS.md)。
