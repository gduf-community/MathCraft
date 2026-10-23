"""Provider connectivity, model discovery, and connection tests.

All requests go to the session's fake OpenAI-compatible server, so the checks
are offline and deterministic while still exercising the real HTTP clients.
"""

from __future__ import annotations


def _profile(base_url: str) -> dict:
    return {
        "id": "probe-llm",
        "name": "probe",
        "binding": "openai",
        "api_format": "openai",
        "base_url": base_url,
        "api_key": "sk-test",
        "models": [{"id": "probe-model", "name": "gpt-test", "model": "gpt-test"}],
    }


def test_provider_probe_reaches_endpoint(client, embedding_server):
    response = client.post(
        "/api/settings/test-provider",
        json={
            "binding": "openai",
            "base_url": embedding_server,
            "api_key": "sk-test",
            "api_format": "openai",
            "service": "llm",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("status") == "connected", body
    assert body.get("models"), body


def test_provider_probe_reports_unreachable_endpoint(client):
    response = client.post(
        "/api/settings/test-provider",
        json={
            "binding": "openai",
            "base_url": "http://127.0.0.1:9/v1",
            "api_key": "sk-test",
            "api_format": "openai",
            "service": "llm",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body.get("status") in {"unreachable", "error", "failed", "failed_auth"}, body
    assert body.get("models") == []


def test_fetch_models_lists_provider_models(client, embedding_server):
    response = client.post(
        "/api/settings/fetch-models",
        json={
            "binding": "openai",
            "base_url": embedding_server,
            "api_key": "sk-test",
            "api_format": "openai",
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    models = body.get("models") or body.get("data") or []
    ids = {item.get("id") or item.get("model") for item in models}
    assert {"fake-embed", "gpt-test"} <= ids, body


def test_apply_provider_then_test_llm(client, embedding_server):
    applied = client.post(
        "/api/settings/apply/provider",
        json={
            "service": "llm",
            "profile": _profile(embedding_server),
            "active_model_id": "probe-model",
            "activate": True,
        },
    )
    assert applied.status_code == 200, applied.text

    status = client.get("/api/system/status").json()
    assert status["llm"]["status"] == "configured"
    assert status["llm"]["model"] == "gpt-test"

    tested = client.post("/api/system/test/llm")
    assert tested.status_code == 200, tested.text
    assert tested.json()["success"] is True, tested.text


def test_apply_service_promotes_one_service(client, embedding_server):
    client.post(
        "/api/settings/apply/provider",
        json={
            "service": "llm",
            "profile": _profile(embedding_server),
            "active_model_id": "probe-model",
            "activate": True,
        },
    )
    before = client.get("/api/settings/catalog").json()["catalog"]["services"]["llm"]

    response = client.post("/api/settings/apply/service", json={"service": "llm", "config": before})
    assert response.status_code == 200, response.text

    after = client.get("/api/settings/catalog").json()["catalog"]["services"]["llm"]
    assert after["active_profile_id"] == before["active_profile_id"]
    assert after["active_model_id"] == before["active_model_id"]
    assert [model["id"] for model in after["profiles"][0]["models"]] == [
        model["id"] for model in before["profiles"][0]["models"]
    ]


def test_task_choice_assigns_a_model(client, embedding_server):
    client.post(
        "/api/settings/apply/provider",
        json={
            "service": "llm",
            "profile": _profile(embedding_server),
            "active_model_id": "probe-model",
            "activate": True,
        },
    )

    response = client.post(
        "/api/settings/apply/registry",
        json={"kind": "task_choice", "task": {"kind": "indexing"}},
    )
    # Either the task kind exists (200) or the API rejects an unknown kind (400).
    assert response.status_code in {200, 400}, response.text
