"""MarginNote4 knowledge-base storage.

Only the store ships with the extracted service. The MarginNote4 chat
capability and its tools depend on the agent loop, which is out of scope; the
knowledge-base connector uses the store directly through ``resolve_db_path``.
"""

from __future__ import annotations

from .models import (
    LearningEvent,
    MarginNoteObject,
    PairedDevice,
    SyncBatch,
    SyncResult,
)
from .store import MarginNoteStore, default_db_path, resolve_db_path

__all__ = [
    "LearningEvent",
    "MarginNoteObject",
    "MarginNoteStore",
    "PairedDevice",
    "SyncBatch",
    "SyncResult",
    "default_db_path",
    "resolve_db_path",
]
