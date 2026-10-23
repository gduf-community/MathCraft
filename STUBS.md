# STUBS — what was replaced, and what the original did

Every module below was **rewritten in place**: the import path is unchanged, so
the surrounding code still reads like upstream, but the behaviour is
single-tenant. Nothing else in the tree was rewritten for behaviour.

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
| `api/main.py` | 833 lines: dependency container, tool/capability registry validation, partners, events, migrations, static frontend | 130 lines: CORS, progress-port wiring, five routers, `/healthz`. |
| `api/routers/system.py` | 633 lines: version checks, update jobs, memory probe, runtime status handshake, SSE | Status + three connectivity tests. `/test/search` explains that search executes in the chat runtime. |
| `runtime/home.py` | `DEEPTUTOR_HOME` semantics | `MATH_Q_HOME`; default is the repository root. |

## Removing the stubs later

To restore multi-user behaviour: replace `api/routers/auth.py` with upstream's
router, drop `services/workspace/` back in, point `MATH_Q_HOME` at a per-user
root, and delete `services/tool_names.py` in favour of the chat tool package.
The call sites are unchanged, which is why the stubs keep upstream signatures.
