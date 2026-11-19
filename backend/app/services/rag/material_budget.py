"""Format retrieved knowledge material within a per-call character budget."""

import re

MATERIAL_CHAR_LIMIT = 4000
PLANNING_MATERIAL_CHAR_LIMIT = 1500

_MATH_DELIMITERS = re.compile(r"\\\\|\\\$|\\[()\[\]]|\$\$?")
_MATH_CLOSERS = {"$": "$", "$$": "$$", r"\(": r"\)", r"\[": r"\]"}
_QUESTION_BOUNDARY = re.compile(r"[。？！\n]")
_SEPARATOR = "\n\n"


def _material_label(hit: dict) -> str:
    doc_name = hit.get("doc_name") or "文档"
    section = hit.get("section") or hit.get("chunk_type") or "未分节"
    pages: set[int] = set()
    for location in hit.get("source_locations") or ():
        if isinstance(location, dict):
            page = location.get("page")
            if type(page) is int and page > 0:
                pages.add(page)

    page_numbers = "、".join(map(str, sorted(pages)))
    page_text = f" · 第{page_numbers}页" if page_numbers else ""
    return f"{doc_name} · {section}{page_text}"


def _truncate_text(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text

    # Include a delimiter starting before the cutoff even if it ends after it.
    formula_start = limit
    closer = None
    for match in _MATH_DELIMITERS.finditer(text, 0, limit + 1):
        if match.start() >= limit:
            break
        delimiter = match.group()
        if closer is not None:
            if delimiter == closer and match.end() <= limit:
                closer = None
                formula_start = limit
        elif delimiter in _MATH_CLOSERS:
            closer = _MATH_CLOSERS[delimiter]
            formula_start = match.start()
        elif match.end() > limit:
            formula_start = match.start()
    return text[:formula_start].rstrip()


def build_material(
    hits: list[dict], *, limit: int = MATERIAL_CHAR_LIMIT,
) -> tuple[str, list[str]]:
    """Pack whole fragments, returning the material and its included source labels."""
    parts: list[str] = []
    labels: list[str] = []
    oversized: list[tuple[bool, str, str, str]] = []
    remaining = limit
    for hit in hits:
        text = (hit.get("text") or "").strip()
        if not text:
            continue
        label = _material_label(hit)
        header = f"【{label}】\n"
        overhead = len(header) + (len(_SEPARATOR) if parts else 0)
        if len(text) + overhead > remaining:
            if not parts and len(header) < limit:
                oversized.append((hit.get("chunk_type") == "question", label, header, text))
            continue
        parts.append(header + text)
        labels.append(label)
        remaining -= overhead + len(text)

    if parts:
        return _SEPARATOR.join(parts), labels

    for is_question, label, header, text in sorted(oversized, key=lambda item: item[0]):
        excerpt = _truncate_text(text, limit - len(header))
        if is_question:
            boundary = max((match.end() for match in _QUESTION_BOUNDARY.finditer(excerpt)), default=0)
            if boundary:
                excerpt = _truncate_text(text, boundary) or excerpt
        if excerpt:
            return header + excerpt, [label]
    return "", []
