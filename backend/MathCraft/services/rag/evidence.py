"""Version-bound source checks and lossless evidence shared by retrieval callers.

The sidecar belongs to an index version, not a second document registry. Whole
parsed documents are conservative evidence units until smaller, verified problem
boundaries exist. A unit may be rejected for size; it is never sliced for an LLM.
"""

from __future__ import annotations

from collections import defaultdict
from functools import wraps
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Literal
from urllib.parse import quote

from pydantic import BaseModel, Field

from MathCraft.services.file_io import atomic_write_json
from .source_pages import SourceRef, preview_url, source_digest

UNITS_FILE = "evidence_units.json"
EVIDENCE_SCHEMA = 1


class KnowledgeError(ValueError):
    """Expected, machine-readable retrieval/generation failure."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)

    def detail(self) -> dict[str, str]:
        return {"kind": self.code, "message": str(self)}

    def result(self, query: str) -> dict:
        return {
            "query": query,
            "content": "",
            "answer": str(self),
            "sources": [],
            "error_type": self.code,
        }


def with_document_scope(method):
    """Validate capabilities/scope before the existing embedding-binding wrapper."""

    @wraps(method)
    async def wrapped(self, *args, **kwargs):
        from .factory import retrieval_capabilities

        is_search = method.__name__ == "search"
        kb_name = kwargs.get("kb_name") or args[1 if is_search else 0]
        provider = self._resolve_provider(kb_name)
        value = kwargs.get("document_keys")
        if not is_search and len(args) > 1:
            value = args[1]
        query = kwargs.get("query", args[0] if args and is_search else "")
        try:
            keys = document_keys(value)
            if keys == []:
                return (
                    []
                    if not is_search
                    else {
                        "query": query,
                        "provider": provider,
                        "content": "",
                        "answer": "",
                        "sources": [],
                        "scope_status": "empty",
                    }
                )
            if (keys is not None or not is_search) and not retrieval_capabilities(provider)[
                "document_scope"
            ]:
                raise KnowledgeError(
                    "document_scope_unsupported", "当前引擎不支持严格文档范围，请使用 LlamaIndex。"
                )
        except KnowledgeError as exc:
            if not is_search:
                raise
            return {**exc.result(query), "provider": provider}
        return await method(self, *args, **kwargs)

    return wrapped


class Evidence(BaseModel):
    evidence_id: str = ""
    unit_id: str = ""
    kb_id: str = ""
    document_key: str = ""
    source_digest: str = ""
    index_version: str = ""
    parser_signature: str = ""
    block_ids: list[str] = Field(default_factory=list)
    evidence_text: str = ""
    page_indices: list[int] = Field(default_factory=list)
    page_labels: list[str] = Field(default_factory=list)
    image_refs: list[str] = Field(default_factory=list)
    image_urls: list[str] = Field(default_factory=list)
    image_status: Literal["none", "unread", "missing", "unknown"] = "unknown"
    source_page_urls: list[str] = Field(default_factory=list)
    file_url: str = ""
    completeness: Literal["complete", "incomplete", "unknown"] = "unknown"
    warnings: list[str] = Field(default_factory=list)
    source_status: Literal["valid", "missing", "changed", "unknown"] = "unknown"


class DocumentReadiness(BaseModel):
    document_key: str
    status: str
    source_digest: str = ""
    index_version: str = ""
    parser_signature: str = ""
    warnings: list[str] = Field(default_factory=list)
    completeness: Literal["complete", "incomplete", "unknown"] = "unknown"


def document_keys(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise KnowledgeError("invalid_document_scope", "文档范围必须是文档路径列表。")
    result = []
    for key in value:
        if (
            not isinstance(key, str)
            or not key
            or "\\" in key
            or ":" in key
            or key.startswith("/")
            or "\x00" in key
            or any(p in {"", ".", ".."} for p in key.split("/"))
            or PurePosixPath(key).as_posix() != key
        ):
            raise KnowledgeError("invalid_document_scope", "文档范围含非法的 raw 相对路径。")
        if key not in result:
            result.append(key)
    return result


def source_path(kb_dir: Path, key: str) -> Path:
    document_keys([key])
    raw = (kb_dir / "raw").resolve()
    path = (raw / key).resolve()
    if not path.is_relative_to(raw):
        raise KnowledgeError("invalid_document_scope", "文档路径越出当前知识库。")
    return path


def source_status(kb_dir: Path, item: dict) -> str:
    path = source_path(kb_dir, item["document_key"])
    if not path.is_file():
        return "missing"
    digest = item.get("source_digest")
    if not digest:
        return "unknown"
    return "valid" if source_digest(path) == digest else "changed"


def load_units(storage_dir: Path) -> dict[str, dict]:
    path = storage_dir / UNITS_FILE
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema_version") != EVIDENCE_SCHEMA or not isinstance(data["units"], dict):
            raise ValueError("schema")
        required = {
            "unit_id",
            "document_key",
            "source_digest",
            "parser_signature",
            "evidence_text",
            "page_indices",
            "warnings",
            "completeness",
        }
        for unit_id, unit in data["units"].items():
            if (
                not isinstance(unit, dict)
                or not required.issubset(unit)
                or unit.get("unit_id") != unit_id
                or not re.fullmatch(r"[0-9a-f]{64}", str(unit.get("source_digest", "")))
                or not unit.get("parser_signature")
            ):
                raise ValueError("identity")
            Evidence.model_validate(unit)
        return data["units"]
    except (ValueError, KeyError, TypeError) as exc:
        raise KnowledgeError(
            "index_provenance_unavailable", "索引证据记录不兼容，请重建索引。"
        ) from exc


def persist_units(
    documents: list[Any], kb_dir: Path, storage_dir: Path, previous: Path | None = None
) -> None:
    units = load_units(previous) if previous else {}
    groups: dict[str, list[Any]] = defaultdict(list)
    for doc in documents:
        key = doc.metadata.get("document_key")
        if key:
            groups[key].append(doc)
    for key, docs in groups.items():
        path = source_path(kb_dir, key)
        digest = source_digest(path)
        signatures = sorted({d.metadata.get("parser_signature") or "unknown" for d in docs})
        # Figure descriptions are generated text, not textbook evidence.
        originals = [
            d for d in docs if d.metadata.get("content_type") not in {"source_visual", "image"}
        ]
        text = "\n\n".join(d.text for d in originals)
        pages = sorted(
            {
                d.metadata["page_index"]
                for d in originals
                if type(d.metadata.get("page_index")) is int
            }
        )
        images = sorted(
            {d.metadata["visual_asset_id"] for d in docs if d.metadata.get("visual_asset_id")}
        )
        warnings = []
        if "unknown" in signatures:
            warnings.append("解析身份未知，需要重新解析或核对。")
        image_status = "none"
        if any(d.metadata.get("page_status") in {"needs_ocr", "unlocated"} for d in originals):
            warnings.append("存在未识别或无法定位的页面内容。")
        if (
            images
            or any(d.metadata.get("visual_status") == "present" for d in docs)
            or re.search(r"!\[|见图|如图|下图|图示", text)
        ):
            image_status = "unread"
            warnings.append("材料含图示；当前文本出题链未读取图像，需核对原页或图像。")
        for target in re.findall(r"!\[[^\]]*\]\(([^)]+)\)", text):
            linked = (path.parent / target).resolve()
            if not re.match(r"https?://", target) and (
                not linked.is_relative_to((kb_dir / "raw").resolve()) or not linked.is_file()
            ):
                image_status = "missing"
                warnings.append("图像引用的本地文件缺失。")
        if not text.strip():
            warnings.append("没有可验证的来源正文。")
        unit_id = hashlib.sha256((key + digest + "|".join(signatures) + text).encode()).hexdigest()
        for old_id in [i for i, u in units.items() if u["document_key"] == key]:
            units.pop(old_id)
        units[unit_id] = {
            "unit_id": unit_id,
            "document_key": key,
            "source_digest": digest,
            "parser_signature": "|".join(signatures),
            "evidence_text": text,
            "page_indices": pages,
            "page_labels": [
                str(d.metadata.get("page_label") or "")
                for d in originals
                if "page_index" in d.metadata
            ],
            "image_refs": images,
            "block_ids": [d.node_id for d in originals],
            "image_status": image_status,
            "completeness": "incomplete" if warnings else "complete",
            "warnings": warnings,
        }
        for doc in docs:
            doc.metadata.update(
                source_digest=digest,
                evidence_unit_id=unit_id,
                parser_signature="|".join(signatures),
                evidence_schema_version=EVIDENCE_SCHEMA,
            )
            doc.excluded_embed_metadata_keys = list(
                set(doc.excluded_embed_metadata_keys) | set(doc.metadata)
            )
    atomic_write_json(storage_dir / UNITS_FILE, {"schema_version": EVIDENCE_SCHEMA, "units": units})


def check_scope(
    kb_dir: Path,
    storage_dir: Path,
    keys: list[str] | None,
    indexed_keys: set[str],
    indexed_sources: dict[str, list[dict]] | None = None,
) -> tuple[list[str] | None, dict[str, dict], list[str]]:
    units = load_units(storage_dir)
    by_key = {u["document_key"]: u for u in units.values()}
    if keys is not None:
        for key in keys:
            path = source_path(kb_dir, key)
            if key not in indexed_keys:
                if not path.is_file():
                    raise KnowledgeError("source_missing", f"来源文件不存在：{key}")
                raise KnowledgeError("document_not_indexed", f"文档尚未进入当前兼容索引：{key}")
            if key not in by_key:
                raise KnowledgeError(
                    "index_provenance_unavailable", f"旧索引缺少来源身份，请重建：{key}"
                )
            if indexed_sources is not None and not any(
                record.get("evidence_unit_id") == by_key[key]["unit_id"]
                and record.get("source_digest") == by_key[key]["source_digest"]
                and record.get("parser_signature") == by_key[key]["parser_signature"]
                for record in indexed_sources.get(key, [])
            ):
                raise KnowledgeError(
                    "index_provenance_unavailable", f"索引节点与证据身份不兼容，请重建：{key}"
                )
            state = source_status(kb_dir, by_key[key])
            if state != "valid":
                raise KnowledgeError(
                    "source_" + state,
                    f"来源文件已{'删除' if state == 'missing' else '变化'}：{key}，请重建索引。",
                )
    warnings = []
    if not units:
        warnings.append("旧索引缺少证据身份；仅兼容普通查询，不可用于严格文档出题。")
        allowed = []
        for key, records in (indexed_sources or {}).items():
            digests = {record.get("source_digest", "") for record in records}
            if all(
                source_status(kb_dir, {"document_key": key, "source_digest": digest})
                in {"valid", "unknown"}
                for digest in digests
            ):
                allowed.append(key)
            else:
                warnings.append(f"已排除失效来源：{key}")
        return (allowed if indexed_sources else keys), units, warnings
    allowed = []
    for key in keys if keys is not None else sorted(by_key):
        if source_status(kb_dir, by_key[key]) == "valid":
            allowed.append(key)
        else:
            warnings.append(f"已排除失效来源：{key}")
    return allowed, units, warnings


def verify_unit_sources(kb_dir: Path, storage_dir: Path) -> None:
    for unit in load_units(storage_dir).values():
        state = source_status(kb_dir, unit)
        if state != "valid":
            raise KnowledgeError("source_" + state, "候选索引包含失效来源，不予发布。")


def public_evidence(unit: dict, kb_id: str, version: str) -> dict:
    evidence = Evidence.model_validate(
        {**unit, "kb_id": kb_id, "index_version": version, "source_status": "valid"}
    )
    evidence.file_url = f"/api/knowledge-bases/{quote(kb_id, safe='')}/files/{quote(evidence.document_key, safe='/')}?source_hash={evidence.source_digest}"
    evidence.image_urls = [
        f"/api/knowledge-bases/{quote(kb_id, safe='')}/visual-assets/{i}"
        for i in evidence.image_refs
    ]
    if evidence.document_key.lower().endswith(".pdf"):
        evidence.source_page_urls = [
            preview_url(
                SourceRef(
                    kb_ref=kb_id,
                    document_key=evidence.document_key,
                    source_digest=evidence.source_digest,
                    page_index=p,
                    parser_signature=evidence.parser_signature,
                )
            )
            for p in evidence.page_indices
        ]
    return evidence.model_dump()


def select_evidence(
    sources: list[dict], *, kb_id: str, document_key: str, max_chars: int = 24000
) -> list[dict]:
    selected = []
    seen = set()
    used = 0
    for source in sources:
        evidence = Evidence.model_validate(source)
        if evidence.kb_id != kb_id or evidence.document_key != document_key:
            raise KnowledgeError("invalid_evidence_reference", "检索证据越出本次允许文档。")
        if evidence.unit_id in seen:
            continue
        seen.add(evidence.unit_id)
        if evidence.completeness != "complete" or evidence.source_status != "valid":
            raise KnowledgeError(
                "evidence_incomplete", "来源证据不完整或未验证：" + "；".join(evidence.warnings)
            )
        if used + len(evidence.evidence_text) > max_chars:
            continue
        used += len(evidence.evidence_text)
        evidence.evidence_id = f"E-{evidence.unit_id[:16]}"
        selected.append(evidence.model_dump())
    if not selected and sources:
        raise KnowledgeError(
            "evidence_budget_exceeded", "完整证据超出本次预算，请缩小资料范围；系统没有截断原文。"
        )
    if len(selected) < len(seen) and selected:
        selected[0]["warnings"].append("预算限制减少了完整证据单元数量，未截断入选单元。")
    return selected
