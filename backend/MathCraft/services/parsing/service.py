"""ParseService — the public entry to the document-parse bridge.

Resolves the active (or requested) engine, computes the content-addressed cache
key, returns a cached :class:`ParsedDocument` on hit, and on miss runs the
engine behind the model-download readiness gate, then caches and returns the IR.
Consumption is pull-based: callers ask for a parse when they need structured
content; nothing is parsed implicitly.
"""

from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path
import shutil
from typing import Any, Callable, Optional

from MathCraft.services.config.runtime_settings import (
    _DEFAULT_DOCUMENT_PARSING_ENGINE,
    load_document_parsing_settings,
)

from . import cache
from .engines.factory import get_parser
from .quality import check_output, inspect_pdf
from .types import ParsedDocument, ParserError

logger = logging.getLogger(__name__)

SCANNED_PDF_OCR_ERROR_CODE = "scanned_pdf_mineru_cloud_not_configured"
SCANNED_PDF_OCR_FAILED_CODE = "scanned_pdf_mineru_cloud_failed"
_SCANNED_PDF_OCR_ERROR = (
    "扫描型 PDF 未提取到正文，必须使用 MinerU 云端 OCR；当前未配置 MinerU 云端模式 "
    "或 API Token，无法启动 OCR 模式。请在设置 → 文档解析中将 MinerU 设置为 cloud "
    "并配置 API Token。"
)


def _matches_supported_format(source_path: str | Path, supported: frozenset[str]) -> bool:
    """Match simple or compound parser suffixes case-insensitively."""
    name = Path(source_path).name.lower()
    return any(name.endswith(str(extension).lower()) for extension in supported)


def _display_extension(source_path: str | Path, supported: frozenset[str]) -> str:
    """Return the most specific advertised suffix for an error message."""
    name = Path(source_path).name.lower()
    matches = [extension for extension in supported if name.endswith(extension.lower())]
    if matches:
        return max(matches, key=len)
    return Path(source_path).suffix.lower() or "this"


def _is_scanned_pdf(source_path: Path) -> bool:
    """Compatibility helper; the decision now includes each page's usable body."""
    inspection = inspect_pdf(source_path)
    return inspection is not None and inspection.needs_ocr


# Engines tried, in order, when the *implicitly* selected engine (the global
# default) does not advertise support for a file's suffix. The global
# single-select is a default, not a per-file command: a mixed KB (MinerU PDFs
# plus .txt/.md notes) must not hard-fail the whole ingest batch on the files
# the chosen engine was never built for (#1502). ``text_only`` leads because
# it is lossless for text files and needs no model.
_FALLBACK_ENGINE_PREFERENCE = ("text_only", "markitdown", "tika")


def _find_fallback_engine(
    source_path: str | Path, primary_engine: str
) -> Optional[tuple[str, Any, Any]]:
    """First installed engine other than ``primary`` that supports the file.

    Returns ``(engine_name, parser, config)`` or ``None``. Engines that are
    not installed are skipped — the fallback must never turn a routing
    decision into an import-time failure.
    """
    for name in _FALLBACK_ENGINE_PREFERENCE:
        if name == primary_engine:
            continue
        try:
            parser = get_parser(name)
        except Exception:
            continue
        supported = parser.supported_formats()
        if not supported or _matches_supported_format(source_path, supported):
            return name, parser, parser.resolve_config()
    return None


class ParseService:
    """Cache-aware, engine-pluggable document parsing."""

    def __init__(self, cache_root: Optional[Path] = None) -> None:
        self._cache_root_override = Path(cache_root) if cache_root else None

    def _cache_root(self) -> Path:
        if self._cache_root_override is not None:
            return self._cache_root_override
        # Resolve lazily per call so the cache root tracks the active
        # user/workspace (multi-user safety), like get_path_service().
        from MathCraft.services.path_service import get_path_service

        return get_path_service().get_parse_cache_root()

    def active_engine(self) -> str:
        return str(
            load_document_parsing_settings().get("engine") or _DEFAULT_DOCUMENT_PARSING_ENGINE
        )

    def supports(self, source_path: str | Path, *, engine: Optional[str] = None) -> bool:
        """Return whether the selected engine advertises support for this path.

        This is a cheap routing check only: it does not require the file to
        exist, initialize models, or evaluate engine readiness.
        """
        engine_name = (engine or self.active_engine()).strip().lower()
        supported = get_parser(engine_name).supported_formats()
        return not supported or _matches_supported_format(source_path, supported)

    def parse(self, source_path: str | Path, *, engine=None, on_output=None) -> ParsedDocument:
        from MathCraft.knowledge.indexing_run import _redact, current_run, failure_code

        run = current_run()
        source = Path(source_path)
        if run:
            run.phase("parsing", source=source)
            run.document(source, "parsing")

        def output(line):
            if run:
                run.phase("parsing", source=source, activity=line)
            if on_output:
                on_output(line)

        try:
            result = self._parse(source, engine=engine, on_output=output)
            if run:
                run.check()
                run.document(
                    source, "parsed", parser=result.engine, parser_signature=result.parser_signature
                )
            return result
        except Exception as exc:
            if run:
                run.document(source, "failed", reason=failure_code(exc), detail=_redact(str(exc)))
            raise

    def _parse(
        self,
        source_path: str | Path,
        *,
        engine: Optional[str] = None,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> ParsedDocument:
        """Parse ``source_path`` with the active (or requested) engine.

        Returns a cached result when one exists for the same bytes + engine
        signature. Raises :class:`ParserError` when the engine is not ready
        (e.g. local models not downloaded and auto-download disabled) or the
        file type is unsupported.
        """
        source_path = Path(source_path)
        if not source_path.is_file():
            raise ParserError(f"File to parse not found: {source_path}")

        inspection = inspect_pdf(source_path)
        scanned_pdf = inspection is not None and inspection.needs_ocr
        if scanned_pdf:
            engine_name, parser, config = self._resolve_scanned_pdf_ocr()
            logger.info(
                "Scanned PDF detected; forcing MinerU cloud OCR for %s", source_path.name
            )
        else:
            engine_name = (engine or self.active_engine()).strip().lower()
            parser = get_parser(engine_name)
            config = parser.resolve_config()

        supported = parser.supported_formats()
        if supported and not _matches_supported_format(source_path, supported):
            if engine is not None:
                # The caller pinned this engine by name — keep the loud error.
                suffix = _display_extension(source_path, supported)
                raise ParserError(
                    f"The '{engine_name}' parsing engine doesn't support {suffix} "
                    f"files. Choose a different engine in Settings → Document Parsing."
                )
            fallback = _find_fallback_engine(source_path, engine_name)
            if fallback is None:
                suffix = _display_extension(source_path, supported)
                raise ParserError(
                    f"The '{engine_name}' parsing engine doesn't support {suffix} "
                    f"files. Choose a different engine in Settings → Document Parsing."
                )
            primary_engine = engine_name
            engine_name, parser, config = fallback
            supported = parser.supported_formats()
            logger.warning(
                "The '%s' parsing engine doesn't support %s files; using '%s' for this file.",
                primary_engine,
                _display_extension(source_path, supported),
                engine_name,
            )

        identity = parser.signature(config)
        legacy_sig = identity.legacy_hash()
        sig = identity.hash()
        expected_digest = cache.source_digest_from_path(source_path)
        source_hash = expected_digest[:16]
        cache_root = self._cache_root()
        with cache.entry_lock(cache_root, source_hash, sig):
            return self._parse_cached(source_path, engine_name, parser, config, sig,
                                      legacy_sig, source_hash, inspection, scanned_pdf, on_output, expected_digest)

    def _parse_cached(self, source_path, engine_name, parser, config, sig, legacy_sig,
                      source_hash, inspection, scanned_pdf, on_output, expected_digest):
        cache_root = self._cache_root()

        def validate(workdir, *, persist=True):
            markdown, blocks, asset_dir = cache.load_ir(workdir)
            quality = check_output(source_path, markdown, blocks, workdir, inspection,
                                   cloud=engine_name == "mineru" and getattr(config, "is_cloud", False))
            if quality.source_digest != expected_digest:
                raise ParserError("检查期间原文件发生变化，未使用产物。", code="source_changed")
            from MathCraft.services.file_io import atomic_write_json
            if persist or quality.status == "failed":
                atomic_write_json(workdir / "quality.json", quality.to_dict())
            if quality.status == "failed":
                raise ParserError("解析质量检查失败：" + "；".join(
                    issue["message"] for issue in quality.issues if issue["severity"] == "error"
                ), code="parse_quality_failed")
            return markdown, blocks, asset_dir, quality.to_dict()

        hit = cache.lookup(cache_root, source_hash, sig)
        # Legacy caches are checked, copied into the new identity, then checked again.
        # The original entry is retained, never silently relabelled as verified.
        if hit is None and (legacy := cache.lookup(cache_root, source_hash, legacy_sig)):
            validate(legacy, persist=False)
            destination = cache.reserve(cache_root, source_hash, sig)
            shutil.copytree(legacy, destination, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(cache.MANIFEST_FILENAME, "quality.json"))
            markdown, blocks, asset_dir, quality = validate(destination)
            cache.write_manifest(destination, {"engine": engine_name, "signature": sig,
                "source_hash": source_hash, "source_digest": expected_digest,
                "source_name": source_path.name, "quality": quality,
                "upgraded_from": legacy_sig})
            hit = destination
        if hit is not None:
            markdown, blocks, asset_dir, quality = validate(hit)
            if markdown.strip() or blocks:
                logger.info("Parse cache hit for %s (%s/%s)", source_path.name, engine_name, sig)
                from MathCraft.knowledge.indexing_run import current_run

                if run := current_run():
                    run.document(source_path, "parsed", parse_reused=True)
                return ParsedDocument(
                    markdown=markdown,
                    blocks=blocks,
                    asset_dir=asset_dir,
                    source_hash=source_hash,
                    parser_signature=sig,
                    engine=engine_name,
                    workdir=hit,
                    quality=quality,
                )
            # A ready stamp alone cannot make missing/empty output usable (#1612).
            logger.warning("Invalid parse cache for %s; restarting this document", source_path.name)
            raise ParserError("解析缓存产物为空，原缓存已保留。", code="parse_quality_failed")

        # Credentials gate actual external work, not reading a compatible completed cache.
        # The cloud adapter can also rebuild a complete IR from validated slice
        # archives without any request. It gates credentials at the first network step.
        if not (engine_name == "mineru" and getattr(config, "is_cloud", False)):
            report = parser.is_ready(config)
            if not report.ready:
                raise ParserError(report.message or f"The '{engine_name}' engine is not ready.")

        workdir = cache.reserve(cache_root, source_hash, sig)
        logger.info("Parsing %s with %s (signature %s)", source_path.name, engine_name, sig)
        try:
            parser.parse(source_path, workdir, config=config, on_output=on_output)
            if cache.source_digest_from_path(source_path) != expected_digest:
                raise ParserError("解析期间原文件发生变化，请重试。", code="source_changed")
            markdown, blocks, asset_dir, quality = validate(workdir)
            if not markdown.strip() and not blocks:
                raise ParserError(
                    f"The '{engine_name}' engine produced no content for {source_path.name}."
                )
            cache.write_manifest(
                workdir,
                {
                    "engine": engine_name,
                    "signature": sig,
                    "source_hash": source_hash,
                    "source_digest": expected_digest,
                    "source_name": source_path.name,
                    "quality": quality,
                },
            )
            return ParsedDocument(
                markdown=markdown,
                blocks=blocks,
                asset_dir=asset_dir,
                source_hash=source_hash,
                parser_signature=sig,
                engine=engine_name,
                workdir=workdir,
                quality=quality,
            )
        except Exception as exc:
            cache.cleanup_failed(workdir)
            if scanned_pdf and getattr(exc, "code", None) == "cloud_credentials_missing":
                raise ParserError(_SCANNED_PDF_OCR_ERROR, code=SCANNED_PDF_OCR_ERROR_CODE) from None
            if scanned_pdf and isinstance(exc, ParserError) and not exc.code:
                raise ParserError(
                    f"扫描型 PDF 的 MinerU 云端 OCR 失败：{exc}",
                    code=SCANNED_PDF_OCR_FAILED_CODE,
                    detail=str(exc),
                ) from exc
            raise

    @staticmethod
    def _resolve_scanned_pdf_ocr() -> tuple[str, Any, Any]:
        """Resolve a cloud-only MinerU config for a scanned PDF."""
        parser = get_parser("mineru")
        config = parser.resolve_config()
        if (
            not getattr(config, "is_cloud", False)
            or not str(getattr(config, "api_base_url", "")).strip()
        ):
            raise ParserError(_SCANNED_PDF_OCR_ERROR, code=SCANNED_PDF_OCR_ERROR_CODE)

        # OCR is a property of this scanned-PDF request. Do not mutate the
        # persisted settings: ordinary MinerU parses keep their configured
        # value, while this path always sends is_ocr=true to the cloud API.
        return "mineru", parser, replace(config, is_ocr=True)


_service: Optional[ParseService] = None


def get_parse_service() -> ParseService:
    """Return the process-wide :class:`ParseService` singleton."""
    global _service
    if _service is None:
        _service = ParseService()
    return _service


__all__ = ["ParseService", "get_parse_service"]
