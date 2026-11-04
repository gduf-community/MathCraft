# AGENTS.md — MathCraft 协作约定

本文件面向在本仓库工作的开发者与 AI Agent，约束三件事：**文档同步**、**敏感信息**、**提交规范**。违反其中任何一条的改动，都视为未完成。

## 1. 文档同步：改功能必须改文档

新增或修改任何功能时，文档与代码必须在同一个提交里更新：

| 改动内容 | 需要同步更新 |
| --- | --- |
| 新增 / 删除 / 重命名目录或重要文件 | `README.md` 的「目录结构」 |
| HTTP 接口、请求/响应字段、WebSocket 消息 | `openapi.json`，并重新生成 `docs/api.md` |
| 新增替身模块、恢复上游行为 | `STUBS.md` |
| 新增依赖、extras、Python 版本要求 | `pyproject.toml` 与 `README.md` |
| 启动方式、端口、环境变量 | `README.md` 的「启动方法」 |

- `README.md` 的目录树必须与真实目录一致：新增目录要补行并写明用途，删除目录要删行，改名要同步。**目录树与实际不符的提交不予合入。**
- 接口改动后重新生成契约与文档：

  ```powershell
  .venv\Scripts\python.exe -c "import json, MathCraft.api.main as m; open('openapi.json','w',encoding='utf-8').write(json.dumps(m.app.openapi(), indent=2, ensure_ascii=False))"
  .venv\Scripts\python.exe tools\gen_api_docs.py
  ```

- 新增功能如果没有对应文档，或者文档描述与代码行为不符，视为未完成。

### 1.1 设计新功能和模块必须补充说明

- 设计新增功能、业务流程或模块时，必须在 `docs/design/` 新增或更新对应设计文档；文档至少说明目标、使用范围、核心流程、接口或数据契约、异常边界和验收标准。
- 开始实现前先检查现有设计文档；实现过程中如果范围、状态或接口发生变化，必须同步更新设计文档。
- 设计文档与代码必须在同一个提交中完成；只有文档变更没有实现时，应明确标注为方案或待实现设计。
- 新增目录、重要文件或对外能力时，同时更新根目录 `README.md`、对应子目录 README 和 API 文档入口，保持文档中的目录与真实结构一致。

## 2. 敏感信息：禁止泄露密钥与配置

- 禁止提交、打印、贴出任何真实凭据：API Key、Token、Cookie、OAuth 凭证、私钥、数据库口令、会话文件。
- `.env` 一律不提交（已在 `.gitignore` 中）。只允许提交 `.env.example` 这类占位样例，值必须为空或明显的假值。
- 模型与提供方配置不要写进代码、测试或文档，统一通过 `/api/settings` 落到 `<runtime-home>/data/user/settings/`；运行时根目录由 `backend/MathCraft/runtime/home.py` 统一解析。
- 运行时数据根与源码包目录分离；环境变量名称以当前路径服务为准，历史名称不作为兼容约束。调整包名或变量名时，已有设置、知识库和索引的数据处理须明确说明。
- 运行时数据（`data/`、`.venv/`、日志、解析缓存、知识库索引）不得提交。
- 提交前自查暂存内容：

  ```powershell
  git diff --cached --stat
  git diff --cached | Select-String -Pattern "sk-|api[_-]?key|secret|token|password|BEGIN .*PRIVATE KEY"
  ```

- 一旦发现密钥进入提交：**先轮换/吊销该密钥**，再清理历史；只删文件不算处理完。
- 测试只能使用假服务与假值（参见 `backend/tests/conftest.py` 的假嵌入端点），不得指向真实账号或真实服务。

## 3. 提交规范：约定式提交，内容使用中文

- 格式：`<type>(<scope>): <中文摘要>`，遵循 [Conventional Commits](https://www.conventionalcommits.org/)。
- `type` 用英文小写：`feat`、`fix`、`docs`、`refactor`、`perf`、`test`、`build`、`ci`、`style`、`chore`、`revert`。
- 摘要、正文、脚注使用中文；`type`、`scope`、代码标识符保持英文。
- 摘要不超过 50 字，不以句号结尾；正文说明「为什么改」和影响面。
- 一个提交只做一件事，不要把格式化、重命名与逻辑修改混在一起。
- 破坏性变更写成 `feat(api)!:`，或在正文加 `BREAKING CHANGE: 说明`。

示例：

```text
feat(knowledge): 支持按目录批量上传文档
fix(settings): 修复模型目录空写入误重置客户端单例
docs(readme): 补充目录结构与启动方式
test(progress): 覆盖索引进度 WebSocket 断线重连
chore(deps): 升级 fastapi 至 0.115
```

### 3.1 分支合并与清理

- 仓库长期只保留 `main` 分支，默认在 `main` 上开展工作；需要隔离任务时才创建临时分支。
- 每次工作完成后，先完成适用检查并按上述规范提交，再将任务分支合并到 `main`，确保全部任务提交都已纳入 `main`。
- 确认合并完成后，删除对应的本地及远端临时分支，尤其是所有已完成任务的 `codex/` 前缀分支；关联的临时 worktree 也应清理，收尾时切回 `main`。
- 合并与清理必须保留现有未提交改动；存在未合并提交或未保存工作时，先妥善处理，不得通过强制删除丢弃工作。
- 收尾时核查本地和远端分支，确认只保留 `main`；如因仍在进行的任务无法清理，应明确报告残留分支及原因。

## 4. 代码与测试

- Python 3.11 – 3.14，唯一主包位于 `backend/MathCraft/`，import 名为 `MathCraft`；启动入口使用 `python -m MathCraft`，ASGI 应用统一为 `MathCraft.app:app`。
- 安装开发依赖：`uv pip install --python .venv/Scripts/python.exe -e ".[dev]"`（现有 `.venv` 没有 pip；标准 venv 用 `.venv\Scripts\python.exe -m pip install -e ".[dev]"`）。
- 运行测试：`.venv\Scripts\python.exe -m pytest -q`（`testpaths` 已指向 `backend/tests`）；改动索引、解析、设置写入等核心路径后必须全绿。
- 保持单租户边界：需要多用户能力时先读 `STUBS.md`，不要顺手恢复上游的多用户行为。
- 可选引擎与解析器必须惰性导入：缺依赖时报告 unavailable，不能让服务启动失败。
- `backend/MathCraft/api/routers/knowledge.py`、`backend/MathCraft/api/routers/settings.py` 已经很大，新增端点放进对应分组的既有结构里，不要整段复制粘贴。

### 4.1 Python 语言规范与风格

- 遵循 PEP 8、PEP 257 和现有 `pyproject.toml` 配置；使用 4 个空格缩进，行宽保持在 100 字符以内，命名分别采用 `snake_case`、`PascalCase` 和 `UPPER_SNAKE_CASE`。
- 新增或修改的公共函数、类和模块应补充必要的类型标注与文档字符串；优先使用具体类型，避免新增 `Any`、通配符导入和无理由的类型忽略。
- 按标准库、第三方依赖、本地模块分组导入；依赖注入优先于隐式全局状态，模块导入阶段保持轻量，不新增 import-time 网络、文件写入或设置持久化副作用。
- 使用小而内聚的函数和明确的数据边界；外部 HTTP、WebSocket、文件和用户输入在边界处校验，接口数据优先使用现有 Pydantic schema，资源使用上下文管理器及时释放。
- 异步代码不得在事件循环中执行阻塞 I/O；异常应使用具体类型并保留上下文，禁止用空的 `except` 或静默降级掩盖错误；日志和异常信息不得包含密钥、Token、Cookie 或用户隐私。
- 格式与静态检查以 Ruff 和 Pyright 为准：至少运行 `.venv\Scripts\python.exe -m ruff check backend`；改动 Pyright 覆盖范围时同步运行 `frontend\node_modules\.bin\pyright.cmd`；行为改动运行 `.venv\Scripts\python.exe -m pytest -q`。

### 代码审查：
当使用skill或者插件进行代码审查时，需要使用没有附带编写代码的上下文的智能体或者子智能体来完成。

### 4.2 React 与 TypeScript 规范与风格

- 前端使用 React 19 + Vite + TypeScript strict；使用函数组件和 Hooks，组件文件及组件、类型名采用 `PascalCase`，变量、函数和 Hooks 采用 `camelCase`，API 与工具模块文件遵循现有小写命名，自定义 Hook 以 `use` 开头。
- Props、API 请求和响应使用明确的 TypeScript 类型；禁止新增 `any` 和无依据的类型断言，外部数据先校验或收窄为安全类型；后端契约类型与 `backend/schemas/`、`frontend/src/types/` 保持同步。
- 组件保持单一职责，优先复用现有组件、API 模块和状态上下文；派生值直接计算，副作用集中在 `useEffect`，依赖数组完整，状态通过不可变更新维护，不直接修改 Props、Context 或数组对象。
- 列表使用稳定且有业务含义的 `key`；异步交互明确处理 loading、error、empty 和成功状态；API 调用放在现有 `src/api/` 层，组件不重复实现请求、鉴权和错误转换。
- 优先使用语义化 HTML 和可访问控件，表单控件提供 label，交互行为支持键盘操作；颜色、焦点、禁用和错误状态遵循现有样式体系，不在单个组件中另建平行设计系统。
- 提交前在 `frontend/` 运行 `npm run typecheck` 和 `npm run lint`；涉及生产构建、路由、资源或打包配置时再运行 `npm run build`，并修复新增的 TypeScript、ESLint 和 React Hooks 诊断。

## 5. 目录约定

- 新功能的设计文档统一放在 `docs/design/`；新增功能设计文档完成后，应同步归档到该目录。
- 路由放 `backend/MathCraft/api/routers/`，业务实现放 `backend/MathCraft/services/<domain>/`，知识库领域逻辑放 `backend/MathCraft/knowledge/`。
- 新增可选依赖走 `pyproject.toml` 的 extras，不加入默认依赖。
- 测试放 `backend/tests/`，文件名 `test_*.py`，通过 `conftest.py` 的 fixture 获取客户端与假嵌入端点。
- `frontend/` 为出题智能体前端（React 19 + Vite），`node_modules/` 与构建产物 `dist/` 不提交；出题服务的数据契约沉淀在 `backend/schemas/` 与前端 `src/types/`，改动时保持两侧字段一致。

## 6. 开发时时刻留意是否需要重构
在开发时，如果发现重构为更合理的代码能使项目接口更清晰，实现更合理，使代码低耦合和高内聚，而不是在有问题的代码上堆叠代码，来使测试通过或解决bug,那就提出重构意见。避免较大更改。

## 分支协作
main分支用于知识库等模块开发，agent分支单独用于智能体开发。