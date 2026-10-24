"""Unified FastAPI application for the MathCraft backend."""

from __future__ import annotations

from contextlib import asynccontextmanager
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import chat, generate, kb
from config import settings
from math_q_agent.api.main import lifespan as knowledge_lifespan
from math_q_agent.api.routers import auth, knowledge, settings as settings_router, system


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

# Question-generation API.
app.include_router(kb.router)
app.include_router(generate.router)
app.include_router(chat.router)

# Knowledge-base, model settings and connectivity API.
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(knowledge.router, prefix="/api", tags=["knowledge-bases"])
app.include_router(knowledge.ws_router, prefix="/ws", tags=["knowledge-bases"])
app.include_router(settings_router.public_router, prefix="/api/settings", tags=["settings"])
app.include_router(settings_router.router, prefix="/api/settings", tags=["settings"])
app.include_router(system.router, prefix="/api/system", tags=["system"])


@app.get("/api/health", tags=["health"])
def health():
    """Check the question-generation dependencies."""

    status = {"chroma_dir": str(settings.chroma_path()), "deepseek_key": bool(settings.deepseek_api_key)}
    try:
        from services.embeddings import embed_one

        dim = len(embed_one("ping"))
        status["ollama_embedding"] = f"ok({dim}d)"
    except Exception as exc:
        status["ollama_embedding"] = f"fail: {exc}"
    return status


@app.get("/healthz", tags=["health"])
async def healthz() -> dict[str, str]:
    """Liveness probe for the unified backend."""

    return {"status": "ok", "service": "MathCraft"}


def run() -> None:
    import argparse
    import uvicorn

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
        default=int(os.getenv("BACKEND_PORT", "8000")),
        help="bind port (default: BACKEND_PORT or 8000)",
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
