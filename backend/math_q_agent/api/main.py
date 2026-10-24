"""FastAPI application for the standalone knowledge-base and model-config backend.

This replaces DeepTutor's 833-line application factory. Everything tied to the
chat turn loop (dependency container, tool/capability registry validation,
partners, events, background leader, data migrations, frontend static assets)
is gone. What remains is the surface this service exists for:

    /api/knowledge-bases/*   knowledge bases, files, indexing, retrieval
    /ws/knowledge-bases/*    indexing progress
    /api/settings/*          model catalog, providers, tasks, parsing config
    /api/system/*            connectivity tests and status
    /api/auth/*              single-tenant identity (always the local admin)

Import-time setup mirrors upstream: runtime settings files are created on first
import and exported into the process environment. See README "Known quirks".
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from math_q_agent.logging import configure_logging
from math_q_agent.services.config import (
    ensure_runtime_settings_files,
    export_runtime_settings_to_env,
    load_auth_settings,
    load_system_settings,
)
from math_q_agent.services.config.origins import normalize_origins

from .routers import auth, knowledge, settings, system

ensure_runtime_settings_files()
export_runtime_settings_to_env(overwrite=True)
configure_logging()

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Wire progress fan-out and log readiness."""

    from math_q_agent.api.utils.progress_broadcaster import ProgressBroadcaster
    from math_q_agent.api.utils.task_log_stream import get_task_stream_manager
    from math_q_agent.knowledge.progress_events import install_progress_ports

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


app = FastAPI(
    title="MathCraft",
    description=(
        "Knowledge-base and model-configuration backend. Extracted from "
        "DeepTutor and reduced to a single-tenant service."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(CORSMiddleware, **build_cors_kwargs())

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(knowledge.router, prefix="/api", tags=["knowledge-bases"])
app.include_router(knowledge.ws_router, prefix="/ws", tags=["knowledge-bases"])
app.include_router(settings.public_router, prefix="/api/settings", tags=["settings"])
app.include_router(settings.router, prefix="/api/settings", tags=["settings"])
app.include_router(system.router, prefix="/api/system", tags=["system"])


@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, Any]:
    """Liveness probe; independent of configured engines or credentials."""

    return {"status": "ok", "service": "MathCraft"}
