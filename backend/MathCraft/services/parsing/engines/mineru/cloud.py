"""MinerU cloud (mineru.net) v4 API backend.

Implements the token-required *Precision API* flow for one local input:

1. ``POST /api/v4/file-urls/batch`` → ``{batch_id, file_urls: [signed_url]}``
2. ``PUT`` the raw file bytes to ``signed_url`` (no auth, no Content-Type)
3. Poll ``GET /api/v4/extract-results/batch/{batch_id}`` until the file's
   ``state`` reaches ``done`` / ``failed``
4. Download the ``full_zip_url`` archive and extract it into a working dir
   whose layout matches the local CLI output (``*.md`` +
   ``*_content_list.json`` + ``images/``), so the downstream question
   extractor is backend-agnostic.

The module is synchronous on purpose: it runs inside the worker thread that
:func:`MathCraft.agents.question.mimic_source.parse_exam_paper_to_templates`
spawns via ``asyncio.to_thread``, so a blocking ``httpx.Client`` is the
simplest correct choice (no nested event loop).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import io
import hashlib
import json
import logging
import stat
import re
from pathlib import Path
import shutil
import tempfile
import time
from urllib.parse import urlsplit
import zipfile

import httpx
from pypdf import PdfReader, PdfWriter

from MathCraft.services.keypool import KeyPool

from .checkpoints import RemoteTask, SliceCheckpoint, job_directory
from .config import MinerUConfig, MinerUError
from .formats import MINERU_PDF_FORMATS, MINERU_SUPPORTED_FORMATS

logger = logging.getLogger(__name__)

# Async polling defaults. MinerU recommends a 3–5s interval; parsing a typical
# exam paper completes well under a few minutes.
DEFAULT_POLL_INTERVAL_SECONDS = 4.0
DEFAULT_TIMEOUT_SECONDS = 300.0
_SUBMIT_TIMEOUT_SECONDS = 60.0
_UPLOAD_TIMEOUT_SECONDS = 300.0
_DOWNLOAD_TIMEOUT_SECONDS = 300.0

_TERMINAL_OK = "done"
_TERMINAL_FAIL = "failed"

# Bounds for the extracted archive (defends a hostile/buggy CDN response).
_MAX_TOTAL_BYTES = 500 * 1024 * 1024
_MAX_ENTRIES = 5000
_MAX_UPLOAD_BYTES = 200 * 1024 * 1024


def _http_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        location = urlsplit(value)
        return location.scheme in {"http", "https"} and bool(location.hostname)
    except ValueError:
        return False


def _extract_results(payload: dict) -> list:
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("extract_result"), list):
        raise MinerUError("MinerU 返回无效的任务状态记录。", code="cloud_result_invalid")
    return data["extract_result"]


def _check_cancel() -> None:
    from MathCraft.knowledge.indexing_run import current_run
    if run := current_run():
        run.check()


def _wait(seconds: float) -> None:
    deadline = time.monotonic() + max(0, seconds)
    while time.monotonic() < deadline:
        _check_cancel()
        time.sleep(min(.25, max(0, deadline - time.monotonic())))


def _validate_part(source: Path, directory: Path) -> None:
    from ...cache import load_ir
    from ...quality import check_output
    markdown, blocks, _ = load_ir(directory)
    quality = check_output(source, markdown, blocks, directory, cloud=True)
    if quality.status == "failed":
        raise MinerUError("云端产物未通过正文、原页或图片完整性检查。",
                          code="cloud_result_invalid")


def parse_cloud(
    source_path: Path,
    output_base: Path,
    config: MinerUConfig,
    *,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Parse ``source_path`` via the MinerU cloud API; return the working dir.

    The working dir sits under ``output_base`` (named after the input stem) and
    holds the unzipped MinerU artifacts. ``on_progress`` (if given) receives a
    short status line whenever the polled task state / page count changes.
    Raises :class:`MinerUError` on any misconfiguration, API error, timeout,
    or extraction failure.
    """
    source_path = Path(source_path)
    if not source_path.is_file():
        raise MinerUError(f"Input file not found: {source_path}")
    if source_path.stem in {"", ".", ".."}:
        raise MinerUError("无效的输入文件名。", code="cloud_result_invalid")
    if source_path.suffix.lower() not in MINERU_SUPPORTED_FORMATS:
        raise MinerUError(f"Unsupported MinerU cloud input format: {source_path.suffix or 'none'}")

    base_url = config.api_base_url.rstrip("/")
    key_pool = KeyPool(config.api_keys) if config.api_keys else None

    def report(message: str) -> None:
        _check_cancel()
        if on_progress is None:
            return
        try:
            on_progress(message)
        except Exception as exc:
            from MathCraft.knowledge.indexing_run import IndexingCancelled
            if isinstance(exc, IndexingCancelled):
                raise
            logger.debug("on_progress callback failed", exc_info=True)

    with httpx.Client(base_url=base_url, headers={"Accept": "application/json"}) as client:
        if source_path.suffix.lower() in MINERU_PDF_FORMATS:
            page_count = _pdf_page_count(source_path)
            if page_count is None or page_count < 1:
                raise MinerUError("PDF 无法读取，未向云端发送。", code="cloud_result_invalid")
            if page_count > config.max_pages_per_part or source_path.stat().st_size > _MAX_UPLOAD_BYTES:
                return _parse_pdf_in_parts(
                    client,
                    source_path,
                    output_base,
                    config,
                    key_pool,
                    page_count=page_count,
                    report=report,
                    poll_interval=poll_interval,
                    timeout=timeout,
                )

        if source_path.stat().st_size > _MAX_UPLOAD_BYTES:
            raise MinerUError("文件超过客户端单次上传体积上限。", code="cloud_input_too_large")
        checkpoint = SliceCheckpoint(job_directory(source_path, config), 0,
                                     page_count if source_path.suffix.lower() in MINERU_PDF_FORMATS else 1)
        from ...cache import entry_lock
        with entry_lock(checkpoint.directory.parent, checkpoint.directory.name, "cloud"):
            archive_bytes = checkpoint.load()
            if archive_bytes is None:
                archive_bytes = _upload_and_fetch_archive(
                    client, source_path, config, key_pool, report=report,
                    poll_interval=poll_interval, timeout=timeout, checkpoint=checkpoint,
                )
            report("MinerU cloud: validating archive")
            working_dir = output_base / source_path.stem
            _reset_dir(working_dir, within=output_base)
            try:
                _extract_archive(archive_bytes, working_dir)
                _validate_part(source_path, working_dir)
            except MinerUError:
                checkpoint.reject()
                raise
            _check_cancel()
            checkpoint.save(archive_bytes)
            RemoteTask(checkpoint, source_path).save("completed")
    logger.info("MinerU cloud parse complete: %s → %s", source_path.name, working_dir)
    return working_dir


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def _upload_and_fetch_archive(
    client: httpx.Client,
    part_path: Path,
    config: MinerUConfig,
    key_pool: KeyPool | None,
    *,
    report: Callable[[str], None],
    poll_interval: float,
    timeout: float,
    checkpoint: SliceCheckpoint,
) -> bytes:
    """Run the upload → poll → download trio for one input file and return the
    result archive bytes. Shared by the single-file path and each slice of the
    auto-split path."""
    task = RemoteTask(checkpoint, part_path)
    if key_pool is None:
        raise MinerUError("需要新的云端工作或查询，但未配置 MinerU API Token。",
                          code="cloud_credentials_missing")
    try:
        batch_id = task.data.get("batch_id")
        if not batch_id:
            if task.data.get("phase") in {"submitting", "submission_unknown"}:
                raise MinerUError("云端提交是否成功未知，未自动重新上传；请先核对远端任务。",
                                  code="cloud_submission_unknown")
            task.save("submitting", source_name=part_path.name)
            report("MinerU cloud: submitting")
            try:
                batch_id, upload_url, owner_fingerprint = _request_upload(client, part_path, config, key_pool,
                                                       request_id=task.data["request_id"])
            except MinerUError as exc:
                known_rejection = exc.code in {"cloud_rate_limited", "cloud_auth_failed"}
                task.save("rejected" if known_rejection else "submission_unknown",
                          error_code=exc.code or "cloud_submission_unknown")
                if not known_rejection:
                    raise MinerUError("云端提交是否成功未知，已保存请求身份；未自动再次提交。",
                                      code="cloud_submission_unknown") from exc
                raise
            task.save("uploading", batch_id=batch_id, credential_fingerprint=owner_fingerprint)
            if not _http_url(upload_url):
                raise MinerUError("云端返回无效上传地址；已保留任务 ID。", code="cloud_result_invalid")
            task.remember_upload(upload_url)
            report("MinerU cloud: uploading")
            _check_cancel()
            task.save("uploading", upload_started=True)
            _upload_file(part_path, upload_url)
            task.save("queued", upload_confirmed=True)
        else:
            report("MinerU cloud: resuming existing task")
            owner = task.data.get("credential_fingerprint")
            matching = [key for key in config.api_keys if hashlib.sha256(key.encode()).hexdigest() == owner]
            key_pool = KeyPool(matching or config.api_keys[:1])
            payload = _get_json(client, f"/api/v4/extract-results/batch/{batch_id}", key_pool)
            task.save(task.data.get("phase") or "queued",
                      credential_fingerprint=payload.get("_credential_fingerprint", owner))
            entry = _match_entry(_extract_results(payload),
                                 task.data.get("source_name") or part_path.name)
            if entry is not None and entry.get("state") == "waiting-file":
                if task.data.get("upload_confirmed"):
                    # waiting-file also includes provider-side enqueueing; never reupload a confirmed PUT.
                    task.save("queued", remote_state="waiting-file")
                elif task.data.get("upload_started"):
                    # This upstream state also includes enqueueing. A lost PUT response
                    # plus waiting-file does not prove that the object was never accepted.
                    raise MinerUError("云端尚未确认上传接收状态；未重复上传，请稍后继续查询。",
                                      code="cloud_upload_unknown")
                else:
                    task.save("uploading", upload_started=True)
                    _upload_file(part_path, task.upload_url())
                    task.save("queued", upload_confirmed=True)
        owner = task.data.get("credential_fingerprint")
        matching = [key for key in config.api_keys if hashlib.sha256(key.encode()).hexdigest() == owner]
        key_pool = KeyPool(matching or config.api_keys[:1])
        zip_url = _poll_for_zip(client, str(batch_id), task.data.get("source_name") or part_path.name,
            poll_interval=poll_interval, timeout=timeout, on_progress=report,
            key_pool=key_pool, task=task)
        task.save("downloading")
        report("MinerU cloud: downloading")
        archive = _download(zip_url)
        task.save("validating")
        return archive
    except Exception as exc:
        from MathCraft.knowledge.indexing_run import IndexingCancelled
        if isinstance(exc, IndexingCancelled):
            task.save("cancelled", resumable=True)
        elif task.data.get("phase") not in {"submission_unknown", "rejected"}:
            task.save(task.data.get("phase") or "unknown", resumable=bool(task.data.get("batch_id")),
                      error_code=getattr(exc, "code", None) or "cloud_connection_interrupted")
        raise


def _parse_pdf_in_parts(
    client: httpx.Client,
    source_path: Path,
    output_base: Path,
    config: MinerUConfig,
    key_pool: KeyPool | None,
    *,
    page_count: int,
    report: Callable[[str], None],
    poll_interval: float,
    timeout: float,
) -> Path:
    """Slice an oversized PDF, parse each part through the normal cloud flow,
    and merge the per-part artifacts into one working dir that is isomorphic to
    the single-file output (one ``*.md`` + ``*_content_list.json`` + ``images/``)."""
    working_dir = output_base / source_path.stem
    _reset_dir(working_dir, within=output_base)
    markdown_chunks: list[str] = []
    content_items: list = []
    has_content_list = False
    checkpoint_job = job_directory(source_path, config)

    with tempfile.TemporaryDirectory(prefix="mineru-slice-") as tmp:
        parts = _split_pdf(source_path, config.max_pages_per_part, Path(tmp))
        total = len(parts)
        report(
            f"MinerU cloud: {source_path.name} has {page_count} pages, exceeding the "
            f"{config.max_pages_per_part}-page per-file limit; auto-splitting into "
            f"{total} part(s)"
        )
        for index, part in enumerate(parts, start=1):
            _check_cancel()
            report(
                f"MinerU cloud: parsing part {index}/{total} (pages {part.start + 1}-{part.end})"
            )
            checkpoint = SliceCheckpoint(checkpoint_job, part.start, part.end)
            from ...cache import entry_lock
            with entry_lock(checkpoint.directory.parent, checkpoint.directory.name, "cloud"):
                archive_bytes = checkpoint.load()
                if archive_bytes is None:
                    archive_bytes = _upload_and_fetch_archive(
                        client, part.path, config, key_pool, report=report,
                        poll_interval=poll_interval, timeout=timeout, checkpoint=checkpoint,
                    )
                else:
                    report(f"MinerU cloud: reusing completed part {index}/{total}")
                report(f"MinerU cloud: merging part {index}/{total} artifacts")
                with tempfile.TemporaryDirectory(prefix="mineru-part-") as part_tmp:
                    part_dir = Path(part_tmp) / "out"
                    part_dir.mkdir()
                    try:
                        _extract_archive(archive_bytes, part_dir)
                        _validate_part(part.path, part_dir)
                    except MinerUError:
                        checkpoint.reject()
                        raise
                    _check_cancel()
                    _merge_part_artifacts(
                        part_dir, working_dir, markdown_chunks=markdown_chunks,
                        content_items=content_items, part_index=index, page_offset=part.start,
                        page_count=part.end - part.start,
                    )
                    has_content_list = True
                    checkpoint.save(archive_bytes)
                    RemoteTask(checkpoint, part.path).save("completed")

    merged_md = "".join(
        chunk if chunk.endswith("\n") else chunk + "\n" for chunk in markdown_chunks
    )
    (working_dir / f"{source_path.stem}.md").write_text(merged_md, encoding="utf-8")
    if has_content_list:
        content_list_path = working_dir / f"{source_path.stem}_content_list.json"
        content_list_path.write_text(
            json.dumps(content_items, ensure_ascii=False), encoding="utf-8"
        )
    logger.info(
        "MinerU cloud parse complete (%d parts): %s → %s", total, source_path.name, working_dir
    )
    return working_dir


def _pdf_page_count(source_path: Path) -> int | None:
    """Number of pages in a PDF, or ``None`` when pypdf cannot read it (e.g. a
    truncated/encrypted file). Unreadable PDFs are rejected before upload."""
    try:
        with PdfReader(str(source_path)) as reader:
            return len(reader.pages)
    except Exception:
        logger.warning("Could not count pages of %s; skipping auto-slicing", source_path.name)
        return None


def _split_pdf(source_path: Path, max_pages_per_part: int, work_dir: Path) -> list[_PdfPart]:
    """Evenly cut ``source_path`` into parts of at most ``max_pages_per_part``
    pages (the last part may be shorter) and write each part PDF into
    ``work_dir``. 250 pages @180 → [180, 70]."""
    try:
        with PdfReader(str(source_path)) as reader:
            total = len(reader.pages)
            def split(start, end):
                part_path = work_dir / f"{source_path.stem}_pages_{start + 1}_{end}.pdf"
                writer = PdfWriter()
                try:
                    for page_number in range(start, end):
                        writer.add_page(reader.pages[page_number])
                    writer.write(part_path)
                finally:
                    writer.close()
                if part_path.stat().st_size > _MAX_UPLOAD_BYTES:
                    if end - start <= 1:
                        raise MinerUError("单页仍超过上传体积上限，未上传。", code="cloud_input_too_large")
                    part_path.unlink()
                    middle = (start + end) // 2
                    return split(start, middle) + split(middle, end)
                return [_PdfPart(path=part_path, start=start, end=end)]

            parts: list[_PdfPart] = []
            for start in range(0, total, max_pages_per_part):
                parts.extend(split(start, min(start + max_pages_per_part, total)))
            return parts
    except MinerUError:
        raise
    except Exception as exc:
        raise MinerUError(f"Failed to split PDF {source_path.name} into parts: {exc}") from exc


def _merge_part_artifacts(
    part_dir: Path,
    working_dir: Path,
    *,
    markdown_chunks: list[str],
    content_items: list,
    part_index: int,
    page_offset: int = 0,
    page_count: int | None = None,
) -> None:
    """Accumulate one part's artifacts: markdown text, ``images/`` (renamed with
    a part prefix so names stay globally unique) and ``content_list`` entries
    (with ``img_path`` rewritten to match)."""
    md_files = sorted(path for path in part_dir.rglob("*.md") if path.is_file())
    if not md_files:
        raise MinerUError(f"MinerU part {part_index} archive contains no markdown output.")
    content_root = md_files[0].parent

    rename_map = _copy_part_images(content_root / "images", working_dir / "images", part_index)

    markdown = md_files[0].read_text(encoding="utf-8")
    for original, unique in sorted(rename_map.items(), key=lambda item: -len(item[0])):
        markdown = markdown.replace(f"images/{original}", f"images/{unique}")
    markdown_chunks.append(markdown)

    for content_list_path in sorted(content_root.glob("*_content_list.json")):
        try:
            payload = json.loads(content_list_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise MinerUError(
                f"MinerU part {part_index} content list is unreadable: {exc}"
            ) from exc
        if isinstance(payload, list):
            _offset_page_indices(payload, page_offset, page_count)
            _rewrite_image_paths(payload, rename_map)
            content_items.extend(payload)

    # Keep the remaining artifacts (middle/model/layout files, origin PDF, …)
    # on disk with a part prefix, mirroring the single-file layout as closely
    # as their per-part nature allows.
    for extra in sorted(content_root.iterdir()):
        if not extra.is_file() or extra.suffix.lower() == ".md":
            continue
        if extra.name.endswith("_content_list.json"):
            continue
        shutil.copyfile(extra, working_dir / f"part{part_index:02d}_{extra.name}")


def _offset_page_indices(node: object, offset: int, page_count: int | None) -> None:
    """Restore zero-based source page indices, including nested content blocks."""
    if isinstance(node, dict):
        for field in ("page_idx", "page_index"):
            if field not in node:
                continue
            index = node[field]
            if (
                type(index) is not int
                or index < 0
                or (page_count is not None and index >= page_count)
            ):
                raise MinerUError("MinerU 分片页码无效。", code="cloud_result_invalid")
            node[field] = index + offset
        for value in node.values():
            _offset_page_indices(value, offset, page_count)
    elif isinstance(node, list):
        for value in node:
            _offset_page_indices(value, offset, page_count)


def _copy_part_images(images_dir: Path, target_dir: Path, part_index: int) -> dict[str, str]:
    """Copy one part's ``images/`` into the merged ``images/`` dir, prefixing
    each name with the part index so names stay globally unique across parts.
    Returns ``{original_name: unique_name}``."""
    if not images_dir.is_dir():
        return {}
    target_dir.mkdir(parents=True, exist_ok=True)
    rename_map: dict[str, str] = {}
    for image in sorted(images_dir.rglob("*")):
        if not image.is_file():
            continue
        relative = image.relative_to(images_dir).as_posix()
        unique_name = f"part{part_index:02d}/{relative}"
        (target_dir / unique_name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(image, target_dir / unique_name)
        rename_map[relative] = unique_name
    return rename_map


def _rewrite_image_paths(node: object, rename_map: dict[str, str]) -> None:
    """Rewrite ``img_path``/``image_path`` values in a content-list tree to the
    renamed (part-prefixed) image files."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("img_path", "image_path") and isinstance(value, str):
                name = value.replace("\\", "/").split("images/", 1)[-1]
                if name in rename_map:
                    node[key] = "images/" + rename_map[name]
            else:
                _rewrite_image_paths(value, rename_map)
    elif isinstance(node, list):
        for item in node:
            _rewrite_image_paths(item, rename_map)


@dataclass(frozen=True)
class _PdfPart:
    """One slice of an oversized PDF: 0-based ``start``, exclusive ``end``."""

    path: Path
    start: int
    end: int


def _request_upload(
    client: httpx.Client, source_path: Path, config: MinerUConfig, key_pool: KeyPool,
    *, request_id: str = "",
) -> tuple[str, str, str]:
    """Return task identity, transport URL and a one-way credential fingerprint."""
    file_entry: dict[str, object] = {"name": source_path.name, "is_ocr": config.is_ocr}
    if request_id:
        # Correlation only: the provider does not promise idempotent submission.
        file_entry["data_id"] = request_id
    body: dict[str, object] = {
        "files": [file_entry],
        "model_version": config.model_version,
        "enable_formula": config.enable_formula,
        "enable_table": config.enable_table,
    }
    if config.api_language:
        body["language"] = config.api_language

    payload = _post_json(client, "/api/v4/file-urls/batch", body, key_pool)
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        raise MinerUError("MinerU API 没有返回可识别的任务身份。", code="cloud_result_invalid")
    batch_id = str(data.get("batch_id") or "").strip()
    file_urls = data.get("file_urls") or []
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", batch_id):
        raise MinerUError("MinerU API 没有返回有效任务 ID。", code="cloud_result_invalid")
    url = file_urls[0] if isinstance(file_urls, list) and file_urls and isinstance(file_urls[0], str) else ""
    return batch_id, url, payload["_credential_fingerprint"]


def _upload_file(source_path: Path, upload_url: str) -> None:
    """PUT the input bytes to the signed URL.

    The signed URL carries its own auth; per MinerU's docs we must NOT send an
    ``Authorization`` or ``Content-Type`` header (a stray Content-Type breaks
    the OSS signature).
    """
    _check_cancel()
    if source_path.stat().st_size > _MAX_UPLOAD_BYTES:
        raise MinerUError("分片超过客户端上传体积上限。", code="cloud_input_too_large")
    data = source_path.read_bytes()
    try:
        response = httpx.put(upload_url, content=data, timeout=_UPLOAD_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPError:
        raise MinerUError("云端上传中断，保留已有任务以便查询后恢复。",
                          code="cloud_upload_interrupted") from None


def _poll_for_zip(
    client: httpx.Client,
    batch_id: str,
    file_name: str,
    *,
    key_pool: KeyPool,
    poll_interval: float,
    timeout: float,
    on_progress: Callable[[str], None] | None = None,
    task: RemoteTask | None = None,
) -> str:
    """Poll the batch results until our file is ``done``; return full_zip_url."""
    deadline = time.monotonic() + timeout
    last_state = ""
    while True:
        _check_cancel()
        payload = _get_json(client, f"/api/v4/extract-results/batch/{batch_id}", key_pool)
        results = _extract_results(payload)
        entry = _match_entry(results, file_name)
        if entry is not None:
            state = str(entry.get("state") or "").strip().lower()
            if state not in {"done", "failed", "waiting-file", "pending", "running", "converting"}:
                state = "unknown"
            last_state = state or last_state
            if task is not None:
                phase = "parsing" if state in {"running", "converting"} else "queued"
                task.save(phase, remote_state=state)
            if on_progress is not None:
                progress = entry.get("extract_progress")
                progress = progress if isinstance(progress, dict) else {}
                total_pages = progress.get("total_pages")
                report = f"MinerU cloud: {state or 'queued'}"
                extracted = progress.get("extracted_pages", 0)
                if type(total_pages) is int and total_pages > 0 and type(extracted) is int:
                    report += f" ({extracted}/{total_pages} pages)"
                # A genuine poll is activity even while the provider stays queued.
                on_progress(report)
            _check_cancel()
            if state == _TERMINAL_OK:
                zip_url = entry.get("full_zip_url")
                if not _http_url(zip_url):
                    raise MinerUError("MinerU 已完成但没有提供有效结果地址。", code="cloud_result_invalid")
                return zip_url
            if state == _TERMINAL_FAIL:
                raise MinerUError("MinerU 远端任务报告解析失败。", code="cloud_remote_failed")
        if time.monotonic() >= deadline:
            raise MinerUError(
                f"MinerU parsing timed out after {int(timeout)}s "
                f"(last state: {last_state or 'unknown'}); 已保存任务，可显式继续等待。",
                code="cloud_wait_budget_exceeded",
            )
        _wait(poll_interval)


def verify_credentials(config: MinerUConfig) -> None:
    """Best-effort connectivity / token check for the Settings → MinerU "Test"
    button. Requests an upload slot (which does not consume parsing quota and
    is never followed by an upload, so it simply expires) and validates the
    business code. Raises :class:`MinerUError` with a user-facing message on
    any failure."""
    if not config.api_keys:
        raise MinerUError("No API token configured.")
    base_url = config.api_base_url.rstrip("/")
    key_pool = KeyPool(config.api_keys)
    body: dict[str, object] = {
        "files": [{"name": "connectivity-check.pdf", "is_ocr": False}],
        "model_version": config.model_version,
        "enable_formula": config.enable_formula,
        "enable_table": config.enable_table,
    }
    if config.api_language:
        body["language"] = config.api_language
    with httpx.Client(base_url=base_url, headers={"Accept": "application/json"}) as client:
        _post_json(client, "/api/v4/file-urls/batch", body, key_pool)


def _download(zip_url: str) -> bytes:
    for attempt in range(3):
        _check_cancel()
        try:
            with httpx.stream("GET", zip_url, timeout=_DOWNLOAD_TIMEOUT_SECONDS,
                              follow_redirects=True) as response:
                response.raise_for_status()
                chunks = []
                size = 0
                for chunk in response.iter_bytes(1024 * 1024):
                    _check_cancel()
                    size += len(chunk)
                    if size > _MAX_TOTAL_BYTES:
                        raise MinerUError("云端 ZIP 下载体积超过上限。", code="cloud_result_invalid")
                    chunks.append(chunk)
                return b"".join(chunks)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in {429, 500, 502, 503, 504} and attempt < 2:
                _retry_wait(exc.response, attempt)
                continue
            raise MinerUError("云端结果下载失败，已保留任务供后续恢复。",
                              code="cloud_rate_limited" if exc.response.status_code == 429 else "cloud_download_failed") from None
        except httpx.HTTPError:
            if attempt < 2:
                _wait(2 ** attempt)
                continue
            raise MinerUError("云端结果下载中断，已保留任务供后续恢复。",
                              code="cloud_download_failed") from None
    raise MinerUError("云端结果下载失败。", code="cloud_download_failed")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _match_entry(results: list, file_name: str) -> dict | None:
    """Pick our file's result row. Single-file batch → first row is ours, but
    match on ``file_name`` when present to be safe."""
    rows = [r for r in results if isinstance(r, dict)]
    if not rows:
        return None
    for row in rows:
        if str(row.get("file_name") or "") == file_name:
            return row
    return rows[0] if len(rows) == 1 and not rows[0].get("file_name") else None


def _retry_wait(response: httpx.Response, attempt: int) -> None:
    delay = min(8.0, float(2 ** attempt))
    header = response.headers.get("Retry-After")
    if header:
        try:
            delay = max(delay, float(header))
        except ValueError:
            from datetime import datetime, timezone
            from email.utils import parsedate_to_datetime
            try:
                delay = max(delay, (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError):
                pass
    if delay > 30:
        raise MinerUError("服务端要求稍后重试；任务已保留，未提前再次请求。",
                          code="cloud_rate_limited")
    _wait(delay)


def _request_json(
    request: Callable[..., httpx.Response],
    path: str,
    key_pool: KeyPool,
    *, safe_retry: bool = False,
    **kwargs,
) -> dict:
    max_attempts = min(4, max(3, len(key_pool)))
    for attempt in range(max_attempts):
        _check_cancel()
        api_key = key_pool.next()
        try:
            response = request(
                path,
                timeout=_SUBMIT_TIMEOUT_SECONDS,
                headers={"Authorization": f"Bearer {api_key}"},
                **kwargs,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status == 429:
                key_pool.mark_429(api_key)
            if (status == 429 or safe_retry and status in {500, 502, 503, 504}) and attempt < max_attempts - 1:
                _retry_wait(exc.response, attempt)
                continue
            code = "cloud_auth_failed" if status in {401, 403} else "cloud_rate_limited" if status == 429 else "cloud_api_failed"
            raise MinerUError(_http_error_message(exc), code=code) from exc
        except httpx.HTTPError as exc:
            if safe_retry and attempt < max_attempts - 1:
                _wait(2 ** attempt)
                continue
            raise MinerUError("MinerU API 连接中断，未丢弃已有任务身份。",
                              code="cloud_connection_interrupted") from exc
        except ValueError as exc:
            raise MinerUError("MinerU API 返回无效 JSON。", code="cloud_result_invalid") from exc
        _check_code(payload)
        payload["_credential_fingerprint"] = hashlib.sha256(api_key.encode()).hexdigest()
        return payload
    raise MinerUError("MinerU API key rotation exhausted.")


def _post_json(client: httpx.Client, path: str, body: dict, key_pool: KeyPool) -> dict:
    return _request_json(client.post, path, key_pool, json=body)


def _get_json(client: httpx.Client, path: str, key_pool: KeyPool) -> dict:
    return _request_json(client.get, path, key_pool, safe_retry=True)


def _check_code(payload: dict) -> None:
    """MinerU wraps errors in ``{"code": <non-zero>, "msg": ...}`` even on
    HTTP 200, so the business code must be inspected explicitly."""
    if not isinstance(payload, dict):
        raise MinerUError("MinerU API 返回无效记录。", code="cloud_result_invalid")
    code = payload.get("code")
    if code not in (0, None):
        # Provider messages may contain signed URLs or input text; publish only the code.
        label = str(code) if type(code) is int else "未知"
        raise MinerUError(f"MinerU API 报告业务错误（{label}）。", code="cloud_api_failed")


def _http_error_message(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    if status in (401, 403):
        return "MinerU API rejected the token (401/403). Check the API token in Settings → MinerU."
    if status == 429:
        return "MinerU API rate limit hit (429). Try again later or reduce request volume."
    return f"MinerU API returned HTTP {status}."


def _reset_dir(path: Path, *, within: Path) -> None:
    root, target = within.resolve(), path.resolve()
    if path.is_symlink() or target == root or not target.is_relative_to(root):
        raise MinerUError("解析输出路径越界，未清理任何目录。", code="cloud_result_invalid")
    if path.exists():
        import shutil

        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _extract_archive(archive_bytes: bytes, target_dir: Path) -> None:
    """Extract the MinerU zip into ``target_dir``, preserving its directory
    tree (the ``images/`` subdir matters) while defending against Zip Slip and
    zip bombs. Unlike :func:`safe_extract_zip`, this keeps subdirectories and
    does not apply a document-extension whitelist — the archive is a trusted
    MinerU artifact, not a user upload."""
    target_root = target_dir.resolve()
    total = 0
    try:
        if len(archive_bytes) > _MAX_TOTAL_BYTES:
            raise MinerUError("云端 ZIP 文件超过上限。", code="cloud_result_invalid")
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if len(members) > _MAX_ENTRIES:
                raise MinerUError("云端 ZIP 条目数超出上限。", code="cloud_result_invalid")
            for member in members:
                # Collapse to a POSIX-relative path and reject traversal.
                rel = Path(member.filename.replace("\\", "/"))
                if rel.is_absolute() or rel.drive or ".." in rel.parts or stat.S_ISLNK(member.external_attr >> 16):
                    raise MinerUError("云端 ZIP 包含不安全路径或符号链接。", code="cloud_result_invalid")
                dest = (target_root / rel).resolve()
                if target_root not in dest.parents and dest != target_root:
                    raise MinerUError("云端 ZIP 路径越界。", code="cloud_result_invalid")
                total += member.file_size
                if total > _MAX_TOTAL_BYTES:
                    raise MinerUError("云端 ZIP 解压体积超出上限。", code="cloud_result_invalid")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out, length=1024 * 1024)
    except zipfile.BadZipFile as exc:
        raise MinerUError("MinerU 返回的 ZIP 无效。", code="cloud_result_invalid") from exc


__all__ = ["parse_cloud", "verify_credentials"]
