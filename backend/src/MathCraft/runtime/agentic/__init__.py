"""Agent-loop surface retained as a thin compatibility shim."""

from __future__ import annotations

from .client import close_agentic_client_pool, reset_agentic_client_pool

__all__ = ["close_agentic_client_pool", "reset_agentic_client_pool"]
