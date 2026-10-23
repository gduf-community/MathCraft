"""Model-configuration write path and engine availability.

Both are HTTP-level checks: one round-trips the catalogue through the API, the
other reads what the engine picker would show.
"""

from __future__ import annotations


def _llm_service() -> dict:
    return {
        "active_profile_id": "p-llm",
        "active_model_id": "m-llm",
        "profiles": [
            {
                "id": "p-llm",
                "name": "local",
                "binding": "openai",
                "api_format": "openai",
                "base_url": "http://127.0.0.1:9999/v1",
                "api_key": "sk-test",
                "models": [{"id": "m-llm", "name": "gpt-test", "model": "gpt-test"}],
            }
        ],
    }


def test_catalog_write_round_trip(client):
    catalog = client.get("/api/settings/catalog").json()["catalog"]
    catalog["services"]["llm"] = _llm_service()

    put = client.put("/api/settings/catalog", json={"catalog": catalog})
    assert put.status_code == 200, put.text

    stored = client.get("/api/settings").json()["catalog"]["services"]["llm"]
    assert stored["active_profile_id"] == "p-llm"
    assert stored["active_model_id"] == "m-llm"
    # Secrets are write-only: reads return the mask.
    assert stored["profiles"][0]["api_key"] == "***"

    applied = client.post("/api/settings/apply", json={"catalog": catalog})
    assert applied.status_code == 200, applied.text


def test_engine_picker_lists_every_pipeline(client):
    response = client.get("/api/knowledge-bases/rag-providers")
    assert response.status_code == 200
    providers = {item["id"]: item for item in response.json()["providers"]}
    assert {"llamaindex", "pageindex", "graphrag", "lightrag", "lightrag-server", "ima", "weknora"} <= set(
        providers
    )
    # The default engine must always be usable; optional binaries are reported,
    # never silently assumed present.
    assert providers["llamaindex"]["configured"] is True
    for provider in providers.values():
        assert isinstance(provider["configured"], bool)
