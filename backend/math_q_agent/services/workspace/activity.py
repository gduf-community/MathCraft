"""No-op workspace activity tracking.

Upstream defers data-mutating work while a workspace import/move is in flight.
Single-tenant runs one data root and never moves it, so the trackers are inert
and keep only their public shape.
"""

from __future__ import annotations

from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncIterator, Iterator


@contextmanager
def data_activity(*args: Any, **kwargs: Any) -> Iterator[None]:
    yield None


@contextmanager
def acquire_activity(*args: Any, **kwargs: Any) -> Iterator[None]:
    yield None


class WorkspaceActivityMiddleware:
    """ASGI middleware that does nothing; kept so upstream wiring still imports."""

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        await self.app(scope, receive, send)


@asynccontextmanager
async def noop_activity(*args: Any, **kwargs: Any) -> AsyncIterator[None]:
    yield None
