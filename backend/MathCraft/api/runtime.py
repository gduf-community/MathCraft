"""Runtime initialization and CORS for the unified MathCraft application.

This replaces DeepTutor's 833-line application factory. Everything tied to the
chat turn loop (dependency container, tool/capability registry validation,
partners, events, background leader, data migrations, frontend static assets)
is gone. What remains is the surface this service exists for:

    /api/knowledge-bases/*   knowledge bases, files, indexing, retrieval
    /ws/knowledge-bases/*    indexing progress
    /api/settings/*          model catalog, providers, tasks, parsing config
    /api/system/*            connectivity tests and status
    /api/auth/*              single-tenant identity (always the local admin)

Runtime settings, environment exports and logging are initialized by the ASGI
lifespan. The single application and its routes are assembled in MathCraft.app.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from MathCraft.runtime.env import load_project_env
from MathCraft.logging import configure_logging
from MathCraft.services.config import (
    ensure_runtime_settings_files,
    export_runtime_settings_to_env,
    load_auth_settings,
    load_system_settings,
)
from MathCraft.services.config.origins import normalize_origins

logger = logging.getLogger(__name__)


def build_cors_kwargs() -> dict[str, Any]:
    """Translate system settings into ``CORSMiddleware`` arguments.

    Auth is off, so the backend mirrors upstream's permissive single-user mode:
    explicit localhost origins plus a permissive regex unless AUTH settings
    enable credentialed cross-origin requests.
    """

    system_settings = load_system_settings()
    auth_settings = load_auth_settings()
    frontend_port = str(system_settings["frontend_port"])
    extra_origins = normalize_origins(
        [system_settings["cors_origin"], system_settings["cors_origins"]]
    )
    origins = [
        f"http://localhost:{frontend_port}",
        f"http://127.0.0.1:{frontend_port}",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    for origin in extra_origins:
        if origin not in origins:
            origins.append(origin)

    return {
        "allow_origins": origins,
        "allow_origin_regex": None if auth_settings["enabled"] else r"https?://.*",
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


class RuntimeCORSMiddleware:
    """Build CORS after lifespan has loaded the deployment's settings."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._config: dict[str, Any] | None = None
        self._middleware: CORSMiddleware | None = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        config = scope["app"].state.cors_kwargs
        if self._middleware is None or self._config is not config:
            self._middleware = CORSMiddleware(self.app, **config)
            self._config = config
        await self._middleware(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize runtime services before accepting requests."""

    app.state.ready = False
    load_project_env()
    ensure_runtime_settings_files()
    export_runtime_settings_to_env(overwrite=True)
    configure_logging()
    app.state.cors_kwargs = build_cors_kwargs()

    from MathCraft.api.utils.progress_broadcaster import ProgressBroadcaster
    from MathCraft.api.utils.task_log_stream import get_task_stream_manager
    from MathCraft.knowledge.progress_events import install_progress_ports

    install_progress_ports(
        broadcast=ProgressBroadcaster.get_instance().broadcast,
        emit_task_event=get_task_stream_manager().emit,
    )
    app.state.ready = True
    logger.info("MathCraft backend ready")
    try:
        yield
    finally:
        app.state.ready = False
        logger.info("MathCraft backend stopped")


__all__ = ["RuntimeCORSMiddleware", "build_cors_kwargs", "lifespan"]
