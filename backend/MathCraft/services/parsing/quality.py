"""General parse checks; fixture pages and textbook answers never enter this module."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any

POLICY = "parse-quality-v1"


@dataclass(frozen=True)
class PageInspection:
    page_index: int
    text_chars: int
    body_chars: int
    image_coverage: float
    needs_ocr: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PdfInspection:
    pages: tuple[PageInspection, ...] = ()
    readable: bool = True

    @property
    def needs_ocr(self) -> bool:
        return any(page.needs_ocr for page in self.pages)


def inspect_pdf(source: Path) -> PdfInspection | None:
    if source.suffix.lower() != ".pdf":
        return None
    import pymupdf

    pages = []
    try:
        with pymupdf.open(source) as document:
            for index, page in enumerate(document):
                text = page.get_text("text").strip()
                rect = page.rect
                body_chars = sum(
                    len(str(block[4]).strip())
                    for block in page.get_text("blocks")
                    if len(block) > 6
                    and block[6] == 0
                    and block[1] >= rect.height * 0.12
                    and block[3] <= rect.height * 0.88
                )
                coverage = min(
                    1.0,
                    sum(
                        (pymupdf.Rect(item["bbox"]) & rect).get_area() / max(rect.get_area(), 1)
                        for item in page.get_image_info()
                    ),
                )
                reasons = []
                if coverage >= 0.35 and (not text or body_chars < 40):
                    reasons.append("image_without_usable_body")
                if text and (text.count("\ufffd") + text.count("\x00")) / len(text) > 0.02:
                    reasons.append("damaged_text_layer")
                pages.append(
                    PageInspection(
                        index,
                        len(text),
                        body_chars,
                        round(coverage, 4),
                        bool(reasons),
                        tuple(reasons),
                    )
                )
    except (OSError, RuntimeError, ValueError):
        return PdfInspection(readable=False)
    return PdfInspection(tuple(pages))


@dataclass
class QualityReport:
    policy: str = POLICY
    status: str = "passed"
    page_count: int | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)
    assets: list[dict[str, Any]] = field(default_factory=list)
    pages: list[dict[str, Any]] = field(default_factory=list)
    source_digest: str = ""

    def add(self, code: str, message: str, *, failure: bool = False, page=None) -> None:
        issue = {"code": code, "message": message, "severity": "error" if failure else "warning"}
        if page is not None:
            issue["page_index"] = page
        if issue not in self.issues:
            self.issues.append(issue)
        if failure:
            self.status = "failed"
        elif self.status != "failed":
            self.status = "warning"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _walk(node):
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def check_output(
    source: Path,
    markdown: str,
    blocks,
    workdir: Path,
    inspection: PdfInspection | None = None,
    *,
    cloud: bool = False,
    content_dir: Path | None = None,
) -> QualityReport:
    """Validate current artifacts on both cache hits and new output. Never fetch assets."""
    report = QualityReport()
    with source.open("rb") as handle:
        report.source_digest = hashlib.file_digest(handle, "sha256").hexdigest()
    pdf = source.suffix.lower() == ".pdf"
    inspection = inspection if inspection is not None else inspect_pdf(source)
    if inspection is not None:
        report.page_count = len(inspection.pages)
        report.pages = [asdict(page) for page in inspection.pages]
        if not inspection.readable:
            report.add("source_unreadable", "原 PDF 无法读取。", failure=True)
    nodes = list(_walk(blocks))
    texts = [
        node[key]
        for node in nodes
        for key in ("text", "content", "table_body", "latex")
        if isinstance(node.get(key), str)
    ]
    text = markdown + "\n" + "\n".join(texts)
    if not text.strip():
        report.add("empty_output", "解析产物没有可用正文。", failure=True)
    if "\ufffd" in text or "\x00" in text:
        report.add("replacement_character", "解析产物含替换字符或空字符，需核对原页。", failure=pdf)
    if re.search(r"formula[-_ ]not[-_ ]decoded|<unk>|\[MISSING_FORMULA\]", text, re.I):
        report.add("unresolved_formula", "存在未解码公式占位，不能作为完整数学材料。", failure=pdf)
    if "data:image/" in text.lower():
        report.add("inline_image_data", "图片 base64 尚未外置，禁止进入文本索引。", failure=pdf)

    located = set()
    for node in nodes:
        page = node.get("page_idx", node.get("page_index"))
        if page is not None:
            if (
                type(page) is not int
                or page < 0
                or (report.page_count is not None and page >= report.page_count)
            ):
                report.add("invalid_page", "解析块页码无效或超出原 PDF 范围。", failure=pdf)
            else:
                located.add(page)
        if "page_idx" in node and "page_index" in node and node["page_idx"] != node["page_index"]:
            report.add("conflicting_page", "同一解析块的原页索引互相矛盾。", failure=pdf)
        if "bbox" in node and node["bbox"] is not None:
            box = node["bbox"]
            if (
                not isinstance(box, (list, tuple))
                or len(box) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in box)
                or box[0] > box[2]
                or box[1] > box[3]
            ):
                report.add(
                    "invalid_bbox", "解析块坐标无效，无法确认原页位置。", failure=pdf, page=page
                )

    if pdf and cloud:
        if not located:
            report.add("page_mapping_unknown", "云端产物缺少原页映射，严格用途需核对。")
        elif inspection is not None:
            for page in inspection.pages:
                if (page.text_chars or page.image_coverage) and page.page_index not in located:
                    report.add(
                        "missing_page",
                        "原页有内容，但云端产物缺少该页。",
                        failure=True,
                        page=page.page_index,
                    )

    references = set(re.findall(r"!\[[^\]]*\]\(([^)]+)\)", markdown))
    references.update(
        str(node[key]) for node in nodes for key in ("img_path", "image_path") if node.get(key)
    )
    from .cache import find_content_dir

    content = content_dir or find_content_dir(workdir)
    root = workdir.resolve()
    for reference in sorted(references):
        if re.match(r"https?://|data:", reference, re.I):
            report.add("external_image_unread", "存在未读取的外部图片，不代表图示条件已完整。")
            continue
        path = Path(reference)
        path = path.resolve() if path.is_absolute() else (content / path).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            report.add("image_missing", "图片引用缺失或越出解析产物目录。", failure=pdf)
            continue
        try:
            from PIL import Image

            with Image.open(path) as image:
                width, height = image.size
                image.verify()
            report.assets.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "width": width,
                    "height": height,
                }
            )
        except ImportError:
            report.add("image_reader_unavailable", "图片读取器不可用，图片完整性未知。")
        except (OSError, ValueError, Image.DecompressionBombError):
            report.add("image_invalid", "图片文件存在但无法读取。", failure=pdf)
    if references:
        report.add("images_not_model_verified", "图片资产检查不代表模型已经读取图示条件。")
    return report


def latest_report(source: Path, cache_root: Path) -> dict[str, Any] | None:
    """Derive diagnostics for an unindexed file from source-bound parse artifacts."""
    if not source.is_file():
        return None
    try:
        with source.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        short = digest[:16]
        directory = cache_root / short[:2] / short
        candidates = sorted(
            directory.glob("*/quality.json"), key=lambda p: p.stat().st_mtime, reverse=True
        )
        for candidate in candidates:
            if not candidate.resolve().is_relative_to(cache_root.resolve()):
                continue
            value = json.loads(candidate.read_text(encoding="utf-8"))
            if value.get("policy") == POLICY and value.get("source_digest") == digest:
                return value
    except (OSError, ValueError, TypeError, AttributeError):
        return None
    return None
