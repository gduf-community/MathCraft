# frontend 目录说明

`frontend/` 是 MathCraft 的 React 前端工程，使用 Vite 构建，负责出题、预览和参数配置等页面交互。

## 目录结构

```text
frontend/
├── src/
│   ├── api/                  # 后端 HTTP 适配层与 mock 数据适配器
│   │   └── mock/             # 本地开发用模拟数据与适配器
│   ├── components/
│   │   ├── settings/         # 模型目录、引擎、解析与真实知识库入口
│   │   ├── profile/          # 教师资料与独立头像上传
│   │   ├── layout/           # 顶部栏、侧边导航和标签栏
│   │   ├── tabs/             # 生成题目、预览题目等页面标签
│   │   │   ├── GenerateTab/  # 对话输入、快捷提示和机器人头像
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

开发服务器从仓库根目录的 `.env` 读取 `FRONTEND_HOST`、`FRONTEND_PORT`，并将 `/api` 请求代理到
`BACKEND_HOST` / `BACKEND_PORT`。部署构建时可设置 `VITE_API_BASE_URL` 指向 MathCraft 后端的 API 根地址。

## 设置与个人资料交互

- 个人中心：头像、昵称、教师身份、任教学段、年级；身份只读，头像先预览，点击「保存资料」后在资料保存成功时上传；失败分别提示并保留待确认头像。顶部资料与个人中心共享服务端状态。
- 设置：模型与服务（含主语言模型、辅助任务模型、嵌入模型和连接管理）、知识库引擎、文档解析。使用 `api/settingsHttp.ts` 访问真实后端，不受出题演示适配器影响。
- 模型使用草稿／应用；引擎、解析、资料独立保存。页面离开和刷新提示未保存更改。浏览器不长期保存明文凭据。
- `store/ProfileContext.tsx` 与 `types/profile.ts` 维护个人资料；模型、引擎和解析的契约分别在 `api/` 与 `types/` 的对应模块。
- 题库管理顶部是真实知识库 API 入口；下方协作和上传进度仍为原演示。学习空间和组卷不构成真实学生闭环。

验证命令：`npm run build`（包含 TypeScript 类型检查）；行为标准见[功能规格](../docs/design/个人中心与应用设置功能规格.md)，执行结果与本机构建限制见[实施记录](../docs/design/个人中心与应用设置实施记录.md)。
