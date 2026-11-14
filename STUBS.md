# STUBS — what was replaced, and what the original did

## 当前 DEV 运维前端演示

现有前端仍保留旧方案的依赖状态、异常中心、质量覆盖、自监控、告警通知和追踪访问模拟。它们已从目标方案移除，**本轮尚未删除前端代码**；`ops_runs` 已接入实际出题入口，后台运行查询和前端尚未对接，不能把演示当作台账数据。边界见 [运行台账基础](docs/design/运维后台运行台账基础.md)和[入口接入](docs/design/运维后台出题入口接入.md)。

- 管理员真实登录后，DEV 才能显式启用合成演示，默认使用真实接口；旧平台资源、账号、模型与安全操作始终调用真实接口。
- 演示数据和通知操作只影响合成客户端；真实请求失败不自动回退演示，未知不冒充正常或失败。
- 演示追踪、合成访问结果和旧独立工具都不是当前 Phoenix 接入证据。当前扩展只导出元数据，不发送任何业务正文。

后续收缩范围见[系统方案](docs/design/运维后台系统方案说明.md)和[三人分工](docs/design/运维后台三人实施分工方案.md)；Phoenix 独立边界见[可选扩展](docs/design/Phoenix可选扩展.md)。

## 本地历史前端隔离预览（2026-11-12）

**状态：5174 临时对照已于 2026-11-12 结束并停服，不再提供可用入口。** `.scratch/frontend-0b5d4b4/`（含 `historical-preview/`、依赖和产物）的递归删除被自动审批审查拒绝，目录尚待清理，仍被 Git 忽略。以下为停服前的历史实现及核验记录，不表示当前仍可访问。

`.scratch/frontend-0b5d4b4/historical-preview/` 曾通过 5174 Vite 提供本地历史界面的合成演示，不接入真实认证或业务。历史路由为 `/historical-preview/`，`role` 支持 teacher／student，`page` 支持 generate、preview、bank、space、fav、records、me、settings；当时可通过参数或原侧栏切换，学生题库位于“我加入的题库”。

- 当时该目录中的附加入口、fixtures、合成 service、页面 isolation 和 guard 与原快照分离；82 个历史受控源文件逐个 Git blob SHA-1 核验零差异，精确对应 `0b5d4b44a9abe356f9a006a4a3edf4206ebe56ef`。根 5174 当时提供原旧登录，旧认证不兼容当前后端；本地预览未改主前端、后端或忽略规则，未新增依赖，快照与附加预览均未提交。
- 明示的合成数据包含 2 个账号、2 个题库、4 个文档、4 道题、2 个收藏组、3 份试卷、3 个学习空间及成员、统计、设置。收藏与资料更新只在内存生效，刷新重置；生成返回固定合成内容。未实现的上传、真实解析、安装、发布等明确拒绝，不模拟真实成功，也不代表真实权限、模型生成或持久化已验证。
- 当时页面只允许回环 5174，合成 fetch 无真实网络 fallback；API／media（包括绝对外域业务地址）由合成服务或阻断处理，XHR 同样拦截。guard v2 只匹配业务路径前缀 `/^\/(api|media)(\/|$)/i`，不拦 `/src/api` 源码模块；Service Worker scope 仅 `/historical-preview/`。认证写入页面私有 `MemoryStorage`，不读写真实 `mathcraft-auth`，不向真实后端发送伪造 Token 或演示请求。
- 独立 preview tsc、ESLint、额外 HTML 入口 Vite bundling 通过；浏览器独立上下文覆盖两角色共 16 个主要页面、16 个深链及 4 个详情，页面异常与业务请求外泄均为 0，两角色收藏变更刷新重置。未知／外网业务请求返回 501，绕过页面 fetch 的原生 API 请求返回 503，media 为占位 SVG，XHR 拦截已验证；根旧登录 controller 为 null、真实 storage sentinel 保留，验证未访问 5173。教师完整欢迎区／快捷提问与学生 3 个空间已实看确认。

历史证据位于 `output/playwright/historical-preview/`：`verification.json`、`details-verification.json` 均 PASS，两份复核脚本及 20 张截图保留在本次清理范围之外。原历史快照 typecheck／build 通过，原全量 lint 的 6 错误／15 警告保留；额外入口构建的大 chunk 警告未通过修改历史源文件消除。历史页面表见[恢复设计](docs/design/登录视觉恢复与历史前端对照.md#历史页面隔离预览)，本次停服与删除受阻情况见其清理状态记录。

## 历史 DeepTutor 裁剪与替身记录

以下正文（包括旧运行路径、收藏 mock 和恢复建议）全部保留为历史记录，不作为当前架构、当前替身范围或恢复步骤；与上面的当前 DEV 运维演示分开理解。

> 历史说明（2026-11-04 核对）：下文仅记录旧 DeepTutor 裁剪版，不是当前实现约束。当前受版本控制的后端位于 `backend/app/`，入口为 `app.main:app`；已包含教师/学生账号、JWT 与数据库可撤销会话、角色与资源权限依赖。原表中的 `backend/MathCraft/`、无条件放行和 `single_user` 描述不适用于当前应用。当前用户系统的完整性仍需按实际接口与验收结果判断，不能据此视为已完成。

The modules below retain the **single-tenant stand-in behaviour** introduced
when this project was cut down from upstream. Paths in this table are relative
to `backend/MathCraft/`, the unified implementation package. The former
`math_q_agent` imports and launch commands are no longer supported, and no
compatibility package is retained. This package move does not restore upstream
multi-user behaviour.

Source: DeepTutor `a31d8262`.

| Module | Original | Stand-in behaviour |
| --- | --- | --- |
| `api/routers/auth.py` | 1,909 lines: JWT cookies, device credentials, session handoff, avatars, roles, admin user CRUD, Codex OAuth callback | Every dependency (`require_auth`, `require_admin`, `require_learning_surface`, `ws_require_auth`) returns the local admin payload and never rejects. `/api/auth/status` and `/me` report `single_user: true`. |
| `services/workspace/context.py` | 275 lines: user-selected content workspace, scoped path service, URL rewriting | One scope with an empty id; URL pass-through; context managers are inert. |
| `services/workspace/knowledge.py` | 237 lines: workspace-qualified knowledge ids, library gating, alias moves | Library scope always on; ids unqualified; `parse_kb_id` returns `None`; catalogue helpers return empty. |
| `services/workspace/{activity,service,resources,models}.py` | ~1,400 lines: migration activity barrier, binding service, resource catalogue | No-op activity, empty item list, `WorkspaceError` on any attempt to switch workspaces. |
| `services/tool_names.py` | `tools/builtin/__init__.py` (2,073 lines) exposed `USER_TOGGLEABLE_TOOL_NAMES` | Just the two name tuples. The chat tool package is out of scope. |
| `services/partners/` | `services/partners/*` (5,393 lines): IM channel managers and scopes | `is_partner_user_id()` always false; no manager. |
| `runtime/agentic/` | 3,465 lines: the agentic chat loop and its client pool | `close_agentic_client_pool()` / `reset_agentic_client_pool()` are no-ops. |
| `capabilities/marginnote4/__init__.py` | Capability + chat tools registration | Exports the store and models only; the connector still uses `resolve_db_path`. |
| `api/runtime.py` (formerly `math_q_agent/api/main.py`) | Application lifecycle, middleware and upstream service assembly | Retains the reduced lifespan, runtime initialization and CORS middleware. `MathCraft.app` assembles the unified routes; `MathCraft.api.main:app` exports that same application. |
| `api/routers/system.py` | 633 lines: version checks, update jobs, memory probe, runtime status handshake, SSE | Status + three connectivity tests. `/test/search` explains that search executes in the chat runtime. |
| `runtime/home.py` | `DEEPTUTOR_HOME` semantics | `MATHCRAFT_HOME`; the default is the process working directory (the repository root when launched there). |

## Isolated document extraction restoration

Baseline `6045b32` omitted `runtime/worker_process.py` and
`runtime/worker_tasks.py` while existing preview and `TextOnlyParser.parse()`
callers still referenced them. This change restores those two infrastructure
modules using the existing extractor, with no new dependencies. It does not
replace any stand-in above or restore upstream multi-tenant behaviour.

The fixed child entry point is
`python -m MathCraft.runtime.worker_process <request_path> <result_path>`.
Trusted temporary files carry a pickle request with `callable_path`, `args`
and `kwargs`. Replies contain `ok/result` on success or
`ok/message/module/type/traceback/attrs` on failure; `attrs` preserves
`filename` when present and omits attributes that cannot be pickled.
`extract_document_text` lazily calls the existing `extract_text_from_path`,
forwarding `filename_hint`, `max_bytes` and `max_chars`.
`extract_document_to_markdown` extracts first, then creates the parent
directory, writes UTF-8 Markdown and returns `None`.

The parent retains timeouts, concurrency limits and cancellation cleanup.
Existing public document exceptions, filename handling, parser error wrapping
and HTTP preview contracts remain the acceptance boundary. The internal error
envelope is not a new HTTP response schema.

Verified on Windows / Python 3.14 on 2026-10-31:
`backend/tests/test_isolated_document_extraction.py` passed all 25 tests,
covering real subprocess text/PDF extraction, Markdown output, successful HTTP
previews, remote errors, timeouts and cancellation. Existing parsing regressions
passed all 9 tests; the full backend suite passed 322 tests with 1 skipped. See
[the restoration design and acceptance criteria](docs/design/后端包统一与接口对齐.md#10-隔离文档解析恢复方案与验收).

## Removing the stubs later

To restore multi-user behaviour: replace `api/routers/auth.py` with upstream's
router, drop `services/workspace/` back in, point `MATHCRAFT_HOME` at a per-user
root, and delete `services/tool_names.py` in favour of the chat tool package.
The stand-ins retain upstream function signatures within `MathCraft`; restoring
multi-user support would require a separate design and implementation change.

## Runtime paths and frontend mock boundary

`MATHCRAFT_HOME` is now the sole runtime-home environment variable, with no
fallback to the old name. Set its value to the original home directory to keep
reading settings, knowledge-base indexes and user-profile files from the same
`data/` directory. The existing layout is unchanged; no data is moved or rebuilt.

The favorites page currently uses an in-memory frontend mock which resets on
refresh. This is not a backend persistence implementation or a restored upstream
feature; package unification does not add favorites endpoints or storage.

See [后端包统一与接口对齐](docs/design/后端包统一与接口对齐.md) for the migration
scope, unchanged contracts and acceptance criteria.
