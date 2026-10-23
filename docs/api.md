# API reference — math_q_agent

Base URL: `http://127.0.0.1:8001`. Interactive docs: `/docs`. Machine contract:
`/openapi.json` (a copy is committed at the repository root).

There is **no authentication**: every request is served as the single local
admin. CORS is permissive by default. Bind to loopback or front it with a
gateway you control.

Errors use FastAPI's envelope: `{"detail": "..."}` with a 4xx/5xx status.

## Knowledge bases

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/api/knowledge-bases` | List Knowledge Bases |
| `POST` | `/api/knowledge-bases` | Create Knowledge Base |
| `GET` | `/api/knowledge-bases/configs` | Get All Kb Configs |
| `POST` | `/api/knowledge-bases/configs/sync` | Sync Configs From Metadata |
| `POST` | `/api/knowledge-bases/connect-folder` | Connect Linked Folder Route |
| `POST` | `/api/knowledge-bases/connect-ima` | Connect Ima Route |
| `POST` | `/api/knowledge-bases/connect-kiwix` | Connect Kiwix Route |
| `POST` | `/api/knowledge-bases/connect-lightrag-server` | Connect Lightrag Server Route |
| `POST` | `/api/knowledge-bases/connect-marginnote4` | Connect Marginnote4 |
| `POST` | `/api/knowledge-bases/connect-obsidian` | Connect Obsidian Vault |
| `POST` | `/api/knowledge-bases/connect-weknora` | Connect Weknora Route |
| `GET` | `/api/knowledge-bases/default` | Get Default Kb |
| `PUT` | `/api/knowledge-bases/default/{kb_name}` | Set Default Kb |
| `POST` | `/api/knowledge-bases/delete` | Delete Knowledge Base By Name |
| `GET` | `/api/knowledge-bases/embedding-usage` | Get Embedding Usage |
| `GET` | `/api/knowledge-bases/health` | Health Check |
| `GET` | `/api/knowledge-bases/kiwix-articles` | Search Kiwix Articles |
| `GET` | `/api/knowledge-bases/kiwix-catalog` | List Kiwix Catalog |
| `POST` | `/api/knowledge-bases/list-ima` | List Ima Route |
| `POST` | `/api/knowledge-bases/probe-folder` | Probe Linked Folder Route |
| `POST` | `/api/knowledge-bases/probe-ima` | Probe Ima Route |
| `POST` | `/api/knowledge-bases/probe-kiwix` | Probe Kiwix Route |
| `POST` | `/api/knowledge-bases/probe-lightrag-server` | Probe Lightrag Server Route |
| `POST` | `/api/knowledge-bases/probe-weknora` | Probe Weknora Route |
| `PUT` | `/api/knowledge-bases/rag-pipelines/active-model` | Set Rag Active Model |
| `GET` | `/api/knowledge-bases/rag-pipelines/graphrag/config` | Get Graphrag Pipeline Config |
| `PUT` | `/api/knowledge-bases/rag-pipelines/graphrag/config` | Update Graphrag Pipeline Config |
| `POST` | `/api/knowledge-bases/rag-pipelines/graphrag/model-compatibility` | Test Graphrag Model Compatibility |
| `GET` | `/api/knowledge-bases/rag-pipelines/ima/config` | Get Ima Pipeline Config |
| `PUT` | `/api/knowledge-bases/rag-pipelines/ima/config` | Update Ima Pipeline Config |
| `GET` | `/api/knowledge-bases/rag-pipelines/lightrag-server/config` | Get Lightrag Server Pipeline Config |
| `PUT` | `/api/knowledge-bases/rag-pipelines/lightrag-server/config` | Update Lightrag Server Pipeline Config |
| `GET` | `/api/knowledge-bases/rag-pipelines/lightrag/config` | Get Lightrag Pipeline Config |
| `PUT` | `/api/knowledge-bases/rag-pipelines/lightrag/config` | Update Lightrag Pipeline Config |
| `GET` | `/api/knowledge-bases/rag-pipelines/lightrag/model-options` | Get Lightrag Model Options |
| `GET` | `/api/knowledge-bases/rag-pipelines/llamaindex/config` | Get Llamaindex Pipeline Config |
| `PUT` | `/api/knowledge-bases/rag-pipelines/llamaindex/config` | Update Llamaindex Pipeline Config |
| `GET` | `/api/knowledge-bases/rag-pipelines/model-options` | Get Rag Model Options |
| `GET` | `/api/knowledge-bases/rag-pipelines/pageindex/config` | Get Pageindex Pipeline Config |
| `PUT` | `/api/knowledge-bases/rag-pipelines/pageindex/config` | Update Pageindex Pipeline Config |
| `GET` | `/api/knowledge-bases/rag-pipelines/{provider}/preflight` | Get Rag Pipeline Preflight |
| `GET` | `/api/knowledge-bases/rag-providers` | Get Rag Providers |
| `PUT` | `/api/knowledge-bases/rag-providers/{provider}/mode` | Set Rag Provider Mode |
| `GET` | `/api/knowledge-bases/supported-file-types` | Get Supported File Types |
| `GET` | `/api/knowledge-bases/tasks/{task_id}/stream` | Stream Task Logs |
| `DELETE` | `/api/knowledge-bases/{kb_name}` | Delete Knowledge Base |
| `GET` | `/api/knowledge-bases/{kb_name}` | Get Knowledge Base Details |
| `GET` | `/api/knowledge-bases/{kb_name}/config` | Get Kb Config |
| `PUT` | `/api/knowledge-bases/{kb_name}/config` | Update Kb Config |
| `GET` | `/api/knowledge-bases/{kb_name}/file-preview-text/{filename}` | Serve Kb Raw File Text Preview |
| `GET` | `/api/knowledge-bases/{kb_name}/files` | List Kb Raw Files |
| `POST` | `/api/knowledge-bases/{kb_name}/files/move` | Move Kb File |
| `DELETE` | `/api/knowledge-bases/{kb_name}/files/{filename}` | Delete Kb File |
| `GET` | `/api/knowledge-bases/{kb_name}/files/{filename}` | Serve Kb Raw File |
| `POST` | `/api/knowledge-bases/{kb_name}/folders` | Create Kb Folder |
| `POST` | `/api/knowledge-bases/{kb_name}/github-source` | Add Github Source |
| `DELETE` | `/api/knowledge-bases/{kb_name}/github-source/{source_id}` | Remove Github Source |
| `GET` | `/api/knowledge-bases/{kb_name}/github-sources` | Get Github Sources |
| `PUT` | `/api/knowledge-bases/{kb_name}/indexing-policy` | Update Pending Indexing Policy |
| `GET` | `/api/knowledge-bases/{kb_name}/indexing-readiness` | Get Indexing Readiness |
| `GET` | `/api/knowledge-bases/{kb_name}/indexing-run` | Get Indexing Run |
| `POST` | `/api/knowledge-bases/{kb_name}/indexing-run/{task_id}/cancel` | Cancel Indexing Run |
| `POST` | `/api/knowledge-bases/{kb_name}/link-folder` | Link Folder |
| `GET` | `/api/knowledge-bases/{kb_name}/linked-folders` | Get Linked Folders |
| `DELETE` | `/api/knowledge-bases/{kb_name}/linked-folders/{folder_id}` | Unlink Folder |
| `GET` | `/api/knowledge-bases/{kb_name}/progress` | Get Progress |
| `POST` | `/api/knowledge-bases/{kb_name}/progress/clear` | Clear Progress |
| `POST` | `/api/knowledge-bases/{kb_name}/query` | Query Knowledge Base |
| `GET` | `/api/knowledge-bases/{kb_name}/query-options` | Get Query Options |
| `POST` | `/api/knowledge-bases/{kb_name}/reindex` | Reindex Knowledge Base |
| `GET` | `/api/knowledge-bases/{kb_name}/reindex-config` | Get Reindex Config |
| `POST` | `/api/knowledge-bases/{kb_name}/retry` | Retry Knowledge Base |
| `GET` | `/api/knowledge-bases/{kb_name}/source-page` | Kb Source Page |
| `POST` | `/api/knowledge-bases/{kb_name}/sync-folder/{folder_id}` | Sync Folder |
| `POST` | `/api/knowledge-bases/{kb_name}/sync-github` | Sync Github Sources |
| `POST` | `/api/knowledge-bases/{kb_name}/sync-web` | Sync Web Sources |
| `POST` | `/api/knowledge-bases/{kb_name}/upload` | Upload Files |
| `GET` | `/api/knowledge-bases/{kb_name}/visual-assets/{asset_id}` | Serve Kb Visual Asset |
| `GET` | `/api/knowledge-bases/{kb_name}/visual-coverage` | Kb Visual Coverage |
| `POST` | `/api/knowledge-bases/{kb_name}/web-source` | Add Web Source |
| `GET` | `/api/knowledge-bases/{kb_name}/web-source-sync` | Get Web Source Sync Jobs |
| `DELETE` | `/api/knowledge-bases/{kb_name}/web-source/{source_id}` | Remove Web Source |
| `POST` | `/api/knowledge-bases/{kb_name}/web-source/{source_id}/cancel` | Cancel Web Source Sync |
| `GET` | `/api/knowledge-bases/{kb_name}/web-source/{source_id}/pairings` | Get Web Source Pairings |
| `POST` | `/api/knowledge-bases/{kb_name}/web-source/{source_id}/retry` | Retry Web Source Sync |
| `PUT` | `/api/knowledge-bases/{kb_name}/web-source/{source_id}/schedule` | Update Web Source Schedule |
| `GET` | `/api/knowledge-bases/{kb_name}/web-sources` | Get Web Sources |

## Settings (model catalogue, providers, parsing)

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/api/settings` | Get Settings |
| `POST` | `/api/settings/apply` | Apply Catalog |
| `POST` | `/api/settings/apply/provider` | Apply Provider Edit |
| `POST` | `/api/settings/apply/registry` | Apply Registry Edit |
| `POST` | `/api/settings/apply/service` | Apply Catalog Service |
| `GET` | `/api/settings/catalog` | Get Catalog |
| `PUT` | `/api/settings/catalog` | Update Catalog |
| `GET` | `/api/settings/chat-attachments` | Get Chat Attachment Settings |
| `PUT` | `/api/settings/chat-attachments` | Update Chat Attachment Settings |
| `PUT` | `/api/settings/chat-response-timeout` | Update Chat Response Timeout |
| `GET` | `/api/settings/chat-starters` | Get Chat Starter Settings |
| `PUT` | `/api/settings/chat-starters` | Update Chat Starter Settings |
| `GET` | `/api/settings/document-parsing` | Get Document Parsing Settings |
| `PUT` | `/api/settings/document-parsing` | Update Document Parsing Settings |
| `POST` | `/api/settings/document-parsing/docling/test` | Test Docling Remote Connection |
| `POST` | `/api/settings/document-parsing/install` | Start Document Parsing Install |
| `POST` | `/api/settings/document-parsing/job/cancel` | Cancel Document Parsing Job |
| `GET` | `/api/settings/document-parsing/job/status` | Document Parsing Job Status |
| `POST` | `/api/settings/document-parsing/models/download` | Start Document Parsing Model Download |
| `POST` | `/api/settings/document-parsing/test` | Test Document Parsing |
| `POST` | `/api/settings/document-parsing/tika/test` | Test Tika Remote Connection |
| `DELETE` | `/api/settings/draft` | Discard Settings Draft |
| `GET` | `/api/settings/draft` | Get Settings Draft |
| `PUT` | `/api/settings/draft` | Update Settings Draft |
| `POST` | `/api/settings/fetch-models` | Fetch Models From Provider |
| `PUT` | `/api/settings/language` | Update Language |
| `GET` | `/api/settings/llm-options` | Get Llm Options |
| `GET` | `/api/settings/mineru` | Get Mineru Settings |
| `PUT` | `/api/settings/mineru` | Update Mineru Settings |
| `POST` | `/api/settings/mineru/models/download` | Start Mineru Models Download |
| `POST` | `/api/settings/mineru/models/download/cancel` | Cancel Mineru Models Download |
| `GET` | `/api/settings/mineru/models/download/status` | Mineru Models Download Status |
| `POST` | `/api/settings/mineru/test` | Test Mineru Connection |
| `POST` | `/api/settings/model-capabilities` | Resolve Model Capabilities |
| `GET` | `/api/settings/network` | Get Network Settings |
| `PUT` | `/api/settings/network` | Update Network Settings |
| `GET` | `/api/settings/presets` | Get Settings Presets |
| `POST` | `/api/settings/presets/{preset_id}/draft` | Stage Settings Preset |
| `GET` | `/api/settings/profile` | Get Settings Profile |
| `POST` | `/api/settings/profile/diff` | Diff Settings Profile |
| `POST` | `/api/settings/providers/codebuddy/auth/cancel` | Cancel Codebuddy Auth |
| `POST` | `/api/settings/providers/codebuddy/auth/logout` | Logout Codebuddy Auth |
| `POST` | `/api/settings/providers/codebuddy/auth/start` | Start Codebuddy Auth |
| `GET` | `/api/settings/providers/codebuddy/auth/status` | Get Codebuddy Auth Status |
| `POST` | `/api/settings/providers/openai-codex/models/reasoning-effort` | Update Openai Codex Reasoning Effort |
| `POST` | `/api/settings/providers/openai-codex/models/refresh` | Refresh Openai Codex Models |
| `POST` | `/api/settings/providers/openai-codex/oauth/cancel` | Cancel Openai Codex Oauth |
| `POST` | `/api/settings/providers/openai-codex/oauth/complete` | Complete Openai Codex Oauth |
| `POST` | `/api/settings/providers/openai-codex/oauth/logout` | Logout Openai Codex Oauth |
| `POST` | `/api/settings/providers/openai-codex/oauth/start` | Start Openai Codex Oauth |
| `GET` | `/api/settings/providers/openai-codex/oauth/status` | Get Openai Codex Oauth Status |
| `GET` | `/api/settings/readiness` | Get Settings Readiness |
| `POST` | `/api/settings/reset` | Reset Settings |
| `GET` | `/api/settings/sidebar` | Get Sidebar Settings |
| `PUT` | `/api/settings/sidebar/description` | Update Sidebar Description |
| `PUT` | `/api/settings/sidebar/nav-order` | Update Sidebar Nav Order |
| `POST` | `/api/settings/test-provider` | Test Provider Connection |
| `POST` | `/api/settings/tests/{service}/start` | Start Service Test |
| `POST` | `/api/settings/tests/{service}/{run_id}/cancel` | Cancel Service Test |
| `GET` | `/api/settings/tests/{service}/{run_id}/events` | Stream Service Test Events |
| `PUT` | `/api/settings/theme` | Update Theme |
| `GET` | `/api/settings/themes` | Get Themes |
| `POST` | `/api/settings/tour/complete` | Complete Tour |
| `POST` | `/api/settings/tour/reopen` | Reopen Tour |
| `GET` | `/api/settings/tour/status` | Tour Status |
| `GET` | `/api/settings/ui` | Get Ui Settings |
| `PUT` | `/api/settings/ui` | Update Ui Settings |

## System

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/api/system/status` | Get System Status |
| `POST` | `/api/system/test/embeddings` | Test Embeddings Connection |
| `POST` | `/api/system/test/llm` | Test Llm Connection |
| `POST` | `/api/system/test/search` | Test Search Connection |

## Identity

| Method | Path | Summary |
| --- | --- | --- |
| `GET` | `/api/auth/me` | Auth Me |
| `GET` | `/api/auth/status` | Auth Status |

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
curl -X POST http://127.0.0.1:8001/api/knowledge-bases \
  -F name=gears -F files=@notes.pdf

# rebuild its index
curl -X POST http://127.0.0.1:8001/api/knowledge-bases/gears/reindex

# retrieve
curl -X POST http://127.0.0.1:8001/api/knowledge-bases/gears/query \
  -H 'Content-Type: application/json' \
  -d '{"query":"helix angle","top_k":5}'

# inspect the model catalogue
curl http://127.0.0.1:8001/api/settings/catalog
```
