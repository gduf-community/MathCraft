# MathCraft 前端

React 19 + TypeScript strict + Vite + Tailwind CSS，教师与学生共用工作台。认证接入真实 HTTP API，不提供演示密码、邮箱密码登录或历史 login 旁路。

## 启动与开发安全

运行 `npm install` 后执行 `npm run dev`，访问 http://127.0.0.1:5173。Vite 显式只绑定 127.0.0.1；/api 代理至 http://127.0.0.1:8000，后端也必须仅绑定 127.0.0.1。不要加 --host 0.0.0.0，不通过外部共享代理或隧道暴露开发账号接口。

开发填充仅在 Vite DEV、浏览器 hostname 为 127.0.0.1 且 config.development_accounts_enabled=true 时显示。按钮通过本机 GET /api/auth/development-account?role 获取配置，只填充，不提交；仍须手动通过 Turnstile 登录。生产构建不显示按钮，不内置任何账号或密码；后端负责生产不挂载接口并校验来源、Host、代理头与环境。

## 认证流程与契约

- 注册：邮箱、6 位码、显示名称、密码与确认密码、教师/学生；学工号可空。成功自动进入工作台。
- 登录：邮箱验证码或学工号密码；发码 action=email_code，密码登录 action=password_login，均执行 Turnstile。学工号保留前导零、区分大小写。
- 找回密码：purpose=reset_password；错误验证码和网络错误保留两个密码输入，仅成功、离开或重新选择流程时清空。新密码 8–64 字符且 UTF-8 不超过 72 字节。
- 个人中心：当前密码改密；旧、新邮箱双验证码换绑；当前密码验证学工号添加、修改、移除。普通资料接口不发送邮箱、学工号或身份。
- config 返回 site_key、csrf_token；认证响应 access_token/token_type/expires_in/user；me 返回 {user}；user-no 与普通资料返回直接 user。
- register 发送 password、confirm_password；reset 发送 new_password、confirm_password（无 role）；PUT password 发送 old_password、new_password、confirm_password；PUT user-no 发送 user_no（移除为 null）与 current_password。
- 邮箱换绑创建返回 change_id；两路发码发送 email、purpose、change_id、turnstile_token；提交 change_id、old_challenge_id、old_code、new_challenge_id、new_code。
- Access token 仅存内存。刷新使用 HttpOnly Cookie，refresh/logout 发送 JSON {}、credentials:include 和 X-CSRF-Token。CSRF 来自 config，不读取或持久化刷新凭据。
- 单标签刷新单飞，Web Locks 跨标签串行轮换与 config Cookie 更新；BroadcastChannel 只广播退出信号，不广播 token。浏览器不支持安全协调时明确失败，不使用非原子存储锁降级。
- 401 写请求仅在 ACCESS_TOKEN_EXPIRED 明确表示认证阶段未执行时最多重试一次；SESSION_REVOKED、TOKEN_EXPIRED 清理状态，不盲目重放写操作。启动清理旧 mathcraft-auth/mc_token/mathcraft-token。

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
| src/styles/login.css | 既有品牌/背景/玻璃面板及自助认证响应式扩展 |
| e2e-auth.mjs | 浏览器/HTTP 接缝合成认证回归 |
| vite.auth-test.config.mjs | 仅回环绑定、envDir:false、不代理真实后端的测试服务器 |

## 检查与浏览器验证

`npm run typecheck`、`npm run lint`、`npm run build`。构建使用不读取 .env 的 Vite 配置；部署公开地址通过受控构建环境注入，禁止凭据进入 VITE_*。

本地无需真实邮箱、Cloudflare 或模型。浏览器回归在 HTTP 边界拦截所有 /api/，使用合成数据和假 Turnstile；不以组件内部函数替身断言。

1. 将 playwright-core 安装在临时工具目录（不加入项目依赖）：`npm install --prefix "$env:TEMP/mathcraft-auth-browser" playwright-core`。
2. 执行 `npx vite --config vite.auth-test.config.mjs`，默认 127.0.0.1:5178；可用 AUTH_TEST_URL 指向专用假服务入口。
3. 设置 AUTH_BROWSER 为已安装 Chromium 的绝对路径；未设置时使用本机 Playwright chromium-1217 路径。执行 `node e2e-auth.mjs`。
4. 覆盖注册直达、旧存储清理、恢复/双标签轮换、改密退出、错码保留密码、双邮箱换绑、学工号和开发只填充；375px/桌面截图保存在系统临时目录。

该验证不代替后端真实数据库、Cookie 安全属性、Redis 并发或 SMTP/Siteverify 测试。真实后端联调使用专用假服务和临时数据，不连接真实账号、生产数据库或未知 Redis。

Windows 若 esbuild 报系统临时目录 Access denied，可将当前进程 TEMP/TMP 指向本任务专用可写临时目录后重试构建；该目录与 dist、node_modules junction 均不得提交。
