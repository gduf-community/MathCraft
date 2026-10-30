"""Real subprocess regressions for document previews and text-only parsing."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import os
from pathlib import Path
import subprocess
import threading

import pytest

from MathCraft.runtime import isolated_worker
from MathCraft.runtime.isolated_worker import (
    IsolatedWorkerError,
    IsolatedWorkerTimeout,
    run_in_isolated_process,
    run_in_isolated_process_sync,
)
from MathCraft.services.parsing.engines.text_only.engine import TextOnlyParser
from MathCraft.services.parsing.types import ParserError
from MathCraft.utils.document_extractor import (
    CorruptDocumentError,
    DocumentTooLargeError,
    EmptyDocumentError,
    MAX_EXTRACTED_CHARS_PER_DOC,
    UnsupportedDocumentError,
    extract_text_from_path,
    extract_text_from_path_isolated,
)


@pytest.fixture
def source_path(tmp_path: Path, request: pytest.FixtureRequest) -> Path:
    path = tmp_path / f"中文 文档{request.param}"
    if request.param == ".pdf":
        import pymupdf

        with pymupdf.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "The derivative of x squared is 2x.")
            document.save(path)
    else:
        path.write_text("数学正文：The derivative of x squared is 2x.", encoding="utf-8")
    return path


@pytest.mark.parametrize("source_path", [".txt", ".pdf"], indirect=True)
async def test_preview_extracts_text_in_real_worker(source_path: Path) -> None:
    text = await extract_text_from_path_isolated(source_path)
    assert text == extract_text_from_path(source_path)
    assert "derivative" in text


@pytest.mark.parametrize("source_path", [".txt", ".pdf"], indirect=True)
def test_text_only_writes_markdown_in_real_worker(source_path: Path, tmp_path: Path) -> None:
    workdir = tmp_path / "输出 目录" / "nested"
    TextOnlyParser().parse(source_path, workdir, config={})
    text = (workdir / f"{source_path.stem}.md").read_text(encoding="utf-8")
    assert text == extract_text_from_path(source_path)
    assert "derivative" in text


async def test_preview_preserves_filename_hint_and_limits(tmp_path: Path) -> None:
    path = tmp_path / "0123456789abcdef"
    text = "中文数学正文 abcdefghijklmnopqrstuvwxyz"
    path.write_text(text, encoding="utf-8")
    kwargs = {"filename_hint": "逻辑名称.txt", "max_bytes": None, "max_chars": 8}
    result = await extract_text_from_path_isolated(path, **kwargs)
    assert result == extract_text_from_path(path, **kwargs)
    assert result.startswith(text[:8])
    assert "truncated" in result
    assert await extract_text_from_path_isolated(
        path, filename_hint="逻辑名称.txt", max_bytes=None, max_chars=None
    ) == text


def test_text_only_keeps_text_beyond_preview_limit(tmp_path: Path) -> None:
    path = tmp_path / "long.txt"
    text = "x" * (MAX_EXTRACTED_CHARS_PER_DOC + 1) + " end"
    path.write_text(text, encoding="utf-8")
    TextOnlyParser().parse(path, tmp_path / "parsed", config={})
    assert (tmp_path / "parsed" / "long.md").read_text(encoding="utf-8") == text


@pytest.mark.parametrize(
    ("filename", "data", "kwargs", "error_type"),
    [
        ("empty.txt", b"", {}, EmptyDocumentError),
        ("broken.pdf", b"not a pdf", {}, CorruptDocumentError),
        ("unsupported.unknown", b"body", {}, UnsupportedDocumentError),
        ("large.txt", b"body", {"max_bytes": 2}, DocumentTooLargeError),
        ("hash", b"", {"filename_hint": "原始名称.txt"}, EmptyDocumentError),
    ],
)
async def test_preview_restores_remote_document_errors(
    tmp_path: Path, filename: str, data: bytes, kwargs: dict, error_type: type[Exception]
) -> None:
    path = tmp_path / filename
    path.write_bytes(data)
    with pytest.raises(error_type) as direct:
        extract_text_from_path(path, **kwargs)
    with pytest.raises(error_type) as isolated:
        await extract_text_from_path_isolated(path, **kwargs)
    assert str(isolated.value) == str(direct.value)
    assert isolated.value.filename == direct.value.filename
    assert isinstance(isolated.value.__cause__, IsolatedWorkerError)


async def test_preview_restores_remote_filesystem_error(tmp_path: Path) -> None:
    with pytest.raises(OSError, match="missing.txt") as raised:
        await extract_text_from_path_isolated(tmp_path / "missing.txt")
    assert raised.value.__cause__.remote_type == "FileNotFoundError"


@pytest.mark.parametrize("filename", ["empty.txt", "broken.pdf", "missing.txt"])
def test_text_only_wraps_remote_failure_without_markdown(tmp_path: Path, filename: str) -> None:
    path = tmp_path / filename
    if filename != "missing.txt":
        path.write_bytes(b"" if filename == "empty.txt" else b"not a pdf")
    workdir = tmp_path / "failed"
    with pytest.raises(ParserError, match=filename) as raised:
        TextOnlyParser().parse(path, workdir, config={})
    assert isinstance(raised.value.__cause__, IsolatedWorkerError)
    assert not workdir.exists()


@pytest.mark.parametrize("source_path", [".txt", ".pdf"], indirect=True)
async def test_http_preview_uses_default_isolated_extractor(
    source_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import FastAPI
    import httpx

    from MathCraft.api.routers import knowledge

    def resolve_file(kb_name: str, filename: str) -> Path:
        assert kb_name == "worker-kb"
        assert filename == source_path.name
        return source_path

    assert knowledge.extract_text_from_path is knowledge._DEFAULT_EXTRACT_TEXT_FROM_PATH
    monkeypatch.setattr(knowledge, "_resolve_kb_raw_file_or_404", resolve_file)
    app = FastAPI()
    app.include_router(knowledge.router, prefix="/api")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get(
            f"/api/knowledge-bases/worker-kb/file-preview-text/{source_path.name}"
        )
    assert response.status_code == 200, response.text
    assert response.text == extract_text_from_path(source_path)
    assert response.headers["content-type"].startswith("text/plain")


async def test_workers_really_run_in_other_processes() -> None:
    sync_pid = run_in_isolated_process_sync("os:getpid")
    async_pid = await run_in_isolated_process("os:getpid")
    assert sync_pid != os.getpid()
    assert async_pid != os.getpid()


@pytest.mark.parametrize(
    ("callable_path", "args", "error_type"),
    [
        ("mathcraft_missing_test_module:run", (), "ModuleNotFoundError"),
        ("builtins:int", ("not-an-integer",), "ValueError"),
    ],
)
def test_worker_reports_import_and_execution_errors(
    callable_path: str, args: tuple, error_type: str
) -> None:
    with pytest.raises(IsolatedWorkerError) as raised:
        run_in_isolated_process_sync(callable_path, *args)
    assert raised.value.remote_type == error_type
    assert raised.value.remote_module == "builtins"
    assert "Traceback" in raised.value.remote_traceback


def test_worker_reports_result_serialization_error(tmp_path: Path) -> None:
    path = tmp_path / "readable.txt"
    path.write_text("body", encoding="utf-8")
    with pytest.raises(IsolatedWorkerError) as raised:
        run_in_isolated_process_sync("builtins:open", str(path))
    assert raised.value.remote_type == "TypeError"
    assert "pickle" in str(raised.value).lower()


@pytest.fixture
def worker_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # A child imports this helper through PYTHONPATH; no parent monkeypatches
    # or test-runner state need to survive a fresh interpreter.
    (tmp_path / "worker_regression_probe.py").write_text(
        "import os, time\n"
        "from pathlib import Path\n"
        "def block(signal):\n"
        "    Path(signal).write_text(str(os.getpid()), encoding='utf-8')\n"
        "    time.sleep(30)\n"
        "def fail():\n"
        "    error = ValueError('probe failure')\n"
        "    error.filename = '原始名称.txt'\n"
        "    error.callback = lambda: None\n"
        "    raise error\n",
        encoding="utf-8",
    )
    pythonpath = os.environ.get("PYTHONPATH", "")
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join(filter(None, [str(tmp_path), pythonpath])))
    return tmp_path / "worker-started"


def test_worker_omits_unserializable_error_attributes(worker_probe: Path) -> None:
    with pytest.raises(IsolatedWorkerError, match="probe failure") as raised:
        run_in_isolated_process_sync("worker_regression_probe:fail")
    assert raised.value.remote_attrs["filename"] == "原始名称.txt"
    assert "callback" not in raised.value.remote_attrs


@pytest.fixture
def worker_slot(monkeypatch: pytest.MonkeyPatch) -> threading.BoundedSemaphore:
    slot = threading.BoundedSemaphore(1)
    monkeypatch.setattr(isolated_worker, "_WORKER_SLOTS", slot)
    return slot


def test_sync_timeout_reaps_worker_and_releases_slot(
    monkeypatch: pytest.MonkeyPatch, worker_slot: threading.BoundedSemaphore
) -> None:
    processes: list[subprocess.Popen] = []
    original_popen = subprocess.Popen

    def start(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(subprocess, "Popen", start)
    with pytest.raises(IsolatedWorkerTimeout):
        run_in_isolated_process_sync("time:sleep", 30, timeout=1)
    assert len(processes) == 1
    assert processes[0].poll() is not None
    assert worker_slot.acquire(blocking=False)
    worker_slot.release()
    assert run_in_isolated_process_sync("os:getpid", timeout=5) != os.getpid()


@pytest.mark.parametrize("cancel", [False, True], ids=["timeout", "cancel"])
async def test_async_cleanup_reaps_worker_and_releases_slot(
    monkeypatch: pytest.MonkeyPatch,
    worker_probe: Path,
    worker_slot: threading.BoundedSemaphore,
    cancel: bool,
) -> None:
    processes: list[asyncio.subprocess.Process] = []
    original_start = asyncio.create_subprocess_exec

    async def start(*args, **kwargs):
        process = await original_start(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
    task = asyncio.create_task(
        run_in_isolated_process(
            "worker_regression_probe:block", str(worker_probe), timeout=10 if cancel else 1
        )
    )
    try:
        if cancel:
            async def wait_for_start() -> None:
                while not worker_probe.exists():
                    if task.done():
                        await task
                    await asyncio.sleep(0.01)

            await asyncio.wait_for(wait_for_start(), timeout=5)
            task.cancel()
        with pytest.raises(asyncio.CancelledError if cancel else IsolatedWorkerTimeout):
            await asyncio.wait_for(task, timeout=5)
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
    assert len(processes) == 1
    assert processes[0].returncode is not None
    assert worker_slot.acquire(blocking=False)
    worker_slot.release()
    assert await asyncio.wait_for(run_in_isolated_process("os:getpid"), timeout=5) != os.getpid()
