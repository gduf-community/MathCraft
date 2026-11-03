"""健康检查：SQLite / Redis / 硅基流动向量与重排 / MinerU Token / Chroma。"""
import time

from fastapi import APIRouter
from sqlalchemy import text

from app import local_secrets
from app.db import engine
from app.services import cache

router = APIRouter(prefix="/api", tags=["health"])

_embed_cache: dict = {"ts": 0.0, "ok": False, "dim": 0}
_rerank_cache: dict = {"ts": 0.0, "ok": False}
_PROBE_TTL = 60.0


def _check_db() -> str:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:
        return f"fail: {exc}"


def _check_redis() -> str:
    try:
        return "ok" if cache.get_redis().ping() else "fail"
    except Exception as exc:
        return f"fail: {exc}"


def _check_embedding() -> str:
    now = time.monotonic()
    if now - _embed_cache["ts"] < _PROBE_TTL:
        return f"ok({_embed_cache['dim']}d)" if _embed_cache["ok"] else "fail"
    try:
        from app.services.rag import embeddings

        dim = len(embeddings.embed_one("健康检查"))
        _embed_cache.update(ts=now, ok=True, dim=dim)
        return f"ok({dim}d)"
    except Exception:
        _embed_cache.update(ts=now, ok=False)
        return "fail"


def _check_rerank() -> str:
    now = time.monotonic()
    if now - _rerank_cache["ts"] < _PROBE_TTL:
        return "ok" if _rerank_cache["ok"] else "fail"
    try:
        from app.services.rag import rerank

        rerank.rerank("健康检查", ["健康检查"], top_n=1)
        _rerank_cache.update(ts=now, ok=True)
        return "ok"
    except Exception:
        _rerank_cache.update(ts=now, ok=False)
        return "fail"


def _check_chroma() -> str:
    try:
        from app.services.rag import vectorstore

        vectorstore.get_client().heartbeat()
        return "ok"
    except Exception as exc:
        return f"fail: {exc}"


@router.get("/health")
def health():
    return {
        "database": _check_db(),
        "redis": _check_redis(),
        "siliconflow_embedding": _check_embedding(),
        "siliconflow_rerank": _check_rerank(),
        "mineru_default_token": bool(local_secrets.MINERU_DEFAULT_TOKEN),
        "chroma": _check_chroma(),
    }
