"""Direct model storage through isolated settings HTTP and public runtime seams."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MATH_Q_HOME", str(tmp_path))


@pytest.fixture
def settings_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MATH_Q_HOME", str(tmp_path))
    settings = tmp_path / "data" / "user" / "settings"
    settings.mkdir(parents=True)
    (settings / "model_catalog.json").write_text(
        json.dumps({"version": 1, "connections": [], "services": {}}), encoding="utf-8"
    )
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from MathCraft.api.routers.settings import router

    app = FastAPI()
    app.include_router(router, prefix="/api/settings")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _direct_catalog(service="llm"):
    return {
        "version": 1,
        "connections": [{"id": "shared", "binding": "openai", "api_key": "fake-shared"}],
        "services": {service: {
            "active_profile_id": "p", "active_model_id": "a",
            "profiles": [{"id": "p", "name": "Old container", "binding": "openai",
                "api_key": "fake-container", "base_url": "http://container.invalid/v1",
                "models": [{"id": "a", "name": "A", "model": "fake-model",
                    "direct_config": {"binding": "openai", "api_key": "",
                        "base_url": "", "extra_headers": {}, "api_version": "",
                        "api_format": "openai"}},
                    {"id": "b", "name": "B", "model": "fake-model",
                     "direct_config": {"binding": "openai", "api_key": "fake-other",
                         "base_url": "http://other.invalid/v1", "api_version": "other",
                         "extra_headers": {"X-Fake": "other"}, "api_format": "openai"}}]},
                {"id": "other", "binding": "openai", "api_key": "fake-pool",
                 "base_url": "http://pool.invalid/v1", "api_version": "pool",
                 "extra_headers": {"X-Fake": "pool"},
                 "models": [{"id": "c", "name": "C", "model": "fake-pool"}]}],
        }},
    }


@pytest.mark.parametrize("service", ["llm", "task", "embedding"])
def test_direct_empty_values_never_borrow_container_or_pool_credentials(service):
    from MathCraft.services.config.provider_runtime import (
        resolve_embedding_runtime_config, resolve_llm_runtime_config,
    )

    catalog = _direct_catalog(service)
    if service == "embedding":
        resolved = resolve_embedding_runtime_config(catalog)
    else:
        resolved = resolve_llm_runtime_config(catalog, service_name=service)
    assert resolved.api_key == ""
    assert resolved.api_version is None
    assert resolved.extra_headers == {}
    assert "invalid" not in resolved.base_url


def _legacy_catalog():
    connection = {"id": "shared", "name": "Fake connection", "binding": "openai",
                  "source_service": "llm", "api_format": "openai", "api_key": "fake-live",
                  "base_url": "http://fake.invalid/v1", "api_version": "fake-version",
                  "extra_headers": {"X-Fake": "fake-header"}, "proxy": "http://proxy.invalid",
                  "service_overrides": {"embedding": {"enabled": True,
                      "binding": "openai", "base_url": "http://embed.invalid/v1/embeddings"}}}
    def profile(pid, models):
        return {"id": pid, "binding": "openai", "provider_ref": {"connection_id": "shared"},
                "batch_size": 4, "batch_delay": 0.5, "models": models}
    return {"version": 1, "connections": [connection], "custom_metadata": {"keep": True},
            "services": {
                "llm": {"active_profile_id": "main", "active_model_id": "a", "profiles": [
                    profile("main", [{"id": "a", "name": " Same ", "model": "fake-main"},
                                     {"id": "b", "name": "Same", "model": "fake-backup"},
                                     {"id": "suffix", "name": "Same (2)", "model": "fake-suffix"},
                                     {"id": "case", "name": "same", "model": "fake-case"}])]},
                "embedding": {"active_profile_id": "embed", "active_model_id": "e", "profiles": [
                    profile("embed", [{"id": "e", "name": "Same", "model": "fake-embed",
                                       "dimension": 16, "send_dimensions": False}])]},
                "task": {"mode": "reference", "selection": {"profile_id": "main", "model_id": "b"},
                         "profiles": []},
                "tts": {"profiles": [], "custom_option": "keep"}}}


def test_read_migrates_formal_catalog_stably_without_applying_draft(settings_client, tmp_path):
    from MathCraft.services.config.model_catalog import ModelCatalogService
    from MathCraft.services.config.provider_runtime import (
        resolve_embedding_runtime_config, resolve_llm_runtime_config,
    )
    from MathCraft.services.rag.embedding_signature import signature_from_config

    path = tmp_path / "data/user/settings/model_catalog.json"
    legacy = _legacy_catalog()
    original_signature = signature_from_config(resolve_embedding_runtime_config(legacy)).hash()
    path.write_text(json.dumps(legacy), encoding="utf-8")
    draft = deepcopy(legacy)
    draft["connections"][0]["api_key"] = "fake-unapplied-draft"
    draft_path = path.with_name("settings_draft.json")
    draft_bytes = json.dumps({"version": 1, "catalog": draft}).encode()
    draft_path.write_bytes(draft_bytes)

    response = settings_client.get("/api/settings/catalog")
    assert response.status_code == 200, response.text
    public = response.json()["catalog"]
    main = public["services"]["llm"]["profiles"][0]
    assert main["models"][0]["direct_config"]["api_key"] == "***"
    names = [model["name"] for service in ("llm", "embedding", "task")
             for profile in public["services"][service]["profiles"] for model in profile["models"]]
    assert len(names) == len(set(names))
    assert "Same" in names and "same" in names and "Same (2)" in names
    assert public["direct_config_migration"]["version"] == 1
    renamed = public["direct_config_migration"]["renamed"]
    assert {"service": "llm", "profile_id": "main", "model_id": "a",
            "old_name": " Same ", "new_name": "Same"} in renamed
    assert {"service": "llm", "profile_id": "main", "model_id": "b",
            "old_name": "Same", "new_name": "Same (3)"} in renamed
    assert "fake-live" not in response.text and "fake-header" not in response.text
    assert draft_path.read_bytes() == draft_bytes
    migrated = ModelCatalogService(path).load()
    assert migrated["connections"][0]["id"] == "shared"
    assert migrated["custom_metadata"] == {"keep": True}
    assert migrated["services"]["tts"]["custom_option"] == "keep"
    assert migrated["services"]["llm"]["active_model_id"] == "a"
    assert migrated["services"]["task"]["mode"] == "profiles"
    assert migrated["services"]["task"]["selection"] == legacy["services"]["task"]["selection"]
    task = resolve_llm_runtime_config(migrated, service_name="task")
    assert task.model == "fake-backup" and task.api_key == "fake-live"
    assert signature_from_config(resolve_embedding_runtime_config(migrated)).hash() == original_signature
    embedding_profile = migrated["services"]["embedding"]["profiles"][0]
    assert embedding_profile["models"][0]["direct_config"]["batch_size"] == 4
    assert embedding_profile["id"] == "embed" and embedding_profile["models"][0]["id"] == "e"
    migrated["connections"][0]["api_key"] = "fake-changed-shared"
    migrated["services"]["llm"]["profiles"][0]["models"][1]["direct_config"]["api_key"] = "fake-changed-main"
    assert resolve_llm_runtime_config(migrated, service_name="task").api_key == "fake-live"
    before = path.read_bytes()
    assert settings_client.get("/api/settings/catalog").json() == response.json()
    assert path.read_bytes() == before


def test_masked_direct_secrets_follow_model_ids_after_reordering(settings_client, tmp_path):
    from MathCraft.services.config.model_catalog import ModelCatalogService
    from MathCraft.services.config.provider_runtime import resolve_llm_runtime_config

    path = tmp_path / "data/user/settings/model_catalog.json"
    service = ModelCatalogService(path)
    catalog = _direct_catalog()
    models = catalog["services"]["llm"]["profiles"][0]["models"]
    models[0]["direct_config"].update(api_key="fake-a", extra_headers={"X-Fake": "fake-a-header"},
                                        oauth={"refresh_token": "fake-nested-token"})
    models[1]["direct_config"].update(api_key="fake-b", extra_headers={"X-Fake": "fake-b-header"})
    service.save(catalog)
    public = settings_client.get("/api/settings/catalog").json()["catalog"]
    assert "fake-nested-token" not in json.dumps(public)
    public["services"]["llm"]["profiles"][0]["models"].reverse()
    response = settings_client.post("/api/settings/apply", json={"catalog": public})
    assert response.status_code == 200, response.text
    config = resolve_llm_runtime_config(service.load())
    assert config.api_key == "fake-a"
    assert config.extra_headers == {"X-Fake": "fake-a-header"}
    assert service.get_active_profile(service.load(), "llm")["oauth"] == {
        "refresh_token": "fake-nested-token"
    }
    assert "fake-a-header" not in response.text
    public = response.json()["catalog"]
    item = next(m for m in public["services"]["llm"]["profiles"][0]["models"] if m["id"] == "a")
    item["direct_config"].update(api_key="", extra_headers={})
    assert settings_client.post("/api/settings/apply", json={"catalog": public}).status_code == 200
    config = resolve_llm_runtime_config(service.load())
    assert config.api_key == "" and config.extra_headers == {}


@pytest.mark.parametrize("contents", [b'{"version": 1,', b'', b'[]'])
def test_invalid_formal_file_is_preserved_instead_of_env_bootstrap(settings_client, tmp_path, contents):
    path = tmp_path / "data/user/settings/model_catalog.json"
    path.write_bytes(contents)
    response = settings_client.get("/api/settings/catalog")
    assert response.status_code >= 400
    assert path.read_bytes() == contents


@pytest.mark.parametrize("service_name,local_endpoint", [
    ("llm", False), ("task", False), ("embedding", False), ("embedding", True),
])
def test_migration_freezes_actual_legacy_pool_inheritance(settings_client, tmp_path, service_name, local_endpoint):
    from MathCraft.services.config.model_catalog import ModelCatalogService
    from MathCraft.services.config.provider_runtime import (
        resolve_embedding_runtime_config, resolve_llm_runtime_config,
    )
    from MathCraft.services.rag.embedding_signature import signature_from_config

    path = tmp_path / "data/user/settings/model_catalog.json"
    empty_profile = {"id": "missing", "name": "Missing credentials", "binding": "openai",
                     "api_key": None, "extra_headers": None,
                     "models": [{"id": "missing-model", "name": "Before", "model": "fake-before"}]}
    pool = {"id": "pool", "binding": "openai", "api_key": "fake-inherited",
            "base_url": "http://127.0.0.1:9/v1/embeddings" if service_name == "embedding"
                        else "http://127.0.0.1:9/v1",
            "api_version": "fake-inherited-version", "extra_headers": {"X-Fake": "inherited"},
            "models": [{"id": "pool-model", "name": "Provider pool", "model": "fake-pool"}]}
    if local_endpoint:
        empty_profile["base_url"] = pool["base_url"]
        pool["binding"] = "vllm"
    legacy = {"version": 1, "services": {
        service_name: {"active_profile_id": "missing", "active_model_id": "missing-model",
                       "profiles": [empty_profile, pool], "mode": "profiles"}}}
    if service_name == "task":
        legacy["services"]["llm"] = {"profiles": [deepcopy(pool)]}
        legacy["services"]["task"]["profiles"] = [empty_profile]
    def resolve(catalog):
        if service_name == "embedding":
            return resolve_embedding_runtime_config(catalog)
        return resolve_llm_runtime_config(catalog, service_name=service_name)
    before = resolve(legacy)
    assert before.api_key == "fake-inherited"
    path.write_text(json.dumps(legacy), encoding="utf-8")
    response = settings_client.get("/api/settings/catalog")
    assert response.status_code == 200, response.text
    migrated = ModelCatalogService(path).load()
    after = resolve(migrated)
    assert (after.api_key, after.base_url, after.api_version, after.extra_headers) == (
        before.api_key, before.base_url, before.api_version, before.extra_headers)
    assert after.binding == before.binding
    if service_name == "embedding":
        if local_endpoint:
            assert before.binding == "vllm"
        assert signature_from_config(after).hash() == signature_from_config(before).hash()
    item = migrated["services"][service_name]["profiles"][0]["models"][0]
    assert item["direct_config"]["api_key"] == "fake-inherited"
    assert not {"models", "id", "name"} & item["direct_config"].keys()


@pytest.mark.parametrize("broken", ["task", "provider", "connection"])
def test_invalid_legacy_reference_stops_migration_without_partial_writes(settings_client, tmp_path, broken):
    path = tmp_path / "data/user/settings/model_catalog.json"
    legacy = _legacy_catalog()
    if broken == "task":
        legacy["services"]["task"]["selection"]["model_id"] = "missing"
    elif broken == "provider":
        legacy["services"]["embedding"]["profiles"][0]["provider_ref"] = {"connection_id": "missing"}
    else:
        profile = legacy["services"]["llm"]["profiles"][0]
        profile.pop("provider_ref")
        profile["connection_id"] = "missing"
    original = json.dumps(legacy).encode()
    path.write_bytes(original)
    for _ in range(2):
        response = settings_client.get("/api/settings/catalog")
        assert response.status_code >= 400
        assert path.read_bytes() == original
        assert "fake-live" not in response.text and "fake-header" not in response.text


def test_atomic_migration_replace_failure_preserves_original_and_retry_is_stable(settings_client, tmp_path, monkeypatch):
    import os
    from MathCraft.services.config.direct_model_config import migrate_direct_catalog

    path = tmp_path / "data/user/settings/model_catalog.json"
    original = json.dumps(_legacy_catalog()).encode()
    path.write_bytes(original)
    expected = migrate_direct_catalog(_legacy_catalog())
    replace = os.replace
    def fail_replace(source, destination):
        if Path(destination) == path:
            raise OSError("simulated interrupted atomic replace")
        return replace(source, destination)
    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_replace)
        assert settings_client.get("/api/settings/catalog").status_code >= 400
    assert path.read_bytes() == original
    assert not list(path.parent.glob(".model_catalog.json.*.tmp"))
    response = settings_client.get("/api/settings/catalog")
    assert response.status_code == 200, response.text
    actual = response.json()["catalog"]
    assert actual["services"]["task"]["active_model_id"] == expected["services"]["task"]["active_model_id"]
    assert actual["direct_config_migration"] == expected["direct_config_migration"]
    first = path.read_bytes()
    assert settings_client.get("/api/settings/catalog").json() == response.json()
    assert path.read_bytes() == first


def test_saved_direct_catalog_remains_authoritative_over_environment(settings_client, tmp_path, monkeypatch):
    from MathCraft.services.config.model_catalog import ModelCatalogService
    from MathCraft.services.config.provider_runtime import resolve_llm_runtime_config

    path = tmp_path / "data/user/settings/model_catalog.json"
    catalog = _direct_catalog()
    catalog["services"]["llm"]["profiles"][0]["models"][0]["direct_config"].update(
        api_key="fake-saved", base_url="http://saved.invalid/v1")
    ModelCatalogService(path).save(catalog)
    before = path.read_bytes()
    monkeypatch.setenv("LLM_MODEL", "fake-environment")
    monkeypatch.setenv("LLM_API_KEY", "fake-environment-key")
    monkeypatch.setenv("LLM_HOST", "http://environment.invalid/v1")
    for _ in range(2):
        response = settings_client.get("/api/settings/catalog")
        assert response.status_code == 200, response.text
        live = ModelCatalogService(path).load()
        runtime = resolve_llm_runtime_config(live)
        assert runtime.model == "fake-model" and runtime.api_key == "fake-saved"
        assert runtime.base_url == "http://saved.invalid/v1"
    assert path.read_bytes() == before
    import os
    assert os.environ["LLM_API_KEY"] == "fake-environment-key"


def test_legacy_local_embedding_root_migrates_to_the_original_visible_endpoint(settings_client, tmp_path):
    from MathCraft.services.config.provider_runtime import resolve_embedding_runtime_config

    path = tmp_path / "data" / "user" / "settings" / "model_catalog.json"
    original = {"version": 1, "connections": [], "services": {"embedding": {
        "active_profile_id": "legacy-embedding", "active_model_id": "legacy-model",
        "profiles": [{"id": "legacy-embedding", "binding": "openai",
            "base_url": "http://127.0.0.1:9/v1", "api_key": "fake-local-key",
            "models": [{"id": "legacy-model", "name": "Local embedding", "model": "fake-embed", "dimension": 8}]}],
    }}}
    path.write_text(json.dumps(original), encoding="utf-8")
    response = settings_client.get("/api/settings/catalog")
    assert response.status_code == 200, response.text
    catalog = response.json()["catalog"]
    model = catalog["services"]["embedding"]["profiles"][0]["models"][0]
    assert model["direct_config"]["base_url"] == "http://127.0.0.1:9/v1/embeddings"
    runtime = resolve_embedding_runtime_config()
    assert runtime.provider_name == "vllm"
    assert runtime.base_url == "http://127.0.0.1:9/v1/embeddings"
    assert runtime.api_key == "fake-local-key"
    assert settings_client.get("/api/settings/catalog").json()["catalog"] == catalog
