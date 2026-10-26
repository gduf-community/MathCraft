"""Process-isolated startup regressions; never load the developer's .env."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


def _run(script: str, home: Path) -> None:
    env = dict(os.environ)
    env["MATH_Q_HOME"] = str(home)
    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("module", ["math_q_agent.api.main", "MathCraft.api.main"])
def test_import_only_declares_app(module: str, tmp_path: Path) -> None:
    _run(
        f'''
        import importlib
        import logging
        import os
        from pathlib import Path
        import math_q_agent.runtime.env as runtime_env

        def unexpected_load():
            raise AssertionError("import must not load .env")

        runtime_env.load_project_env = unexpected_load
        before_env = dict(os.environ)
        before_handlers = list(logging.getLogger().handlers)
        module = importlib.import_module({module!r})
        schema = module.app.openapi()
        assert "/healthz" in schema["paths"]
        assert dict(os.environ) == before_env
        assert logging.getLogger().handlers == before_handlers
        assert not Path(os.environ["MATH_Q_HOME"]).exists()
        ''',
        tmp_path / "unused-home",
    )


@pytest.mark.parametrize("module", ["math_q_agent.api.main", "MathCraft.api.main"])
def test_startup_uses_home_loaded_after_import(module: str, tmp_path: Path) -> None:
    _run(
        f'''
        import importlib
        import json
        import os
        from pathlib import Path
        from fastapi.testclient import TestClient
        import math_q_agent.runtime.env as runtime_env

        old_home = Path(os.environ["MATH_Q_HOME"])
        home = old_home.parent / "startup-home"
        settings = home / "data" / "user" / "settings"
        settings.mkdir(parents=True)
        (settings / "model_catalog.json").write_text("{{}}", encoding="utf-8")
        (settings / "system.json").write_text(
            json.dumps({{"frontend_port": 5678}}), encoding="utf-8"
        )
        (settings / "auth.json").write_text(
            json.dumps({{"enabled": True}}), encoding="utf-8"
        )
        for key in ("FRONTEND_PORT", "AUTH_ENABLED"):
            os.environ.pop(key, None)
        calls = []
        def load_test_env():
            calls.append("load")
            os.environ["MATH_Q_HOME"] = str(home)
            return home / ".env"

        runtime_env.load_project_env = load_test_env
        app = importlib.import_module({module!r}).app
        assert calls == []
        assert not old_home.exists()
        with TestClient(app) as client:
            assert calls == ["load"]
            assert app.state.ready is True
            assert client.get("/healthz").status_code == 200
            assert (settings / "document_parsing.json").exists()
            assert not old_home.exists()
            assert "http://localhost:5678" in app.state.cors_kwargs["allow_origins"]
            assert app.state.cors_kwargs["allow_origin_regex"] is None
            if {module!r} == "math_q_agent.api.main":
                response = client.options("/healthz", headers={{
                    "origin": "http://localhost:5678",
                    "access-control-request-method": "GET",
                }})
                assert response.status_code == 200
                assert response.headers["access-control-allow-origin"] == "http://localhost:5678"
                denied = client.options("/healthz", headers={{
                    "origin": "https://unconfigured.invalid",
                    "access-control-request-method": "GET",
                }})
                assert denied.status_code == 400
        assert app.state.ready is False
        ''',
        tmp_path / "import-home",
    )


def test_failed_initialization_never_reports_ready(tmp_path: Path) -> None:
    _run(
        '''
        from fastapi.testclient import TestClient
        import math_q_agent.runtime.env as runtime_env
        runtime_env.load_project_env = lambda: None
        import math_q_agent.api.main as main

        def fail():
            raise PermissionError("startup settings unavailable")

        main.ensure_runtime_settings_files = fail
        try:
            with TestClient(main.app):
                raise AssertionError("startup should have failed")
        except PermissionError:
            pass
        assert main.app.state.ready is False
        ''',
        tmp_path / "failed-home",
    )


def test_cli_reads_environment_before_parsing_listen_options(tmp_path: Path) -> None:
    _run(
        '''
        import os
        import sys
        import uvicorn
        import math_q_agent.runtime.env as runtime_env

        def load_test_env():
            os.environ["BACKEND_HOST"] = "127.0.0.2"
            os.environ["BACKEND_PORT"] = "8123"

        runtime_env.load_project_env = load_test_env
        from MathCraft.app import app, run
        calls = []
        uvicorn.run = lambda application, **kwargs: calls.append((application, kwargs))
        sys.argv = ["MathCraft"]
        run()
        assert calls[0][0] is app
        assert calls[0][1]["host"] == "127.0.0.2"
        assert calls[0][1]["port"] == 8123
        ''',
        tmp_path / "cli-home",
    )


@pytest.mark.parametrize(
    ("environment_port", "arguments", "expected_port"),
    [(None, [], 8127), ("8128", [], 8128), ("8128", ["--port", "8129"], 8129)],
)
def test_cli_preserves_saved_port_and_override_priority(
    tmp_path: Path, environment_port: str | None, arguments: list[str], expected_port: int,
) -> None:
    _run(
        f'''
        import json
        import os
        from pathlib import Path
        import sys
        import uvicorn
        import math_q_agent.runtime.env as runtime_env

        home = Path(os.environ["MATH_Q_HOME"])
        settings = home / "data" / "user" / "settings"
        settings.mkdir(parents=True)
        (settings / "system.json").write_text(
            json.dumps({{"backend_port": 8127}}), encoding="utf-8"
        )
        os.environ.pop("BACKEND_PORT", None)
        def load_test_env():
            if {environment_port!r} is not None:
                os.environ["BACKEND_PORT"] = {environment_port!r}

        runtime_env.load_project_env = load_test_env
        from MathCraft.app import run
        calls = []
        uvicorn.run = lambda application, **kwargs: calls.append(kwargs)
        sys.argv = ["MathCraft"] + {arguments!r}
        run()
        assert calls[0]["port"] == {expected_port}
        ''',
        tmp_path / "cli-home",
    )
