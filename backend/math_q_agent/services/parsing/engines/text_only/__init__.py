"""Built-in text-only parsing engine.

This is the default, dependency-light path: it reuses math_q_agent's legacy text
extractors and emits markdown/plain text for downstream RAG providers.
"""

from .engine import TextOnlyParser

__all__ = ["TextOnlyParser"]
