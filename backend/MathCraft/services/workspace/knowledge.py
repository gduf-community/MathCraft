"""Single-tenant knowledge-library scope.

Upstream gates knowledge-base visibility on a selected workspace and qualifies
catalog ids with a workspace prefix. With one data root the library is always
enabled, ids are unqualified, and every base directory belongs to the single
workspace.
"""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import Any

library_request: ContextVar[bool] = ContextVar("knowledge_library_request", default=False)


def qualified_kb_id(name: str, workspace_id: str = "") -> str:
    return name


def canonical_kb_id(value: str) -> str:
    return value


def workspace_id_for_kb_base_dir(base_dir: str | Path) -> str | None:
    return None


def parse_kb_id(value: str) -> tuple[str, str] | None:
    """Upstream splits ``workspace::kb``; single-tenant ids carry no prefix."""
    return None


def move_aliases() -> dict[str, str]:
    return {}


def knowledge_catalog() -> list[dict[str, Any]]:
    return []


def resolve_qualified(kb_ref: str, *, require_write: bool = False) -> Any:
    raise LookupError(f"unknown knowledge base: {kb_ref}")


def resolve_selected(kb_ref: str, selected: list[str], *, require_write: bool = False) -> Any:
    raise LookupError(f"unknown knowledge base: {kb_ref}")


def learning_source_access(refs: Any) -> Any:
    return refs


learning_source_kbs: ContextVar[list] = ContextVar("learning_source_kbs", default=[])
