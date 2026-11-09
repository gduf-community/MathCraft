# MathCraft 前端

React 19 + TypeScript strict + Vite + Tailwind CSS，教师与学生共用工作台，管理员进入管理面板。账号由管理员开通，认证接入真实 HTTP API。主体方案已实现，前端及浏览器回归通过，完整后端验收受 Chroma 初始化失败阻塞。

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

## 目录与模块

| 路径 | 职责 |
| --- | --- |
| src/api/session.ts | 内存会话、CSRF、Cookie、刷新协调、统一认证 HTTP |
| src/api/auth.ts | 严格认证与安全资料契约、密码规则 |
| src/api/backend.ts | 业务请求和 DTO 映射；共用会话传输 |
| src/api/settingsHttp.ts、urls.ts | 设置接口及公开服务地址 |
| src/store/AuthContext.tsx | 会话恢复、登录门禁、退出 |
| src/store/AppContext.tsx | 业务状态与资料保存 |
| src/components/auth/ | LoginPage、EmailCodeFields、Turnstile |
| src/components/tabs/ProfileTab/ | 基本资料、模型配置、SecuritySettings |
| src/components/settings/ | 模型、知识库、解析配置 |
| src/components/tabs/ | 出题、预览、题库、组卷记录、空间、收藏 |
| src/styles/login.css | 既有品牌/背景/玻璃面板与两种登录入口响应式布局 |
| e2e-auth.mjs | 浏览器/HTTP 接缝合成认证回归 |
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


认证审查回归：在 frontend 目录运行 `node auth-session-regression.mjs`。该脚本通过真实会话模块的公开接口验证认证响应原子提交、跨标签身份切换不重放和旧刷新不清理新登录；仅替换浏览器协调与 HTTP，不访问真实服务。开发账号按钮使用 POST `/api/auth/development-account?role=...`（JSON `{}`），保持精确 Origin 来源校验。原 GET 仅为兼容入口。


### 工作台窄屏布局

小于 768px 时，工作台导航改为四列、主内容与快速出题面板纵向排列，顶部账号操作允许换行。页面自然纵向滚动，参数栏展开、折叠和全部操作仍可到达；不使用横向裁切隐藏控件。桌面参数栏宽度及拖拽行为不变。375px 验收应同时检查文档宽度、对话发送、标签切换与参数栏折叠/展开。

PR #8 修复回归：运行 `node auth-session-regression.mjs` 与 `node logout-session-regression.mjs`。前者覆盖真实 XHR 上传的预刷新、显式过期单次重试、撤销不重放、角色／账号变化和旧响应隔离；后者覆盖注销使用原 Bearer（不刷新）、无本地凭据不匿名注销、不广播清除其他账号及旧注销不清除新登录。退出依赖 Origin/CSRF 与当前标签 Authorization，允许 access 过期后安全撤销原 sid。

注销网络失败后，登录页显示失败说明和“重试退出”按钮，并保留仅用于撤销重试的内存凭据；点击按钮会真实重试原 sid，旧退出失败不会覆盖新登录状态；确认后清除，新显式登录成功后才丢弃它；登录网络、解析或映射失败仍保留原退出重试凭证。未确认期间拒绝刷新恢复；重新加载保留 sessionStorage 的非凭据退出阻断标记；内存中的撤销重试凭据会丢失，不保证网络不可达期间已完成服务端撤销。

## main 账号整合说明

账号由管理员开通，所有启用账号默认使用 account 密码登录；可选已验证邮箱登录，均由服务端识别三角色，页面不选身份。管理员安全区域支持自身邮箱配置，历史邮箱不自动验证，未验证邮箱不阻断密码登录。运维管理员进入管理面板，不能进入题库教学工作台。个人资料保存等待服务端成功，空手机号可清除；未填写性别不默认选择。个人模型凭据通过用户级接口保存或明确清除，连接测试只针对已保存凭据。当前支持的个人模型配置与认证边界见 [整合设计](../docs/design/账号系统整合与审查修复.md)。

会话回归：`node auth-session-regression.mjs`、`node logout-session-regression.mjs`、`node isolation-session-regression.mjs`。管理面板离线回归：`node admin-panel-regression.mjs`。`src/components/tabs/ProfileTab/PersonalModelSettings.tsx` 为两页共享组件。Vite 使用启动时新建的空临时目录，隔离项目 `.env` 文件；进程显式注入的 `VITE_*` 仍属于公开前端配置。

## 本次实施验证（2026-11-09）

本次已通过前端 typecheck；lint 为 0 错误、15 条原有警告。build 在独立 TEMP 重试成功，首次失败为 esbuild 默认 TEMP 清理权限问题。OpenAPI 与 docs/api.md 已在测试隔离环境重新生成并核对注册/学工号登录路由删除、绑定/解绑存在、EmailLogin 无 role、UserPayload.email_verified 为必填字段。

本次已通过 auth-session-regression、logout-session-regression、isolation-session-regression、admin-panel-regression、e2e-auth 五个脚本，五个脚本 ESLint 为 0 错误、0 警告。浏览器无异常或意外外网请求；桌面与 375px 截图已完成视觉检查，产物在 output/playwright/auth-account/，包含 login-desktop/mobile 及安全区 8 张截图。本次七份文档的相对本地链接检查 missing_local_links=0。后端用户 ID 绑定修复后的 127 项认证相关测试已通过。Ruff（含 scripts）保留 11 项既有诊断、Pyright 保留 19 项既有诊断，新增诊断均为 0，本次修改文件的 Ruff 通过。后端完整 pytest 已执行：285 passed、79 subtests passed、20 failed，耗时 16 分 26 秒。20 项失败集中于文档、聊天、出题和健康检查，底层 Chroma PersistentClient 报 `InternalError: (code: 14) unable to open database file`；独立新目录初始化同样复现，无需经过认证或业务 API。扫描 PDF 用例也在扫描检测前的向量清理处中断。本次认证用例没有失败，但完整后端验收未通过，不能将本轮记录为全量通过。
