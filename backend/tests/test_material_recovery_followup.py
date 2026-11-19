"""资料删除、题目写入及派生 OCR 文件的真实故障恢复回归。"""
import asyncio
import os
from pathlib import Path
from threading import Event

import httpx
import pymupdf
import pytest

from app import local_secrets
from app.config import settings
from app.db import SessionLocal
from app.models import DeletionOperation, Document, GenerationTask, Question, User
from app.services import banks, documents, mineru
from conftest import make_questions
from test_deletion_retry_acid import _fail_unlink, material


def test_bank_delete_finishes_or_reports_pending_child_files(
    client, teacher, db, material, monkeypatch,
):
    """单资料 SQL 已删除时，整库 DELETE 仍须等到该资料原件也清理成功。"""
    bank_id, doc_id, path = material
    original = _fail_unlink(monkeypatch, path)
    assert client.delete(f"/api/banks/{bank_id}/documents/{doc_id}",
                         headers=teacher).status_code == 503
    assert client.delete(f"/api/banks/{bank_id}", headers=teacher).status_code == 503
    assert path.exists()
    monkeypatch.setattr(Path, "unlink", original)
    assert client.delete(f"/api/banks/{bank_id}", headers=teacher).status_code == 204
    assert not path.exists()
    db.expire_all()
    assert all(op.status == "completed" for op in db.query(DeletionOperation).all())


@pytest.mark.parametrize("scope", ["bank", "document"])
def test_pending_delete_remains_in_owner_list_only(
    client, teacher, student, db, material, monkeypatch, scope,
):
    bank_id, doc_id, path = material
    suffix = "" if scope == "bank" else f"/documents/{doc_id}"
    _fail_unlink(monkeypatch, path)
    assert client.delete(f"/api/banks/{bank_id}{suffix}", headers=teacher).status_code == 503
    if scope == "bank":
        rows = client.get("/api/banks?scope=owned", headers=teacher).json()
        assert len(rows) == 1
        assert rows[0]["id"] == bank_id
        assert rows[0]["status"] == "deleting"
        assert rows[0]["source"] == "owned"
        assert rows[0]["can_delete_bank"]
        assert not rows[0]["can_upload_document"]
        assert not rows[0]["can_edit_bank"]
        assert client.get("/api/banks", headers=student).json() == []
    else:
        rows = client.get(f"/api/banks/{bank_id}/documents", headers=teacher).json()
        assert len(rows) == 1
        assert rows[0]["id"] == doc_id
        assert rows[0]["name"] == path.name
        assert rows[0]["status"] == "deleting"
        assert rows[0]["format"] == "MD"
        assert rows[0]["size_bytes"] == path.stat().st_size
        assert rows[0]["stage"]
        assert "storage_path" not in rows[0]
        assert client.get(f"/api/banks/{bank_id}/documents", headers=student).status_code == 404


def _material_question(db, bank_id, doc_id):
    owner = db.query(User).filter_by(account="teacher").one()
    question_id = make_questions(db, owner.id, [("single", "A", 5)])[0]
    question = db.get(Question, question_id)
    from app.models import GenerationBatch

    batch = db.get(GenerationBatch, question.batch_id)
    batch.bank_id, batch.document_id = bank_id, doc_id
    question.bank_id, question.document_id = bank_id, doc_id
    db.commit()
    return question_id, batch.id, owner.id


@pytest.mark.parametrize("scope", ["bank", "document"])
def test_material_delete_erases_generation_task_result_copies(
    client, teacher, db, material, scope,
):
    bank_id, doc_id, _ = material
    _, batch_id, owner_id = _material_question(db, bank_id, doc_id)
    db.add(GenerationTask(id="material_task", user_id=owner_id, bank_id=bank_id,
                          document_id=doc_id, run_id="test_run", params_json="{}",
                          status="done", batch_id=batch_id,
                          result_json='{"questions":[{"stem":"removed"}]}',
                          review_json='{"review":"removed"}'))
    db.commit()
    suffix = "" if scope == "bank" else f"/documents/{doc_id}"
    assert client.delete(f"/api/banks/{bank_id}{suffix}", headers=teacher).status_code == 204
    db.expire_all()
    task = db.get(GenerationTask, "material_task")
    assert task.result_json is None
    assert task.review_json is None
    assert task.batch_id is None


@pytest.mark.parametrize("scope", ["bank", "document"])
@pytest.mark.parametrize("action", ["update", "delete", "batch-delete"])
def test_question_mutation_refuses_material_already_deleting(
    client, teacher, db, material, scope, action,
):
    bank_id, doc_id, _ = material
    question_id, _, _ = _material_question(db, bank_id, doc_id)
    banks._prepare_deletion(db, scope, bank_id if scope == "bank" else doc_id, bank_id, None)
    if action == "update":
        response = client.put(f"/api/questions/{question_id}", headers=teacher,
                              json={"stem": "must not acknowledge this edit"})
    elif action == "delete":
        response = client.delete(f"/api/questions/{question_id}", headers=teacher)
    else:
        response = client.post("/api/questions/batch-delete", headers=teacher,
                               json={"question_ids": [question_id]})
    assert response.status_code == 409
    db.expire_all()
    assert db.get(Question, question_id).stem == "测试题目 1"


def test_question_update_rechecks_after_another_session_starts_delete(
    client, teacher, db, material, monkeypatch,
):
    """依赖已鉴权之后、写门禁之前启动的删除，不能仍确认编辑成功。"""
    from app.api import questions

    bank_id, doc_id, _ = material
    question_id, _, _ = _material_question(db, bank_id, doc_id)
    gate = questions.assert_mutations_allowed

    def begin_delete(session):
        with SessionLocal() as other:
            banks._prepare_deletion(other, "document", doc_id, bank_id, None)
        return gate(session)

    monkeypatch.setattr(questions, "assert_mutations_allowed", begin_delete)
    response = client.put(f"/api/questions/{question_id}", headers=teacher, json={"stem": "lost"})
    assert response.status_code == 409
    db.expire_all()
    assert db.get(Question, question_id).stem == "测试题目 1"


def test_ocr_publish_failure_preserves_previous_complete_file(
    db, material, monkeypatch,
):
    _, doc_id, path = material
    source = path.with_suffix(".pdf")
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.save(source)
    doc = db.get(Document, doc_id)
    doc.name = source.name
    doc.format = "PDF"
    doc.storage_path = source.as_posix()
    db.commit()

    result_dir = settings.ocr_path() / doc_id
    previous = "# 旧版 OCR\n\n旧版教材正文。"
    replacement = "# 新版 OCR\n\n新版教材正文。"
    original_pdf = source.read_bytes()
    with pymupdf.open(source) as pdf:
        identity = mineru._cache_identity(source, pdf.page_count)
    mineru._publish_markdown(result_dir, previous, identity)
    manifest = result_dir / "full.manifest.json"
    previous_manifest = manifest.read_bytes()

    # 源文件变化后，旧缓存对当前源失效，触发新的 OCR 发布。
    with pymupdf.open() as pdf:
        pdf.new_page()
        pdf.new_page()
        pdf.save(source)

    def extract(token, file_path, target_dir, on_progress=None):
        with pymupdf.open(file_path) as pdf:
            identity = mineru._cache_identity(file_path, pdf.page_count)
        mineru._publish_markdown(target_dir, replacement, identity)
        return replacement, target_dir

    monkeypatch.setattr(mineru, "extract_pdf", extract)
    monkeypatch.setattr(documents.vectorstore, "add_chunks", lambda *args, **kwargs: None)
    destination = result_dir / "full.md"
    original_replace = os.replace

    def fail_replace(source, target):
        if Path(target) == destination:
            raise OSError("injected replacement failure")
        original_replace(source, target)

    token = local_secrets.MINERU_DEFAULT_TOKEN
    with monkeypatch.context() as fault:
        fault.setattr(os, "replace", fail_replace)
        documents.run_ingestion(doc_id, token)

    db.refresh(doc)
    assert doc.status == "failed"
    assert doc.ocr_status == "failed"
    assert destination.read_text(encoding="utf-8") == previous
    assert manifest.read_bytes() == previous_manifest
    assert not list(result_dir.glob("*.tmp"))
    assert mineru.read_cached_markdown(source, result_dir) is None
    original_source = source.with_name("previous.pdf")
    original_source.write_bytes(original_pdf)
    assert mineru.read_cached_markdown(original_source, result_dir) == previous

    documents.run_ingestion(doc_id, token)
    db.refresh(doc)
    assert doc.status == "ready"
    assert doc.ocr_status == "done"
    assert mineru.read_cached_markdown(source, result_dir) == replacement


@pytest.mark.asyncio
@pytest.mark.parametrize("create", [False, True])
async def test_upload_database_gate_does_not_block_event_loop(
    client, teacher, material, monkeypatch, create,
):
    """同步写门禁等待期间，ASGI 事件循环仍能调度其他工作。"""
    from app.api import banks as bank_api
    from app.main import app

    bank_id, _, _ = material
    entered, pulse = Event(), Event()
    responsive = []
    gate = documents.assert_mutations_allowed

    def slow_gate(session):
        entered.set()
        responsive.append(pulse.wait(3))
        return gate(session)

    monkeypatch.setattr(documents, "assert_mutations_allowed", slow_gate)
    monkeypatch.setattr(bank_api, "assert_mutations_allowed", slow_gate)
    monkeypatch.setattr(documents, "run_ingestion", lambda *args, **kwargs: None)
    url = "/api/banks/with-document" if create else f"/api/banks/{bank_id}/documents"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver") as async_client:
        upload = asyncio.create_task(async_client.post(
            url, headers=teacher, data={"name": "new material"} if create else {},
            files={"file": ("notes.md", b"# fake material", "text/markdown")},
        ))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            pulse.set()
            response = await upload
        finally:
            pulse.set()
            if not upload.done():
                await upload
    assert response.status_code == (201 if create else 202)
    assert responsive and all(responsive)
