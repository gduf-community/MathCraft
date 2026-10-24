# frontend 目录说明

`frontend/` 是 MathCraft 的 React 前端工程，使用 Vite 构建，负责出题、预览和参数配置等页面交互。

## 目录结构

```text
frontend/
├── src/
│   ├── api/                  # 后端 HTTP 适配层与 mock 数据适配器
│   │   └── mock/             # 本地开发用模拟数据与适配器
│   ├── components/
│   │   ├── layout/           # 顶部栏、侧边导航和标签栏
│   │   ├── tabs/             # 生成题目、预览题目等页面标签
│   │   │   ├── GenerateTab/  # 对话输入、快捷提示和机器人头像
│   │   │   └── PreviewTab/   # 题目卡片、答案、组卷和评分编辑
│   │   └── ui/               # 通用下拉框、提示等基础组件
│   ├── lib/                  # LaTeX 等前端工具
│   ├── store/                # 全局应用状态与上下文
│   ├── styles/               # 全局样式
│   ├── types/                # 前端 TypeScript 类型
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
