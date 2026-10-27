# frontend 目录说明

`frontend/` 是 MathCraft 的 React 前端工程，使用 Vite 构建，负责出题、预览和参数配置等页面交互。

## 目录结构

```text
frontend/
├── src/
│   ├── api/                  # 后端 HTTP 适配层与 mock 数据适配器
│   │   ├── favorites.ts      # 收藏域 API 封装（当前转调 mock）
│   │   └── mock/             # 本地开发用模拟数据与适配器
│   ├── components/
│   │   ├── settings/         # 模型目录、引擎、解析与真实知识库入口
│   │   ├── profile/          # 教师资料与独立头像上传
│   │   ├── layout/           # 顶部栏、侧边导航和标签栏
│   │   ├── tabs/             # 生成题目、预览题目等页面标签
│   │   │   ├── GenerateTab/  # 对话输入、快捷提示和机器人头像
│   │   │   ├── FavoritesTab/ # 题目收藏页：收藏夹、筛选、只读卡片与批量操作
│   │   │   ├── BankTab/      # 真实知识库入口与既有题库演示
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

开发服务器从仓库根目录的 `.env` 读取 `FRONTEND_HOST`、`FRONTEND_PORT`（默认 `127.0.0.1:5173`），并将 `/api` 请求代理到 `BACKEND_HOST` / `BACKEND_PORT`（默认 `127.0.0.1:8000`）。Vite 不读取后端保存的 `system.json`：建议按根 README 使用 `python -m MathCraft --port 8000` 启动后端；使用其他端口时，须同步根目录 `.env` 的 `BACKEND_PORT` 并重启开发服务器。

`VITE_API_BASE_URL` 用于指定后端 API 地址；设置后也会优先作为开发服务器的 `/api` 代理目标。

当前题库页面的文档上传和向量化进度由 `useDocUpload` 调用 `bankMock` 并通过定时器模拟，不发送文件内容，也不启动后端索引。真实文档上传、解析与索引应通过正式知识库 API 完成，请参阅 [API 文档](../docs/api.md)。

「题目收藏」页面本期只做前端：页面依赖 `store/FavoritesContext.tsx`，Context 只依赖 `api/favorites.ts` 封装，该封装内部转调 `api/mock/favoritesMock.ts`。刷新页面即重置，不读写后端；后端接入时只需替换 `api/favorites.ts` 的实现。预览页星标与收藏页共用同一份内存收藏状态；收藏页卡片只读，组卷入口仅做加入清单提示与计数。设计说明见 [题目收藏页面设计](../docs/design/题目收藏页面设计.md)。

## 页面设计与范围

[个人中心与模型配置页面设计](../docs/design/个人中心与模型配置页面设计.md)记录本期页面范围：左侧底部独立「设置」，默认打开「模型与服务 → 主语言模型」；设置分为模型与服务、知识库引擎、文档解析，模型用途仅含主语言模型、辅助任务模型（提供「跟随主模型」）与嵌入模型，并支持提供方及连接管理。模型采用独立草稿/应用，其他分区独立保存。个人中心仅五项教师资料，教师身份只读，头像及资料独立持久化；学习空间保留未开放提示与现有组卷占位，不实现学生发布接收作答闭环。对应的[本地功能规格](../docs/design/个人中心与应用设置功能规格.md)记录用户故事、保存契约和验收标准；本期按本地 Markdown 完成实施与验收。

## 设置与个人资料交互

- 个人中心：头像、昵称、教师身份、任教学段、年级；身份只读，头像先预览，点击「保存资料」后在资料保存成功时上传；失败分别提示并保留待确认头像。顶部资料与个人中心共享服务端状态。
- 设置：模型与服务（含主语言模型、辅助任务模型、嵌入模型和连接管理）、知识库引擎、文档解析。使用 `api/settingsHttp.ts` 访问真实后端，不受出题演示适配器影响。
- 模型使用草稿／应用；引擎、解析、资料独立保存。页面离开和刷新提示未保存更改。浏览器不长期保存明文凭据。
- `store/ProfileContext.tsx` 与 `types/profile.ts` 维护个人资料；模型、引擎和解析的契约分别在 `api/` 与 `types/` 的对应模块。
- 题库管理顶部是真实知识库 API 入口；下方协作和上传进度仍为原演示。学习空间和组卷不构成真实学生闭环。

验证命令：`npm run build`（包含 TypeScript 类型检查）；行为标准见[功能规格](../docs/design/个人中心与应用设置功能规格.md)，执行结果与本机构建限制见[实施记录](../docs/design/个人中心与应用设置实施记录.md)。
