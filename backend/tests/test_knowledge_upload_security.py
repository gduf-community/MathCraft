"""Regression tests for upload transaction safety and raw-file serving headers."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
import zipfile

import pytest
from fastapi import HTTPException, UploadFile

from MathCraft.api.routers import knowledge


def _upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(file=BytesIO(content), filename=filename)


def test_failed_batch_preserves_existing_same_named_file(tmp_path: Path) -> None:
    target_dir = tmp_path / "raw"
    target_dir.mkdir()
    existing = target_dir / "notes.txt"
    existing.write_bytes(b"original material")

    with pytest.raises(HTTPException):
        knowledge._save_uploaded_files(
            [
                _upload("notes.txt", b"replacement material"),
                _upload("rejected.exe", b"this must fail"),
            ],
            target_dir,
            allowed_extensions={".txt", ".zip"},
        )

    assert existing.read_bytes() == b"original material"
    assert not (target_dir / "rejected.exe").exists()


def test_failed_zip_batch_preserves_existing_same_named_file(tmp_path: Path) -> None:
    target_dir = tmp_path / "raw"
    target_dir.mkdir()
    existing = target_dir / "notes.txt"
    existing.write_bytes(b"original material")

    archive_data = BytesIO()
    with zipfile.ZipFile(
        archive_data, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9
    ) as archive:
        archive.writestr("notes.txt", b"replacement material")
        # This entry trips the extractor's compression-ratio guard after the
        # same-named file has already been written to the staging directory.
        archive.writestr("suspicious.txt", b"a" * (512 * 1024))

    with pytest.raises(HTTPException):
        knowledge._save_uploaded_files(
            [_upload("bundle.zip", archive_data.getvalue())],
            target_dir,
            allowed_extensions={".txt", ".zip"},
        )

    assert existing.read_bytes() == b"original material"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "disposition"),
    [
        ("unsafe.html", "attachment"),
        ("unsafe.htm", "attachment"),
        ("unsafe.svg", "attachment"),
        ("unsafe.xhtml", "attachment"),
        ("document.pdf", "inline"),
        ("document.txt", "inline"),
    ],
)
async def test_raw_file_response_blocks_active_content_inline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    disposition: str,
) -> None:
    target = tmp_path / filename
    target.write_text("content", encoding="utf-8")
    monkeypatch.setattr(
        knowledge,
        "_resolve_kb_raw_file_or_404",
        lambda kb_name, requested: target,
    )

    response = await knowledge.serve_kb_raw_file("test-kb", filename)

    assert response.headers["content-disposition"].startswith(f"{disposition};")
    assert response.headers["x-content-type-options"] == "nosniff"
