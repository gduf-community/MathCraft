"""HTTP contracts of the standalone backend.

These are the seams that matter: every assertion goes through an HTTP request
and observes the response or the data directory, never a private function.
"""

from __future__ import annotations

import time


def _create_kb(client, name: str, text: bytes = b"The helix angle of a gear is 20 degrees.") -> dict:
    response = client.post(
        "/api/knowledge-bases",
        data={"name": name},
        files={"files": ("notes.txt", text, "text/plain")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _wait_for_index(client, name: str, timeout: float = 90.0) -> dict:
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        last = client.get(f"/api/knowledge-bases/{name}").json()
        stats = last.get("statistics", {})
        if stats.get("rag_initialized"):
            return stats
        status = stats.get("status")
        if status in {"error", "failed"}:
            raise AssertionError(f"indexing failed: {stats}")
        time.sleep(0.5)
    raise AssertionError(f"indexing timed out: {last}")


def test_healthz(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_single_tenant_identity(client):
    response = client.get("/api/auth/status")
    assert response.status_code == 200
    body = response.json()
    assert body["single_user"] is True
    assert body["auth_enabled"] is False
    assert body["user"]["is_admin"] is True


def test_model_catalog_is_readable(client):
    response = client.get("/api/settings")
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {"catalog", "providers", "ui", "task_kinds", "connection_targets"}
    services = body["catalog"]["services"]
    assert set(services) == {
        "llm",
        "task",
        "embedding",
        "search",
        "tts",
        "stt",
        "imagegen",
        "videogen",
    }
    # Secrets never round-trip in clear text.
    embedding = services["embedding"]["profiles"][0]
    assert embedding["api_key"] == "***"


def test_knowledge_base_lifecycle(client):
    created = _create_kb(client, "lifecycle-kb")
    assert created["name"] == "lifecycle-kb"

    listing = client.get("/api/knowledge-bases").json()
    assert any(item["name"] == "lifecycle-kb" for item in listing)

    detail = client.get("/api/knowledge-bases/lifecycle-kb")
    assert detail.status_code == 200
    assert detail.json()["name"] == "lifecycle-kb"

    files = client.get("/api/knowledge-bases/lifecycle-kb/files").json()
    assert [entry["name"] for entry in files["files"]] == ["notes.txt"]

    deleted = client.delete("/api/knowledge-bases/lifecycle-kb")
    assert deleted.status_code == 200
    assert client.get("/api/knowledge-bases/lifecycle-kb").status_code == 404


def test_duplicate_name_is_rejected(client):
    _create_kb(client, "dupe-kb")
    response = client.post(
        "/api/knowledge-bases",
        data={"name": "dupe-kb"},
        files={"files": ("notes.txt", b"second", "text/plain")},
    )
    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


def test_query_options_without_index(client):
    _create_kb(client, "options-kb")
    response = client.get("/api/knowledge-bases/options-kb/query-options")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "llamaindex"
    assert body["modes"] == ["default"]
    assert body["max_top_k"] == 50


def test_query_unknown_knowledge_base(client):
    response = client.post("/api/knowledge-bases/nope/query", json={"query": "anything"})
    assert response.status_code == 404


def test_index_and_retrieve_end_to_end(client):
    _create_kb(
        client,
        "e2e-kb",
        b"The helix angle of a gear is 20 degrees. A worm gear has a lead angle.",
    )
    stats = _wait_for_index(client, "e2e-kb")
    assert stats["rag_initialized"] is True

    response = client.post(
        "/api/knowledge-bases/e2e-kb/query",
        json={"query": "what is the helix angle", "top_k": 3},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kb_name"] == "e2e-kb"
    assert body["sources"], body
    first = body["sources"][0]
    assert {"content", "file", "score"} <= set(first)
    # Synthesis is opt-in: no answer unless requested.
    assert "answer" not in body
