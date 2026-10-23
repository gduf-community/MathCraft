# math_q_agent — knowledge-base and model-configuration backend

A standalone FastAPI service that exposes two things and nothing else:

- **Knowledge bases** — create, upload, parse, index, retrieve, watch progress.
- **Model configuration** — providers, models, embedding, rerank roles, task
  assignment, connectivity tests, parsing-engine settings.

It was extracted from [DeepTutor](https://github.com/landing-ai/DeepTutor) at
commit `a31d8262` and reduced to a single-tenant service. This repository is a
**snapshot**: it does not track upstream.

## Quick start

```bash
uv venv .venv
uv pip install --python .venv/Scripts/python.exe -e .
.venv/Scripts/python.exe -m math_q_agent --port 8001
```

Then:

```bash
curl http://127.0.0.1:8001/healthz
curl http://127.0.0.1:8001/api/settings
curl -X POST http://127.0.0.1:8001/api/knowledge-bases -F name=demo -F files=@notes.pdf
```

Interactive API docs: `http://127.0.0.1:8001/docs`. Machine contract:
`python -c "import json,math_q_agent.api.main as m; print(json.dumps(m.app.openapi()))"`.

## Data directory

Everything the service persists lives under `$MATH_Q_HOME/data`:

```
data/
├── knowledge_bases/
│   ├── kb_config.json          # registry of every knowledge base
│   └── <kb>/
│       ├── raw/                # uploaded sources
│       ├── metadata.json
│       ├── .progress.json      # durable indexing progress
│       ├── version-N/          # index artifacts + meta.json
│       └── visual_assets/
├── parse_cache/<hash>/<parser>/ # parsed document cache
└── user/settings/*.json        # model catalog, parsing, engine settings
```

`MATH_Q_HOME` defaults to this repository root. Point it at a mounted volume in
any real deployment.

## Engines

Eight RAG engines are wired in, matching upstream:

| Engine | Default install | Notes |
| --- | --- | --- |
| `llamaindex` | yes | default engine, full text + vector + optional BM25 |
| `pageindex` | yes (`pageindex` package) | reasoning-as-retrieval |
| `graphrag` | no | `pip install -e ".[graphrag]"`, needs Python < 3.14 |
| `lightrag` | no | `pip install -e ".[rag-lightrag]"` |
| `lightrag_server` | no | talks to an external LightRAG server |
| `ima` | no | talks to an external IMA deployment |
| `kiwix` | no | talks to an external Kiwix server |
| `weknora` | no | talks to an external WeKnora deployment |

Optional engines import lazily: without their dependencies they report
*unavailable* in the engine list and in preflight, while their configuration
endpoints keep working. Cross-encoder reranking is the `.[rag-rerank]` extra.

Document parsing ships seven engines (`text_only`, `pymupdf4llm`, `markitdown`,
`liteparse`, `docling`, `mineru`, `tika`); all but `text_only` are optional and
install through the `parse-*` extras. MinerU and Tika can also run as external
CLI/service targets.

## Authentication

There is none. Every request is served as the local admin, `/api/auth/status`
reports `single_user: true`, and CORS is permissive by default. Bind to
loopback or put the service behind your own gateway.

## Testing

```bash
uv pip install --python .venv/Scripts/python.exe pytest pytest-asyncio
.venv/Scripts/python.exe -m pytest tests -q
```

The suite drives the real ASGI app through `TestClient` against a throwaway data
root (`tests/.data-home`). It starts a fake OpenAI-compatible `/embeddings`
endpoint so the default LlamaIndex pipeline can index and retrieve without any
external credentials — the end-to-end test creates a knowledge base, uploads a
document, waits for indexing and asserts retrieved passages.

## Known quirks kept from upstream

These are deliberate: the extraction preserves behaviour rather than refactoring
it. Each one is a real trap when reading the code.

1. Runtime settings files are created and exported into `os.environ` at **import
   time** of `math_q_agent.api.main`.
2. `CATALOG_PATH` and `PROJECT_ROOT` are resolved once at import; changing
   `MATH_Q_HOME` after import has no effect.
3. Catalogue writes reset the LLM/embedding client singletons; a no-op write
   must not.
4. The model catalogue has **no** environment-variable overlay layer — that is
   asserted by upstream tests and preserved.
5. `services/config/loader.py` still reads `main.yaml`/`agents.yaml` for chat
   agent parameters. Only the parsing/embedding/model paths are used here.

## Layout

```
math_q_agent/
├── api/            FastAPI app, routers, progress fan-out
├── knowledge/      knowledge-base domain: manager, manifests, indexing runs
├── services/
│   ├── config/     runtime settings + model catalogue
│   ├── llm/        provider clients (wire protocols)
│   ├── embedding/  embedding clients
│   ├── rag/        pipelines, retrieval service, index versioning
│   ├── parsing/    document parsing engines
│   ├── web_source/ web crawling connector
│   └── ...         connectors and support services
├── multi_user/     upstream user model, driven by the single-user stubs
├── capabilities/marginnote4/  MarginNote4 store (connector only)
└── runtime/        data-root resolution
```

See `STUBS.md` for every module replaced by a single-tenant stand-in.

## License

Apache-2.0. Upstream notices are preserved in `THIRD_PARTY_NOTICES.md`.
