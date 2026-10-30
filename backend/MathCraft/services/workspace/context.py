"""Single-tenant workspace scope: one data root, no switching."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class WorkspaceScope:
    """Identity of the one content workspace this service exposes."""

    workspace_id: str = ""

    @property
    def root(self) -> None:
        return None


_scope: ContextVar[WorkspaceScope | None] = ContextVar("content_workspace_scope", default=None)


def get_workspace_scope() -> WorkspaceScope | None:
    return _scope.get()


def current_workspace_id() -> str:
    scope = _scope.get()
    return scope.workspace_id if scope else ""


def workspace_url(url: str) -> str:
    """Upstream rewrites URLs to carry the workspace id; single-tenant keeps them."""
    return url


def resolve_workspace_scope(workspace_id: str | None = None) -> WorkspaceScope:
    return WorkspaceScope()


def install_workspace_scope(workspace_id: str | None = None) -> WorkspaceScope:
    scope = WorkspaceScope()
    _scope.set(scope)
    return scope


@contextmanager
def workspace_context(workspace_id: str | WorkspaceScope | None = None) -> Iterator[WorkspaceScope]:
    scope = WorkspaceScope()
    token = _scope.set(scope)
    try:
        yield scope
    finally:
        _scope.reset(token)


@contextmanager
def account_workspace_context(account) -> Iterator[WorkspaceScope]:
    with workspace_context() as scope:
        yield scope


def scoped_path_service(account):
    """Workspace-scoped path service; one data root means no re-rooting."""

    return account
