# API reference — MathCraft

Examples use `http://127.0.0.1:8000`, matching the README command
`python -m MathCraft`. Without a CLI override, `BACKEND_PORT`, or
saved system settings, the backend defaults to `8000`. Replace the HTTP and
WebSocket example ports with the actual deployment port. Interactive docs:
`/docs`. Machine contract: `/openapi.json` (a copy is committed at the repository root).

There is **no authentication**: every request is served as the single local
admin. CORS is permissive by default. Bind to loopback or front it with a
gateway you control.

Errors use FastAPI's `detail` envelope with a 4xx/5xx status. Most details are safe text; the documented direct-model committed/readback-failed outcome uses a structured code and message.

## Health

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/api/health` | Health |

## Knowledge bases

| Method | Path | Summary |
| --- | --- | --- |


## Question generation

| Method | Path | Summary |
| --- | --- | --- |
| `POST` | `/api/generate` | Generate Sync |
| `GET` | `/api/generate/batches/latest` | Latest Batch |
| `GET` | `/api/generate/progress/{task_id}` | Get Progress |
| `POST` | `/api/generate/start` | Start Generation |

## Question chat

| Method | Path | Summary |
| --- | --- | --- |
| `POST` | `/api/chat/sessions` | Create Session |
| `DELETE` | `/api/chat/sessions/{session_id}` | Delete Session |
| `GET` | `/api/chat/sessions/{session_id}` | Get Session |
| `POST` | `/api/chat/sessions/{session_id}/messages` | Send Message |

## Settings (model catalogue, providers, parsing)

| Method | Path | Summary |
| --- | --- | --- |


## System

| Method | Path | Summary |
| --- | --- | --- |


## Identity

| Method | Path | Summary |
| --- | --- | --- |
| `POST` | `/api/auth/change-password` | Change Password Public |
| `GET` | `/api/auth/config` | Public Config |
| `POST` | `/api/auth/login` | Login |
| `POST` | `/api/auth/logout` | Logout |
| `GET` | `/api/auth/me` | Me |
| `PUT` | `/api/auth/password` | Change Password Logged In |

## Teacher profile and avatar

| Method | Path | Summary |
| --- | --- | --- |


## Question generation contract

### `POST /api/generate`

The parameterized endpoint accepts `kb_id`, `doc_id`, `types` (each item has a
question `type` and a `count` from 1 to 20), `difficulty`, `source_mode`,
optional `scope`, and optional `existing_stems`. It returns a JSON array of
`Question` objects. `existing_stems` is the caller's current question bank;
the service uses it for prompt-level and normalized-stem deduplication.

### `POST /api/chat`

The chat endpoint accepts `kb_id`, `doc_id`, `message`, `history`,
`slot_state`, and `existing_stems`, and returns:

```json
{
  "reply": "请补充每种题型的数量。",
  "slot_state": {},
  "questions": [],
  "done": false
}
```

The client must send the returned `slot_state` back on the next turn. The
state accumulates explicit requirements across turns; missing question type,
per-type count, scope, source mode, or difficulty keeps `done` false and does
not start generation. Once all required slots are present, the response
contains the newly generated `questions` and sets `done` to true. The
`existing_stems` list is also sent on each turn so generated questions can be
deduplicated against questions already shown by the parameterized flow.

This supports the "set parameters first, then continue in chat" flow: the
parameterized call supplies the initial question set, and a later chat call
uses the same `kb_id`/`doc_id` plus the current `slot_state` and
`existing_stems` to request additional questions. The server does not infer
or persist client-side state between requests.

## Teacher profile contract

- `GET /api/user-profile` reads the single local teacher's profile.
- `PUT /api/user-profile` accepts only `nickname`, `teaching_stage` and `grade`; identity remains read-only. Stage values are empty, `primary`, `junior`, or `senior`; grade is an empty string or a matching number string (1–6, 7–9, 10–12 respectively).
- `POST /api/user-profile/avatar` accepts a multipart `file` and persists the avatar independently. Valid PNG, JPEG or WebP images up to 5 MiB are accepted; each dimension is at most 4096 pixels; animated, SVG and invalid image bodies are rejected. Images are re-encoded as PNG, and the returned avatar URL includes a content hash to refresh the view.
- `GET /api/user-profile/avatar` serves the stored image; it returns 404 before the first upload. Profile reads return `avatar_url` or null.
- The UI previews selected images locally and uploads only after the user confirms Save Profile and the profile PUT succeeds. Profile and avatar writes are separate requests; a partial failure is reported separately and is not rolled back as one transaction.
- Personal data never enters the model catalog or draft. `/api/settings/profile` remains a configuration export and is not the teacher profile API.

## Direct model configuration contract

- Language (`llm`), embedding (`embedding`) and independent task (`task`) configurations keep stable `profile_id` / model `id` references. Each model has a `direct_config` object containing its own provider `binding`, `base_url`, credentials and applicable connection parameters. The legacy profile container is an internal compatibility detail.
- `POST /api/settings/direct-model` accepts `{service, profile_id, model, make_default?, restore_draft?, draft_updated_at?}`. It merges only this model into the latest live catalog within one locked atomic write; it never promotes a saved settings draft. The first model in a category becomes its default; adding another keeps the existing default. Saving an independent task configuration preserves the task mode.
- `POST /api/settings/direct-model/default` and `/api/settings/direct-model/delete` accept `{service, profile_id, model_id}`. Default selection is separate from selecting a model for editing. `POST /api/settings/direct-model/task-mode` accepts `{mode: "inherit" | "profiles"}` and preserves independent configurations.
- `GET /api/settings/direct-model/draft` returns a masked migrated preview of the saved draft, preserving its original `updated_at` revision and file. Explicit restoration uses `restore_draft: true` with `draft_updated_at` and the exact service/profile/model IDs; only this item is restored, and a changed draft revision is rejected. Ordinary saves never consult draft credentials.
- These operations return `{catalog}` with masked credentials. If the write completed but server-side readback failed, HTTP 503 includes `detail: {code: "model_write_committed_readback_failed", message}`; runtime caches are invalidated and clients must display a pending-verification state, retain local edits, and re-read rather than report a rejected write. Other storage failures use a safe string detail. Configuration names are trimmed, nonempty and globally unique across the three categories, using case-sensitive comparison. Model identifiers may repeat. Masks retain only the same model's saved credentials; an explicit empty value clears them.
- `POST /api/settings/test-provider` discovers models from the current form without saving it. Include `service`, `profile_id` and `model_id` when retaining an existing masked direct configuration; versioned explicit draft restoration uses the same two restoration fields. Unsaved model IDs are permitted when credentials are supplied directly. `/api/settings/fetch-models` uses the same discovery semantics. Results include `status`, `models` and the actual upstream `http_status` when available. A stable `reason` code classifies the result without exposing the upstream body; the UI presents a localized explanation. Transport failures have no invented HTTP status; rejected requests are never successful empty lists. No inference or embedding is performed.
- Discovery is optional and manual. Failure permits manual model identifiers and saving. A successful list request does not establish inference or embedding access.
- Legacy live configurations migrate atomically to independent fields while retaining IDs, defaults and knowledge-base bindings. Historical name adjustments are reported in catalog migration metadata. Saved drafts remain separate and are never applied by migration or a direct-model save. Saved catalogs retain precedence over environment initialization; these endpoints never rewrite `.env`.

Specification and acceptance: [模型直接配置功能规格](design/模型直接配置功能规格.md), [实施记录](design/模型直接配置实施记录.md).

## Retrieval contract

### `POST /api/knowledge-bases/{kb_name}/query`

```json
{
  "query": "what is the helix angle of the gear",
  "top_k": 8,
  "search_mode": "local",
  "synthesize": false
}
```

- `top_k` — 1..50, defaults to the engine's configured default.
- `search_mode` — engine-specific; omit to use the knowledge base's own mode.
  `GET /query-options` lists what the engine accepts.
- `synthesize` — controls whether the response includes `answer`. When `true`,
  the endpoint exposes the engine's returned `answer` or `content`; it does not
  initiate an additional LLM synthesis step. With the default LlamaIndex engine,
  this value contains retrieved context. Engine-specific retrieval may itself use an LLM.

Response:

```json
{
  "query": "what is the helix angle of the gear",
  "kb_name": "gears",
  "provider": "llamaindex",
  "mode": "default",
  "sources": [
    {
      "content": "The helix angle of a gear is 20 degrees.",
      "file": "notes.txt",
      "title": "notes.txt",
      "source": "/data/knowledge_bases/gears/raw/notes.txt",
      "page": "",
      "chunk_id": "abc123",
      "score": 0.7417
    }
  ],
  "answer": "..."
}
```

`answer` is present only when `synthesize` is true. When the engine cannot
answer (no embedding model, index not built), the response still returns 200
with `sources: []`, an `error_type` and a human-readable `detail`, so a client
can show the fix instead of a stack trace. A missing knowledge base is 404; an
engine crash is 502.

### `GET /api/knowledge-bases/{kb_name}/query-options`

```json
{
  "kb_name": "gears",
  "provider": "llamaindex",
  "modes": ["default"],
  "default_mode": "default",
  "default_top_k": 8,
  "max_top_k": 50,
  "synthesize_available": true,
  "index_ready": true
}
```

## Indexing progress WebSocket

```
ws://127.0.0.1:8000/ws/knowledge-bases/{kb_name}/progress?task_id=<optional>
```

- No authentication; the socket is accepted immediately.
- Without `task_id` you receive live progress for the knowledge base.
- With `task_id` the current durable snapshot is replayed first, then live
  updates, so a reconnect never loses state.
- Progress is also persisted at `<kb>/.progress.json` and readable through
  `GET /api/knowledge-bases/{kb}/progress`.

Message shapes:

```json
{"type": "progress", "data": {"stage": "processing_file", "progress_percent": 42, "current": 3, "total": 7, "message": "..."}}
{"type": "progress", "data": {"stage": "completed", "progress_percent": 100, "current": 1, "total": 1, "message": "..."}}
{"type": "progress", "data": {"stage": "error", "progress_percent": 0, "error": "Initialization failed: ...", "message": "Initialization failed: ..."}}
```

Every WebSocket message uses the outer `type: "progress"`. Terminal states
are identified by `data.stage` equal to `completed` or `error`; there are no
separate `complete` or `error` message types. The progress value exposed by
the durable progress snapshot is `data.progress_percent`.

## curl examples

```bash
# create a knowledge base with one file
curl -X POST http://127.0.0.1:8000/api/knowledge-bases \
  -F name=gears -F files=@notes.pdf

# rebuild its index
curl -X POST http://127.0.0.1:8000/api/knowledge-bases/gears/reindex

# retrieve
curl -X POST http://127.0.0.1:8000/api/knowledge-bases/gears/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"helix angle","top_k":5}'

# inspect the model catalogue
curl http://127.0.0.1:8000/api/settings/catalog
```
