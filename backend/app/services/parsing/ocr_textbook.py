"""Build retrievable textbook passages from MinerU OCR artifacts."""
import hashlib
import html
import json
import math
import re
from pathlib import Path, PurePosixPath

from app.config import settings
from app.services.mineru import _plan_parts
from app.services.parsing.base import ParsedBlock

_VISUALS = {"image", "chart", "table"}
_CONTENT = {"text", "equation", *_VISUALS}
_TOC = re.compile(r"^目\s*[录錄]$")
_TOC_LEADER = re.compile(r"(?:\.{3,}|…{2,}|·{3,})\s*\d+\s*$")
_HEADING = re.compile(r"^(?:第[一二三四五六七八九十\d]+[章节]|附录|[§]|习题\s*\d)")


def _field(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(item.strip() for item in value if isinstance(item, str))
    return ""


def _part_entries(folder: Path) -> list[dict]:
    candidates = sorted(folder.rglob("*_content_list.json"))
    if len(candidates) != 1:
        return []
    try:
        data = json.loads(candidates[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _visual_body(item: dict, kind: str) -> str:
    parts = [_field(item.get(f"{kind}_{suffix}")) for suffix in ("caption", "footnote")]
    if kind == "table":
        table = re.sub(r"</tr\s*>", "\n", _field(item.get("table_body")), flags=re.I)
        table = re.sub(r"</t[dh]\s*>", " | ", table, flags=re.I)
        parts.append(html.unescape(re.sub(r"<[^>]+>", "", table)).strip())
    return "\n".join(filter(None, parts))


def _location(item: dict, folder: Path, page: int, kind: str, index: int) -> dict:
    location = {"page": page, "kind": kind}
    bbox = item.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4 and all(
        type(value) in (int, float) and math.isfinite(value) for value in bbox
    ):
        location["bbox"] = bbox
    asset = PurePosixPath(_field(item.get("img_path")))
    if (kind in _VISUALS and asset.name and not asset.is_absolute() and ".." not in asset.parts
            and (folder / asset.as_posix()).is_file()):
        key = f"{page}:{index}:{asset.as_posix()}"
        location["asset_ref"] = hashlib.sha256(key.encode()).hexdigest()[:24]
    return location


def _markdown_passages(markdown: str) -> list[ParsedBlock]:
    passages: list[ParsedBlock] = []
    section = ""
    for paragraph in re.split(r"\n\s*\n", markdown.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        if paragraph.startswith("#"):
            section = paragraph.splitlines()[0].lstrip("# ").strip()
        if _TOC.fullmatch(section) or _TOC_LEADER.search(paragraph):
            continue
        for start in range(0, len(paragraph), settings.chunk_size):
            passages.append(ParsedBlock(paragraph[start:start + settings.chunk_size], {
                "section": section, "chunk_type": "general",
            }))
    return passages


def parse_ocr_textbook(markdown: str, result_dir: Path, page_count: int) -> list[ParsedBlock]:
    """Group source blocks by page and heading. Use Markdown if layout artifacts are missing."""
    plan = _plan_parts(page_count)
    passages: list[ParsedBlock] = []
    pending: list[str] = []
    locations: list[dict] = []
    section = ""
    page = 0
    in_toc = False

    def flush() -> None:
        if pending:
            passages.append(ParsedBlock("\n\n".join(pending), {
                "section": section, "chunk_type": "general", "source_locations": locations.copy(),
            }))
        pending.clear()
        locations.clear()

    for part, (start, end) in enumerate(plan):
        folder = result_dir if len(plan) == 1 else result_dir / f"part_{part:02d}"
        entries = _part_entries(folder)
        if not entries:
            return _markdown_passages(markdown)
        for index, item in enumerate(entries):
            kind, page_index = item.get("type"), item.get("page_idx")
            if (not isinstance(kind, str) or kind not in _CONTENT
                    or type(page_index) is not int or not 0 <= page_index < end - start):
                continue
            next_page = start + page_index + 1
            body = _field(item.get("text")) if kind not in _VISUALS else _visual_body(item, kind)
            heading = kind == "text" and bool(item.get("text_level") or _HEADING.match(body))
            if next_page != page:
                flush()
                page = next_page
            if heading:
                flush()
                section = body
                in_toc = bool(_TOC.fullmatch(body))
            if in_toc or _TOC_LEADER.search(body):
                continue
            location = _location(item, folder, page, kind, index)
            if not body and kind in _VISUALS:
                body = {"image": "图像", "chart": "图表", "table": "表格"}[kind]
                if not pending:
                    continue
            if not body:
                continue
            if pending and sum(map(len, pending)) + len(pending) * 2 + len(body) > settings.chunk_size:
                if kind not in _VISUALS or _visual_body(item, kind):
                    flush()
            pending.append(body)
            locations.append(location)
    flush()
    return passages or _markdown_passages(markdown)
