# MathCraft 前端

React 19 + TypeScript strict + Vite + Tailwind CSS，提供教师与学生共用工作台，以及独立的管理员面板。账号由管理员开通，通过后端 HTTP API 认证。

## 目录与模块

| 路径 | 用途 |
| --- | --- |
| `src/api/` | 认证会话、业务请求、题库、文档预览与模型配置接口 |
| `src/components/auth/` | 登录、邮箱验证码与 Turnstile |
| `src/components/layout/`、`src/components/tabs/` | 工作台布局与出题、预览、题库、收藏等页面 |
| `src/components/settings/`、`src/components/admin/` | 个人模型设置与管理员面板 |
| `src/components/ui/` | 提示、确认框等共用控件 |
| `src/store/`、`src/types/` | 认证与业务状态、共用类型 |
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

## 代理和认证配置注意

- 登录支持账号密码和已验证邮箱验证码；角色由服务端识别，管理员进入管理面板。认证可用状态与配置来自 `GET /api/auth/config`，后端配置入口见[根 README](../README.md)。
- 后端允许的 Origin 须包含实际前端来源（协议、主机和端口）。刷新和退出依赖 Cookie、CSRF 与可信来源；生产使用 HTTPS。访问令牌仅保存在内存，刷新凭据由 HttpOnly Cookie 管理；浏览器需支持 Web Locks。
- Turnstile 由认证配置的请求级 `turnstile_enabled` 控制，不使用前端环境变量推断。后端 `TURNSTILE_ENABLED=false` 仅允许在 development/test 环境对实际回环请求生效，生产必须启用验证。
- 开发账号填充仅在 Vite 开发模式、浏览器地址为 `127.0.0.1` 且后端允许时显示；按钮只填充，不自动登录，前端不内置账号或密码。

## 功能要点

- 个人凭据在“模型与服务”保存：留空保留，明确勾选后清除；连接测试使用已保存配置。管理员在“模型与检索”维护平台模型与索引重建，嵌入模型变更需重建后生效。
- 题库支持 PDF、DOCX、XLSX、MD／markdown、TXT 批量上传；校验格式、空文件及名称／大小／修改时间重复项，部分失败可只重试未受理文件。上传受理后仍需等待后台处理完成，列表可查看失败详情。
- MD／TXT 提供分页文本预览，文本读取上限为 2 MiB；PDF 通过认证请求获取 Blob 后打开窗口，DOCX／XLSX 提供下载。关闭或切换文档时取消预览请求。

### 工作台窄屏布局

小于 768px 时导航改为四列，主内容与快速出题面板纵向排列，账号操作允许换行；参数栏可展开或折叠。

## 相关文档

- [API 文档](../docs/api.md)：请求与响应契约。
- [管理员与账号开通设计](../docs/design/管理员与账号开通设计.md)、[账号系统整合与审查修复](../docs/design/账号系统整合与审查修复.md)：账号、认证与安全设置。
- [设置拆分与保存反馈设计](../docs/design/设置拆分与保存反馈设计.md)、[模型配置功能规格](../docs/design/模型直接配置功能规格.md)、[配置来源与知识库流程](../docs/design/模型配置来源与普通知识库流程.md)：个人及平台模型配置。
- [知识库模块说明](../docs/design/知识库模块说明.md)、[题目收藏页面设计](../docs/design/题目收藏页面设计.md)：题库、上传预览与收藏。
