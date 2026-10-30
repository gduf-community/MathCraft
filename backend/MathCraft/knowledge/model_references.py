"""Read knowledge-base embedding references without loading indexing engines."""

from __future__ import annotations

import json
from pathlib import Path


class KnowledgeBaseReferenceError(ValueError):
    """The registry cannot safely establish whether an embedding model is used."""


def embedding_model_is_referenced(
    knowledge_bases_root: Path, profile_id: str, model_id: str,
) -> bool:
    """Check persisted bindings; an absent registry means no registered references.

    Unreadable files and malformed registry entries raise a domain error so a
    caller can fail closed. No registry data or filesystem errors are exposed.
    Missing/null/empty selections remain valid legacy unbound entries.
    """
    registry_path = knowledge_bases_root / "kb_config.json"
    try:
        registry = json.loads(registry_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        raise KnowledgeBaseReferenceError from None
    if not isinstance(registry, dict):
        raise KnowledgeBaseReferenceError
    knowledge_bases = registry.get("knowledge_bases", {})
    if not isinstance(knowledge_bases, dict):
        raise KnowledgeBaseReferenceError
    for entry in knowledge_bases.values():
        if not isinstance(entry, dict):
            raise KnowledgeBaseReferenceError
        selection = entry.get("embedding_selection")
        if selection is None:
            continue
        if not isinstance(selection, dict):
            raise KnowledgeBaseReferenceError
        if not selection:
            continue
        if any(
            not isinstance(selection.get(field), str) or not selection[field].strip()
            for field in ("profile_id", "model_id")
        ):
            raise KnowledgeBaseReferenceError
        if selection["profile_id"] == profile_id and selection["model_id"] == model_id:
            return True
    return False
