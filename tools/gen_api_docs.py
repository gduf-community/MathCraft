"""Generate docs/api.md from the committed openapi.json."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))

GROUPS = [
    (("/api/health", "/healthz"), "Health"),
    (("/api/knowledge-bases",), "Knowledge bases"),
    (("/api/generate",), "Question generation"),
    (("/api/chat",), "Question chat"),
    (("/api/questions",), "Saved questions and provenance"),
    (("/api/settings",), "Settings (model catalogue, providers, parsing)"),
    (("/api/system",), "System"),
    (("/api/auth",), "Identity"),
    (("/api/user-profile",), "Teacher profile and avatar"),
]


def table(prefixes: tuple[str, ...]) -> str:
    rows = []
    for path, ops in sorted(spec["paths"].items()):
        if not any(path.startswith(prefix) for prefix in prefixes):
            continue
        for method, op in sorted(ops.items()):
            summary = (op.get("summary") or "").strip()
            rows.append(f"| `{method.upper()}` | `{path}` | {summary} |")
    return "\n".join(rows)


PREAMBLE = """# API reference — MathCraft

Examples use `http://127.0.0.1:8000`, matching the README command
`python -m MathCraft`. Without a CLI override, `BACKEND_PORT`, or
saved system settings, the backend defaults to `8000`. Replace the HTTP and
WebSocket example ports with the actual deployment port. Interactive docs:
`/docs`. Machine contract: `/openapi.json` (a copy is committed at the repository root).

There is **no authentication**: every request is served as the single local
admin. CORS is permissive by default. Bind to loopback or front it with a
gateway you control.

Errors use FastAPI's `detail` envelope with a 4xx/5xx status. Most details are safe text; the documented direct-model committed/readback-failed outcome uses a structured code and message.

"""

MODEL_DIRECT = """## Direct model configuration contract

- Language (`llm`), embedding (`embedding`) and independent task (`task`) configurations keep stable `profile_id` / model `id` references. Each model has a `direct_config` object containing its own provider `binding`, `base_url`, credentials and applicable connection parameters. The legacy profile container is an internal compatibility detail.
- `POST /api/settings/direct-model` accepts `{service, profile_id, model, make_default?, restore_draft?, draft_updated_at?}`. It merges only this model into the latest live catalog within one locked atomic write; it never promotes a saved settings draft. The first model in a category becomes its default; adding another keeps the existing default. Saving an independent task configuration preserves the task mode.
- `POST /api/settings/direct-model/default` and `/api/settings/direct-model/delete` accept `{service, profile_id, model_id}`. Default selection is separate from selecting a model for editing. `POST /api/settings/direct-model/task-mode` accepts `{mode: "inherit" | "profiles"}` and preserves independent configurations.
- `GET /api/settings/direct-model/draft` returns a masked migrated preview of the saved draft, preserving its original `updated_at` revision and file. Explicit restoration uses `restore_draft: true` with `draft_updated_at` and the exact service/profile/model IDs; only this item is restored, and a changed draft revision is rejected. Ordinary saves never consult draft credentials.
- These operations return `{catalog}` with masked credentials. If the write completed but server-side readback failed, HTTP 503 includes `detail: {code: "model_write_committed_readback_failed", message}`; runtime caches are invalidated and clients must display a pending-verification state, retain local edits, and re-read rather than report a rejected write. Other storage failures use a safe string detail. Configuration names are trimmed, nonempty and globally unique across the three categories, using case-sensitive comparison. Model identifiers may repeat. Masks retain only the same model's saved credentials; an explicit empty value clears them.
- `POST /api/settings/test-provider` discovers models from the current form without saving it. Include `service`, `profile_id` and `model_id` when retaining an existing masked direct configuration; versioned explicit draft restoration uses the same two restoration fields. Unsaved model IDs are permitted when credentials are supplied directly. `/api/settings/fetch-models` uses the same discovery semantics. Results include `status`, `models` and the actual upstream `http_status` when available. A stable `reason` code classifies the result without exposing the upstream body; the UI presents a localized explanation. Transport failures have no invented HTTP status; rejected requests are never successful empty lists. No inference or embedding is performed.
- Discovery is optional and manual. Failure permits manual model identifiers and saving. A successful list request does not establish inference or embedding access.
- Legacy live configurations migrate atomically to independent fields while retaining IDs, defaults and knowledge-base bindings. Historical name adjustments are reported in catalog migration metadata. Saved drafts remain separate and are never applied by migration or a direct-model save. Saved catalogs retain precedence over environment initialization; these endpoints never rewrite `.env`.

Specification and acceptance: [模型直接配置功能规格](design/模型直接配置功能规格.md), [实施记录](design/模型直接配置实施记录.md).

"""

QUESTION_GENERATION = """## Question generation contract

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

Both generation paths check the selected document against a compatible published
index. Expected `/api/generate` failures use HTTP 422 with
`detail: {kind, message}`. Expected `/api/chat` failures return `done: false`,
empty `questions`, `error_type` and a readable `reply`, retaining confirmed slots.
Unknown original-problem structure/count returns `exercise_analysis_unavailable`.

Successful questions are saved with immutable server-validated `sources` and
`review_status`. Each model result declares only its actual `evidence_ids`;
unknown, missing or out-of-scope IDs and model-supplied locators are rejected.
Variants use `variant_reference`, new questions use `concept_reference`.
No confirmed originals are generated by the current batch.

### Saved questions

- `GET /api/questions` lists saved question snapshots.
- `GET /api/questions/{question_id}` reads one and rechecks original file identity.
- `PUT /api/questions/{question_id}` accepts only editable question fields
  (`type`, `score`, `difficulty`, `stem`, `options`, `answer`, `analysis`,
  `knowledgePoint`). Source fields are forbidden. Mathematical edits retain
  provenance and set `edited_requires_review`; score edits cannot clear it.

Snapshots live in `<MATHCRAFT_HOME>/data/questions/`; restart does not lose them.
Legacy questions remain readable with empty sources and `legacy_unknown`.
This does not add persistent favorites, publishing, study spaces or versions.

"""

RETRIEVAL = """## Retrieval contract

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
- `document_keys` — optional raw POSIX relative paths. Omitted/null means the
  ordinary full library; `[]` is an empty scope. Invalid paths fail explicitly.
  All retrieval branches and fallback stay within the same allowed corpus.
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

`GET /api/knowledge-bases/{kb_name}/document-readiness` reports per-document
index/source compatibility, not merely raw-file existence. Strict document
generation currently requires LlamaIndex; other engines explicitly report
`document_scope_unsupported`. Query options expose these capabilities.

Sources retain `content` as a display summary and add full `evidence_text`,
`unit_id`, `kb_id`, `document_key`, `source_digest`, `index_version`,
`parser_signature`, block IDs, zero-based `page_indices`, page labels,
`image_refs`, `image_urls`, `image_status`, trusted page/file URLs,
`completeness`, warnings and `source_status`. The current complete unit is an
entire parsed document, not a verified exercise. Engine-generated answers are
not textbook evidence. Long evidence is never silently sliced for generation:
whole units are reduced or `evidence_budget_exceeded` requests a smaller scope.
Unseen images or incomplete pages restrict strict generation. Numbered exercise
boundaries remain heuristic and expose unknown completeness / exercise status.

Legacy indexes without provenance remain available to ordinary queries with
an explicit unknown warning, but strict generation requires rebuilding. Missing,
changed and unindexed files have distinct results. Query responses report the
actual `retrieval_profile`, with warnings when BM25 is unavailable.
Saved source links include a digest; raw file requests with `source_hash` reject
replacement with HTTP 409. Source pages and visual assets retain their existing
source checks.

Parse artifact checks additionally expose `quality_status` (`passed`, `warning`,
`failed`, or legacy `unknown`) and `quality_policy` on document readiness and
evidence. These describe artifact integrity, never mathematical review. Quality
failures prevent cache completion and candidate publication. Cache hits are
rechecked before use, and compatible completed IR/slice archives can be reused
without cloud credentials. A new external request still requires credentials.

Indexing-run diagnostics retain stable parser/cloud error codes. Explicit retry
resumes known remote tasks; it does not automatically repeat an unknown
submission or ambiguous upload. Waiting-budget exhaustion retains resumable
task identity. Signed transport URLs remain backend-private and never enter
normal progress or evidence responses. Cloud recovery and sample boundaries:
[知识库第二批实施记录](design/知识库第二批实施记录.md).

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
curl -X POST http://127.0.0.1:8000/api/knowledge-bases \\
  -F name=gears -F files=@notes.pdf

# rebuild its index
curl -X POST http://127.0.0.1:8000/api/knowledge-bases/gears/reindex

# retrieve
curl -X POST http://127.0.0.1:8000/api/knowledge-bases/gears/query \\
  -H 'Content-Type: application/json' \\
  -d '{"query":"helix angle","top_k":5}'

# inspect the model catalogue
curl http://127.0.0.1:8000/api/settings/catalog
```
"""


def main() -> int:
    parts = [PREAMBLE]
    for prefix, title in GROUPS:
        parts.append(f"## {title}\n\n| Method | Path | Summary |\n| --- | --- | --- |\n{table(prefix)}\n\n")
    parts.append(QUESTION_GENERATION)
    parts.append("""## Teacher profile contract

- `GET /api/user-profile` reads the single local teacher's profile.
- `PUT /api/user-profile` accepts only `nickname`, `teaching_stage` and `grade`; identity remains read-only. Stage values are empty, `primary`, `junior`, or `senior`; grade is an empty string or a matching number string (1–6, 7–9, 10–12 respectively).
- `POST /api/user-profile/avatar` accepts a multipart `file` and persists the avatar independently. Valid PNG, JPEG or WebP images up to 5 MiB are accepted; each dimension is at most 4096 pixels; animated, SVG and invalid image bodies are rejected. Images are re-encoded as PNG, and the returned avatar URL includes a content hash to refresh the view.
- `GET /api/user-profile/avatar` serves the stored image; it returns 404 before the first upload. Profile reads return `avatar_url` or null.
- The UI previews selected images locally and uploads only after the user confirms Save Profile and the profile PUT succeeds. Profile and avatar writes are separate requests; a partial failure is reported separately and is not rolled back as one transaction.
- Personal data never enters the model catalog or draft. `/api/settings/profile` remains a configuration export and is not the teacher profile API.

""")
    parts.append(MODEL_DIRECT)
    parts.append(RETRIEVAL)
    text = "".join(parts)
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "api.md").write_text(text, encoding="utf-8")
    print(f"wrote docs/api.md ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
