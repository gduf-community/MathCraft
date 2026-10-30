"""Model discovery over local fake HTTP servers; no inference or real accounts."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import time
from threading import Thread

import pytest

from test_direct_model_settings import direct_client, model_entry, save_model


@pytest.fixture
def discovery_server():
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.server.requests.append(("GET", self.path, dict(self.headers)))
            if getattr(self.server, "drop_connection", False):
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            time.sleep(getattr(self.server, "response_delay", 0))
            self.send_response(self.server.status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(getattr(self.server, "raw_response", None) or json.dumps(self.server.payload).encode())
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_POST(self):
            self.server.requests.append(("POST", self.path, dict(self.headers)))
            self.send_error(500, "Unexpected model invocation")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.status = 200
    server.payload = {"data": [{"id": "fake-chat"}]}
    server.requests = []
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.base_url = f"http://127.0.0.1:{server.server_port}/v1"
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=3)
        server.server_close()


@pytest.mark.parametrize("http_status,status", [
    (401, "auth_error"), (403, "auth_error"), (429, "rate_limited"),
    (404, "unavailable"), (500, "http_error"), (302, "http_error"),
])
def test_discovery_routes_share_safe_failure_semantics(direct_client, discovery_server, http_status, status):
    discovery_server.status = http_status
    discovery_server.payload = {"error": "fake-sensitive-body Bearer fake-secret"}
    results = []
    for route in ("fetch-models", "test-provider"):
        response = direct_client.post(f"/api/settings/{route}", json={
            "binding": "deepseek", "base_url": discovery_server.base_url,
            "api_key": "fake-secret", "api_format": "openai",
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == status
        assert body["http_status"] == http_status
        assert body["models"] == []
        assert body["reason"]
        assert "fake-secret" not in response.text
        assert "fake-sensitive-body" not in response.text
        results.append(body)
    assert results[0] == results[1]
    assert [(method, path) for method, path, _ in discovery_server.requests] == [("GET", "/v1/models"), ("GET", "/v1/models")]
    assert all(headers["Authorization"] == "Bearer fake-secret" for _, _, headers in discovery_server.requests)


@pytest.mark.parametrize("binding,path,expected", [
    ("deepseek", "/v1", "/v1/models"),
    ("deepseek", "/v1/models", "/v1/models"),
    ("deepseek", "/models", "/models"),
    ("deepseek", "/v1/chat/completions", "/v1/models"),
    ("deepseek", "/v1/embeddings", "/v1/models"),
    ("ollama", "/api/embed", "/api/tags"),
    ("ollama", "/api/embeddings", "/api/tags"),
    ("ollama", "/api/tags", "/api/tags"),
])
def test_unsaved_model_discovery_normalizes_catalog_paths(direct_client, discovery_server, binding, path, expected):
    host = discovery_server.base_url.removesuffix("/v1")
    for route in ("fetch-models", "test-provider"):
        response = direct_client.post(f"/api/settings/{route}", json={
            "binding": binding, "base_url": host + path, "api_key": "fake-unsaved-key",
            "profile_id": "new-unsaved-profile", "model_id": "new-unsaved-model",
        })
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "connected", response.text
    assert [(method, path) for method, path, _ in discovery_server.requests] == [("GET", expected)] * 2
    assert direct_client.get("/api/settings/catalog").json()["catalog"]["services"]["llm"]["profiles"] == []


@pytest.mark.parametrize("scenario,expected", [
    ("normal", "connected"), ("empty", "connected"),
    ("non_json", "unavailable"), ("invalid_shape", "unavailable"),
    ("network", "unreachable"), ("timeout", "timeout"),
])
def test_discovery_distinguishes_empty_invalid_and_transport_results(direct_client, discovery_server, monkeypatch, scenario, expected):
    if scenario == "empty":
        discovery_server.payload = {"data": []}
    elif scenario == "non_json":
        discovery_server.raw_response = b"fake-sensitive-body not json"
    elif scenario == "invalid_shape":
        discovery_server.payload = {"error": "fake-sensitive-body"}
    elif scenario == "network":
        discovery_server.drop_connection = True
    elif scenario == "timeout":
        import aiohttp
        original_timeout = aiohttp.ClientTimeout
        monkeypatch.setattr(aiohttp, "ClientTimeout", lambda **kwargs: original_timeout(total=0.03))
        discovery_server.response_delay = 0.15
    results = []
    for route in ("fetch-models", "test-provider"):
        response = direct_client.post(f"/api/settings/{route}", json={
            "binding": "deepseek", "base_url": discovery_server.base_url, "api_key": "",
            "profile_id": "unsaved", "model_id": "unsaved-model",
        })
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == expected
        assert body["reason"]
        if scenario in {"network", "timeout"}:
            assert "http_status" not in body
        else:
            assert body["http_status"] == 200
        if scenario != "normal":
            assert body["models"] == []
        if scenario == "empty":
            assert body["reason"] == "empty_models"
        assert "fake-sensitive-body" not in response.text
        results.append(body)
    assert results[0] == results[1]
    assert discovery_server.requests
    assert all((method, path) == ("GET", "/v1/models") for method, path, _ in discovery_server.requests)


def test_discovery_restores_only_explicit_same_id_credential_sources(direct_client, discovery_server):
    from copy import deepcopy

    client = direct_client
    assert save_model(client, model_entry(base_url=discovery_server.base_url, extra_headers={"X-Fake": "fake-live-header"})).status_code == 200
    assert discovery_server.requests == []
    catalog = client.get("/api/settings/catalog").json()["catalog"]
    draft_catalog = deepcopy(catalog)
    draft_catalog["services"]["llm"]["profiles"][0]["models"][0]["direct_config"].update(
        api_key="fake-draft-key", extra_headers={"X-Fake": "fake-draft-header"},
    )
    draft = client.put("/api/settings/draft", json={"catalog": draft_catalog}).json()["draft"]
    for restore in (False, True):
        for route in ("fetch-models", "test-provider"):
            response = client.post(f"/api/settings/{route}", json={
                "service": "llm", "profile_id": "p-first", "model_id": "m-first",
                "api_key": "***", "extra_headers": {"X-Fake": "***"},
                "restore_draft": restore, "draft_updated_at": draft["updated_at"],
            })
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "connected"
            headers = discovery_server.requests[-1][2]
            assert headers["Authorization"] == ("Bearer fake-draft-key" if restore else "Bearer fake-live-key")
            assert headers["X-Fake"] == ("fake-draft-header" if restore else "fake-live-header")
            assert "fake-live-key" not in response.text
            assert "fake-draft-key" not in response.text
    for route in ("fetch-models", "test-provider"):
        missing = client.post(f"/api/settings/{route}", json={
            "profile_id": "missing", "model_id": "missing", "api_key": "***",
            "base_url": discovery_server.base_url,
        })
        assert missing.status_code == 400, missing.text
    assert [(method, path) for method, path, _ in discovery_server.requests] == [("GET", "/v1/models")] * 4
    assert client.get("/api/settings/draft").json()["draft"] == draft
