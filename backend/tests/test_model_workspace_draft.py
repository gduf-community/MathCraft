"""Model workspace drafts through HTTP and public runtime configuration readers.

Use function-scoped homes and production route registrations without startup's
project .env loader. No developer settings or provider accounts are used.
"""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread

import pytest


@pytest.fixture
def workspace_client(tmp_path, monkeypatch, embedding_server):
    monkeypatch.setenv("MATH_Q_HOME", str(tmp_path))
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    # Seed before importing routes so even incidental reads see only fake data.
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "model_catalog.json").write_text(
        json.dumps({"version": 1, "connections": [], "services": {}}),
        encoding="utf-8",
    )

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from math_q_agent.api.routers.settings import router

    isolated = FastAPI()
    isolated.include_router(router, prefix="/api/settings")
    with TestClient(isolated) as client:
        baseline = _catalog(embedding_server)
        response = client.post("/api/settings/apply", json={"catalog": baseline})
        assert response.status_code == 200, response.text
        yield client


def _catalog(base_url):
    return {
        "version": 1,
        "workspace_metadata": {"revision": "legacy-compatible"},
        "connections": [{
            "id": "shared-provider",
            "name": "Fake shared provider",
            "provider": "openai",
            "binding": "openai",
            "api_format": "openai",
            "source_service": "llm",
            "base_url": base_url,
            "api_key": "fake-live-key",
            "extra_headers": {"X-Workspace-Test": "fake-live-header"},
        }],
        "services": {
            "llm": {
                "active_profile_id": "main-profile",
                "active_model_id": "main-old",
                "profiles": [{
                    "id": "main-profile",
                    "name": "Multiple models",
                    "connection_id": "shared-provider",
                    "models": [
                        {"id": "main-old", "model": "fake-main-old"},
                        {"id": "main-new", "model": "fake-main-new",
                         "workspace_metadata": {"label": "keep-model-extension"}},
                    ],
                }],
            },
            "task": {
                "mode": "inherit",
                "active_profile_id": "task-private",
                "active_model_id": "task-independent",
                "profiles": [{
                    "id": "task-private",
                    "name": "Independent legacy task",
                    "binding": "openai",
                    "api_format": "openai",
                    "base_url": base_url,
                    "api_key": "fake-task-key",
                    "models": [{"id": "task-independent", "model": "fake-task-private"}],
                }],
            },
            "embedding": {
                "active_profile_id": "embedding-reference",
                "active_model_id": "embedding-old",
                "profiles": [{
                    "id": "embedding-reference",
                    "name": "Cross-service reference",
                    "provider_ref": {"service": "llm", "profile_id": "main-profile"},
                    "models": [
                        {"id": "embedding-old", "model": "fake-embed-old", "dimension": 8},
                        {"id": "embedding-new", "model": "fake-embed-new", "dimension": 16},
                    ],
                }],
            },
            "tts": {
                "active_profile_id": "voice-private",
                "active_model_id": "voice-model",
                "profiles": [{
                    "id": "voice-private", "binding": "openai", "base_url": base_url,
                    "api_key": "fake-voice-key",
                    "models": [{"id": "voice-model", "model": "fake-voice"}],
                    "workspace_metadata": {"label": "keep-other-service"},
                }],
            },
        },
    }


def _live(client):
    response = client.get("/api/settings/catalog")
    assert response.status_code == 200, response.text
    return response.json()["catalog"]


def _draft(client):
    response = client.get("/api/settings/draft")
    assert response.status_code == 200, response.text
    return response.json()["draft"]


def _save_draft(client, catalog, extensions=None):
    response = client.put(
        "/api/settings/draft",
        json={"catalog": catalog, "extensions": extensions or {}},
    )
    assert response.status_code == 200, response.text
    return response.json()["draft"]


def test_bodyless_apply_promotes_changed_defaults_and_resolves_shared_references(workspace_client):
    from math_q_agent.services.config.provider_runtime import (
        resolve_embedding_runtime_config,
        resolve_llm_runtime_config,
    )

    client = workspace_client
    before = _live(client)
    proposed = deepcopy(before)
    proposed["services"]["llm"]["active_model_id"] = "main-new"
    proposed["services"]["embedding"]["active_model_id"] = "embedding-new"
    proposed["services"]["task"].update({
        "mode": "reference",
        "selection": {"profile_id": "main-profile", "model_id": "main-old"},
    })
    proposed["connections"][0]["name"] = "Renamed shared provider"
    extensions = {"workspace_notes": {"selected_page": "embedding", "keep": ["opaque"]}}
    _save_draft(client, proposed, extensions)

    staged = _draft(client)
    assert staged["catalog"] == proposed
    assert staged["extensions"] == extensions
    assert _live(client) == before
    assert resolve_llm_runtime_config().model == "fake-main-old"
    assert resolve_llm_runtime_config(service_name="task").model == "fake-main-old"
    assert resolve_embedding_runtime_config().model == "fake-embed-old"

    applied = client.post("/api/settings/apply")
    assert applied.status_code == 200, applied.text
    after = _live(client)
    assert applied.json()["catalog"] == after
    assert after["services"]["llm"]["active_model_id"] == "main-new"
    assert after["services"]["embedding"]["active_model_id"] == "embedding-new"
    assert after["services"]["task"]["selection"] == {
        "profile_id": "main-profile", "model_id": "main-old",
    }
    assert after["services"]["llm"]["profiles"] == before["services"]["llm"]["profiles"]
    assert after["services"]["embedding"]["profiles"] == before["services"]["embedding"]["profiles"]
    assert after["services"]["task"]["mode"] == "profiles"
    for profile in before["services"]["task"]["profiles"]:
        assert profile in after["services"]["task"]["profiles"]
    assert len(after["services"]["task"]["profiles"]) == len(before["services"]["task"]["profiles"]) + 1
    assert after["services"]["tts"] == before["services"]["tts"]
    assert after["workspace_metadata"] == {"revision": "legacy-compatible"}
    llm = resolve_llm_runtime_config()
    task = resolve_llm_runtime_config(service_name="task")
    embedding = resolve_embedding_runtime_config()
    assert (llm.model, task.model, embedding.model, embedding.dimension) == (
        "fake-main-new", "fake-main-old", "fake-embed-new", 16,
    )
    for config in (llm, task, embedding):
        assert config.api_key == "fake-live-key"
        assert config.extra_headers["X-Workspace-Test"] == "fake-live-header"
    assert llm.base_url == before["connections"][0]["base_url"]
    assert embedding.base_url == before["connections"][0]["base_url"] + "/embeddings"
    assert _draft(client) is None


@pytest.fixture
def credential_provider():
    """An actual HTTP provider that identifies which fake credentials reached it."""
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            identities = {
                ("Bearer fake-live-key", "fake-live-header"): "credential-live",
                ("Bearer fake-draft-key", "fake-draft-header"): "credential-draft",
            }
            identity = identities.get((
                self.headers.get("Authorization"), self.headers.get("X-Workspace-Test"),
            ))
            status = 200 if self.path == "/v1/models" and identity else 401
            body = json.dumps({
                "object": "list",
                "data": [{"id": identity, "object": "model"}] if status == 200 else [],
            }).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            # Do not log request headers, including even these fake credentials.
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"http://127.0.0.1:{server.server_port}/v1"
        finally:
            server.shutdown()
            thread.join(timeout=5)


@pytest.mark.parametrize("source", ["connection", "legacy-profile"])
@pytest.mark.parametrize(
    "key,header,identity",
    [
        pytest.param("***", "***", "credential-live", id="keep"),
        pytest.param("fake-draft-key", "fake-draft-header", "credential-draft", id="replace"),
        pytest.param("", "", None, id="clear"),
    ],
)
def test_masked_draft_resave_keeps_replaces_or_clears_credentials(
    workspace_client, credential_provider, source, key, header, identity,
):
    from math_q_agent.services.config.provider_runtime import resolve_llm_runtime_config

    client = workspace_client
    service_name = "llm" if source == "connection" else "task"
    profile_id = "main-profile" if source == "connection" else "task-private"
    model_id = "main-old" if source == "connection" else "task-independent"

    def selected(catalog):
        profile = next(p for p in catalog["services"][service_name]["profiles"] if p["id"] == profile_id)
        return next(m for m in profile["models"] if m["id"] == model_id)

    before = _live(client)
    proposed = deepcopy(before)
    if service_name == "task":
        proposed["services"]["task"]["mode"] = "profiles"
    selected(proposed)["direct_config"].update(
        binding="openai", api_format="openai", api_key="fake-live-key",
        extra_headers={"X-Workspace-Test": "fake-live-header"}, base_url=credential_provider,
    )
    established = client.post("/api/settings/apply", json={"catalog": proposed})
    assert established.status_code == 200, established.text
    before = _live(client)
    assert resolve_llm_runtime_config(service_name=service_name).api_key == "fake-live-key"

    proposed = deepcopy(before)
    selected(proposed)["direct_config"].update(api_key=key, extra_headers={"X-Workspace-Test": header})
    _save_draft(client, proposed)
    saved = _draft(client)
    saved_credentials = selected(saved["catalog"])["direct_config"]
    assert saved_credentials["api_key"] == ("***" if key else "")
    assert saved_credentials["extra_headers"]["X-Workspace-Test"] == ("***" if header else "")
    selected(saved["catalog"])["name"] = "Renamed after masked read"
    _save_draft(client, saved["catalog"], saved["extensions"])
    staged = _draft(client)
    reread = client.get("/api/settings/draft")
    for secret in ("fake-live-key", "fake-draft-key", "fake-live-header", "fake-draft-header"):
        assert secret not in reread.text
    assert _live(client) == before
    assert resolve_llm_runtime_config(service_name=service_name).api_key == "fake-live-key"

    probe = client.post("/api/settings/test-provider", json={
        "service": service_name, "profile_id": profile_id, "model_id": model_id,
        "binding": "openai", "api_format": "openai", "base_url": credential_provider,
        "api_key": "***" if key else "", "extra_headers": {"X-Workspace-Test": "***" if header else ""},
        "restore_draft": True, "draft_updated_at": staged["updated_at"],
    })
    assert probe.status_code == 200, probe.text
    if identity is None:
        assert probe.json()["status"] == "auth_error", probe.text
    else:
        assert probe.json()["status"] == "connected", probe.text
        assert {item["id"] for item in probe.json()["models"]} == {identity}
    assert _live(client) == before

    applied = client.post("/api/settings/apply")
    assert applied.status_code == 200, applied.text
    after = _live(client)
    assert applied.json()["catalog"] == after
    assert selected(after)["name"] == "Renamed after masked read"
    assert selected(after)["direct_config"]["api_key"] == ("***" if key else "")
    assert _draft(client) is None
    resolved = resolve_llm_runtime_config(service_name=service_name)
    assert resolved.api_key == ("fake-live-key" if key == "***" else key)
    assert resolved.extra_headers["X-Workspace-Test"] == ("fake-live-header" if header == "***" else header)
    assert resolved.base_url == credential_provider



def test_task_modes_preserve_independent_configuration_across_bodyless_applies(workspace_client):
    from math_q_agent.services.config.provider_runtime import resolve_llm_runtime_config

    client = workspace_client
    independent = _live(client)["services"]["task"]["profiles"]
    expected_current = "fake-main-old"
    for mode, expected in (
        ("profiles", "fake-task-private"),
        ("reference", "fake-main-old"),
        ("inherit", "fake-main-new"),
        ("profiles", "fake-task-private"),
    ):
        before = _live(client)
        proposed = deepcopy(before)
        proposed["services"]["llm"]["active_model_id"] = "main-new"
        proposed["services"]["task"].update({
            "mode": mode,
            "selection": {"profile_id": "main-profile", "model_id": "main-old"},
        })
        if mode == "profiles":
            proposed["services"]["task"].update(active_profile_id="task-private", active_model_id="task-independent")
        _save_draft(client, proposed)
        assert _live(client) == before
        assert resolve_llm_runtime_config(service_name="task").model == expected_current

        applied = client.post("/api/settings/apply")
        assert applied.status_code == 200, applied.text
        after = _live(client)
        assert after["services"]["task"]["mode"] == ("profiles" if mode == "reference" else mode)
        for profile in independent:
            assert profile in after["services"]["task"]["profiles"]
        assert resolve_llm_runtime_config(service_name="task").model == expected
        assert _draft(client) is None
        expected_current = expected


def test_failed_apply_preserves_live_runtime_and_draft_for_retry(
    workspace_client, tmp_path, monkeypatch,
):
    from math_q_agent.services.config.provider_runtime import resolve_llm_runtime_config

    client = workspace_client
    before = _live(client)
    proposed = deepcopy(before)
    proposed["services"]["llm"]["active_model_id"] = "main-new"
    proposed["services"]["llm"]["profiles"][0]["models"][1]["direct_config"].update(
        api_key="fake-draft-key", extra_headers={"X-Workspace-Test": "fake-draft-header"},
    )
    _save_draft(client, proposed, {"workspace_notes": {"recover": "pending-edit"}})
    staged = _draft(client)
    real_replace = os.replace
    catalog_path = tmp_path / "data" / "user" / "settings" / "model_catalog.json"

    def deny_catalog_write(source, destination, *args, **kwargs):
        # Inject a failure only at the OS boundary, leaving all app code real.
        if Path(destination) == catalog_path:
            raise PermissionError("fake-draft-key at private-test-path")
        return real_replace(source, destination, *args, **kwargs)

    with monkeypatch.context() as filesystem:
        filesystem.setattr(os, "replace", deny_catalog_write)
        failed = client.post("/api/settings/apply")
    assert failed.status_code == 503, failed.text
    assert "fake-draft-key" not in failed.text
    assert "private-test-path" not in failed.text
    assert _live(client) == before
    assert resolve_llm_runtime_config().model == "fake-main-old"
    assert resolve_llm_runtime_config().api_key == "fake-live-key"
    assert _draft(client) == staged

    recovered = client.post("/api/settings/apply")
    assert recovered.status_code == 200, recovered.text
    assert _live(client)["services"]["llm"]["active_model_id"] == "main-new"
    resolved = resolve_llm_runtime_config()
    assert resolved.model == "fake-main-new"
    assert resolved.api_key == "fake-draft-key"
    assert resolved.extra_headers["X-Workspace-Test"] == "fake-draft-header"
    assert _draft(client) is None


@pytest.mark.parametrize(
    "declaration,expected_key,expected_headers",
    [
        pytest.param({}, "fake-pool-key", {"X-Fake-Auth": "fake-pool-header"}, id="undeclared"),
        pytest.param({"api_key": None, "extra_headers": None}, "fake-pool-key",
                     {"X-Fake-Auth": "fake-pool-header"}, id="inherit"),
        pytest.param({"api_key": "", "extra_headers": {}}, "", {}, id="clear"),
        pytest.param({"api_key": [], "extra_headers": {}}, [], {}, id="clear-key-pool"),
        pytest.param({"api_key": ["fake-private-a", "fake-private-b"],
                      "extra_headers": {"X-Fake-Auth": "fake-private-header"}},
                     ["fake-private-a", "fake-private-b"],
                     {"X-Fake-Auth": "fake-private-header"}, id="private-key-pool"),
    ],
)
def test_independent_profile_distinguishes_inherited_and_cleared_credentials(
    workspace_client, embedding_server, declaration, expected_key, expected_headers,
):
    from math_q_agent.services.config.provider_runtime import resolve_llm_runtime_config

    # Exercise legacy, unnormalised catalogs at the public runtime reader too.
    catalog = _catalog(embedding_server)
    primary = catalog["services"]["llm"]["profiles"][0]
    primary.pop("connection_id")
    primary.update({
        "binding": "openai", "base_url": embedding_server,
        "api_key": "fake-pool-key", "extra_headers": {"X-Fake-Auth": "fake-pool-header"},
    })
    task = catalog["services"]["task"]
    task["mode"] = "profiles"
    independent = task["profiles"][0]
    independent.pop("api_key")
    independent.pop("extra_headers", None)
    independent["base_url"] = embedding_server + "/private"
    independent.update(declaration)
    before = deepcopy(catalog)

    resolved = resolve_llm_runtime_config(catalog=catalog, service_name="task")

    assert resolved.model == "fake-task-private"
    assert resolved.base_url == embedding_server + "/private"
    assert resolved.api_key == expected_key
    assert resolved.extra_headers == expected_headers
    assert catalog == before


def test_bodyless_apply_preserves_explicit_direct_credential_clearing(workspace_client):
    from math_q_agent.services.config.provider_runtime import resolve_llm_runtime_config

    client = workspace_client
    before = _live(client)
    proposed = deepcopy(before)
    proposed["services"]["task"]["mode"] = "profiles"
    proposed["services"]["task"]["profiles"][0]["models"][0]["direct_config"].update({
        "api_key": None, "extra_headers": None,
    })
    _save_draft(client, proposed)
    assert _live(client) == before
    assert resolve_llm_runtime_config(service_name="task").model == "fake-main-old"

    applied = client.post("/api/settings/apply")
    assert applied.status_code == 200, applied.text
    after = _live(client)
    independent = after["services"]["task"]["profiles"][0]
    assert independent["models"][0]["direct_config"]["api_key"] is None
    assert independent["models"][0]["direct_config"]["extra_headers"] is None
    resolved = resolve_llm_runtime_config(service_name="task")
    assert resolved.model == "fake-task-private"
    assert resolved.api_key == ""
    assert resolved.extra_headers == {}
    assert _draft(client) is None


def test_cleared_independent_main_profile_does_not_borrow_another_profiles_key(workspace_client):
    from math_q_agent.services.config.provider_runtime import resolve_llm_runtime_config

    client = workspace_client
    proposed = _live(client)
    profiles = proposed["services"]["llm"]["profiles"]
    main = profiles[0]
    main.pop("connection_id")
    main["models"][0]["direct_config"].update(
        binding="openai", api_key="fake-main-private-key", extra_headers={"X-Fake-Auth": "fake-main-private-header"},
    )
    neighbor = deepcopy(main)
    neighbor.update({
        "id": "same-vendor-neighbor", "api_key": "fake-neighbor-key",
        "extra_headers": {"X-Fake-Auth": "fake-neighbor-header"},
        "models": [{"id": "neighbor-model", "model": "fake-neighbor-model"}],
    })
    profiles.append(neighbor)
    established = client.post("/api/settings/apply", json={"catalog": proposed})
    assert established.status_code == 200, established.text
    before = _live(client)
    assert resolve_llm_runtime_config().api_key == "fake-main-private-key"
    proposed = deepcopy(before)
    proposed["services"]["llm"]["profiles"][0]["models"][0]["direct_config"].update({"api_key": "", "extra_headers": {}})
    _save_draft(client, proposed)
    assert _live(client) == before
    assert resolve_llm_runtime_config().api_key == "fake-main-private-key"

    applied = client.post("/api/settings/apply")
    assert applied.status_code == 200, applied.text
    after = _live(client)
    assert after["services"]["llm"]["profiles"][0]["models"][0]["direct_config"]["api_key"] == ""
    assert after["services"]["llm"]["profiles"][1] == before["services"]["llm"]["profiles"][1]
    resolved = resolve_llm_runtime_config()
    assert resolved.model == "fake-main-old"
    assert resolved.api_key == ""
    assert resolved.extra_headers == {}
    assert _draft(client) is None


@pytest.mark.parametrize(
    "credentials,expected_key,expected_headers",
    [
        pytest.param({}, "fake-live-key", {"X-Workspace-Test": "fake-live-header"}, id="unchanged"),
        pytest.param({"api_key": None, "extra_headers": None}, "", {}, id="null-clears"),
        pytest.param({"api_key": "", "extra_headers": {}}, "", {}, id="clear"),
        pytest.param({"api_key": [], "extra_headers": {}}, [], {}, id="clear-key-pool"),
        pytest.param({"api_key": None, "extra_headers": {}}, "", {}, id="clear-only-headers"),
        pytest.param({"api_key": "", "extra_headers": None}, "", {}, id="clear-only-key"),
    ],
)
def test_saved_direct_task_credentials_do_not_inherit_and_survive_reload(
    workspace_client, tmp_path, credentials, expected_key, expected_headers,
):
    from math_q_agent.services.config.model_catalog import ModelCatalogService
    from math_q_agent.services.config.provider_runtime import resolve_llm_runtime_config

    client = workspace_client
    before = _live(client)
    proposed = deepcopy(before)
    connection = {"binding": "openai", "api_format": "openai",
                  "base_url": before["connections"][0]["base_url"],
                  "api_key": "fake-live-key", "extra_headers": {"X-Workspace-Test": "fake-live-header"}}
    connection.update(credentials)
    proposed["services"]["task"] = {
        "mode": "profiles", "active_profile_id": "direct-task", "active_model_id": "direct-task-model",
        "profiles": [{"id": "direct-task", "models": [{"id": "direct-task-model", "name": "Direct task",
                     "model": "fake-bare-task", "direct_config": connection}]}],
    }
    _save_draft(client, proposed)
    assert _live(client) == before
    applied = client.post("/api/settings/apply")
    assert applied.status_code == 200, applied.text
    stored = _live(client)["services"]["task"]["profiles"][0]["models"][0]["direct_config"]
    assert stored["api_key"] == ("***" if expected_key else credentials.get("api_key", "***"))
    resolved = resolve_llm_runtime_config(service_name="task")
    assert resolved.model == "fake-bare-task"
    assert resolved.api_key == expected_key
    assert resolved.extra_headers == expected_headers
    assert _draft(client) is None
    restarted = ModelCatalogService(tmp_path / "data" / "user" / "settings" / "model_catalog.json")
    reloaded = restarted.load()
    after_reload = resolve_llm_runtime_config(reloaded, service=restarted, service_name="task")
    assert (after_reload.model, after_reload.api_key, after_reload.extra_headers) == (
        "fake-bare-task", expected_key, expected_headers,
    )



def test_loading_legacy_catalog_preserves_missing_task_credentials_across_migration(
    workspace_client, tmp_path, embedding_server,
):
    from math_q_agent.services.config.model_catalog import ModelCatalogService
    from math_q_agent.services.config.provider_runtime import resolve_llm_runtime_config

    catalog = _catalog(embedding_server)
    task = catalog["services"]["task"]
    task["mode"] = "profiles"
    task["profiles"][0].pop("api_key")
    task["profiles"][0].pop("extra_headers", None)
    path = tmp_path / "legacy-catalog.json"
    path.write_text(json.dumps(catalog), encoding="utf-8")

    for _ in range(2):
        reader = ModelCatalogService(path)
        migrated = reader.load()
        resolved = resolve_llm_runtime_config(migrated, service=reader, service_name="task")
        assert resolved.model == "fake-task-private"
        assert resolved.api_key == "fake-live-key"
        assert resolved.extra_headers == {"X-Workspace-Test": "fake-live-header"}
        assert migrated["services"]["task"]["profiles"][0]["api_key"] is None
        assert migrated["services"]["task"]["profiles"][0]["extra_headers"] is None


@pytest.mark.parametrize("declare_empty_key", [False, True], ids=["missing", "clear"])
def test_environment_bootstrap_preserves_task_credential_intent(
    workspace_client, tmp_path, embedding_server, monkeypatch, declare_empty_key,
):
    from math_q_agent.services.config.model_catalog import ModelCatalogService
    from math_q_agent.services.config.provider_runtime import resolve_llm_runtime_config

    for name in tuple(os.environ):
        if name.startswith(("LLM_", "TASK_", "EMBEDDING_")):
            monkeypatch.delenv(name)
    for name, value in {
        "LLM_MODEL": "fake-env-main", "LLM_API_KEY": "fake-env-key",
        "LLM_BASE_URL": embedding_server, "TASK_MODEL": "fake-env-task",
        "TASK_MODE": "profiles",
    }.items():
        monkeypatch.setenv(name, value)
    if declare_empty_key:
        monkeypatch.setenv("TASK_API_KEY", "")
    path = tmp_path / "environment-catalog.json"

    for _ in range(2):
        reader = ModelCatalogService(path)
        catalog = reader.load()
        task = resolve_llm_runtime_config(catalog, service=reader, service_name="task")
        assert task.model == "fake-env-task"
        assert task.api_key == ("" if declare_empty_key else "fake-env-key")
        assert catalog["services"]["task"]["profiles"][0]["api_key"] == (
            "" if declare_empty_key else None
        )
