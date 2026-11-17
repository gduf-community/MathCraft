"""用真实 PDF、假 HTTP 和文件故障验证 OCR 缓存不会复用半成品。"""

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.services import mineru
from app.services.rag import vectorstore
from conftest import create_bank
from test_mineru import (
    _FAKE_TOKEN,
    _MineruServer,
    _make_pdf,
    _result_markdown,
    mineru_server,
)


def test_unmarked_part_is_reprocessed(
    tmp_path: Path, mineru_server: _MineruServer,
) -> None:
    """中断遗留的非空分片不能仅凭文件存在被当成完成结果。"""
    source = tmp_path / "fake-scan.pdf"
    source.write_bytes(_make_pdf(201))
    result_dir = tmp_path / "ocr"
    partial = result_dir / "part_00" / "full.md"
    partial.parent.mkdir(parents=True)
    partial.write_text("# Interrupted", encoding="utf-8")
    mineru_server.fail_parse = False

    markdown, _ = mineru.extract_pdf(_FAKE_TOKEN, source, result_dir)

    assert mineru_server.submitted == [f"part_{i:02d}.pdf" for i in range(8)]
    assert markdown == "\n\n".join(_result_markdown(i) for i in range(8))


@pytest.mark.parametrize("failure_point", ["fsync", "content", "manifest"])
def test_interrupted_part_publication_retries_only_uncommitted_parts(
    tmp_path: Path, mineru_server: _MineruServer, monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    """落盘及两次替换任一处失败后，不复用半成品，保留已完成分片供重试。"""
    source = tmp_path / "fake-scan.pdf"
    source.write_bytes(_make_pdf(201))
    result_dir = tmp_path / "ocr"
    mineru_server.fail_parse = False
    original_replace = os.replace
    original_fsync = os.fsync
    synced: set[int] = set()

    def sync(fd: int) -> None:
        if failure_point == "fsync":
            raise OSError("injected disk sync failure")
        original_fsync(fd)
        synced.add(os.fstat(fd).st_ino)

    def replace(src: str | Path, dst: str | Path) -> None:
        destination = Path(dst)
        temporary = Path(src)
        assert temporary.parent == destination.parent
        assert temporary.stat().st_ino in synced
        if destination.parent.name == "part_04" and destination.name == (
            "full.manifest.json" if failure_point == "manifest" else "full.md"
        ):
            raise OSError("injected atomic replacement failure")
        original_replace(src, dst)

    with monkeypatch.context() as fault:
        fault.setattr(os, "fsync", sync)
        fault.setattr(os, "replace", replace)
        with pytest.raises(OSError, match="injected"):
            mineru.extract_pdf(_FAKE_TOKEN, source, result_dir)

    assert not (result_dir / "full.md").exists()
    assert not (result_dir / "part_04" / "full.manifest.json").exists()
    assert not list(result_dir.rglob("*.tmp"))
    if failure_point == "content":
        assert not (result_dir / "part_04" / "full.md").exists()

    markdown, _ = mineru.extract_pdf(_FAKE_TOKEN, source, result_dir)
    expected_pending = range(8) if failure_point == "fsync" else range(5)
    assert mineru_server.submitted == [f"part_{i:02d}.pdf" for i in expected_pending]
    assert markdown == "\n\n".join(_result_markdown(i) for i in range(8))


@pytest.mark.parametrize("failure_point", ["content", "manifest"])
def test_failed_merge_can_resume_without_redownloading_completed_parts(
    tmp_path: Path, mineru_server: _MineruServer, monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    """整本发布失败时不报告有效全文，重试使用已完成分片恢复全文。"""
    source = tmp_path / "fake-scan.pdf"
    source.write_bytes(_make_pdf(201))
    result_dir = tmp_path / "ocr"
    mineru_server.fail_parse = False
    original_replace = os.replace

    def replace(src: str | Path, dst: str | Path) -> None:
        destination = Path(dst)
        if destination.parent == result_dir and destination.name == (
            "full.md" if failure_point == "content" else "full.manifest.json"
        ):
            raise OSError("injected merge publication failure")
        original_replace(src, dst)

    with monkeypatch.context() as fault:
        fault.setattr(os, "replace", replace)
        with pytest.raises(OSError, match="injected"):
            mineru.extract_pdf(_FAKE_TOKEN, source, result_dir)

    assert mineru.read_cached_markdown(source, result_dir) is None
    requests_before = len(mineru_server.requests)
    markdown, _ = mineru.extract_pdf(_FAKE_TOKEN, source, result_dir)
    assert len(mineru_server.requests) == requests_before
    assert mineru.read_cached_markdown(source, result_dir) == markdown


@pytest.mark.parametrize("damage", ["truncated", "same-length", "range", "part-index"])
def test_damaged_part_is_reprocessed_without_discarding_other_parts(
    tmp_path: Path, mineru_server: _MineruServer, damage: str,
) -> None:
    """长度、哈希与页范围任一不匹配，都只重做受损片，避免误拼接全文。"""
    source = tmp_path / "fake-scan.pdf"
    source.write_bytes(_make_pdf(201))
    result_dir = tmp_path / "ocr"
    mineru_server.fail_parse = False
    mineru.extract_pdf(_FAKE_TOKEN, source, result_dir)
    part = result_dir / "part_04" / "full.md"
    if damage in ("truncated", "same-length"):
        content = part.read_bytes()
        part.write_bytes(content[:3] if damage == "truncated" else b"x" * len(content))
    else:
        path = part.with_name("full.manifest.json")
        manifest = json.loads(path.read_bytes())
        manifest["identity"]["page_start" if damage == "range" else "part_index"] = 0
        path.write_text(json.dumps(manifest), encoding="utf-8")

    markdown, _ = mineru.extract_pdf(_FAKE_TOKEN, source, result_dir)

    assert mineru_server.submitted == ["part_04.pdf"]
    assert markdown == "\n\n".join(_result_markdown(i) for i in range(8))


@pytest.mark.parametrize("damage", ["unmarked", "truncated", "same-length", "source", "model"])
def test_full_cache_is_reused_only_for_matching_complete_content(
    tmp_path: Path, mineru_server: _MineruServer, monkeypatch: pytest.MonkeyPatch,
    damage: str,
) -> None:
    """整本缓存命中须满足完成标记、内容及来源一致，并保留正常重复调用复用。"""
    source = tmp_path / "fake-scan.pdf"
    source.write_bytes(_make_pdf(1))
    result_dir = tmp_path / "ocr"
    mineru_server.fail_parse = False
    markdown, _ = mineru.extract_pdf(_FAKE_TOKEN, source, result_dir)
    requests_before = len(mineru_server.requests)
    assert mineru.read_cached_markdown(source, result_dir) == markdown
    assert mineru.extract_pdf(_FAKE_TOKEN, source, result_dir)[0] == markdown
    assert len(mineru_server.requests) == requests_before

    part = result_dir / "full.md"
    if damage == "unmarked":
        (result_dir / "full.manifest.json").unlink()
    elif damage in ("truncated", "same-length"):
        content = part.read_bytes()
        part.write_bytes(content[:3] if damage == "truncated" else b"x" * len(content))
    elif damage == "source":
        source.write_bytes(_make_pdf(1))
    else:
        monkeypatch.setattr(mineru, "MODEL_VERSION", "fake-other-model")

    assert mineru.read_cached_markdown(source, result_dir) is None
    assert mineru.extract_pdf(_FAKE_TOKEN, source, result_dir)[0] == markdown
    assert len(mineru_server.requests) > requests_before


def test_document_reprocess_does_not_bypass_manifest_validation(
    client: TestClient, teacher: dict[str, str], monkeypatch: pytest.MonkeyPatch,
    mineru_server: _MineruServer,
) -> None:
    """入库入口也拒绝旧全文缓存，重试仍执行 OCR 而非处理截断正文。"""
    monkeypatch.setattr(vectorstore, "delete_document_chunks", lambda *args, **kwargs: None)
    saved = client.put(
        "/api/users/me/model-settings", headers=teacher, json={"mineru_token": _FAKE_TOKEN},
    )
    assert saved.status_code == 200
    bank = create_bank(client, teacher)
    uploaded = client.post(
        f"/api/banks/{bank['id']}/documents", headers=teacher,
        files={"file": ("fake-scan.pdf", _make_pdf(1), "application/pdf")},
    )
    assert uploaded.status_code == 202
    document_id = uploaded.json()["document_id"]
    assert mineru_server.poll_count == 1
    cached = settings.ocr_path() / document_id / "full.md"
    cached.write_text("# Interrupted full result", encoding="utf-8")

    retried = client.post(
        f"/api/banks/{bank['id']}/documents/{document_id}/reprocess", headers=teacher,
    )

    assert retried.status_code == 202
    assert mineru_server.poll_count == 2
    response = client.get(f"/api/banks/{bank['id']}/documents/{document_id}", headers=teacher)
    assert response.json()["status"] == "failed"
    assert response.json()["ocr_status"] == "failed"
