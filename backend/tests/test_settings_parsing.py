"""Document-parsing engine configuration.

The settings surface must expose every engine, report which are available, and
accept an engine switch without disturbing the other engines' stored settings.
"""

from __future__ import annotations

ALL_ENGINES = {
    "text_only",
    "docling",
    "mineru",
    "tika",
    "markitdown",
    "pymupdf4llm",
    "liteparse",
}


def test_document_parsing_payload(client):
    response = client.get("/api/settings/document-parsing")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["engine"] in ALL_ENGINES
    assert ALL_ENGINES <= set(body["engines"]), set(body["engines"])
    available = body["available_engines"]
    available_ids = {
        item.get("id") or item.get("name") if isinstance(item, dict) else item for item in available
    }
    assert ALL_ENGINES >= available_ids
    # Availability is reported, never assumed: the pure-python engine works
    # everywhere, optional engines may be absent.
    assert "text_only" in available_ids
    # Readiness is the structured view the UI renders.
    assert isinstance(body["readiness"], dict)


def test_document_parsing_engine_switch_round_trip(client):
    original = client.get("/api/settings/document-parsing").json()["engine"]

    switched = client.put("/api/settings/document-parsing", json={"engine": "text_only"})
    assert switched.status_code == 200, switched.text
    assert client.get("/api/settings/document-parsing").json()["engine"] == "text_only"

    restored = client.put("/api/settings/document-parsing", json={"engine": original})
    assert restored.status_code == 200, restored.text
    assert client.get("/api/settings/document-parsing").json()["engine"] == original


def test_document_parsing_per_engine_update_is_isolated(client):
    before = client.get("/api/settings/document-parsing").json()
    mineru_before = dict(before["engines"]["mineru"])

    update = client.put(
        "/api/settings/document-parsing",
        json={"engines": {"mineru": {"language": "en"}}},
    )
    assert update.status_code == 200, update.text

    after = client.get("/api/settings/document-parsing").json()
    assert after["engines"]["mineru"]["language"] == "en"
    # A partial update must not wipe unrelated knobs.
    for key, value in mineru_before.items():
        if key == "language":
            continue
        assert after["engines"]["mineru"][key] == value

    # Other engines keep their slices untouched.
    assert after["engines"]["docling"] == before["engines"]["docling"]

    client.put("/api/settings/document-parsing", json={"engines": {"mineru": mineru_before}})


def test_mineru_env_overrides_persisted_settings(tmp_path: Path):
    from math_q_agent.services.config.runtime_settings import RuntimeSettingsService

    service = RuntimeSettingsService(
        tmp_path,
        process_env={
            "MINERU_MODE": "cloud",
            "MINERU_API_BASE_URL": "https://mineru.example.test",
            "MINERU_API_TOKEN": "fake-mineru-token",
        },
    )
    service.save_mineru({"mode": "local", "api_token": ""})

    effective = service.load_mineru()

    assert effective["mode"] == "cloud"
    assert effective["api_base_url"] == "https://mineru.example.test"
    assert effective["api_token"] == "fake-mineru-token"
