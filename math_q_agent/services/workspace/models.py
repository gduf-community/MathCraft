"""Errors and value objects for the single-tenant workspace stand-in."""

from __future__ import annotations


class WorkspaceError(Exception):
    """Raised when a workspace operation cannot be satisfied."""


class WorkspaceItem:
    def __init__(self, name: str = "", path: str = "") -> None:
        self.name = name
        self.path = path


class WorkspaceBinding:
    def __init__(self, workspace_id: str = "") -> None:
        self.workspace_id = workspace_id
