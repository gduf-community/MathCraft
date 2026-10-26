"""Unified FastAPI application for the MathCraft backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from math_q_agent.runtime.env import load_project_env
from api import chat, generate
from math_q_agent.api.main import lifespan as knowledge_lifespan
from math_q_agent.api.routers import auth, knowledge, profile, settings as settings_router, system


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize knowledge-base services in the unified process."""

    async with knowledge_lifespan(app):
        yield


app = FastAPI(title="MathCraft", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Question-generation orchestration API.
app.include_router(generate.router)
app.include_router(chat.router)

# Knowledge-base, model settings and connectivity API.
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(profile.router, prefix="/api/user-profile", tags=["user-profile"])
app.include_router(knowledge.router, prefix="/api", tags=["knowledge-bases"])
app.include_router(knowledge.ws_router, prefix="/ws", tags=["knowledge-bases"])
app.include_router(settings_router.public_router, prefix="/api/settings", tags=["settings"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(system.router, prefix="/api/system", tags=["system"])


@app.get("/api/health", tags=["health"])
async def health():
    """检查正式知识库和正式模型配置是否可用。"""

    from math_q_agent.multi_user.knowledge_access import list_visible_knowledge_bases
    from math_q_agent.services.llm.config import get_llm_config
    from math_q_agent.services.rag.factory import DEFAULT_PROVIDER

    try:
        knowledge_bases = len(list_visible_knowledge_bases())
    except Exception as exc:
        knowledge_bases = f"fail: {exc}"
    try:
        model_configured = bool(get_llm_config().model)
    except Exception:
        model_configured = False
    return {
        "rag_provider": DEFAULT_PROVIDER,
        "knowledge_bases": knowledge_bases,
        "llm_configured": model_configured,
    }


@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    """Liveness probe for the unified backend."""

    return {"status": "ok", "service": "MathCraft"}


def run() -> None:
    import argparse
    import uvicorn

    from math_q_agent.services.config import load_launch_settings

    load_project_env()
    launch_settings = load_launch_settings()

    parser = argparse.ArgumentParser(
        prog="MathCraft",
        description="Unified knowledge-base, model-settings and question-generation backend.",
    )
    parser.add_argument(
        "--host",
        default=os.getenv("BACKEND_HOST", "127.0.0.1"),
        help="bind address (default: BACKEND_HOST or 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=launch_settings.backend_port,
        help="bind port (default: BACKEND_PORT or saved system settings)",
    )
    parser.add_argument("--reload", action="store_true", help="reload on source changes")
    args = parser.parse_args()
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


__all__ = ["app", "run"]
