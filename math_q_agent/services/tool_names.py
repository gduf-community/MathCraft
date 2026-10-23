"""Built-in tool names that settings surfaces reference.

Upstream reads these from the chat tool package, which the extracted service
does not ship. Only the name tuples are needed here: the settings "enabled
tools" list is gone, while the readiness matrix and interface settings still
validate stored tool names against them.
"""

from __future__ import annotations

USER_TOGGLEABLE_TOOL_NAMES: tuple[str, ...] = (
    "brainstorm",
    "web_search",
    "paper_search",
    "zotero_search",
    "reason",
    "geogebra_analysis",
    "imagegen",
    "videogen",
)

CONFIGURABLE_BUILTIN_TOOL_NAMES: tuple[str, ...] = (
    "preprint",
    "research_audit",
    "research_lit",
    "rag",
    "kb_files",
    "knowledge_frontier",
    "read_source",
    "read_memory",
    "write_memory",
)

__all__ = ["CONFIGURABLE_BUILTIN_TOOL_NAMES", "USER_TOGGLEABLE_TOOL_NAMES"]
