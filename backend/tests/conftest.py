"""Shared fixtures: an isolated data root, a fake embedding endpoint, a client.

The application resolves its runtime home and settings directory at import
time, so ``MATH_Q_HOME`` is set here before ``math_q_agent.api.main`` is
imported. Tests that need a clean tree remove ``tests/.data-home`` first.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import threading
import time
from pathlib import Path

import pytest

DATA_HOME = Path(__file__).resolve().parent / ".data-home"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_port(port: int, timeout: float = 10.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.05)
    raise RuntimeError(f"embedding stub did not start on port {port}")


@pytest.fixture(scope="session")
def embedding_server() -> str:
    """A minimal OpenAI-compatible ``/embeddings`` endpoint."""

    from fastapi import FastAPI
    import uvicorn

    app = FastAPI()

    @app.post("/v1/embeddings")
    async def embeddings(payload: dict) -> dict:
        inputs = payload.get("input")
        if isinstance(inputs, str):
            inputs = [inputs]
        vectors = []
        for index, text in enumerate(inputs):
            seed = sum(ord(ch) for ch in str(text)) or 1
            vectors.append(
                {
                    "object": "embedding",
                    "index": index,
                    "embedding": [float((seed >> (i % 8)) % 13 + 1) for i in range(8)],
                }
            )
        return {
            "object": "list",
            "model": payload.get("model", "fake-embed"),
            "data": vectors,
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }

    @app.get("/v1/models")
    async def models() -> dict:
        return {
            "object": "list",
            "data": [
                {"id": "fake-embed", "object": "model"},
                {"id": "gpt-test", "object": "model"},
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(payload: dict) -> dict:
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": payload.get("model", "gpt-test"),
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "OK"},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1, "total_tokens": 4},
        }

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    _wait_for_port(port)
    yield f"http://127.0.0.1:{port}/v1"
    server.should_exit = True
    thread.join(timeout=5)


def _catalog(base_url: str) -> dict:
    profile = {
        "id": "emb-1",
        "name": "Test embedding",
        "binding": "openai",
        "api_format": "openai",
        "base_url": base_url,
        "api_key": "test-key",
        "models": [
            {
                "id": "emb-model-1",
                "name": "fake-embed",
                "model": "fake-embed",
                "dimension": 8,
            }
        ],
    }
    empty = {"active_profile_id": None, "active_model_id": None, "profiles": []}
    services = {name: dict(empty) for name in ("llm", "task", "search", "tts", "stt", "imagegen", "videogen")}
    services["embedding"] = {
        "active_profile_id": "emb-1",
        "active_model_id": "emb-model-1",
        "profiles": [profile],
    }
    services["search"].pop("active_model_id", None)
    return {"version": 1, "connections": [], "services": services}


@pytest.fixture(scope="session")
def client(embedding_server: str):
    """A TestClient bound to a fresh data root with a working embedding slot."""

    shutil.rmtree(DATA_HOME, ignore_errors=True)
    DATA_HOME.mkdir(parents=True, exist_ok=True)
    os.environ["MATH_Q_HOME"] = str(DATA_HOME)
    # Tests must not inherit a developer's local MinerU deployment overrides.
    # The env override itself is covered with an explicit RuntimeSettingsService
    # process_env fixture in test_settings_parsing.py.
    for key in tuple(os.environ):
        if key.startswith("MINERU_"):
            os.environ.pop(key, None)
    # ``load_project_env`` runs during app import. Keep the key explicitly
    # empty so a developer's ignored local .env cannot reintroduce a real
    # MinerU credential into tests.
    os.environ["MINERU_API_TOKEN"] = ""

    from fastapi.testclient import TestClient

    import math_q_agent.api.main as main

    settings_dir = DATA_HOME / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "model_catalog.json").write_text(
        json.dumps(_catalog(embedding_server), indent=2), encoding="utf-8"
    )

    with TestClient(main.app) as test_client:
        yield test_client
