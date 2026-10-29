"""Direct model edits at the isolated settings HTTP boundary."""

from copy import deepcopy
import json

import pytest


@pytest.fixture
def direct_client(tmp_path, monkeypatch):
    monkeypatch.setenv("MATH_Q_HOME", str(tmp_path))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from math_q_agent.services.path_service import PathService
    from math_q_agent.services.config import model_catalog, settings_draft
    from math_q_agent.api.routers import settings

    paths = PathService(tmp_path / "data")
    monkeypatch.setattr(PathService, "_instance", paths)
    for module in (model_catalog, settings_draft, settings):
        monkeypatch.setattr(module, "get_path_service", lambda: paths)
    catalog = model_catalog.ModelCatalogService(paths.get_settings_file("model_catalog"))
    draft = settings_draft.SettingsDraftService(paths.get_settings_file("settings_draft"))
    catalog.save({"version": 1, "connections": [], "services": {}})
    monkeypatch.setattr(settings, "get_model_catalog_service", lambda: catalog)
    monkeypatch.setattr(model_catalog, "get_model_catalog_service", lambda: catalog)
    monkeypatch.setattr(settings, "get_settings_draft_service", lambda: draft)
    app = FastAPI()
    app.include_router(settings.router, prefix="/api/settings")
    with TestClient(app) as client:
        yield client


def model_entry(model_id="m-first", name="First model", **connection):
    return {
        "id": model_id, "name": name, "model": "fake-chat",
        "direct_config": {
            "binding": "openai", "base_url": "http://127.0.0.1:9/v1",
            "api_key": "fake-live-key", "api_format": "openai", **connection,
        },
    }


def save_model(client, model=None, service="llm", profile_id="p-first", **fields):
    return client.post("/api/settings/direct-model", json={
        "service": service, "profile_id": profile_id,
        "model": model or model_entry(), **fields,
    })


def test_first_model_is_live_default_and_response_is_masked(direct_client):
    response = save_model(direct_client)
    assert response.status_code == 200, response.text
    bucket = response.json()["catalog"]["services"]["llm"]
    assert (bucket["active_profile_id"], bucket["active_model_id"]) == ("p-first", "m-first")
    assert bucket["profiles"][0]["models"][0]["direct_config"]["api_key"] == "***"
    assert "fake-live-key" not in response.text
    assert direct_client.get("/api/settings/catalog").json()["catalog"] == response.json()["catalog"]


def test_defaults_task_mode_and_delete_are_explicit_operations(direct_client):
    client = direct_client
    assert save_model(client).status_code == 200
    second = model_entry("m-second", "Second model")
    response = save_model(client, second)
    assert response.status_code == 200, response.text
    assert response.json()["catalog"]["services"]["llm"]["active_model_id"] == "m-first"
    target = {"service": "llm", "profile_id": "p-first", "model_id": "m-second"}
    selected = client.post("/api/settings/direct-model/default", json=target)
    assert selected.status_code == 200, selected.text
    assert selected.json()["catalog"]["services"]["llm"]["active_model_id"] == "m-second"
    task = save_model(client, model_entry("m-task", "Task backup"), service="task", profile_id="p-task")
    assert task.status_code == 200, task.text
    assert task.json()["catalog"]["services"]["task"]["mode"] == "inherit"
    task_selected = client.post("/api/settings/direct-model/default", json={
        "service": "task", "profile_id": "p-task", "model_id": "m-task",
    })
    assert task_selected.json()["catalog"]["services"]["task"]["mode"] == "inherit"
    for mode in ("profiles", "inherit"):
        changed = client.post("/api/settings/direct-model/task-mode", json={"mode": mode})
        assert changed.status_code == 200, changed.text
        assert changed.json()["catalog"]["services"]["task"]["mode"] == mode
        assert changed.json()["catalog"]["services"]["task"]["profiles"][0]["models"][0]["id"] == "m-task"
    deleted = client.post("/api/settings/direct-model/delete", json=target)
    assert deleted.status_code == 200, deleted.text
    bucket = deleted.json()["catalog"]["services"]["llm"]
    assert bucket["active_model_id"] == "m-first"
    assert [m["id"] for m in bucket["profiles"][0]["models"]] == ["m-first"]
    assert client.post("/api/settings/direct-model/delete", json=target).status_code == 404


def test_concurrent_names_are_unique_and_different_models_survive(direct_client):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    def pair(names):
        barrier = Barrier(2)
        def write(index):
            barrier.wait(timeout=5)
            return save_model(direct_client, model_entry(f"m-{index}-{names[index]}", names[index]),
                              service=("llm", "embedding")[index], profile_id=f"p-{index}")
        with ThreadPoolExecutor(max_workers=2) as pool:
            return list(pool.map(write, range(2)))

    responses = pair(["Shared name", "Shared name"])
    assert sorted(r.status_code for r in responses) == [200, 409]
    responses = pair(["Separate name", "separate name"])
    assert [r.status_code for r in responses] == [200, 200]
    catalog = direct_client.get("/api/settings/catalog").json()["catalog"]
    names = [m["name"] for s in catalog["services"].values()
             for p in s["profiles"] for m in p.get("models", [])]
    assert sorted(names) == ["Separate name", "Shared name", "separate name"]


@pytest.mark.parametrize("route", ["catalog", "apply", "apply/provider", "apply/service", "apply/registry"])
def test_legacy_write_paths_reject_duplicate_direct_names(direct_client, route):
    client = direct_client
    assert save_model(client).status_code == 200
    if route == "apply/registry":
        assert save_model(client, model_entry("m-duplicate", "Previously unique")).status_code == 200
    before = client.get("/api/settings/catalog").json()["catalog"]
    profile = {"id": "p-duplicate", "binding": "openai", "base_url": "http://127.0.0.1:9/v1",
               "api_key": "fake-other", "api_format": "openai",
               "models": [model_entry("m-duplicate", "First model")]}
    catalog = deepcopy(before)
    catalog.pop("direct_config_migration", None)
    catalog["services"]["embedding"]["profiles"] = [profile]
    if route == "catalog":
        response = client.put("/api/settings/catalog", json={"catalog": catalog})
    elif route == "apply":
        response = client.post("/api/settings/apply", json={"catalog": catalog})
    elif route == "apply/provider":
        response = client.post("/api/settings/apply/provider", json={"service": "embedding", "profile": profile})
    elif route == "apply/service":
        response = client.post("/api/settings/apply/service", json={"service": "embedding", "config": catalog["services"]["embedding"]})
    else:
        profile = before["services"]["llm"]["profiles"][0]
        response = client.post("/api/settings/apply/registry", json={"kind": "model", "service": "llm", "profile_id": profile["id"], "ref": {"service": "llm", "profile_id": profile["id"]}, "model": model_entry("m-duplicate", "First model")})
    assert response.status_code == 409, response.text
    assert client.get("/api/settings/catalog").json()["catalog"] == before


def test_mask_sources_require_explicit_versioned_draft_restore(direct_client):
    from math_q_agent.services.config.provider_runtime import resolve_llm_runtime_config

    client = direct_client
    assert save_model(client, model_entry(extra_headers={"X-Fake": "fake-live-header"})).status_code == 200
    assert save_model(client, model_entry("m-sibling", "Sibling")).status_code == 200
    before = client.get("/api/settings/catalog").json()["catalog"]
    draft_catalog = deepcopy(before)
    draft_models = draft_catalog["services"]["llm"]["profiles"][0]["models"]
    draft_models[0]["direct_config"].update(api_key="fake-draft-key", extra_headers={"X-Fake": "fake-draft-header"})
    draft_models[1]["model"] = "fake-unapplied-sibling"
    draft_response = client.put("/api/settings/draft", json={"catalog": draft_catalog})
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()["draft"]
    model = deepcopy(draft["catalog"]["services"]["llm"]["profiles"][0]["models"][0])
    model["name"] = "Updated current"
    ordinary = save_model(client, model)
    assert ordinary.status_code == 200, ordinary.text
    runtime = resolve_llm_runtime_config(catalog_only=True)
    assert runtime.api_key == "fake-live-key"
    assert runtime.extra_headers == {"X-Fake": "fake-live-header"}
    assert client.get("/api/settings/draft").json()["draft"] == draft
    stale = save_model(client, model, restore_draft=True, draft_updated_at="outdated")
    assert stale.status_code == 409, stale.text
    missing_revision = save_model(client, model, restore_draft=True)
    assert missing_revision.status_code == 400, missing_revision.text
    restored = save_model(client, model, restore_draft=True, draft_updated_at=draft["updated_at"])
    assert restored.status_code == 200, restored.text
    runtime = resolve_llm_runtime_config(catalog_only=True)
    assert runtime.api_key == "fake-draft-key"
    assert runtime.extra_headers == {"X-Fake": "fake-draft-header"}
    assert "fake-draft-key" not in restored.text
    assert client.get("/api/settings/draft").json()["draft"] == draft
    models = restored.json()["catalog"]["services"]["llm"]["profiles"][0]["models"]
    assert models[1]["model"] == "fake-chat"


def test_provider_is_required_and_saved_identifiers_are_trimmed(direct_client):
    client = direct_client
    response = save_model(client, model_entry(binding="   "))
    assert response.status_code == 400, response.text
    assert client.get("/api/settings/catalog").json()["catalog"]["services"]["llm"]["profiles"] == []
    model = model_entry("  m-trim  ", "  Trimmed config  ", api_key="")
    model["model"] = "  fake-trim  "
    response = save_model(client, model, profile_id="  p-trim  ")
    assert response.status_code == 200, response.text
    bucket = response.json()["catalog"]["services"]["llm"]
    assert (bucket["active_profile_id"], bucket["active_model_id"]) == ("p-trim", "m-trim")
    saved = bucket["profiles"][0]["models"][0]
    assert (saved["name"], saved["model"], saved["direct_config"]["api_key"]) == ("Trimmed config", "fake-trim", "")


def test_legacy_draft_preview_projects_model_references_without_writes(direct_client):
    client = direct_client
    assert save_model(client).status_code == 200
    before = client.get("/api/settings/catalog").json()["catalog"]
    legacy = deepcopy(before)
    legacy.pop("direct_config_migration", None)
    model = legacy["services"]["llm"]["profiles"][0]["models"][0]
    model.pop("direct_config")
    model["provider_ref"] = {"connection_id": "draft-connection"}
    legacy["connections"] = [{"id": "draft-connection", "binding": "deepseek", "provider": "deepseek",
                              "base_url": "http://127.0.0.1:9/v1", "api_format": "openai",
                              "api_key": "fake-draft-owner", "extra_headers": {"X-Fake": "fake-draft-header"}}]
    saved = client.put("/api/settings/draft", json={"catalog": legacy}).json()["draft"]
    response = client.get("/api/settings/direct-model/draft")
    assert response.status_code == 200, response.text
    preview = response.json()["draft"]
    projected = preview["catalog"]["services"]["llm"]["profiles"][0]["models"][0]
    assert preview["updated_at"] == saved["updated_at"]
    assert projected["id"] == "m-first"
    assert projected["direct_config"]["binding"] == "deepseek"
    assert projected["direct_config"]["base_url"] == "http://127.0.0.1:9/v1"
    assert projected["direct_config"]["api_key"] == "***"
    assert "fake-draft-owner" not in response.text
    assert "fake-draft-header" not in response.text
    assert client.get("/api/settings/draft").json()["draft"] == saved
    assert client.get("/api/settings/catalog").json()["catalog"] == before


def test_legacy_missing_name_is_derived_but_blank_or_direct_names_are_rejected(direct_client):
    client = direct_client
    catalog = client.get("/api/settings/catalog").json()["catalog"]
    catalog["services"]["llm"]["profiles"] = [{"id": "legacy-profile", "binding": "openai",
        "base_url": "http://127.0.0.1:9/v1", "api_key": "fake-key",
        "models": [{"id": "legacy-model", "model": "fake-legacy-model"}]}]
    response = client.post("/api/settings/apply", json={"catalog": catalog})
    assert response.status_code == 200, response.text
    saved = response.json()["catalog"]
    assert saved["services"]["llm"]["profiles"][0]["models"][0]["name"] == "fake-legacy-model"
    for entry in ({"id": "legacy-model", "model": "fake-legacy-model", "name": " "},
                  {key: value for key, value in model_entry().items() if key != "name"}):
        proposed = deepcopy(saved)
        proposed["services"]["llm"]["profiles"][0]["models"] = [entry]
        rejected = client.post("/api/settings/apply", json={"catalog": proposed})
        assert rejected.status_code == 400, rejected.text


def test_legacy_task_reference_copies_only_target_and_allocates_a_unique_name(direct_client):
    from math_q_agent.services.config.provider_runtime import resolve_llm_runtime_config

    client = direct_client
    assert save_model(client).status_code == 200
    assert save_model(client, model_entry("m-backup", "First model (2)"), service="task", profile_id="p-backup").status_code == 200
    before = client.get("/api/settings/catalog").json()["catalog"]
    task = deepcopy(before["services"]["task"])
    task.update(mode="reference", selection={"profile_id": "p-first", "model_id": "m-first"})
    response = client.post("/api/settings/apply/service", json={"service": "task", "config": task})
    assert response.status_code == 200, response.text
    catalog = response.json()["catalog"]
    assert catalog["services"]["llm"] == before["services"]["llm"]
    assert catalog["services"]["task"]["mode"] == "profiles"
    assert sorted(m["name"] for p in catalog["services"]["task"]["profiles"] for m in p["models"]) == ["First model (2)", "First model (3)"]
    assert resolve_llm_runtime_config(service_name="task", catalog_only=True).api_key == "fake-live-key"


def test_legacy_profile_credentials_do_not_override_direct_model_connections(direct_client):
    from math_q_agent.services.config.provider_runtime import resolve_llm_runtime_config

    client = direct_client
    assert save_model(client).status_code == 200
    assert save_model(client, model_entry("m-other", "Other profile"), profile_id="p-other").status_code == 200
    before = client.get("/api/settings/catalog").json()["catalog"]
    profile = deepcopy(before["services"]["llm"]["profiles"][0])
    profile.update(api_key="fake-updated-legacy-key", base_url="http://127.0.0.1:9/v1")
    response = client.post("/api/settings/apply/provider", json={"service": "llm", "profile": profile})
    assert response.status_code == 200, response.text
    assert resolve_llm_runtime_config(catalog_only=True).api_key == "fake-live-key"
    profiles = response.json()["catalog"]["services"]["llm"]["profiles"]
    assert profiles[1] == before["services"]["llm"]["profiles"][1]


def test_deleting_a_kb_bound_embedding_is_rejected_without_catalog_changes(direct_client, tmp_path):
    client = direct_client
    response = save_model(client, model_entry("m-embed", "Bound embedding"), service="embedding", profile_id="p-embed")
    assert response.status_code == 200, response.text
    before = response.json()["catalog"]
    root = tmp_path / "data" / "knowledge_bases"
    root.mkdir(parents=True)
    (root / "kb_config.json").write_text(json.dumps({"knowledge_bases": {
        "fake-bound-kb": {"path": "fake-bound-kb", "rag_provider": "llamaindex",
                          "embedding_selection": {"profile_id": "p-embed", "model_id": "m-embed"}},
    }}), encoding="utf-8")
    response = client.post("/api/settings/direct-model/delete", json={
        "service": "embedding", "profile_id": "p-embed", "model_id": "m-embed",
    })
    assert response.status_code == 409, response.text
    assert client.get("/api/settings/catalog").json()["catalog"] == before


@pytest.mark.parametrize("route", ["", "/catalog", "/direct-model"])
@pytest.mark.parametrize("failure", ["invalid_reference", "corrupt_json"])
def test_catalog_migration_failures_are_safe_and_preserve_the_original_file(direct_client, tmp_path, route, failure):
    path = tmp_path / "data" / "user" / "settings" / "model_catalog.json"
    if failure == "corrupt_json":
        original = b'{"api_key":"fake-migration-secret", broken'
    else:
        original = json.dumps({"version": 1, "connections": [], "services": {"llm": {"profiles": [{
            "id": "bad-profile", "api_key": "fake-migration-secret", "models": [{"id": "bad-model", "name": "Bad", "model": "fake", "provider_ref": {"connection_id": "missing"}}],
        }]}}}).encode()
    path.write_bytes(original)
    if route == "/direct-model":
        response = save_model(direct_client)
    else:
        response = direct_client.get("/api/settings" + route)
    assert response.status_code == 409, response.text
    assert "迁移" in response.json()["detail"]
    assert "原配置已保留" in response.json()["detail"]
    assert "fake-migration-secret" not in response.text
    assert path.read_bytes() == original


def test_changing_legacy_shared_source_keeps_each_direct_model_independent(direct_client):
    from math_q_agent.services.config.provider_runtime import resolve_llm_runtime_config

    client = direct_client
    assert save_model(client).status_code == 200
    assert save_model(client, model_entry("m-other", "Independent other"), profile_id="p-other").status_code == 200
    catalog = client.get("/api/settings/catalog").json()["catalog"]
    catalog["connections"] = [{"id": "shared", "binding": "openai", "provider": "openai",
                               "base_url": "http://127.0.0.1:9/v1", "api_key": "fake-old-shared"}]
    for profile in catalog["services"]["llm"]["profiles"]:
        profile["connection_id"] = "shared"
    established = client.put("/api/settings/catalog", json={"catalog": catalog})
    assert established.status_code == 200, established.text
    before = established.json()["catalog"]
    changed = deepcopy(before)
    changed["connections"][0]["api_key"] = "fake-changed-shared"
    changed["connections"][0]["base_url"] = "http://127.0.0.1:10/v1"
    response = client.put("/api/settings/catalog", json={"catalog": changed})
    assert response.status_code == 200, response.text
    old_models = [p["models"] for p in before["services"]["llm"]["profiles"]]
    new_models = [p["models"] for p in response.json()["catalog"]["services"]["llm"]["profiles"]]
    assert new_models == old_models
    runtime = resolve_llm_runtime_config(catalog_only=True)
    assert runtime.api_key == "fake-live-key"
    assert runtime.base_url == "http://127.0.0.1:9/v1"


@pytest.mark.parametrize("route", ["", "/catalog", "/direct-model"])
def test_catalog_storage_errors_are_safe_and_actionable(direct_client, tmp_path, monkeypatch, route):
    from pathlib import Path

    path = tmp_path / "data" / "user" / "settings" / "model_catalog.json"
    before = path.read_bytes()
    read_text = Path.read_text
    def denied_read(target, *args, **kwargs):
        if target == path:
            raise PermissionError("fake-read-secret private-storage-path")
        return read_text(target, *args, **kwargs)
    with monkeypatch.context() as filesystem:
        filesystem.setattr(Path, "read_text", denied_read)
        response = save_model(direct_client) if route == "/direct-model" else direct_client.get("/api/settings" + route)
    assert response.status_code == 503, response.text
    assert "存储读写失败" in response.json()["detail"]
    assert "fake-read-secret" not in response.text
    assert "private-storage-path" not in response.text
    assert path.read_bytes() == before


@pytest.mark.parametrize("operation", ["save", "default", "delete", "task-mode"])
def test_committed_write_with_unreadable_readback_is_pending_and_refreshes_runtime(
    direct_client, tmp_path, monkeypatch, operation,
):
    """An OS read fault after replace must not misreport a durable write as rejected."""
    import os
    from pathlib import Path
    from math_q_agent.services.llm.config import clear_llm_config_cache, get_llm_config

    client = direct_client
    assert save_model(client).status_code == 200
    assert save_model(client, model_entry("m-second", "Second model", base_url="http://127.0.0.1:10/v1")).status_code == 200
    clear_llm_config_cache()
    assert get_llm_config().base_url == "http://127.0.0.1:9/v1"
    path = tmp_path / "data" / "user" / "settings" / "model_catalog.json"
    real_replace, real_read = os.replace, Path.read_text
    committed = False

    def replace_then_lose_read(source, destination, *args, **kwargs):
        nonlocal committed
        result = real_replace(source, destination, *args, **kwargs)
        if Path(destination) == path:
            committed = True
        return result

    def unreadable_after_commit(target, *args, **kwargs):
        if target == path and committed:
            raise PermissionError("fake-post-write-secret private-settings-path")
        return real_read(target, *args, **kwargs)

    with monkeypatch.context() as filesystem:
        filesystem.setattr(os, "replace", replace_then_lose_read)
        filesystem.setattr(Path, "read_text", unreadable_after_commit)
        if operation == "save":
            response = save_model(client, model_entry(name="Saved new name", base_url="http://127.0.0.1:11/v1"))
        elif operation == "task-mode":
            response = client.post("/api/settings/direct-model/task-mode", json={"mode": "inherit"})
        else:
            response = client.post("/api/settings/direct-model/" + operation, json={
                "service": "llm", "profile_id": "p-first", "model_id": "m-first" if operation == "delete" else "m-second",
            })
    try:
        assert committed
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "model_write_committed_readback_failed"
        assert "fake-post-write-secret" not in response.text
        assert "private-settings-path" not in response.text
        confirmed = client.get("/api/settings/catalog").json()["catalog"]
        if operation == "save":
            assert confirmed["services"]["llm"]["profiles"][0]["models"][0]["name"] == "Saved new name"
        elif operation in {"default", "delete"}:
            assert confirmed["services"]["llm"]["active_model_id"] == "m-second"
        else:
            assert confirmed["services"]["task"]["mode"] == "inherit"
        expected_url = "http://127.0.0.1:11/v1" if operation == "save" else "http://127.0.0.1:10/v1" if operation in {"default", "delete"} else "http://127.0.0.1:9/v1"
        assert get_llm_config().base_url == expected_url
    finally:
        clear_llm_config_cache()


@pytest.mark.parametrize("replacement_key", ["fake-replaced-key", ""])
def test_direct_edit_keeps_other_runtime_and_advanced_fields(direct_client, replacement_key):
    from math_q_agent.services.config.provider_runtime import resolve_llm_runtime_config

    client = direct_client
    assert save_model(client).status_code == 200
    spare = model_entry("m-spare", "Spare advanced", api_format="openai_chat",
                        api_version="fake-version", extra_headers={"X-Fake": "fake-header"},
                        proxy="http://127.0.0.1:19", vendor_extension={"keep": True})
    spare.update(context_window=8192, reasoning_effort="high", custom_metadata={"keep": True})
    before = save_model(client, spare, profile_id="p-spare")
    assert before.status_code == 200, before.text
    selection = {"profile_id": "p-spare", "model_id": "m-spare"}
    runtime_before = resolve_llm_runtime_config(llm_selection=selection, catalog_only=True)
    changed = model_entry(name="Renamed primary", api_key=replacement_key,
                          base_url="http://127.0.0.1:10/v1", api_format="openai_responses",
                          wire_api="responses", api_version="fake-new-version", extra_headers={"X-New": "fake-new-header"})
    saved = save_model(client, changed)
    assert saved.status_code == 200, saved.text
    profiles = saved.json()["catalog"]["services"]["llm"]["profiles"]
    assert profiles[1] == before.json()["catalog"]["services"]["llm"]["profiles"][1]
    assert resolve_llm_runtime_config(llm_selection=selection, catalog_only=True) == runtime_before
    primary = resolve_llm_runtime_config(catalog_only=True)
    assert primary.api_key == replacement_key
    assert primary.base_url == "http://127.0.0.1:10/v1"
    assert primary.api_format == "openai_responses"
    assert primary.wire_api == "responses"
    assert primary.extra_headers == {"X-New": "fake-new-header"}
    confirmed = client.get("/api/settings/catalog").json()["catalog"]
    assert confirmed["services"]["llm"]["profiles"][1] == profiles[1]
