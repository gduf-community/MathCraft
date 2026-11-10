"""文档上传、异步入库、状态轮询、检索测试、OCR 路径测试。"""
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Barrier, get_ident
from types import SimpleNamespace

import httpx
import openai
import pymupdf as fitz
import pytest

from app.config import settings
from app.services import knowledge_simplify, mineru
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
    """记录外部服务边界，保留 API、后台任务与简化管线的真实行为。"""

    keys: list[str] = field(default_factory=list)
    calls: list[tuple[str, str, tuple[str, ...], int]] = field(default_factory=list)
    ocr_documents: list[str] = field(default_factory=list)
    rejected_keys: set[str] = field(default_factory=set)
    summary_barrier: Barrier | None = None
    omit_second_section: bool = False


def _ocr_markdown(marker: str) -> str:
    return f"# 第一章 {marker}\n\n" + "\n\n".join(
        f"## 第{i}节 定义\n\n导数是差商的极限，描述函数的瞬时变化率。"
        for i in range(1, 6)
    )


@pytest.fixture
def simplify_probe(monkeypatch) -> _SimplifyProbe:
    """只替换 OCR、LLM 客户端和向量存储，不替换简化辅助函数。"""
    probe = _SimplifyProbe()
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    monkeypatch.setattr(vectorstore, "add_chunks", lambda *args, **kwargs: None)
    monkeypatch.setattr(vectorstore, "delete_document_chunks", lambda *args, **kwargs: None)

    def fake_extract(token, file_path, result_dir, on_progress=None):
        probe.ocr_documents.append(file_path.stem)
        result_dir.mkdir(parents=True, exist_ok=True)
        markdown = _ocr_markdown(file_path.stem)
        (result_dir / "full.md").write_text(markdown, encoding="utf-8")
        return markdown, result_dir

    def fake_get_client(api_key=None):
        key = api_key or settings.deepseek_api_key
        probe.keys.append(key)
        if not key or key in probe.rejected_keys:
            raise openai.AuthenticationError(
                "测试服务拒绝空值或指定假 Key",
                response=httpx.Response(
                    401, request=httpx.Request("POST", "https://llm.example.test/completions"),
                ),
                body={"error": "test-only-invalid-key"},
            )

        def fake_create(**kwargs):
            prompt = kwargs["messages"][-1]["content"]
            if kwargs.get("response_format"):
                match = re.search(r"^# (第一章 .+)$", prompt, re.M)
                assert match is not None, "目录请求必须包含 OCR 结果"
                chapter = match.group(1)
                probe.calls.append((key, chapter, (), get_ident()))
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
                probe.calls.append((key, chapter, sections, get_ident()))
                if probe.summary_barrier is not None:
                    probe.summary_barrier.wait(timeout=10)
                content = "\n\n".join(
                    f"### {title}\n\n#### 差商极限\n\n本节概括：导数描述瞬时变化率。"
                    for title in sections
                    if not (probe.omit_second_section and len(sections) > 1
                            and title == "第2节 定义")
                )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=None,
            )

        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create)))

    monkeypatch.setattr(mineru, "extract_pdf", fake_extract)
    monkeypatch.setattr(llm, "get_client", fake_get_client)
    return probe


def _save_deepseek_key(client, headers: dict[str, str], key: str) -> None:
    response = client.put(
        "/api/users/me/model-settings", json={"deepseek_api_key": key}, headers=headers,
    )
    assert response.status_code == 200, response.text


def _upload_scan(client, headers: dict[str, str], *, new_bank: bool = False,
                 bank_id: str | None = None) -> tuple[str, str]:
    if not new_bank and bank_id is None:
        bank_id = create_bank(client, headers)["id"]
    response = client.post(
        "/api/banks/with-document" if new_bank else f"/api/banks/{bank_id}/documents",
        data={"name": "凭据回归题库"} if new_bank else {},
        files={"file": ("scan.pdf", _make_pdf(False), "application/pdf")},
        headers=headers,
    )
    assert response.status_code == (201 if new_bank else 202), response.text
    data = response.json()
    if new_bank:
        return data["bank"]["id"], data["document"]["document_id"]
    return bank_id, data["document_id"]


def _assert_simplified_ready(client, headers: dict[str, str], bank_id: str,
                             document_id: str) -> None:
    url = f"/api/banks/{bank_id}/documents/{document_id}"
    response = client.get(url, headers=headers)
    assert response.status_code == 200, response.text
    document = response.json()
    assert document["status"] == "ready", document
    assert document["format"] == "MD", document
    assert document["ocr_status"] == "done", document
    assert document["chunk_count"] > 0
    downloaded = client.get(f"{url}/download", headers=headers)
    assert downloaded.status_code == 200, downloaded.text
    assert "知识点简化版" in downloaded.text
    assert "本节概括：" in downloaded.text, "不能用 OCR 原文回退冒充简化成功"


@pytest.mark.parametrize("new_bank", [False, True], ids=["existing-bank", "first-document"])
def test_scanned_pdf_personal_deepseek_key_without_server_key(
    client, teacher, simplify_probe, new_bank,
):
    """两种上传入口都能在服务端无 Key 时使用已保存的个人 Key。"""
    key = "fake-personal-deepseek-key-for-tests-only"
    _save_deepseek_key(client, teacher, key)
    bank_id, document_id = _upload_scan(client, teacher, new_bank=new_bank)
    assert simplify_probe.keys, "测试必须执行到真实 simplify 的 llm.get_client"
    assert set(simplify_probe.keys) == {key}, "OCR 后简化必须使用操作者的个人 Key"
    _assert_simplified_ready(client, teacher, bank_id, document_id)


@pytest.mark.parametrize("new_bank", [False, True], ids=["existing-bank", "first-document"])
@pytest.mark.parametrize("personal_key", ["fake-personal-priority-key", ""],
                         ids=["personal-priority", "server-fallback"])
def test_scanned_pdf_deepseek_key_priority(
    client, teacher, monkeypatch, simplify_probe, new_bank, personal_key,
):
    """服务端非空时，上传与首文档入口仍遵守个人优先、服务端兜底。"""
    server_key = "fake-server-fallback-key"
    monkeypatch.setattr(settings, "deepseek_api_key", server_key)
    _save_deepseek_key(client, teacher, personal_key)
    bank_id, document_id = _upload_scan(client, teacher, new_bank=new_bank)
    assert simplify_probe.keys
    assert set(simplify_probe.keys) == {personal_key or server_key}
    _assert_simplified_ready(client, teacher, bank_id, document_id)


@pytest.mark.parametrize("editor_key", ["fake-editor-current-key", ""],
                         ids=["editor-personal", "editor-server-fallback"])
def test_scanned_pdf_cached_ocr_reprocess_uses_current_editor(
    client, teacher, student, monkeypatch, simplify_probe, editor_key,
):
    """上传者简化鉴权失败后，另一 editor 复用 OCR 并使用自己的有效 Key 重试。"""
    server_key = "fake-server-reprocess-key"
    uploader_key = "fake-uploader-rejected-key"
    monkeypatch.setattr(settings, "deepseek_api_key", server_key)
    simplify_probe.rejected_keys.add(uploader_key)
    _save_deepseek_key(client, teacher, uploader_key)
    _save_deepseek_key(client, student, editor_key)
    bank_id, document_id = _upload_scan(client, teacher)
    url = f"/api/banks/{bank_id}/documents/{document_id}"
    failed = client.get(url, headers=teacher).json()
    assert failed["status"] == "failed", failed
    assert failed["ocr_status"] == "done", failed
    assert simplify_probe.keys == [uploader_key]
    assert simplify_probe.ocr_documents == [document_id]
    cached_ocr = settings.ocr_path() / document_id / "full.md"
    assert cached_ocr.exists()
    cached_content = cached_ocr.read_text(encoding="utf-8")
    added = client.post(
        f"/api/banks/{bank_id}/members",
        json={"account": "student", "role": "editor"}, headers=teacher,
    )
    assert added.status_code == 201, added.text
    simplify_probe.keys.clear()
    response = client.post(f"{url}/reprocess", headers=student)
    assert response.status_code == 202, response.text
    assert simplify_probe.keys
    assert set(simplify_probe.keys) == {editor_key or server_key}
    assert simplify_probe.ocr_documents == [document_id], "已有 OCR 不应再次调用 MinerU"
    assert cached_ocr.read_text(encoding="utf-8") == cached_content
    _assert_simplified_ready(client, student, bank_id, document_id)


def test_scanned_pdf_concurrent_users_keep_summary_keys_isolated(
    client, teacher, student, simplify_probe,
):
    """两名操作者同时上传，四个真实概括线程交错执行也不能串 Key。"""
    teacher_key, student_key = "fake-concurrent-teacher-key", "fake-concurrent-student-key"
    _save_deepseek_key(client, teacher, teacher_key)
    _save_deepseek_key(client, student, student_key)
    bank_id = create_bank(client, teacher)["id"]
    added = client.post(
        f"/api/banks/{bank_id}/members",
        json={"account": "student", "role": "editor"}, headers=teacher,
    )
    assert added.status_code == 201, added.text
    # 五节正文自然拆为两批；四方屏障保证两个用户的概括真正同时在途。
    simplify_probe.summary_barrier = Barrier(4)
    with ThreadPoolExecutor(max_workers=2) as pool:
        teacher_upload = pool.submit(_upload_scan, client, teacher, bank_id=bank_id)
        student_upload = pool.submit(_upload_scan, client, student, bank_id=bank_id)
        _, teacher_doc = teacher_upload.result(timeout=30)
        _, student_doc = student_upload.result(timeout=30)
    for headers, document_id, expected_key in [
        (teacher, teacher_doc, teacher_key), (student, student_doc, student_key),
    ]:
        _assert_simplified_ready(client, headers, bank_id, document_id)
        calls = [call for call in simplify_probe.calls if call[1] == f"第一章 {document_id}"]
        assert calls, "每份文档均需执行真实目录提取与概括"
        assert {call[0] for call in calls} == {expected_key}
        assert any(not call[2] for call in calls), "需覆盖目录提取"
        assert len({call[3] for call in calls if call[2]}) >= 2, "需覆盖多个概括线程"


def test_simplify_missing_section_retry_keeps_personal_key(simplify_probe):
    """目录、并发概括及漏节补写全部使用同一次调用的个人 Key。"""
    key = "fake-missing-section-personal-key"
    simplify_probe.omit_second_section = True
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


def test_scanned_pdf_uses_mineru(client, teacher, monkeypatch):
    """扫描件走 MinerU OCR：打桩 extract_pdf，验证状态机走 ocr 并最终 ready。"""
    bank = create_bank(client, teacher)

    def fake_extract(token, file_path, result_dir, on_progress=None):
        result_dir.mkdir(parents=True, exist_ok=True)
        md = result_dir / "full.md"
        md.write_text("# OCR 结果\n\n导数的定义与求导法则。", encoding="utf-8")
        return md.read_text(encoding="utf-8"), result_dir

    def fake_simplify(markdown, source_name="教材", on_progress=None, *, api_key=None):
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
