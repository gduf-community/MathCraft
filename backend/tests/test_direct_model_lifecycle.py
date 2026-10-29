"""Public client lifetime across read-only settings and rejected writes."""

from copy import deepcopy
import logging
import os
from pathlib import Path

import pytest

from test_direct_model_settings import direct_client, model_entry, save_model  # noqa: F401


@pytest.mark.parametrize("operation", ["read", "unchanged_save", "discovery", "rejected_write"])
def test_readonly_or_rejected_settings_keep_existing_clients(
    direct_client, embedding_server, tmp_path, monkeypatch, caplog, operation,
):
    from math_q_agent.services.embedding.client import get_embedding_client, reset_embedding_client
    from math_q_agent.services.llm.client import get_llm_client, reset_llm_client
    from math_q_agent.services.llm.config import clear_llm_config_cache

    # Public constructors may synchronize SDK environment; retain fixture isolation.
    monkeypatch.setenv("OPENAI_API_KEY", "fake-unused-environment-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://127.0.0.1:9/v1")
    caplog.set_level(logging.DEBUG)
    client = direct_client
    primary = model_entry(api_key="fake-lifecycle-llm-secret", base_url=embedding_server,
                          extra_headers={"X-Fake": "fake-lifecycle-header-secret"})
    saved = save_model(client, primary)
    assert saved.status_code == 200, saved.text
    embedding = model_entry("m-embed", "Lifecycle embedding", api_key="fake-lifecycle-embed-secret",
                            base_url=embedding_server + "/embeddings")
    embedding["dimension"] = 8
    assert save_model(client, embedding, service="embedding", profile_id="p-embed").status_code == 200
    baseline = client.get("/api/settings/catalog").json()["catalog"]
    llm = get_llm_client()
    embed = get_embedding_client()
    try:
        if operation == "read":
            assert client.get("/api/settings").status_code == 200
            assert client.get("/api/settings/catalog").status_code == 200
        elif operation == "unchanged_save":
            same = baseline["services"]["llm"]["profiles"][0]["models"][0]
            response = save_model(client, same)
            assert response.status_code == 200, response.text
        elif operation == "discovery":
            for route in ("/api/settings/test-provider", "/api/settings/fetch-models"):
                response = client.post(route, json={
                    **primary["direct_config"], "api_key": "***", "extra_headers": {"X-Fake": "***"},
                    "service": "llm", "profile_id": "p-first", "model_id": "m-first",
                })
                assert response.status_code == 200, response.text
                assert response.json()["status"] == "connected", response.text
        else:
            path = tmp_path / "data" / "user" / "settings" / "model_catalog.json"
            real_replace = os.replace

            def deny_catalog_replace(source, destination, *args, **kwargs):
                if Path(destination) == path:
                    raise PermissionError("fake-lifecycle-os-secret private-lifecycle-path")
                return real_replace(source, destination, *args, **kwargs)

            changed = deepcopy(primary)
            changed["name"] = "Rejected lifecycle rename"
            with monkeypatch.context() as filesystem:
                filesystem.setattr(os, "replace", deny_catalog_replace)
                response = save_model(client, changed)
            assert response.status_code == 503, response.text
            assert "fake-lifecycle-os-secret" not in response.text
            assert "private-lifecycle-path" not in response.text
        assert client.get("/api/settings/catalog").json()["catalog"] == baseline
        assert get_llm_client() is llm
        assert get_embedding_client() is embed
        for secret in ("fake-lifecycle-llm-secret", "fake-lifecycle-embed-secret",
                       "fake-lifecycle-header-secret", "fake-lifecycle-os-secret", "private-lifecycle-path"):
            assert secret not in caplog.text
    finally:
        reset_llm_client()
        reset_embedding_client()
        clear_llm_config_cache()
