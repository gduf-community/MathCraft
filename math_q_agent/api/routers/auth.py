"""Single-tenant authentication stand-in.

Upstream authenticates every knowledge-base and settings route, resolves a
per-user workspace and gates learning surfaces by role. The extracted service
serves one operator, so every dependency below succeeds with the local admin
identity and installs it into the request context. The signatures and dependency
injection points are kept so a real auth layer can be dropped back in.

See ``STUBS.md`` for the original implementation (1,909 lines).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, WebSocket

from math_q_agent.multi_user.context import get_current_user
from math_q_agent.multi_user.models import LOCAL_ADMIN_ID, LOCAL_ADMIN_USERNAME

router = APIRouter()


@dataclass(frozen=True)
class TokenPayload:
    """Decoded credential payload; single-tenant always carries the admin."""

    username: str = LOCAL_ADMIN_USERNAME
    role: str = "admin"
    user_id: str = LOCAL_ADMIN_ID
    device_credential_id: str = ""
    device_session_nonce: str = ""


def _local_token() -> TokenPayload:
    return TokenPayload()


async def require_auth() -> TokenPayload:
    """Allow every request and resolve it to the local admin."""
    return _local_token()


async def require_admin() -> TokenPayload:
    return await require_auth()


async def require_learning_surface() -> TokenPayload:
    return await require_auth()


class _WsAuthFailed:
    """Sentinel returned by :func:`ws_require_auth` when a socket is rejected."""


ws_auth_failed = _WsAuthFailed()


async def ws_require_auth(websocket: WebSocket) -> TokenPayload | _WsAuthFailed:
    """Authorize a WebSocket before ``accept()``; always allowed here."""
    return _local_token()


@router.get("/status")
async def auth_status() -> dict[str, Any]:
    """Report the single local identity so clients can skip a login screen."""

    user = get_current_user()
    return {
        "auth_enabled": False,
        "single_user": True,
        "user": user.public_dict(),
    }


@router.get("/me")
async def auth_me() -> dict[str, Any]:
    return {"user": get_current_user().public_dict(), "single_user": True}


__all__ = [
    "TokenPayload",
    "require_admin",
    "require_auth",
    "require_learning_surface",
    "router",
    "ws_auth_failed",
    "ws_require_auth",
]
