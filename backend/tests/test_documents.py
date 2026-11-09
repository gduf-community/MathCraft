"""文档上传、异步入库、状态轮询、检索测试、OCR 路径测试。"""
import io

import pymupdf as fitz

from app.services import knowledge_simplify, mineru
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


def test_scanned_pdf_uses_mineru(client, teacher, monkeypatch):
    """扫描件走 MinerU OCR：打桩 extract_pdf，验证状态机走 ocr 并最终 ready。"""
    bank = create_bank(client, teacher)

    def fake_extract(token, file_path, result_dir, on_progress=None):
        result_dir.mkdir(parents=True, exist_ok=True)
        md = result_dir / "full.md"
        md.write_text("# OCR 结果\n\n导数的定义与求导法则。", encoding="utf-8")
        return md.read_text(encoding="utf-8"), result_dir

    def fake_simplify(markdown, source_name="教材", on_progress=None):
        return ("# 《scan》知识点简化版\n\n## 第一章 函数与极限\n\n"
                "### 第一节 映射与函数\n\n映射由定义域、目标集和对应法则确定。\n"), {}

    monkeypatch.setattr(mineru, "extract_pdf", fake_extract)
    monkeypatch.setattr(knowledge_simplify, "build_simplified_markdown", fake_simplify)

    pdf = _make_pdf(False)
    resp = client.post(
        f"/api/banks/{bank['id']}/documents",
        files={"file": ("scan.pdf", pdf, "application/pdf")},
        headers=teacher,
    )
    assert resp.status_code == 202
    doc_id = resp.json()["document_id"]

    data = client.get(f"/api/banks/{bank['id']}/documents/{doc_id}", headers=teacher).json()
    assert data["is_scanned"] is True
    assert data["ocr_status"] == "done"
    assert data["status"] == "ready"
    assert data["chunk_count"] > 0
    assert data["page_count"] == 1
