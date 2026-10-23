"""Agentic client pool hooks.

Upstream keeps a pool of long-lived agentic LLM clients and tears it down when
provider configuration changes. The extracted service builds clients per call,
so teardown is a no-op that preserves the call sites.
"""

from __future__ import annotations


def close_agentic_client_pool() -> None:
    return None


def reset_agentic_client_pool() -> None:
    return None


__all__ = ["close_agentic_client_pool", "reset_agentic_client_pool"]
