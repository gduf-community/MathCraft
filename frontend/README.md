# MathCraft 前端

智能出题平台的教学端 Web 应用：React 19 + TypeScript + Vite + Tailwind CSS。

## 功能模块

| 模块 | 说明 |
|---|---|
| 登录 | 演示账号 student / teacher（密码 123123），预留认证接口（`src/api/auth.ts`） |
| 智能出题 | 对话式出题（左侧 Agent 会话）+ 快速出题参数面板（右侧），后端按题型多 agent 并行生成，进度按完成度加权实时展示 |
| 题目预览 | 题目卡片、编辑、收藏分组弹窗、组卷发布；学生身份下组卷仅保存记录 |
| 题库管理 | 我创建的 / 我加入的题库，成员管理，文档上传入库 |
| 组卷记录 | 试卷多标签查看；学生可作答（选项点选、填空输入、交卷 AI 批卷、复盘解析），教师可编辑并重新发布 |
| 学习空间 | 教师创建 / 解散空间、发布试卷、停止作答门禁删除、讲解视图（题目导航分区 + 作答分布）；学生凭编号加入、退出、在线作答 |
| 题目收藏 | 多标签收藏夹，点亮星标弹窗选择分组，实时联动 |
| 个人中心 | 资料编辑、头像上传（滚轮缩放 + 拖动裁剪） |
| 设置 | 模型与服务、知识库连接、知识库引擎、文档解析（对接后端设置接口） |

## 快速开始

```bash
npm install
npm run dev     # http://localhost:5173，/api 代理到本地后端
```

## 架构约定

- 数据访问收敛到 `src/api/`：`client.ts` 定义接口，`httpAdapter.ts` 走真实后端，`mock/mockAdapter.ts` 提供纯前端演示数据，可一键切换
- 全局状态在 `src/store/AppContext.tsx`（业务）与 `src/store/AuthContext.tsx`（登录态），页面组件不直接硬编码数据
- 演示性内容（空间成员、作答分布等）均在 mock 层并标注「演示数据」，接真实后端时只替换适配器实现
- 题目排序、讲解/作答视图分区共用 `src/lib/order.ts`，保证题号与组卷模块顺序一致

## 设置模块

`src/components/settings/` 与 `src/api/{settingsHttp,urls,engineSettings,modelSettings,parsingSettings}.ts` 来自社区版，直连后端设置端点；共享层（AppContext / App / SideNav）已按其依赖接入。
