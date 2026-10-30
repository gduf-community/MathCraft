"""System status and model connectivity tests.

Reduced from DeepTutor's 633-line router: version checks, update jobs, memory
probes, runtime-status handshakes and process listings belong to the desktop
app and the chat runtime, both out of scope here. What remains answers the one
question a model-configuration UI asks: "does my configured model actually
work?"
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from MathCraft.api.routers.auth import require_admin
from MathCraft.services.config import (
    resolve_search_runtime_config,
    supported_search_providers_hint,
)

router = APIRouter()


def get_embedding_client(*args, **kwargs):
    from MathCraft.services.embedding.client import get_embedding_client as resolve

    return resolve(*args, **kwargs)


def get_embedding_config(*args, **kwargs):
    from MathCraft.services.embedding.config import get_embedding_config as resolve

    return resolve(*args, **kwargs)


def get_llm_config(*args, **kwargs):
    from MathCraft.services.llm.config import get_llm_config as resolve

    return resolve(*args, **kwargs)


def get_token_limit_kwargs(*args, **kwargs):
    from MathCraft.services.llm.config import get_token_limit_kwargs as resolve

    return resolve(*args, **kwargs)


async def llm_complete(*args, **kwargs):
    from MathCraft.services.llm import complete

    return await complete(*args, **kwargs)


class TestResponse(BaseModel):
    success: bool
    message: str
    model: str | None = None
    response_time_ms: float | None = None
    error: str | None = None


@router.get("/status")
async def get_system_status() -> dict[str, Any]:
    """Report configuration state for backend, LLM, embeddings and search."""

    result: dict[str, Any] = {
        "backend": {"status": "online", "timestamp": datetime.now().isoformat()},
        "llm": {"status": "unknown", "model": None, "testable": True},
        "embeddings": {"status": "unknown", "model": None, "testable": True},
        "search": {"status": "optional", "provider": None, "testable": True},
    }

    try:
        llm_config = get_llm_config()
        result["llm"]["model"] = llm_config.model
        result["llm"]["status"] = "configured"
    except ValueError as exc:
        result["llm"]["status"] = "not_configured"
        result["llm"]["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001 - status endpoint reports any failure
        result["llm"]["status"] = "error"
        result["llm"]["error"] = str(exc)

    try:
        embedding_config = get_embedding_config()
        result["embeddings"]["model"] = embedding_config.model
        result["embeddings"]["status"] = "configured"
    except ValueError as exc:
        result["embeddings"]["status"] = "not_configured"
        result["embeddings"]["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        result["embeddings"]["status"] = "error"
        result["embeddings"]["error"] = str(exc)

    try:
        search_config = resolve_search_runtime_config()
        if search_config.requested_provider:
            result["search"]["provider"] = search_config.provider
            if search_config.unsupported_provider:
                result["search"]["status"] = "unsupported"
                result["search"]["error"] = (
                    f"{search_config.requested_provider} is deprecated/unsupported. "
                    f"Switch to {supported_search_providers_hint()}."
                )
            elif search_config.missing_credentials:
                result["search"]["status"] = "missing_credentials"
                result["search"]["error"] = "Set profile.api_key in Settings > Catalog."
            else:
                result["search"]["status"] = "configured"
    except Exception as exc:  # noqa: BLE001
        result["search"]["status"] = "error"
        result["search"]["error"] = str(exc)

    return result


@router.post("/test/llm", response_model=TestResponse)
async def test_llm_connection(_: Any = Depends(require_admin)) -> TestResponse:
    """Send one minimal completion to prove the configured LLM is reachable."""

    start_time = time.time()
    try:
        llm_config = get_llm_config()
        model = llm_config.model
        base_url = llm_config.base_url.rstrip("/")
        for suffix in ["/chat/completions", "/completions"]:
            if base_url.endswith(suffix):
                base_url = base_url[: -len(suffix)]

        api_key = llm_config.api_key or "sk-no-key-required"
        token_kwargs = get_token_limit_kwargs(model, max_tokens=200)
        response = await llm_complete(
            model=model,
            prompt="Say 'OK' to confirm you are working. Do not produce long output.",
            system_prompt="You are a helpful assistant. Respond briefly.",
            binding=llm_config.binding,
            api_key=api_key,
            base_url=base_url,
            temperature=0.1,
            **token_kwargs,
        )
        response_time = (time.time() - start_time) * 1000
        if response and response.strip():
            return TestResponse(
                success=True,
                message="LLM connection successful",
                model=model,
                response_time_ms=round(response_time, 2),
            )
        return TestResponse(
            success=False,
            message="LLM connection failed: Empty response",
            model=model,
            error="Empty response from API",
        )
    except ValueError as exc:
        return TestResponse(success=False, message=f"LLM configuration error: {exc!s}", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        return TestResponse(
            success=False,
            message=f"LLM connection failed: {exc!s}",
            response_time_ms=round((time.time() - start_time) * 1000, 2),
            error=str(exc),
        )


@router.post("/test/embeddings", response_model=TestResponse)
async def test_embeddings_connection(_: Any = Depends(require_admin)) -> TestResponse:
    """Probe a two-item batch so the multi-chunk indexing path is exercised."""

    start_time = time.time()
    try:
        embedding_config = get_embedding_config()
        embedding_client = get_embedding_client()
        model = embedding_config.model
        binding = embedding_config.binding

        test_texts = ["test", "retrieval batch probe"]
        embeddings = await embedding_client.embed(test_texts)
        response_time = (time.time() - start_time) * 1000

        if (
            embeddings is not None
            and len(embeddings) == len(test_texts)
            and all(len(vector) > 0 for vector in embeddings)
            and len({len(vector) for vector in embeddings}) == 1
        ):
            return TestResponse(
                success=True,
                message=f"Embeddings connection successful ({binding} provider)",
                model=model,
                response_time_ms=round(response_time, 2),
            )
        return TestResponse(
            success=False,
            message="Embeddings connection failed: Invalid response",
            model=model,
            error="Embedding response must contain one non-empty vector per input",
        )
    except ValueError as exc:
        return TestResponse(
            success=False, message=f"Embeddings configuration error: {exc!s}", error=str(exc)
        )
    except Exception as exc:  # noqa: BLE001
        return TestResponse(
            success=False,
            message=f"Embeddings connection failed: {exc!s}",
            response_time_ms=round((time.time() - start_time) * 1000, 2),
            error=str(exc),
        )


@router.post("/test/search", response_model=TestResponse)
async def test_search_connection(_: Any = Depends(require_admin)) -> TestResponse:
    """Search providers are configured here but consumed by the chat runtime.

    The catalog still carries the ``search`` service slot, so the settings UI
    keeps validating it; executing a web query is out of scope for this
    service and returns an explicit explanation instead of a fake success.
    """

    try:
        search_config = resolve_search_runtime_config()
    except Exception as exc:  # noqa: BLE001
        return TestResponse(success=False, message=f"Search configuration error: {exc!s}", error=str(exc))

    if search_config.provider == "none":
        return TestResponse(
            success=False,
            message="Search is disabled",
            error="Set a Search provider in Settings > Catalog.",
        )
    if search_config.unsupported_provider:
        return TestResponse(
            success=False,
            message=f"Search provider `{search_config.requested_provider}` is deprecated/unsupported.",
            error=f"Switch to {supported_search_providers_hint()}",
        )
    return TestResponse(
        success=False,
        message="Search execution is not available in this service",
        model=search_config.provider,
        error=(
            "The search slot is stored and validated, but web search runs in the "
            "chat runtime, which is not part of this backend."
        ),
    )
