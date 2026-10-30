from __future__ import annotations

import json
from pathlib import Path

import pytest


pytestmark = pytest.mark.usefixtures("client")

def _clear_model_env(monkeypatch) -> None:
    for prefix in ("LLM", "TASK", "EMBEDDING"):
        for suffix in (
            "BINDING", "PROVIDER", "MODEL", "MODEL_ID", "API_KEY", "KEY",
            "BASE_URL", "HOST", "API_BASE_URL", "API_FORMAT", "API_VERSION",
            "DIMENSION", "EMBEDDING_DIMENSION", "PROFILE_NAME",
        ):
            monkeypatch.delenv(f"{prefix}_{suffix}", raising=False)


def test_empty_catalog_is_bootstrapped_from_env(tmp_path: Path, monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("LLM_BINDING", "openai")
    monkeypatch.setenv("LLM_MODEL", "gpt-test")
    monkeypatch.setenv("LLM_API_KEY", "env-llm-key")
    monkeypatch.setenv("LLM_HOST", "http://llm.local/v1")
    monkeypatch.setenv("TASK_MODEL", "task-test")
    monkeypatch.setenv("TASK_MODE", "inherit")
    monkeypatch.setenv("EMBEDDING_BINDING", "openai")
    monkeypatch.setenv("EMBEDDING_MODEL", "embed-test")
    monkeypatch.setenv("EMBEDDING_DIMENSION", "1536")

    from MathCraft.services.config.model_catalog import ModelCatalogService

    catalog = ModelCatalogService(tmp_path / "model_catalog.json").load()

    llm = catalog["services"]["llm"]["profiles"][0]
    task = catalog["services"]["task"]["profiles"][0]
    embedding = catalog["services"]["embedding"]["profiles"][0]
    assert llm["api_key"] == "env-llm-key"
    assert llm["base_url"] == "http://llm.local/v1"
    assert llm["models"][0]["model"] == "gpt-test"
    assert task["models"][0]["model"] == "task-test"
    assert catalog["services"]["task"]["mode"] == "inherit"
    assert embedding["models"][0]["dimension"] == 1536


def test_saved_catalog_overrides_env_values(tmp_path: Path, monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("LLM_BINDING", "openai")
    monkeypatch.setenv("LLM_MODEL", "env-model")
    monkeypatch.setenv("LLM_API_KEY", "env-key")
    monkeypatch.setenv("LLM_HOST", "http://env.local/v1")

    path = tmp_path / "model_catalog.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "connections": [],
                "services": {
                    "llm": {
                        "active_profile_id": "saved-profile",
                        "active_model_id": "saved-model",
                        "profiles": [
                            {
                                "id": "saved-profile",
                                "name": "Saved",
                                "binding": "openai",
                                "base_url": "http://saved.local/v1",
                                "api_key": "saved-key",
                                "models": [
                                    {
                                        "id": "saved-model",
                                        "name": "Saved",
                                        "model": "saved-model",
                                    }
                                ],
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    from MathCraft.services.config.model_catalog import ModelCatalogService

    catalog = ModelCatalogService(path).load()
    profile = catalog["services"]["llm"]["profiles"][0]
    assert profile["api_key"] == "saved-key"
    assert profile["base_url"] == "http://saved.local/v1"
    assert profile["models"][0]["model"] == "saved-model"



def test_existing_empty_catalog_stays_authoritative(tmp_path: Path, monkeypatch) -> None:
    _clear_model_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "env-model")
    path = tmp_path / "model_catalog.json"
    path.write_text("{}", encoding="utf-8")

    from MathCraft.services.config.model_catalog import ModelCatalogService

    catalog = ModelCatalogService(path).load()
    assert catalog["services"]["llm"]["profiles"] == []


def test_shell_environment_wins_over_dotenv_loader_contract(tmp_path: Path, monkeypatch) -> None:
    from MathCraft.services.config.model_catalog import ModelCatalogService

    _clear_model_env(monkeypatch)
    monkeypatch.setenv("LLM_MODEL", "shell-model")

    catalog = ModelCatalogService(tmp_path / "model_catalog.json").load()
    assert catalog["services"]["llm"]["profiles"][0]["models"][0]["model"] == "shell-model"
