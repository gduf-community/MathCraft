# STUBS — what was replaced, and what the original did

## 当前 DEV 运维前端演示（2026-11-11）

用户授权在 G0 真实追踪验收前按 v1 契约先行实现七入口与管理员通知前端；演示用于验证界面与联调语义，五个 ops 后端接口仍待实现。入口和状态见[前端说明](frontend/README.md#运维后台前端先行)，完整授权范围与验收记录见[运维后台升级方案](docs/design/运维后台升级方案.md)。

- 管理员完成真实登录后，仅 Vite DEV 显示“使用演示数据”；默认关闭，主动勾选才加载 `frontend/src/api/adminOpsDemo.ts` 的合成客户端。生产没有演示入口，demo 模块不进入生产产物；生产产物核验已通过，结果见升级方案第 10.2 节。
- 合成数据仅用于运维统计、运行列表／详情、依赖、异常和管理员通知。旧平台资源／历史批次统计仍由 `LegacyOverview.tsx` 请求真实 `/api/admin/overview`；账号、模型与检索、账号安全继续真实读写，不受演示开关影响，不绕过登录、角色或资源归属校验。
- 场景为 `normal`（典型运行与异常）、`loading`（缓慢加载）、`empty`（空数据）、`partial`（部分可用与未知）、`error`（服务不可用）。演示通知已读和删除只影响当前合成客户端内存，不写入真实通知或更改告警恢复状态。
- `frontend/src/api/adminOps.ts` 负责真实请求；404、403、503、网络失败等如实显示错误及重试，不能自动切换 mock。未知值仍按契约显示未知，不因演示或请求失败填为零／成功。
- 合成追踪状态或演示跳转不能证明 SDK → Phoenix 已贯通，不把演示数据写作真实运行、探测、告警或清理证据。G0 真实追踪、G1 后端契约冻结、G3 贯通仍未通过；前端检查和离线浏览器回归已通过，详见[验收记录](docs/design/运维后台升级方案.md#102-本轮前端验收记录)。

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
