"""文档上传、异步入库、状态轮询、检索测试、OCR 路径测试。"""
import io
import json
import re
from dataclasses import dataclass, field
from threading import get_ident
from types import SimpleNamespace
from unittest.mock import Mock

import pymupdf as fitz
import pytest

from app import local_secrets
from app.config import settings
from app.models import Document, DocumentChunk
from app.services import knowledge_simplify, mineru
from app.services.parsing import ocr_textbook
from app.services.rag import llm, vectorstore
from conftest import create_bank, upload_markdown


def _make_pdf(with_text: bool) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    if with_text:
        page.insert_text(
            (72, 72),
            "Derivative definition and rules. " * 6,
            fontsize=12,
        )
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


@dataclass
class _SimplifyProbe:
    """记录简化管线对 LLM 的调用。"""

    keys: list[str | None] = field(default_factory=list)
    calls: list[tuple[str | None, str, tuple[str, ...], int]] = field(default_factory=list)


def _ocr_markdown(marker: str) -> str:
    return f"# 第一章 {marker}\n\n" + "\n\n".join(
        f"## 第{i}节 定义\n\n导数是差商的极限，描述函数的瞬时变化率。"
        for i in range(1, 6)
    )


@pytest.fixture
def simplify_probe(monkeypatch) -> _SimplifyProbe:
    probe = _SimplifyProbe()

    def fake_get_client(api_key=None):
        probe.keys.append(api_key)

        def fake_create(**kwargs):
            prompt = kwargs["messages"][-1]["content"]
            if kwargs.get("response_format"):
                match = re.search(r"^# (第一章 .+)$", prompt, re.M)
                assert match is not None, "目录请求必须包含 OCR 结果"
                chapter = match.group(1)
                probe.calls.append((api_key, chapter, (), get_ident()))
                content = json.dumps({"chapters": [{
                    "title": chapter,
                    "sections": [
                        {"title": f"第{i}节 定义", "points": ["差商极限"]}
                        for i in range(1, 6)
                    ],
                }]}, ensure_ascii=False)
            else:
                chapter_data = json.loads(
                    prompt.split("目录结构：", 1)[1].split("\n\n正文：", 1)[0],
                )
                chapter = chapter_data["title"]
                sections = tuple(section["title"] for section in chapter_data["sections"])
                probe.calls.append((api_key, chapter, sections, get_ident()))
                content = "\n\n".join(
                    f"### {title}\n\n#### 差商极限\n\n本节概括：导数描述瞬时变化率。"
                    for title in sections
                    if len(sections) == 1 or title != "第2节 定义"
                )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=None,
            )

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))

    monkeypatch.setattr(llm, "get_client", fake_get_client)
    return probe


def test_simplify_missing_section_retry_keeps_personal_key(simplify_probe):
    """目录、并发概括及漏节补写全部使用同一次调用的个人 Key。"""
    key = "fake-missing-section-personal-key"
    markdown, _ = knowledge_simplify.build_simplified_markdown(
        _ocr_markdown("漏节补写"), api_key=key,
    )
    assert simplify_probe.keys
    assert set(simplify_probe.keys) == {key}
    assert any(not call[2] for call in simplify_probe.calls)
    assert any(len(call[2]) > 1 for call in simplify_probe.calls)
    repairs = [call for call in simplify_probe.calls if call[2] == ("第2节 定义",)]
    assert len(repairs) == 1, "假响应故意遗漏的节必须真正触发补写"
    assert repairs[0][3] == get_ident(), "补写需覆盖并发概括之外的调用路径"
    assert "### 第2节 定义\n\n#### 差商极限\n\n本节概括：" in markdown
    assert "本节内容未能生成" not in markdown


def test_upload_markdown_and_ready(client, teacher):
    bank = create_bank(client, teacher)
    doc = upload_markdown(client, teacher, bank["id"])

    resp = client.get(f"/api/banks/{bank['id']}/documents/{doc['document_id']}", headers=teacher)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["stage"] == "入库完成"
    assert data["chunk_count"] > 0
    assert data["progress"] == 100
    assert data["is_scanned"] is False
    assert data["ocr_status"] == "not_needed"

    listing = client.get(f"/api/banks/{bank['id']}/documents", headers=teacher).json()
    assert len(listing) == 1
    assert listing[0]["id"] == doc["document_id"]


def test_document_status_and_reprocess(client, teacher):
    bank = create_bank(client, teacher)
    doc = upload_markdown(client, teacher, bank["id"])
    doc_id = doc["document_id"]

    resp = client.post(f"/api/banks/{bank['id']}/documents/{doc_id}/reprocess", headers=teacher)
    assert resp.status_code == 202
    status = client.get(f"/api/banks/{bank['id']}/documents/{doc_id}", headers=teacher).json()
    assert status["status"] == "ready"
    assert status["chunk_count"] > 0


def test_download_document_permissions(client, teacher, student):
    bank = create_bank(client, teacher)
    doc = upload_markdown(client, teacher, bank["id"])
    url = f"/api/banks/{bank['id']}/documents/{doc['document_id']}/download"

    assert client.get(url, headers=teacher).status_code == 200
    assert client.get(url, headers=student).status_code in (403, 404)


def test_delete_document(client, teacher):
    bank = create_bank(client, teacher)
    doc = upload_markdown(client, teacher, bank["id"])
    assert client.delete(
        f"/api/banks/{bank['id']}/documents/{doc['document_id']}", headers=teacher
    ).status_code == 204
    assert client.get(
        f"/api/banks/{bank['id']}/documents/{doc['document_id']}", headers=teacher
    ).status_code == 404


def test_reject_unsupported_format(client, teacher):
    bank = create_bank(client, teacher)
    resp = client.post(
        f"/api/banks/{bank['id']}/documents",
        files={"file": ("bad.exe", b"MZ", "application/octet-stream")},
        headers=teacher,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "UNSUPPORTED_FORMAT"


def test_upload_txt_document(client, teacher):
    """TXT 文档可直接上传并完成解析入库。"""
    bank = create_bank(client, teacher)
    content = "极限的定义\n\n当 x 趋于 0 时，sin(x)/x 趋于 1。这是重要极限。".encode("utf-8")
    resp = client.post(
        f"/api/banks/{bank['id']}/documents",
        files={"file": ("notes.txt", content, "text/plain")},
        headers=teacher,
    )
    assert resp.status_code == 202, resp.text
    doc_id = resp.json()["document_id"]
    doc = client.get(f"/api/banks/{bank['id']}/documents/{doc_id}", headers=teacher).json()
    assert doc["format"] == "TXT"
    assert doc["status"] == "ready"
    assert doc["chunk_count"] >= 1


def test_search_sparse_and_dense(client, teacher):
    bank = create_bank(client, teacher)
    upload_markdown(client, teacher, bank["id"])

    sparse = client.post(
        f"/api/banks/{bank['id']}/search",
        json={"query": "隐函数求导", "mode": "sparse", "top_k": 3},
        headers=teacher,
    )
    assert sparse.status_code == 200
    assert sparse.json()["results"], "FTS5 中文稀疏检索应命中"

    dense = client.post(
        f"/api/banks/{bank['id']}/search",
        json={"query": "导数定义", "mode": "dense", "top_k": 3},
        headers=teacher,
    )
    assert dense.status_code == 200
    assert dense.json()["results"]


def test_search_hybrid_rerank(client, teacher):
    bank = create_bank(client, teacher)
    upload_markdown(client, teacher, bank["id"])

    resp = client.post(
        f"/api/banks/{bank['id']}/search",
        json={"query": "隐函数求导", "mode": "hybrid_rerank", "top_k": 3},
        headers=teacher,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["reranked"], "混合检索重排结果不应为空"
    assert len(data["reranked"]) <= 3
    assert data["sparse"], "稀疏结果不应为空"


def test_scanned_pdf_detection():
    import tempfile
    from pathlib import Path

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(_make_pdf(False))
        blank = Path(f.name)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(_make_pdf(True))
        text = Path(f.name)

    assert mineru.detect_scanned_pdf(blank)[0] is True
    assert mineru.detect_scanned_pdf(text)[0] is False
    blank.unlink(missing_ok=True)
    text.unlink(missing_ok=True)


_RAW_OCR_TEXT = "青岚曲线在原点的切线斜率等于七。"
_RAW_OCR_MARKDOWN = f"# OCR 结果\n\n{_RAW_OCR_TEXT}"


def test_ocr_textbook_preserves_source_locations_across_parts(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr_textbook, "_plan_parts", lambda page_count: [(0, 15), (15, 32)])
    first = tmp_path / "part_00"
    second = tmp_path / "part_01"
    first.mkdir()
    (second / "images").mkdir(parents=True)
    (second / "images" / "curve.png").touch()
    (first / "scan_content_list.json").write_text(json.dumps([
        {"type": "text", "page_idx": 14, "text": "第一章 导数", "text_level": 1},
    ]), encoding="utf-8")
    (second / "scan_content_list.json").write_text(json.dumps([
        {"type": "equation", "page_idx": 0, "text": "f'(x) = 2x", "bbox": [1, 2, 30, 40]},
        {
            "type": "image", "page_idx": 0, "img_path": "images/curve.png",
            "image_caption": ["抛物线"], "bbox": [5, 45, 70, 90],
        },
        {"type": "text", "page_idx": 1, "text": "切线的斜率随横坐标变化。"},
    ]), encoding="utf-8")

    heading, illustrated, next_page = ocr_textbook.parse_ocr_textbook("备用正文", tmp_path, 32)

    assert heading.text == "第一章 导数"
    assert heading.meta["source_locations"] == [{"page": 15, "kind": "text"}]
    assert illustrated.text == "f'(x) = 2x\n\n抛物线"
    assert illustrated.meta["section"] == heading.text
    equation, figure = illustrated.meta["source_locations"]
    assert equation == {"page": 16, "kind": "equation", "bbox": [1, 2, 30, 40]}
    asset_ref = figure["asset_ref"]
    assert re.fullmatch(r"[0-9a-f]{24}", asset_ref)
    assert figure == {
        "page": 16, "kind": "image", "bbox": [5, 45, 70, 90], "asset_ref": asset_ref,
    }
    assert next_page.text == "切线的斜率随横坐标变化。"
    assert next_page.meta["source_locations"] == [{"page": 17, "kind": "text"}]


@pytest.fixture
def scan_ingestion(monkeypatch):
    def extract(token, file_path, result_dir, on_progress=None):
        with fitz.open(file_path) as pdf:
            identity = mineru._cache_identity(file_path, pdf.page_count)
        mineru._publish_markdown(result_dir, _RAW_OCR_MARKDOWN, identity)
        return _RAW_OCR_MARKDOWN, result_dir

    ocr = Mock(side_effect=extract)
    simplify = Mock(side_effect=AssertionError("扫描件入库不应调用知识点简化"))
    monkeypatch.setattr(mineru, "extract_pdf", ocr)
    monkeypatch.setattr(knowledge_simplify, "build_simplified_markdown", simplify)
    monkeypatch.setattr(vectorstore, "add_chunks", Mock())
    monkeypatch.setattr(vectorstore, "delete_document_chunks", Mock())
    return ocr, simplify


def _upload_scan(client, headers, pdf, *, new_bank=False):
    upload_url = "/api/banks/with-document"
    if not new_bank:
        bank_id = create_bank(client, headers)["id"]
        upload_url = f"/api/banks/{bank_id}/documents"
    response = client.post(
        upload_url,
        data={"name": "扫描件题库"} if new_bank else {},
        files={"file": ("scan.pdf", pdf, "application/pdf")},
        headers=headers,
    )
    assert response.status_code == (201 if new_bank else 202), response.text
    data = response.json()
    if new_bank:
        bank_id = data["bank"]["id"]
        data = data["document"]
    return bank_id, data["document_id"]


def _assert_raw_ocr_indexed_as_pdf(client, headers, db, bank_id, document_id, pdf):
    url = f"/api/banks/{bank_id}/documents/{document_id}"
    response = client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["status"] == "ready", data
    assert data["is_scanned"] is True
    assert data["ocr_status"] == "done"
    assert data["page_count"] == 1
    assert data["format"] == "PDF"
    assert data["name"] == "scan.pdf"
    assert data["size_bytes"] == len(pdf)

    chunks = db.query(DocumentChunk).filter_by(document_id=document_id).all()
    assert data["chunk_count"] == len(chunks)
    assert any(_RAW_OCR_TEXT in chunk.text for chunk in chunks)

    downloaded = client.get(f"{url}/download", headers=headers)
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/pdf"
    assert downloaded.content == pdf


@pytest.mark.parametrize("new_bank", [False, True], ids=["existing-bank", "first-document"])
def test_scanned_pdf_indexes_raw_ocr(client, teacher, db, scan_ingestion, new_bank):
    ocr, simplify = scan_ingestion
    pdf = _make_pdf(False)
    bank_id, document_id = _upload_scan(client, teacher, pdf, new_bank=new_bank)

    ocr.assert_called_once()
    simplify.assert_not_called()
    _assert_raw_ocr_indexed_as_pdf(client, teacher, db, bank_id, document_id, pdf)


@pytest.mark.parametrize("legacy", [False, True], ids=["pdf", "legacy-simplified-markdown"])
def test_scanned_pdf_reprocess_reuses_ocr_without_token(
    client, teacher, db, monkeypatch, scan_ingestion, legacy,
):
    ocr, simplify = scan_ingestion
    pdf = _make_pdf(False)
    bank_id, document_id = _upload_scan(client, teacher, pdf)
    ocr.assert_called_once()
    cached_ocr = settings.ocr_path() / document_id / "full.md"
    assert cached_ocr.read_text(encoding="utf-8") == _RAW_OCR_MARKDOWN

    if legacy:
        old_markdown = settings.upload_path() / bank_id / f"{document_id}_simplified.md"
        old_markdown.write_text("# 旧知识点简化版", encoding="utf-8")
        doc = db.get(Document, document_id)
        doc.format = "MD"
        doc.name = "scan_知识点简化版.md"
        doc.storage_path = old_markdown.as_posix()
        doc.size_bytes = old_markdown.stat().st_size
        db.commit()

    previous_ids = {chunk.id for chunk in db.query(DocumentChunk).filter_by(document_id=document_id)}
    assert previous_ids
    monkeypatch.setattr(local_secrets, "MINERU_DEFAULT_TOKEN", "")
    url = f"/api/banks/{bank_id}/documents/{document_id}"
    response = client.post(f"{url}/reprocess", headers=teacher)

    assert response.status_code == 202, response.text
    ocr.assert_called_once()
    simplify.assert_not_called()
    _assert_raw_ocr_indexed_as_pdf(client, teacher, db, bank_id, document_id, pdf)
    rebuilt_ids = {chunk.id for chunk in db.query(DocumentChunk).filter_by(document_id=document_id)}
    assert previous_ids.isdisjoint(rebuilt_ids)
