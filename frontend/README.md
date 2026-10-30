# frontend 目录说明

`frontend/` 是 MathCraft 的 React 前端工程，使用 Vite 构建，负责出题、预览和参数配置等页面交互。

## 目录结构

```text
frontend/
├── src/
│   ├── api/                  # 后端 HTTP 适配层与 mock 数据适配器
│   │   ├── favorites.ts      # 收藏域 API 封装（当前转调 mock）
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
│   │   │   ├── FavoritesTab/ # 题目收藏页：收藏夹、筛选、只读卡片与批量操作
│   │   │   ├── BankTab/      # 题库协作与既有题库演示
│   │   │   └── PreviewTab/   # 题目卡片、答案、组卷和评分编辑
│   │   └── ui/               # 通用下拉框、提示等基础组件
│   │       └── ConfigurationDialog.tsx # 临时配置面板、焦点与关闭管理
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

「题目收藏」页面本期只做前端：页面依赖 `store/FavoritesContext.tsx`，Context 只依赖 `api/favorites.ts` 封装，该封装内部转调 `api/mock/favoritesMock.ts`。刷新页面即重置，不读写后端；后端接入时只需替换 `api/favorites.ts` 的实现。预览页星标与收藏页共用同一份内存收藏状态；收藏页卡片只读，组卷入口仅做加入清单提示与计数。设计说明见 [题目收藏页面设计](../docs/design/题目收藏页面设计.md)。

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

## 临时配置弹出面板

新建知识库、更改引擎绑定和新增模型采用 `ui/ConfigurationDialog.tsx` 的居中模态面板，标题与底部按钮固定，长内容内部滚动。点击遮罩不会关闭；取消、关闭和 Esc 统一检查未保存修改；提交期间阻止关闭与重复提交，失败保留输入。新增成功后返回原列表，建库提交信息与状态由原列表展示和刷新。既有模型详情、引擎和文档解析保留完整设置页面。设计和验收见[临时配置弹出面板设计](../docs/design/临时配置弹出面板设计.md)，请求字段沿用[API 文档](../docs/api.md)。

## API 契约核对（2026-10-30）

以迁移后的 `backend/MathCraft/app.py` 为统一后端入口：`MathCraft.app` 与 `MathCraft.api.main` 导出同一个 app，知识库、设置和个人资料路由位于 `backend/MathCraft/api/routers/`，出题与对话路由位于 `backend/api/`。前端 URL 使用实际公开路由，不包含 Python 包名，不需要新增接口。

| 调用范围 | 实际方法 / 路由与关键契约 |
| --- | --- |
| 出题知识库列表 | `GET /api/knowledge-bases` 返回数组；`id` 允许为空，使用 `id || name` 作为选择值，有正式 ID 时原样保留 |
| 出题文档列表 | `GET /api/knowledge-bases/{kb}/files` 返回 `{ files }`；仅展示 `type: "file"`，`name` 为 raw 下 POSIX 相对路径，同时作为 `doc_id`；知识库路径参数 URL 编码 |
| 参数出题 | `POST /api/generate` 使用 `kb_id`、`doc_id`、`types`、`difficulty`、`source_mode`、`scope`、`existing_stems`；返回 `Question[]`，现有默认来源仍为 `variant_data` |
| 对话出题 | `POST /api/chat` 使用 `kb_id`、`doc_id`、`message`、`history[{role,text}]`、`slot_state`、`existing_stems`；返回 `{ reply, slot_state, questions, done }`；`questions` 仅是本轮新增题目 |
| 模型与服务 | `/api/settings`、`/draft`、`/direct-model/draft`、`/direct-model`、`/direct-model/{delete,default,task-mode}`、`/apply`、`/test-provider`、`/fetch-models` 的方法与现有字段匹配；保留模型写入/发现的受控错误与写成功读回失败处理 |
| 引擎设置 | `/api/knowledge-bases/rag-providers`、`rag-providers/{provider}/mode`、`rag-pipelines/{engine}/config`、`rag-pipelines/{provider}/preflight`、`rag-pipelines/lightrag/model-options` 和 WeKnora/Kiwix 探测匹配 |
| 文档解析 | `/api/settings/document-parsing` 的读取、局部保存、检测、安装、下载及 `/job/{status,cancel}` 匹配；MinerU 检测与下载任务使用独立 `/api/settings/mineru` 路径，保留日志游标和取消语义 |
| 知识库连接 | 列表、引擎目录、嵌入模型选项、`/{kb}/config` 读取/保存、建库调用匹配；建库使用 `FormData`，不手工覆盖 multipart boundary；无文件建库返回 `task_id: null`，显示已创建但未启动索引 |
| 教师资料 | `GET/PUT /api/user-profile`；`POST /api/user-profile/avatar` 的 multipart 字段为 `file`，头像读取为同路径 GET；写入资料不回传只读身份/头像字段 |
| 地址与实时通道 | HTTP 统一经 `apiUrl`；`urls.ts` 提供 `wsUrl`，但当前没有实际 `WebSocket` / `EventSource` / axios 调用；Vite 开发/预览均代理 `/api` 与 `/ws`，生产代理仍由部署端提供 |

本轮修复：

- `api/httpAdapter.ts` 复用 `settingsHttp.ts`，修正知识库可空 ID 映射；错误响应支持 FastAPI 的字符串、`detail.message` 对象、422 的 `loc/msg` 数组和顶层消息，空/非 JSON 错误保留 HTTP 状态。校验错误只读取位置与消息，不回显 `input` 等字段。
- `store/AppContext.tsx` 对初始化与文档读取错误显示既有提示；切库立即清空旧文档，递增请求序号丢弃过期列表响应，出题前校验文档属于所选知识库。
- 对话历史与槽位按知识库/文档隔离，切换或重选文档会使旧请求失效；同文档串行发送，迟到成功/失败都不能写入回复、题目、槽位或关闭新请求的等待状态。A→B→A 由递增 token 区分。有效响应将本轮题目按 ID 追加，不覆盖已有预览题目。
- `api/client.ts` 的端点清单仅列已存在的知识库/文档/出题/对话路由；`KnowledgeConnections.tsx` 对齐空库 `task_id: null` 的成功响应。页面视觉与持久化范围不变。

检查结果：

- 对迁移后路由声明逐项核对 55 个 HTTP 方法/路径组合，全部匹配统一 app 的挂载；这包含当前页面实际使用的引擎枚举展开。
- 临时 Node 夹具直接执行 TypeScript 转译后的真实 API 适配器，13 组请求/响应场景通过：可空 ID、嵌套文档路径、generate/chat 请求字段、422/409/429/500/502 错误、204、multipart、同源 HTTP/WSS。
- 临时 hook 夹具执行真实 `AppProvider` 回调，5 组场景通过：有效题目追加与历史、重复发送保护、A→B、A→B→A、同文档重选、旧错误与等待状态隔离。临时夹具通过 stdin 执行，没有增加测试文件。
- `npm exec tsc -- --noEmit` 与 `npm run build` 用于类型检查和生产构建。仓库没有 lint 脚本或配置，未虚报 lint 通过。本机首次构建遇到 Windows 系统临时目录下 esbuild 文件清理被拒，改用 `frontend/node_modules/.cache/mathcraft-build-temp` 作为当前进程的 `TEMP` / `TMP` 后构建通过；仅保留现有大 chunk 提示。
- 未使用真实模型或第三方凭据进行端到端生成，联网生成、引擎探测及真实索引仍需在后端配置完成后验收。

保留的演示边界：题目收藏与收藏夹仍通过 `api/favorites.ts` 转调明确声明的内存 mock；题库协作、学习空间、题目编辑/删除、组卷及记录仍为本地演示。当前后端未提供这些页面需要的持久化业务接口，本次不新增或假接接口。
