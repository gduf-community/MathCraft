"""Configuration defaults follow runtime home without reloading modules."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from MathCraft.logging.config import load_logging_config
from MathCraft.multi_user.context import reset_current_user, set_current_user
from MathCraft.multi_user.models import CurrentUser, UserScope
from MathCraft.multi_user.paths import get_admin_path_service, local_admin_user
from MathCraft.services.config import get_runtime_settings_dir, load_launch_settings
from MathCraft.services.config.capabilities_settings import get_visualize_params
from MathCraft.services.config.loader import (
    get_agent_params,
    get_chat_params,
    load_config_with_main,
    load_config_with_main_async,
    resolve_config_path,
)
from MathCraft.services.config.model_catalog import ModelCatalogService, get_model_catalog_service
from MathCraft.services.path_service import PathService, get_path_service
from MathCraft.services.search import _get_web_search_config


@pytest.fixture(autouse=True)
def isolated_paths(monkeypatch):
    # Preserve any application's existing singleton and request context.
    monkeypatch.setattr(PathService, "_instance", None)
    token = set_current_user(None)
    try:
        yield
    finally:
        reset_current_user(token)


def _seed(home: Path, *, level: str, budget: int, port: int) -> Path:
    settings = home / "data" / "user" / "settings"
    settings.mkdir(parents=True)
    (settings / "main.yaml").write_text(
        yaml.safe_dump({
            "logging": {"level": level},
            "tools": {"web_search": {"max_results": budget}},
        }), encoding="utf-8",
    )
    (settings / "agents.yaml").write_text(
        yaml.safe_dump({"capabilities": {
            "visualize": {"max_tokens": budget},
            "chat": {"responding": {"max_tokens": budget}},
        }}), encoding="utf-8",
    )
    (settings / "system.json").write_text(
        json.dumps({"backend_port": port}), encoding="utf-8",
    )
    return settings


@pytest.mark.asyncio
async def test_imported_configuration_follows_home_without_reset(tmp_path, monkeypatch):
    for key in ("BACKEND_PORT", "FRONTEND_PORT"):
        monkeypatch.delenv(key, raising=False)
    first_home = tmp_path / "first"
    second_home = tmp_path / "second"
    settings_a = _seed(first_home, level="DEBUG", budget=1200, port=18001)
    settings_b = _seed(second_home, level="ERROR", budget=2400, port=18002)
    services = []
    for home, settings, level, budget, port in (
        (first_home, settings_a, "DEBUG", 1200, 18001),
        (second_home, settings_b, "ERROR", 2400, 18002),
        (first_home, settings_a, "DEBUG", 1200, 18001),
    ):
        monkeypatch.setenv("MATHCRAFT_HOME", str(home))
        assert get_runtime_settings_dir() == settings
        assert get_path_service().project_root == home
        assert get_admin_path_service().get_settings_dir() == settings
        assert local_admin_user().scope.root == home / "data"
        assert resolve_config_path("main.yaml") == (settings / "main.yaml", False)
        config = load_config_with_main("main.yaml")
        assert config["logging"]["level"] == level
        assert config["paths"]["user_log_dir"] == str(home / "data/user/logs")
        assert await load_config_with_main_async("main.yaml") == config
        assert load_logging_config().level == level
        assert load_logging_config().log_dir == str(home / "data/user/logs")
        assert get_agent_params("visualize")["max_tokens"] == budget
        assert get_visualize_params()["max_tokens"] == budget
        assert get_chat_params()["responding"]["max_tokens"] == budget
        assert _get_web_search_config()["max_results"] == budget
        launch = load_launch_settings()
        assert launch.settings_dir == settings
        assert launch.backend_port == port
        assert ModelCatalogService().path == settings / "model_catalog.json"
        service = get_model_catalog_service()
        assert service.path == settings / "model_catalog.json"
        services.append(service)
    assert services[0] is services[2]
    assert services[0] is not services[1]


@pytest.mark.asyncio
async def test_explicit_paths_survive_home_switch(tmp_path, monkeypatch):
    home = tmp_path / "explicit"
    settings = _seed(home, level="DEBUG", budget=1200, port=18001)
    monkeypatch.setenv("MATHCRAFT_HOME", str(tmp_path / "ambient"))
    for key in ("BACKEND_PORT", "FRONTEND_PORT"):
        monkeypatch.delenv(key, raising=False)
    assert get_runtime_settings_dir(home) == settings
    assert load_config_with_main("main.yaml", home)["logging"]["level"] == "DEBUG"
    assert (await load_config_with_main_async("main.yaml", home))["logging"]["level"] == "DEBUG"
    assert load_launch_settings(home).settings_dir == settings
    assert load_launch_settings(home).backend_port == 18001
    catalog_path = tmp_path / "custom-catalog.json"
    catalog = ModelCatalogService(catalog_path)
    monkeypatch.setenv("MATHCRAFT_HOME", str(tmp_path / "changed"))
    catalog.save({"version": 1, "connections": [], "services": {}})
    assert catalog.path == catalog_path
    assert catalog_path.is_file()
    assert ModelCatalogService.get_instance(catalog_path).path == catalog_path.resolve()
    with pytest.raises(FileNotFoundError, match="ambient|changed"):
        resolve_config_path("main.yaml")


@pytest.mark.parametrize("kind", ["admin", "user"])
def test_explicit_scope_is_not_replaced_by_ambient_home(tmp_path, monkeypatch, kind):
    scoped_home = tmp_path / "scoped"
    settings = _seed(scoped_home, level="WARNING", budget=1800, port=18003)
    user = CurrentUser(
        id="test-account", username="test-account", role=kind,
        scope=UserScope(kind=kind, user_id="test-account", root=scoped_home / "data"),
    )
    token = set_current_user(user)
    try:
        for ambient in (tmp_path / "first", tmp_path / "second"):
            monkeypatch.setenv("MATHCRAFT_HOME", str(ambient))
            assert get_runtime_settings_dir() == settings
            assert load_logging_config().level == "WARNING"
            assert ModelCatalogService().path == settings / "model_catalog.json"
            expected_catalog = (
                ambient / "data/user/settings/model_catalog.json"
                if kind == "user" else settings / "model_catalog.json"
            )
            # Preserve the existing non-admin catalog inheritance policy.
            assert get_model_catalog_service().path == expected_catalog
    finally:
        reset_current_user(token)
    assert get_runtime_settings_dir() == tmp_path / "second/data/user/settings"


def test_explicit_path_service_singleton_is_not_replaced(tmp_path, monkeypatch):
    service = PathService(tmp_path / "pinned-data")
    monkeypatch.setattr(PathService, "_instance", service)
    monkeypatch.setenv("MATHCRAFT_HOME", str(tmp_path / "other"))
    assert get_path_service() is service
    assert get_runtime_settings_dir() == service.get_settings_dir()
