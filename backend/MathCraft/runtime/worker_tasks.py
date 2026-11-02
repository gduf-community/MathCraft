"""Synchronous document tasks loaded only inside isolated worker processes."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def extract_document_text(file_path: str | Path, **kwargs: Any) -> str:
    """Extract text with the existing filename hints, limits, and public errors.

    Forward options unchanged so omitted limits retain the extractor's defaults
    and explicit None limits remain disabled. Keep document imports lazy.
    """
    from MathCraft.utils.document_extractor import extract_text_from_path

    return extract_text_from_path(file_path, **kwargs)


def extract_document_to_markdown(
    source_path: str | Path, output_path: str | Path, **kwargs: Any
) -> None:
    """Write extracted text as UTF-8 Markdown only after extraction succeeds."""
    text = extract_document_text(source_path, **kwargs)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
