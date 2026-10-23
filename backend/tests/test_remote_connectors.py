"""Remote connectors: an unreachable target must fail loudly and cheaply.

Kiwix, IMA, WeKnora and LightRAG-server knowledge bases are pointers to
external services. Nothing here requires such a service: the point is that a
wrong address produces a readable error, never a hang, a 500, or a knowledge
base that pretends to be connected.

Port 9 (discard) is used deliberately: connection is refused immediately.
"""

from __future__ import annotations

UNREACHABLE = "http://127.0.0.1:9"


def _names(client) -> set[str]:
    return {item["name"] for item in client.get("/api/knowledge-bases").json()}


def test_probe_lightrag_server_reports_unreachable(client):
    response = client.post(
        "/api/knowledge-bases/probe-lightrag-server",
        json={"server_url": UNREACHABLE, "api_key": ""},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("ok") is False, body
    assert body.get("error") or body.get("detail")


def test_connect_lightrag_server_refuses_unreachable(client):
    response = client.post(
        "/api/knowledge-bases/connect-lightrag-server",
        json={"name": "remote-lr", "server_url": UNREACHABLE, "api_key": ""},
    )
    assert response.status_code in {400, 502, 200}, response.text
    if response.status_code == 200:
        # If registration succeeded it must be flagged as not ready.
        detail = client.get("/api/knowledge-bases/remote-lr").json()
        assert detail["statistics"]["status"] != "ready"
        client.delete("/api/knowledge-bases/remote-lr")
    else:
        assert "remote-lr" not in _names(client)


def test_probe_weknora_reports_unreachable(client):
    response = client.post(
        "/api/knowledge-bases/probe-weknora",
        json={"server_url": UNREACHABLE, "api_key": "k", "knowledge_base_id": "kb-1"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("ok") is False, body


def test_probe_ima_reports_missing_configuration(client):
    response = client.post(
        "/api/knowledge-bases/probe-ima",
        json={"client_id": "", "api_key": "", "knowledge_base_id": "kb-1"},
    )
    assert response.status_code in {200, 400, 422}, response.text
    if response.status_code == 200:
        assert response.json().get("ok") is False


def test_probe_kiwix_reports_unreachable(client):
    response = client.post(
        "/api/knowledge-bases/probe-kiwix",
        json={"server_url": UNREACHABLE, "zim_name": "wikipedia_en_all"},
    )
    assert response.status_code in {200, 400, 502}, response.text
    if response.status_code == 200:
        assert response.json().get("ok") is False


def test_kiwix_catalog_reports_unreachable(client):
    response = client.get(
        "/api/knowledge-bases/kiwix-catalog", params={"server_url": UNREACHABLE}
    )
    assert response.status_code in {200, 400, 502}, response.text
    if response.status_code == 200:
        assert response.json().get("ok") is False or not response.json().get("items")


def test_invalid_github_source_is_rejected(client):
    client.post(
        "/api/knowledge-bases",
        data={"name": "gh-kb"},
        files={"files": ("notes.txt", b"placeholder", "text/plain")},
    )
    response = client.post(
        "/api/knowledge-bases/gh-kb/github-source",
        json={"repo_url": "https://github.com/example/definitely-not-a-real-repo-xyz"},
    )
    assert response.status_code in {400, 404, 422, 502}, response.text
    client.delete("/api/knowledge-bases/gh-kb")


def test_web_source_requires_a_url(client):
    client.post(
        "/api/knowledge-bases",
        data={"name": "web-kb"},
        files={"files": ("notes.txt", b"placeholder", "text/plain")},
    )
    response = client.post(
        "/api/knowledge-bases/web-kb/web-source",
        json={"url": ""},
    )
    assert response.status_code in {400, 422}, response.text
    sources = client.get("/api/knowledge-bases/web-kb/web-sources").json()
    assert (sources.get("sources") if isinstance(sources, dict) else sources) == []
    client.delete("/api/knowledge-bases/web-kb")
