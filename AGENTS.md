# AGENTS.md — MathCraft 协作约定

本文件面向在本仓库工作的开发者与 AI Agent，约束三件事：**文档同步**、**敏感信息**、**提交规范**。违反其中任何一条的改动，都视为未完成。

当前实现以 `backend/app/`、`frontend/src/` 和根 `openapi.json` 为准；`STUBS.md` 与早期设计文档记录历史实现，不能据此恢复旧目录、单租户替身或旧启动入口。修改本文件需要用户明确授权。

## 1. 文档同步：改功能必须改文档

新增或修改任何功能时，文档与代码必须在同一个提交里更新：

| 改动内容 | 需要同步更新 |
| --- | --- |
| 新增 / 删除 / 重命名目录或重要文件 | `README.md` 的「目录结构」 |
| HTTP 接口、请求/响应字段、WebSocket 消息 | `openapi.json`，并重新生成 `docs/api.md` |
| 新增替身模块、移除替身或恢复上游行为 | `STUBS.md`，明确当前行为与历史说明的边界 |
| 新增依赖、extras、Python 版本要求 | `pyproject.toml` 与 `README.md` |
| 启动方式、端口、环境变量 | `README.md` 的「启动方法」 |

- `README.md` 的目录树必须与真实目录一致：新增目录要补行并写明用途，删除目录要删行，改名要同步。**目录树与实际不符的提交不予合入。**
- 接口改动后重新生成契约与文档：

  ```powershell
  .venv\Scripts\python.exe -c "import json, sys; sys.path.insert(0,'backend'); from app.main import app; open('openapi.json','w',encoding='utf-8').write(json.dumps(app.openapi(), indent=2, ensure_ascii=False))"
  .venv\Scripts\python.exe tools\gen_api_docs.py
  ```

- 新增功能如果没有对应文档，或者文档描述与代码行为不符，视为未完成。`tools/gen_api_docs.py` 仍含旧接口分组，接口文档更新时需核对是否覆盖本次相关路径，不能只以脚本成功退出作为完成依据。

### 1.1 设计新功能和模块必须补充说明

- 设计新增功能、业务流程或模块时，必须在 `docs/design/` 新增或更新对应设计文档；文档至少说明目标、使用范围、核心流程、接口或数据契约、异常边界和验收标准。
- 开始实现前先检查现有设计文档；实现过程中如果范围、状态或接口发生变化，必须同步更新设计文档。
- 设计文档与代码必须在同一个提交中完成；只有文档变更没有实现时，应明确标注为方案或待实现设计。
- 新增目录、重要文件或对外能力时，同时更新根目录 `README.md`、对应子目录 README 和 API 文档入口，保持文档中的目录与真实结构一致。

## 2. 敏感信息：禁止泄露密钥与配置

- 禁止提交、打印、贴出任何真实凭据：API Key、Token、Cookie、OAuth 凭证、私钥、数据库口令、会话文件。
- 任意位置的 `.env` 与 `local_secrets.py` 一律不提交；不要假设所有位置已被忽略，暂存前用 `git check-ignore` 核实。只允许提交 `.env.example`、`local_secrets.example.py` 这类占位样例，凭据值必须为空或明显的假值。
- 当前应用配置以 `backend/app/config.py` 为准；个人模型凭据通过现有 `/api/users/me/model-settings` 接口保存到 `UserModelSetting`。测试只能使用明确假值，文档与样例使用占位值；不再使用历史 `/api/settings` 或 runtime-home 约定。
- 数据库、上传、OCR、头像和向量目录由当前配置解析，与源码分离。调整包名、路径或变量名时，明确已有用户、设置、题库和索引的迁移方式。`backend/app/local_secrets.py` 是现有本地敏感配置文件，不读取或输出其中真实值，不扩大其使用范围。
- 运行时数据（`data/`、`.venv/`、日志、解析缓存、知识库索引）不得提交。
- 提交前自查暂存内容：

  ```powershell
  git diff --cached --stat
  git diff --cached | Select-String -Pattern "sk-|api[_-]?key|secret|token|password|BEGIN .*PRIVATE KEY"
  ```

- 一旦发现密钥进入提交：**先轮换/吊销该密钥**，再清理历史；只删文件不算处理完。
- 测试只能使用假服务与假值，外部模型通过 `backend/tests/conftest.py` 打桩，不得指向真实账号或生产服务。当前夹具使用临时 SQLite 和本机 Redis 15 号库，并调用 `flushdb()`；运行前确认该 Redis 实例与逻辑库专供测试，无需为文档修改启动或清空 Redis。

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

### 3.1 分支协作与清理

- `main` 用于知识库及通用基础模块，`agent` 用于智能体模块；它们是长期分支，不按临时分支清理。用户系统涉及公共后端和智能体前端，开始实现前确认目标分支；只读调查不切换分支。
- 更新仓库先检查未提交改动，再通过 SSH 远端执行 fetch，只在可安全快进时更新当前分支。保留用户已有修改与未跟踪文件，不自动暂存、覆盖或提交它们。
- 需要隔离任务时创建 `codex/` 前缀临时分支。完成后运行适用检查，按中文约定式提交要求提交，并合并到该任务约定的目标分支；不要一律合并到 `main`。
- 仅清理本任务创建且已确认合并、无未保存工作的临时分支和 worktree。其他任务或他人的分支不擅自删除，收尾报告未清理项及原因。

## 4. 代码与测试

- 当前 Python 后端位于 `backend/app/`，import 名为 `app`；ASGI 入口是 `app.main:app`。从 `backend/` 执行 `uv sync` 安装依赖，执行 `uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1` 启动。仓库根 `.venv` 的测试与静态检查配置由根 `pyproject.toml` 管理；不要混用旧的 `MathCraft` 包入口。
- 数据库使用 SQLAlchemy + Alembic，登录与任务缓存依赖 Redis；账号已按教师、学生区分，不再遵循历史单租户替身约束。保护现有登录、角色校验和资源归属校验；新增注册、管理员、组织或角色能力前先确认需求与设计。
- 后端路由放 `backend/app/api/`，业务服务放 `backend/app/services/`，模型与请求契约分别放 `backend/app/models/`、`backend/app/schemas/`；在既有领域边界内扩展，不复制整段模块。
- 可选依赖保持惰性导入；缺少可选能力时报告 unavailable，不因引入新可选依赖导致应用启动失败。
- 验证按改动范围选择：纯文档修改检查差异、路径和命令；可逆且低影响的改动不编写复述实现的测试。后端行为变更运行相关接口测试；涉及认证、授权、数据隔离、数据库迁移或共享核心链路时，在确认测试 Redis 隔离后运行 `.venv\Scripts\python.exe -m pytest -q`。检查通过后，仅因新改动、失败或未解决风险而扩大或重复测试。

### 4.1 Python 语言规范与风格

- 遵循 PEP 8、PEP 257 和现有 `pyproject.toml` 配置；使用 4 个空格缩进，行宽保持在 100 字符以内，命名分别采用 `snake_case`、`PascalCase` 和 `UPPER_SNAKE_CASE`。
- 新增或修改的公共函数、类和模块应补充必要的类型标注与文档字符串；优先使用具体类型，避免新增 `Any`、通配符导入和无理由的类型忽略。
- 按标准库、第三方依赖、本地模块分组导入；依赖注入优先于隐式全局状态，模块导入阶段保持轻量，不新增 import-time 网络、文件写入或设置持久化副作用。
- 使用小而内聚的函数和明确的数据边界；外部 HTTP、WebSocket、文件和用户输入在边界处校验，接口数据优先使用现有 Pydantic schema，资源使用上下文管理器及时释放。
- 异步代码不得在事件循环中执行阻塞 I/O；异常应使用具体类型并保留上下文，禁止用空的 `except` 或静默降级掩盖错误；日志和异常信息不得包含密钥、Token、Cookie 或用户隐私。
- 修改 Python 代码时运行 `.venv\Scripts\python.exe -m ruff check backend/app backend/tests`；改动 Pyright 覆盖范围时运行 `frontend\node_modules\.bin\pyright.cmd`。检查范围以根 `pyproject.toml` 为准；遗留未跟踪的 `backend/src/` 不是当前实现，不在本任务中顺手清理。对既有诊断与新增诊断分开报告。

### 代码审查：
当使用skill或者插件进行代码审查时，需要使用没有附带编写代码的上下文的智能体或者子智能体来完成。

### 4.2 React 与 TypeScript 规范与风格

- 前端使用 React 19 + Vite + TypeScript strict；使用函数组件和 Hooks，组件文件及组件、类型名采用 `PascalCase`，变量、函数和 Hooks 采用 `camelCase`，API 与工具模块文件遵循现有小写命名，自定义 Hook 以 `use` 开头。
- Props、API 请求和响应使用明确的 TypeScript 类型；禁止新增 `any` 和无依据的类型断言，外部数据先校验或收窄为安全类型；后端契约以 `backend/app/schemas/` 与根 `openapi.json` 为准，前端 `frontend/src/api/`、`frontend/src/types/` 及相关 store 的类型映射保持同步。
- 组件保持单一职责，优先复用现有组件、API 模块和状态上下文；派生值直接计算，副作用集中在 `useEffect`，依赖数组完整，状态通过不可变更新维护，不直接修改 Props、Context 或数组对象。
- 列表使用稳定且有业务含义的 `key`；异步交互明确处理 loading、error、empty 和成功状态；API 调用放在现有 `src/api/` 层，组件不重复实现请求、鉴权和错误转换。
- 优先使用语义化 HTML 和可访问控件，表单控件提供 label，交互行为支持键盘操作；颜色、焦点、禁用和错误状态遵循现有样式体系，不在单个组件中另建平行设计系统。
- 修改前端代码后在 `frontend/` 运行 `npm run typecheck` 和 `npm run lint`；涉及生产构建、路由、资源或打包配置时再运行 `npm run build`，并修复新增的 TypeScript、ESLint 和 React Hooks 诊断。

## 5. 目录约定

- 新功能的设计文档统一放在 `docs/design/`；新增功能设计文档完成后，应同步归档到该目录。
- 后端目录遵循第 4 节；题库与文档业务沿用现有 banks/documents 模块，检索与出题编排位于 `backend/app/services/rag/`。`apps/desktop/` 与 `packages/contracts/` 是预留目录，不视为已实现客户端或契约生成机制。
- 依赖变更同步对应 `pyproject.toml` 和锁文件；后端独立 uv 工作流与仓库根安装配置都受影响时同步维护。可选能力使用明确的可选依赖分组，不默认加入核心依赖。
- 测试放 `backend/tests/`，文件名 `test_*.py`，通过 `conftest.py` 的 fixture 获取客户端、临时数据与模型替身；Redis 测试隔离要求见第 2 节。
- `frontend/` 为教师与学生共用的 React 19 + Vite 前端，`node_modules/` 与构建产物 `dist/` 不提交；API 请求、响应与前端映射同时维护，不能把历史设计或残留 mock 当作当前功能证据。

## 6. 开发时时刻留意是否需要重构
在开发时，如果发现重构为更合理的代码能使项目接口更清晰，实现更合理，使代码低耦合和高内聚，而不是在有问题的代码上堆叠代码，来使测试通过或解决bug,那就提出重构意见。避免较大更改。
