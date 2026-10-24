"""Generate docs/api.md from the committed openapi.json."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))

GROUPS = [
    ("/api/knowledge-bases", "Knowledge bases"),
    ("/api/settings", "Settings (model catalogue, providers, parsing)"),
    ("/api/system", "System"),
    ("/api/auth", "Identity"),
]


def table(prefix: str) -> str:
    rows = []
    for path, ops in sorted(spec["paths"].items()):
        if not path.startswith(prefix):
            continue
        for method, op in sorted(ops.items()):
            summary = (op.get("summary") or "").strip()
            rows.append(f"| `{method.upper()}` | `{path}` | {summary} |")
    return "\n".join(rows)


PREAMBLE = """# API reference — MathCraft

Base URL: `http://127.0.0.1:8001`. Interactive docs: `/docs`. Machine contract:
`/openapi.json` (a copy is committed at the repository root).

There is **no authentication**: every request is served as the single local
admin. CORS is permissive by default. Bind to loopback or front it with a
gateway you control.

Errors use FastAPI's envelope: `{"detail": "..."}` with a 4xx/5xx status.

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
- `search_mode` — engine-specific; omit to use the knowledge base's own mode.
  `GET /query-options` lists what the engine accepts.
- `synthesize` — `false` returns retrieved passages only. `true` additionally
  asks the configured LLM to write an answer.

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
ws://127.0.0.1:8001/ws/knowledge-bases/{kb_name}/progress?task_id=<optional>
```

- No authentication; the socket is accepted immediately.
- Without `task_id` you receive live progress for the knowledge base.
- With `task_id` the current durable snapshot is replayed first, then live
  updates, so a reconnect never loses state.
- Progress is also persisted at `<kb>/.progress.json` and readable through
  `GET /api/knowledge-bases/{kb}/progress`.

Message shapes:

```json
{"type": "progress", "data": {"stage": "indexing", "percent": 42, "current": 3, "total": 7, "message": "..."}}
{"type": "error", "message": "Initialization failed: ..."}
{"type": "complete", "data": {"stage": "completed", "percent": 100}}
```

## curl examples

```bash
# create a knowledge base with one file
curl -X POST http://127.0.0.1:8001/api/knowledge-bases \\
  -F name=gears -F files=@notes.pdf

# rebuild its index
curl -X POST http://127.0.0.1:8001/api/knowledge-bases/gears/reindex

# retrieve
curl -X POST http://127.0.0.1:8001/api/knowledge-bases/gears/query \\
  -H 'Content-Type: application/json' \\
  -d '{"query":"helix angle","top_k":5}'

# inspect the model catalogue
curl http://127.0.0.1:8001/api/settings/catalog
```
"""


def main() -> int:
    parts = [PREAMBLE]
    for prefix, title in GROUPS:
        parts.append(f"## {title}\n\n| Method | Path | Summary |\n| --- | --- | --- |\n{table(prefix)}\n\n")
    parts.append(RETRIEVAL)
    text = "".join(parts)
    (ROOT / "docs").mkdir(exist_ok=True)
    (ROOT / "docs" / "api.md").write_text(text, encoding="utf-8")
    print(f"wrote docs/api.md ({len(text)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
