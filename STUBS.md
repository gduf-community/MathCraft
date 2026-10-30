# STUBS — what was replaced, and what the original did

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
