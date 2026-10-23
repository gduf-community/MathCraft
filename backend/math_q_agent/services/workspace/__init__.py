"""Single-tenant stand-in for DeepTutor's content-workspace feature.

Upstream lets a user select a content workspace whose root re-homes knowledge
bases, memory and settings. The extracted service supports one tenant and one
data root, so every workspace concept collapses to "the one data root":

    workspace_id  -> ""
    workspace URL -> unchanged
    library scope -> always enabled

The module keeps upstream names and signatures so the surrounding code reads
the same; see ``STUBS.md`` for the original implementation.
"""

from __future__ import annotations

from .context import (
    WorkspaceScope,
    current_workspace_id,
    get_workspace_scope,
    install_workspace_scope,
    workspace_context,
    workspace_url,
)
from .models import WorkspaceError
from .service import ContentWorkspaceService, get_content_workspace_service

__all__ = [
    "ContentWorkspaceService",
    "WorkspaceError",
    "WorkspaceScope",
    "current_workspace_id",
    "get_content_workspace_service",
    "get_workspace_scope",
    "install_workspace_scope",
    "workspace_context",
    "workspace_url",
]
