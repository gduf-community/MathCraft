# MathCraft 前端

React 19 + TypeScript strict + Vite + Tailwind CSS，提供教师与学生共用工作台，以及独立的管理员面板。账号由管理员开通，通过后端 HTTP API 认证。

## 目录与模块

| 路径 | 用途 |
| --- | --- |
| `src/api/` | 认证会话、业务请求、题库、文档预览与模型配置接口 |
| `src/api/adminOps.ts`、`src/api/adminOpsDemo.ts` | 运维真实请求适配与仅 DEV 显式启用的合成演示；五个 ops 后端接口仍待实现 |
| `src/components/auth/` | 登录、邮箱验证码与 Turnstile |
| `src/components/layout/`、`src/components/tabs/` | 工作台布局与出题、预览、题库、收藏等页面 |
| `src/components/tabs/GenerateTab/` | 四模式对话、图片附件、消息操作和生成进度；旧 QuickPrompts 已移除 |
| `src/components/settings/`、`src/components/admin/` | 个人模型设置与管理员面板 |
| `src/components/admin/LegacyOverview.tsx` | 原平台资源与历史批次统计，独立读取真实接口 |
| `src/components/admin/ops/` | 运维概览、运行／依赖／异常页面、运行抽屉、管理员通知及共用查询与展示 |
| `src/components/admin/ops/OpsExtensions.tsx` | 运维自监控、配置、版本／审核范围证据及告警只读指引 |
| `src/components/admin/ops/useOpsClock.ts` | 使用服务端快照及页面经过时间复核观测有效期 |
| `src/components/ui/` | 提示、确认框等共用控件 |
| `src/components/ui/ConfirmCard.tsx`、`src/components/ui/SegmentedControl.tsx` | 数据操作预览确认与四模式选择 |
| `src/store/`、`src/types/` | 认证与业务状态、共用类型 |
| `src/types/ops.ts` | 运维 v1 前端类型与客户端边界，不代表后端 schema 或 OpenAPI 已新增 |
| `src/styles/`、`src/assets/`、`src/lib/` | 样式、静态资源与工具函数 |
| `vite.config.ts` | 开发代理、环境文件隔离与构建配置 |
| `*-regression.mjs`、`e2e-auth.mjs` | 会话、组件与浏览器回归脚本 |

## 启动

先按[后端说明](../backend/README.md)启动后端及其依赖，再在仓库根目录执行：

```powershell
cd frontend
npm install
npm run dev
```

访问 `http://127.0.0.1:5173`；端口被占用时以 Vite 输出地址为准。开发服务器仅绑定 `127.0.0.1`，`/api` 和 `/media` 代理到 `http://127.0.0.1:8000`。本机开发时后端也应绑定回环地址，避免通过公共代理或隧道暴露开发账号接口。

## 构建与检查

以下命令均在 `frontend/` 执行：

```powershell
npm run typecheck  # TypeScript 检查
npm run lint       # ESLint 检查
npm run build      # 类型检查并生成 dist/
npm run preview -- --host 127.0.0.1  # 本机预览构建产物
```

开发代理仅用于 `npm run dev`；构建预览和生产部署需另行配置 API 与媒体文件访问。`vite.config.ts` 使用空临时目录隔离项目 `.env` 文件；公开地址通过启动或构建进程的 `VITE_API_BASE_URL`、`VITE_WS_BASE_URL` 注入，留空使用当前站点来源。`VITE_*` 会进入浏览器代码，不得放入密钥；临时目录权限错误时检查进程 `TEMP`／`TMP` 是否可写。

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

运行 `ops-panel-regression.mjs`，在 `frontend/` 执行 `node ops-panel-regression.mjs`。使用离线浏览器与合成请求验证七入口、通知、DEV 五种场景及 375／768／1024／1440px 布局，不依赖真实模型或生产服务。离线浏览器对旧接口的测试拦截不等于应用演示模式可替换旧平台数据。

2026-11-11 历史记录中，类型检查、lint、构建、离线回归 9 组与四种宽度检查已通过，核验了生产无演示入口／demo 模块，保留 3 条原有 lint 警告及大分包提示；这些结果不覆盖 2026-11-12 补全。新增检查已完成并记录于[升级方案第 10.3 节](../docs/design/运维后台升级方案.md#103-2026-11-12-补全检查)，不得沿用旧计数或警告结论。前端检查不能替代 G0／G1／G3。

## 代理和认证配置注意

- 登录支持账号密码和已验证邮箱验证码；角色由服务端识别，管理员进入管理面板。认证可用状态与配置来自 `GET /api/auth/config`，后端配置入口见[根 README](../README.md)。
- 后端允许的 Origin 须包含实际前端来源（协议、主机和端口）。刷新和退出依赖 Cookie、CSRF 与可信来源；生产使用 HTTPS。访问令牌仅保存在内存，刷新凭据由 HttpOnly Cookie 管理；浏览器需支持 Web Locks。
- Turnstile 由认证配置的请求级 `turnstile_enabled` 控制，不使用前端环境变量推断。后端 `TURNSTILE_ENABLED=false` 仅允许在 development/test 环境对实际回环请求生效，生产必须启用验证。
- 开发账号填充仅在 Vite 开发模式、浏览器地址为 `127.0.0.1` 且后端允许时显示；按钮只填充，不自动登录，前端不内置账号或密码。

## 功能要点

- 个人凭据在“模型与服务”保存：留空保留，明确勾选后清除；连接测试使用已保存配置。管理员在“模型与检索”维护平台模型与索引重建，嵌入模型变更需重建后生效。
- 题库支持 PDF、DOCX、XLSX、MD／markdown、TXT 批量上传；校验格式、空文件及名称／大小／修改时间重复项，部分失败可只重试未受理文件。上传受理后仍需等待后台处理完成，列表可查看失败详情。
- MD／TXT 提供分页文本预览，文本读取上限为 2 MiB；PDF 通过认证请求获取 Blob 后打开窗口，DOCX／XLSX 提供下载。关闭或切换文档时取消预览请求。
- 对话提供快速出题、创新命题、知识答疑和数据管理四种模式；输入框支持动态行数和图片附件。图片用于出题要求抽取，数据删除／改名需先查看影响预览并确认；模式、接口与异步隔离边界见[四模式说明](../docs/design/对话四模式与主线整合.md)。

### 登录页居中与滚动边界

保留历史浅蓝背景、左上品牌与玻璃卡片，已取消左侧介绍及其占位。外层固定动态视口并使用 `overflow: clip`，背景与装饰独立裁切，卡片在桌面和窄屏均相对整个视口居中；常规／大屏／窄屏目标宽度分别为 432／468／400px，受可用宽度约束，手机左右各至少留 16px。超高内容仅在 `login-card__body` 内部滚动，外层与整页均不可滚动；仅在登录页作用域取消 Turnstile 关闭后遗留的 65px 空白。已监听 `visualViewport` 的 `height`、`width`、`offsetTop`、`offsetLeft`，适配软键盘仅改变视觉视口及页面放大的情况；手机输入框字号为 16px，避免聚焦自动放大。

沿用当前密码登录、邮箱验证码登录、找回密码及全部认证逻辑，不恢复历史注册身份选择，不改 API。47 组布局、触摸、两倍 pinch 及视觉视口缩短模拟检查通过；手机真机键盘未验证。结构、根因、静态检查与完整认证脚本的验证边界见[账号系统整合与审查修复](../docs/design/账号系统整合与审查修复.md#登录页居中与滚动边界2026-11-11已实现)。

### 工作台窄屏布局

小于 768px 时导航改为四列，主内容与快速出题面板纵向排列，账号操作允许换行；参数栏可展开或折叠。

### 运维后台前端先行

三人协作见[实施分工方案](../docs/design/运维后台三人实施分工方案.md)。2026-11-12 新增前端及合成交互已完成，本次前端检查及独立复审已通过；真实授权审计和后端联调待完成。`src/types/ops.ts` 已加入可选自监控、每题最终版本与审核范围证据、详情重出配置及告警指引／配置，准确结构和待 G1 映射差异见[联调契约第 1.2 节](../docs/design/运维后台接口与联调契约.md#12-2026-11-12-前端先行扩展待-g1-冻结)；后端 schema、事件采集、OpenAPI 仍未实现／冻结，本次不改 OpenAPI。

本轮按用户授权在 G0 前依照 v1 契约先行实现前端，保留“平台概览、账号管理、模型与检索、账号安全”，新增“出题运行、依赖状态、异常中心”，共七个入口，并增加管理员通知。平台概览内将运维统计与原平台资源／历史批次统计分别展示；运行列表与详情、依赖观测、异常轮次和通知使用独立的运维客户端。实现与文件职责见[模块说明](../docs/design/运维后台模块说明.md#m7-运维后台界面)。

只有以管理员身份登录后，Vite DEV 页面才显示“使用演示数据”勾选项；默认不勾选并请求真实接口。主动勾选后，合成数据仅覆盖运维统计、运行、依赖、异常和通知，保留 `normal`、`loading`、`empty`、`partial`、`error` 五种场景，另增 `trace_denied`、`trace_audit_failed`、`trace_expired`、`trace_simulated_success` 四种追踪访问结果模拟。模拟成功只显示合成反馈，不打开正文、不形成真实审计。旧平台资源统计、账号管理、模型与检索、账号安全始终请求真实接口；演示通知的已读、删除只影响内存。生产没有演示入口，demo 模块不进入生产产物；本次产物检查已通过，见升级方案第 10.3 节。

`OpsExtensions.tsx` 在概览内展示自监控和只读生效配置，并以三按钮定位近 24 小时新建的监控链路异常、容量异常、通知失败轮次；这不是全部活动故障列表。运行详情按每题最终内容版本分别展示实际完成范围、明确通过范围及逐条新旧证据，不由运行摘要 revision 或集合版本替代每题版本。配置字段缺省显示“未提供”，显式 null 显示“证据未知”，不自行补默认阈值。告警增加三规则与安全未知规则的原始标识展示和通用只读指引。

`useOpsClock.ts` 以服务端 `generated_at` 加页面经过时间复核新鲜度；依赖时钟位于 `DependenciesPanel` 顶层，筛选重挂卡片不能延长证据有效期，自监控也复核时间。解析器只校验时间结构和 `fresh_until > observed_at`，保留原状态，不按客户端 `Date.now()` 覆写证据；过期 unknown 由 UI 判断。分页追加后暂停自动刷新，刷新第一页失败保留集合及暂停状态；通知竞争、筛选与抽屉焦点修复纳入本次通过的离线回归。

经过时间单调累加 `max(wallDelta, performanceDelta, 0)`，兼顾校时回拨及 Windows 休眠；新快照只向前校准，空数据／旧快照不能回拨。概览时钟提升至父层，依赖时钟保留在面板顶层，过滤不重新起算。未来 `observed_at > generated_at` 的观测在该快照持续 unknown，不会等一会儿自动变 healthy。独立审查修复与脚本后段仍在复核，阶段性构建／回归记录见升级方案第 10.3 节，不代表全部检查通过。

真实 `OpsClient.openTrace(path)` 是异步接口，固定返回 `not_integrated` 并关闭正文访问；即使摘要为 available 或带有安全路径，也不会跳转或请求未接入的授权／审计 API。独立授权、打开前到期复核和真实审计仍待后端接入，本次未新增后端或审计 API。

真实 API 返回错误时显示真实错误和重试入口，不能自动回退到 mock 或把未知数据填成零／正常。通知已读与告警恢复分别表达，追踪不可用不改写执行结果。前端 API 适配与 `src/types/ops.ts` 仅对应 v1 联调设计；五个 `/api/admin/ops/*` 后端接口及运维通知生成／关联字段仍待实现。G0 真实追踪、G1 后端契约冻结、G3 真实链路贯通均未通过，本轮不代表整套运维后台已经上线。

## 相关文档

- [API 文档](../docs/api.md)：请求与响应契约。
- [管理员与账号开通设计](../docs/design/管理员与账号开通设计.md)、[账号系统整合与审查修复](../docs/design/账号系统整合与审查修复.md)：账号、认证与安全设置。
- [设置拆分与保存反馈设计](../docs/design/设置拆分与保存反馈设计.md)、[模型配置功能规格](../docs/design/模型直接配置功能规格.md)、[配置来源与知识库流程](../docs/design/模型配置来源与普通知识库流程.md)：个人及平台模型配置。
- [知识库模块说明](../docs/design/知识库模块说明.md)、[题目收藏页面设计](../docs/design/题目收藏页面设计.md)：题库、上传预览与收藏。
- 运维方案与前端先行记录：[系统方案说明](../docs/design/运维后台系统方案说明.md)、[运维后台升级方案](../docs/design/运维后台升级方案.md)、[接口与联调契约](../docs/design/运维后台接口与联调契约.md)、[模块说明](../docs/design/运维后台模块说明.md)、[三人实施分工](../docs/design/运维后台三人实施分工方案.md)、[运行手册](../docs/design/运维后台运行手册.md)；DEV 演示与历史替身的边界见 [STUBS](../STUBS.md)。
