"""Workspace-scoped resources; single-tenant exposes none."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class WorkspaceResources:
    """Resource bindings a content workspace may expose."""

    knowledge_bases: Any = None
    memory: Any = None
    notebooks: Any = None


def current_resources() -> WorkspaceResources:
    return WorkspaceResources()
