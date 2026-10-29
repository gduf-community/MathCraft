"""Only effective references may protect a provider container from deletion."""

from copy import deepcopy
import json

import pytest

from test_direct_model_settings import direct_client, model_entry, save_model


def test_independent_model_does_not_keep_a_legacy_source_dependency(direct_client):
    client = direct_client
    assert save_model(client).status_code == 200
    independent = model_entry("m-copy", "Independent copy")
    independent["provider_ref"] = {"service": "llm", "profile_id": "p-first"}
    assert save_model(client, independent, service="embedding", profile_id="p-copy").status_code == 200
    before = client.get("/api/settings/catalog").json()["catalog"]["services"]["embedding"]
    deleted = client.post("/api/settings/direct-model/delete", json={
        "service": "llm", "profile_id": "p-first", "model_id": "m-first",
    })
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["catalog"]["services"]["embedding"] == before
    from math_q_agent.services.config.provider_runtime import resolve_embedding_runtime_config

    resolved = resolve_embedding_runtime_config()
    assert resolved.model == "fake-chat"
    assert resolved.api_key == "fake-live-key"


def test_unmigrated_hidden_service_reference_still_protects_its_source(direct_client):
    client = direct_client
    assert save_model(client).status_code == 200
    catalog = client.get("/api/settings/catalog").json()["catalog"]
    changed = deepcopy(catalog)
    changed["services"]["tts"] = {
        "active_profile_id": "hidden-tts", "active_model_id": "hidden-voice",
        "profiles": [{"id": "hidden-tts", "provider_ref": {
            "service": "llm", "profile_id": "p-first"},
            "models": [{"id": "hidden-voice", "name": "Fake voice", "model": "fake-voice"}]}],
    }
    applied = client.post("/api/settings/apply", json={"catalog": changed})
    assert applied.status_code == 200, applied.text
    rejected = client.post("/api/settings/direct-model/delete", json={
        "service": "llm", "profile_id": "p-first", "model_id": "m-first",
    })
    assert rejected.status_code == 409, rejected.text
    assert client.get("/api/settings/catalog").json()["catalog"] == applied.json()["catalog"]


@pytest.mark.parametrize("contents", [
    pytest.param(b'{"fake-secret": "fake-registry-secret",', id="invalid-json"),
    pytest.param(b'\xff', id="invalid-encoding"),
    pytest.param(b'[]', id="non-object-registry"),
    pytest.param(b'{"knowledge_bases": null}', id="null-kb-map"),
    pytest.param(b'{"knowledge_bases": []}', id="non-object-kb-map"),
    pytest.param(b'{"knowledge_bases": {"fake-kb": null}}', id="non-object-entry"),
    pytest.param(b'{"knowledge_bases": {"fake-kb": {"embedding_selection": []}}}', id="non-object-selection"),
    pytest.param(b'{"knowledge_bases": {"fake-kb": {"embedding_selection": {"profile_id": "p-embed"}}}}', id="incomplete-selection"),
])
def test_bad_kb_registry_blocks_embedding_delete_without_catalog_changes(
    direct_client, tmp_path, contents,
):
    client = direct_client
    saved = save_model(
        client, model_entry("m-embed", "Protected embedding"),
        service="embedding", profile_id="p-embed",
    )
    assert saved.status_code == 200, saved.text
    before = client.get("/api/settings/catalog").json()["catalog"]
    registry = tmp_path / "data" / "knowledge_bases" / "kb_config.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_bytes(contents)

    rejected = client.post("/api/settings/direct-model/delete", json={
        "service": "embedding", "profile_id": "p-embed", "model_id": "m-embed",
    })
    assert rejected.status_code == 409, rejected.text
    assert rejected.json()["detail"] == (
        "Knowledge-base references could not be verified. Retry before deleting."
    )
    assert "fake-registry-secret" not in rejected.text
    assert client.get("/api/settings/catalog").json()["catalog"] == before


@pytest.mark.parametrize("registry_contents", [
    pytest.param(None, id="absent-registry"),
    pytest.param({}, id="legacy-empty-registry"),
    pytest.param({"knowledge_bases": {
        "legacy-kb": {},
        "unbound-kb": {"embedding_selection": None},
        "empty-selection-kb": {"embedding_selection": {}},
        "other-kb": {"embedding_selection": {"profile_id": "p-other", "model_id": "m-other"}},
    }}, id="unbound-and-unrelated-entries"),
])
def test_unreferenced_embedding_can_be_deleted_with_legacy_registry_entries(
    direct_client, tmp_path, registry_contents,
):
    client = direct_client
    saved = save_model(
        client, model_entry("m-embed", "Unused embedding"),
        service="embedding", profile_id="p-embed",
    )
    assert saved.status_code == 200, saved.text
    if registry_contents is not None:
        registry = tmp_path / "data" / "knowledge_bases" / "kb_config.json"
        registry.parent.mkdir(parents=True, exist_ok=True)
        registry.write_text(json.dumps(registry_contents), encoding="utf-8")

    deleted = client.post("/api/settings/direct-model/delete", json={
        "service": "embedding", "profile_id": "p-embed", "model_id": "m-embed",
    })
    assert deleted.status_code == 200, deleted.text
    assert client.get("/api/settings/catalog").json()["catalog"]["services"]["embedding"]["profiles"] == []
