"""Single-tenant workspace service facade."""

from __future__ import annotations

from typing import Any

from .models import WorkspaceBinding, WorkspaceError, WorkspaceItem


class ContentWorkspaceService:
    """Every read returns the one data root; every write is rejected."""

    def list_items(self) -> list[WorkspaceItem]:
        return []

    def current_binding(self) -> WorkspaceBinding:
        return WorkspaceBinding()

    def bind(self, *args: Any, **kwargs: Any) -> WorkspaceBinding:
        raise WorkspaceError("workspace switching is not available in single-tenant mode")

    def unbind(self, *args: Any, **kwargs: Any) -> None:
        return None


_service = ContentWorkspaceService()


def get_content_workspace_service() -> ContentWorkspaceService:
    return _service


def current_resources() -> list[Any]:
    return []
