# frontend 目录说明

`frontend/` 是 MathCraft 的 React 前端工程，使用 Vite 构建，负责出题、预览和参数配置等页面交互。

## 目录结构

```text
frontend/
├── src/
│   ├── api/                  # 后端 HTTP 适配层与 mock 数据适配器
│   │   ├── urls.ts           # 共享 HTTP / WebSocket 地址构造
│   │   └── mock/             # 本地开发用模拟数据与适配器
│   ├── components/
│   │   ├── settings/         # 模型目录、引擎、解析与真实知识库入口
│   │   │   ├── ModelSettings.tsx # 三类直接配置、当前项保存与旧草稿恢复
│   │   │   └── model/        # 模型表单及保留的内部兼容组件
│   │   │       ├── DirectModelEditor.tsx # 独立参数、手动发现与高级设置
│   │   │       ├── directCatalog.ts # 当前项合并、名称校验、协议和请求头解析
│   │   │       ├── ModelWorkspace.tsx # 旧模型列表与响应式详情兼容组件
│   │   │       └── providerDirectory.ts # 旧目录能力映射兼容组件
│   │   ├── profile/          # 教师资料与独立头像上传
│   │   ├── layout/           # 顶部栏、侧边导航和标签栏
│   │   ├── tabs/             # 生成题目、预览题目等页面标签
│   │   │   ├── GenerateTab/  # 对话输入、快捷提示和机器人头像
│   │   │   ├── BankTab/      # 题库协作与既有题库演示
│   │   │   └── PreviewTab/   # 题目卡片、答案、组卷和评分编辑
│   │   └── ui/               # 通用下拉框、提示等基础组件
│   ├── lib/                  # LaTeX 等前端工具
│   ├── store/                # 全局应用状态与上下文
│   ├── styles/               # 全局样式
│   ├── types/                # 前端 TypeScript 类型
│   ├── vite-env.d.ts         # Vite 环境变量类型声明
│   ├── App.tsx               # 应用根组件
│   ├── constants.ts          # 前端常量
│   └── main.tsx              # Vite 入口
├── index.html                # 页面 HTML 入口
├── package.json              # 脚本与依赖
├── vite.config.ts            # Vite 配置
├── tsconfig.json             # TypeScript 配置
└── package-lock.json         # npm 依赖锁定文件
```

## 常用命令

```powershell
npm install
npm run dev
npm run build
npm run preview
```

## 共享环境配置

前后端共享仓库根目录 `.env`，无需建立 `frontend/.env`。Vite 以配置文件位置确定根目录，不依赖终端启动目录；保留 Vite 的模式文件规则（根目录 `.env.local`、`.env.[mode]`、`.env.[mode].local`），shell 同名变量优先。未配置、空值或纯空白使用下表默认值。

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `FRONTEND_HOST` | `127.0.0.1` | 开发及预览服务器监听地址 |
| `FRONTEND_PORT` | `5173` | 开发服务器端口 |
| `FRONTEND_PREVIEW_PORT` | `4173` | `npm run preview` 端口 |
| `BACKEND_HOST` | `127.0.0.1` | 默认代理目标主机，与后端共享 |
| `BACKEND_PORT` | `8000` | 默认代理目标端口，与后端共享 |
| `FRONTEND_PROXY_TARGET` | 空，自动推导 | 开发及预览代理的显式 HTTP(S) 目标 |
| `VITE_API_BASE_URL` | 空，同源 | 浏览器 HTTP 请求的地址前缀，不含末尾 `/api` |
| `VITE_WS_BASE_URL` | 空，跟随 API 或页面源 | 浏览器 WebSocket 地址前缀，支持 WS(S) / HTTP(S)，不含末尾 `/ws` |

可在根 `.env` 配置下列公开网络参数（不需要为使用默认行为增加配置）：

```dotenv
BACKEND_HOST=127.0.0.1
BACKEND_PORT=8000
FRONTEND_HOST=127.0.0.1
FRONTEND_PORT=5173
FRONTEND_PREVIEW_PORT=4173
FRONTEND_PROXY_TARGET=
VITE_API_BASE_URL=
VITE_WS_BASE_URL=
```

开发及预览服务器代理 `/api` 和 `/ws`，均支持 WebSocket 升级。HTTP 代理目标按 `FRONTEND_PROXY_TARGET` > 绝对 HTTP(S) `VITE_API_BASE_URL` > `BACKEND_HOST` / `BACKEND_PORT` 推导；绝对 WS(S) / HTTP(S) `VITE_WS_BASE_URL` 可单独指定 `/ws` 代理目标。后端监听 `0.0.0.0` 时代理使用 `127.0.0.1` 连接；监听 `::` 时使用 `[::1]`，其他 IPv6 地址自动加方括号。端口必须为 1–65535 的整数，配置非法时启动报错；沿用 Vite 默认行为，端口占用时自动尝试后续端口。

`src/api/urls.ts` 统一生成 HTTP 和 WebSocket URL，所有 HTTP 入口使用 `apiUrl`；`settingsHttp.ts` 保留原有导出以兼容调用方。传入路径包含完整 `/api/...` 或 `/ws/...` 路由，地址前缀会去除末尾斜杠。例如 API 地址为 `https://api.example.invalid/` 时，请求变为 `https://api.example.invalid/api/...`，WebSocket 默认变为 `wss://api.example.invalid/ws/...`；没有显式地址时使用当前页面源，HTTPS 页面自动使用 WSS。相对前缀（如 `/gateway`）用于已有反向代理部署，需要由部署端处理 `/gateway/api` 和 `/gateway/ws`。

Vite 不读取后端保存的 `system.json`。如果后端通过命令行或已保存设置使用其他端口，须同步根 `.env` 的 `BACKEND_PORT`（或设置 `FRONTEND_PROXY_TARGET`）。修改环境配置后重启 Vite；`VITE_API_BASE_URL` 和 `VITE_WS_BASE_URL` 在构建时写入浏览器产物，生产部署修改后须重新构建。静态托管需要由部署端提供同源 `/api`、`/ws` 反向代理，或在构建前配置浏览器可访问的绝对地址并配置后端跨域。

共享 `.env` 的后端密钥不会整体注入浏览器；只为公开地址启用上述两个 `VITE_` 前缀，禁止在它们及同前缀变量中填写密钥、口令或其他凭据。

当前题库页面的文档上传和向量化进度由 `useDocUpload` 调用 `bankMock` 并通过定时器模拟，不发送文件内容，也不启动后端索引。真实文档上传、解析与索引应通过正式知识库 API 完成，请参阅 [API 文档](../docs/api.md)。

## 页面设计与范围

[个人中心与模型配置页面设计](../docs/design/个人中心与模型配置页面设计.md)记录页面演进与确认需求。当前左侧底部独立「设置」默认进入「模型与服务 → 语言模型」，设置分为模型与服务、知识库连接、知识库引擎、文档解析。语言模型、嵌入模型及任务模型采用直接配置及当前项保存；任务支持跟随主模型和独立配置，取消共享连接管理入口。个人中心保持五项教师资料，学习空间及学生闭环仍未开放。

## 设置与个人资料交互

- 个人中心：头像、昵称、教师身份、任教学段、年级；身份只读，头像先预览，点击「保存资料」后在资料保存成功时上传；失败分别提示并保留待确认头像。顶部资料与个人中心共享服务端状态。
- 设置：模型与服务（含语言模型、嵌入模型和任务模型直接配置）、知识库连接、知识库引擎、文档解析。使用 `api/settingsHttp.ts` 访问真实后端，不受出题演示适配器影响。
- 模型使用当前项“保存并启用”，旧草稿明确逐项恢复；引擎、解析、资料独立保存。页面离开和刷新提示未保存更改。浏览器不长期保存明文凭据。
- `store/ProfileContext.tsx` 与 `types/profile.ts` 维护个人资料；模型、引擎和解析的契约分别在 `api/` 与 `types/` 的对应模块。
- 题库管理直接进入既有题库协作演示；真实知识库连接、建库与引擎绑定统一在设置的「知识库连接」分区管理。学习空间和组卷不构成真实学生闭环。

验证命令：`npm run build`（包含 TypeScript 类型检查）；行为标准见[功能规格](../docs/design/个人中心与应用设置功能规格.md)，执行结果与本机构建限制见[实施记录](../docs/design/个人中心与应用设置实施记录.md)。

历史模型与服务页面优化已形成[独立功能规格](../docs/design/模型与服务页面优化功能规格.md)：提供方优先导航，提供方卡片及模型列表/详情布局参考 DeepTutor，视觉保留 MathCraft 风格。已实现提供方搜索与能力筛选、同提供方多个连接、模型搜索和独立默认操作、辅助任务三模式切换。兼容旧 Profile、引用和高级字段；历史验收与构建环境说明见[实施记录](../docs/design/模型与服务页面优化实施记录.md)；连接优先、任务三模式及草稿/应用交互已由下文直接配置方案替代。

## 模型直接配置

模型与服务默认打开语言模型，另有嵌入模型和任务模型。取消共享连接入口；同一表单维护完整参数，名称全局唯一且区分大小写。模型标识允许手填及重复，列表由用户手动获取，发现失败仍可保存。选中配置不切换默认，首项保存自动默认，后续备用项需显式设为默认。

「保存并启用」只发送当前项，成功后读回核实，保留其他本地编辑；失败保留输入，写成功但读回失败显示待核实。任务只有跟随/独立两种模式，保存备用不改变模式。旧草稿通过安全迁移预览逐项恢复，携带版本及配置 ID，不执行整份草稿应用。规格与 A01—A24 边界见[模型直接配置功能规格](../docs/design/模型直接配置功能规格.md)。

模型直接配置实现入口：`src/components/settings/ModelSettings.tsx` 维护正式快照、逐项保存及草稿恢复来源；`model/DirectModelEditor.tsx` 提供完整表单与手动发现，`model/directCatalog.ts` 负责单项编辑合并及名称校验。浏览器验收与构建证据见[模型直接配置实施记录](../docs/design/模型直接配置实施记录.md)。
