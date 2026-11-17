"""删除 SQL 提交后的原 DELETE 恢复及入库门禁竞争回归。"""
from pathlib import Path

import pytest
from fastapi import BackgroundTasks
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError

from app.api.documents import reprocess_document
from app.config import settings
from app.db import SessionLocal
from app.deps import resolve_bank_access
from app.errors import AppError
from app.models import Bank, BankMember, DeletionOperation, Document, User
from app.services import banks, documents
from app.services.rag import vectorstore
from conftest import create_bank


@pytest.fixture()
def material(client, teacher, db, tmp_path, monkeypatch):
    """仅使用临时原件及假向量服务，不启动入库或读取模型凭据。"""
    bank_id = create_bank(client, teacher)["id"]
    owner = db.query(User).filter_by(account="teacher").one()
    path = tmp_path / "source.md"
    path.write_text("test source", encoding="utf-8")
    doc = Document(id="retry_doc", bank_id=bank_id, name=path.name, format="MD",
                   size_bytes=path.stat().st_size, storage_path=path.as_posix(),
                   status="ready", uploader_id=owner.id)
    db.add(doc)
    db.commit()
    monkeypatch.setattr(vectorstore, "get_client", lambda: object())
    monkeypatch.setattr(vectorstore, "delete_document_chunks", lambda *args: None)
    monkeypatch.setattr(vectorstore, "delete_bank_collection", lambda *args: None)
    monkeypatch.setattr(type(settings), "upload_path", lambda self: tmp_path / "uploads")
    return bank_id, doc.id, path


def _fail_unlink(monkeypatch, path):
    original = Path.unlink

    def fail(instance, *args, **kwargs):
        if instance == path:
            raise PermissionError("fake file busy")
        return original(instance, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail)
    return original


@pytest.mark.parametrize("scope", ["document", "bank"])
def test_original_delete_retries_sql_deleted_and_completed(
    client, teacher, student, db, material, monkeypatch, scope,
):
    """SQL 行消失后仍可由原所有者重试，清理失败不能提前返回 204。"""
    bank_id, doc_id, path = material
    url = f"/api/banks/{bank_id}" + (f"/documents/{doc_id}" if scope == "document" else "")
    original = _fail_unlink(monkeypatch, path)
    assert client.delete(url, headers=teacher).status_code == 503
    db.expire_all()
    operation = db.query(DeletionOperation).one()
    assert operation.status == "sql_deleted"
    assert db.get(Document, doc_id) is None
    if scope == "bank":
        assert db.get(Bank, bank_id).status == "deleted"
        assert db.query(BankMember).filter_by(bank_id=bank_id).count() == 0
    assert client.delete(url, headers=student).status_code == 404
    assert client.delete(url, headers=teacher).status_code == 503
    assert path.exists()
    monkeypatch.setattr(Path, "unlink", original)

    def unavailable(*args):
        raise AssertionError("SQL 清理完成后的重试不得再次访问向量存储")

    monkeypatch.setattr(vectorstore, "get_client", unavailable)
    monkeypatch.setattr(vectorstore, "delete_document_chunks", unavailable)
    monkeypatch.setattr(vectorstore, "delete_bank_collection", unavailable)
    assert client.delete(url, headers=teacher).status_code == 204
    assert not path.exists()
    assert client.delete(url, headers=teacher).status_code == 204
    db.expire_all()
    assert db.get(DeletionOperation, operation.id).status == "completed"


@pytest.mark.parametrize("permission", ["editor", "readonly", "quit", "removed", "forged"])
def test_document_retry_requires_current_edit_permission(
    client, teacher, student, db, material, monkeypatch, permission,
):
    """保留记录不能让退出、被移出、降权或伪造 creator 的成员恢复删除。"""
    bank_id, doc_id, path = material
    editor = db.query(User).filter_by(account="student").one()
    member = BankMember(id="retry_editor", bank_id=bank_id, user_id=editor.id, role="editor")
    db.add(member)
    db.commit()
    url = f"/api/banks/{bank_id}/documents/{doc_id}"
    original = _fail_unlink(monkeypatch, path)
    assert client.delete(url, headers=student).status_code == 503
    if permission == "removed":
        db.delete(member)
    elif permission == "quit":
        member.status = "quit"
    elif permission != "editor":
        member.role = "creator" if permission == "forged" else permission
    db.commit()
    monkeypatch.setattr(Path, "unlink", original)
    response = client.delete(url, headers=student)
    assert response.status_code == (204 if permission == "editor" else
                                    404 if permission in {"quit", "removed"} else 403)
    if permission != "editor":
        assert path.exists()
        assert client.delete(url, headers=teacher).status_code == 204
    assert not path.exists()


def test_retry_cannot_use_operation_from_another_bank(
    client, teacher, db, material, monkeypatch,
):
    bank_id, doc_id, path = material
    original = _fail_unlink(monkeypatch, path)
    url = f"/api/banks/{bank_id}/documents/{doc_id}"
    assert client.delete(url, headers=teacher).status_code == 503
    other_id = create_bank(client, teacher, "other")["id"]
    monkeypatch.setattr(Path, "unlink", original)
    assert client.delete(f"/api/banks/{other_id}/documents/{doc_id}",
                         headers=teacher).status_code == 404
    assert path.exists()


@pytest.mark.parametrize("change", ["removed", "readonly", "disabled", "auth_version"])
def test_retry_rechecks_editor_after_dependency_before_gate(
    client, teacher, student, db, material, monkeypatch, change,
):
    """DELETE 依赖已通过后仍须在恢复门禁内拒绝并发撤销的编辑权限。"""
    bank_id, doc_id, path = material
    editor = db.query(User).filter_by(account="student").one()
    editor_id = editor.id
    db.add(BankMember(id="retry_editor", bank_id=bank_id, user_id=editor_id, role="editor"))
    db.commit()
    url = f"/api/banks/{bank_id}/documents/{doc_id}"
    original_unlink = _fail_unlink(monkeypatch, path)
    assert client.delete(url, headers=student).status_code == 503
    monkeypatch.setattr(Path, "unlink", original_unlink)
    gate = banks.assert_mutations_allowed

    def revoke_before_gate(session):
        with SessionLocal() as writer:
            if change in {"removed", "readonly"}:
                member = writer.query(BankMember).filter_by(bank_id=bank_id,
                                                          user_id=editor_id).one()
                if change == "removed":
                    writer.delete(member)
                else:
                    member.role = "readonly"
            else:
                actor = writer.get(User, editor_id)
                if change == "disabled":
                    actor.status = "disabled"
                else:
                    actor.auth_version += 1
            writer.commit()
        return gate(session)

    monkeypatch.setattr(banks, "assert_mutations_allowed", revoke_before_gate)
    response = client.delete(url, headers=student)
    assert response.status_code == (404 if change == "removed" else
                                    403 if change == "readonly" else 401)
    assert path.exists()
    db.expire_all()
    assert db.query(DeletionOperation).one().status == "sql_deleted"


@pytest.mark.parametrize("action", ["upload", "reprocess"])
@pytest.mark.parametrize("change", ["bank_delete", "document_delete", "removed", "readonly",
                                   "disabled", "auth_version", "platform_role"])
def test_mutation_rechecks_state_after_dependency_before_gate(
    client, teacher, db, material, monkeypatch, action, change,
):
    """依赖已缓存允许状态；另一会话在门禁前提交删除或撤权后不能再发布入库。"""
    bank_id, doc_id, path = material
    owner = db.query(User).filter_by(account="teacher").one()
    access = resolve_bank_access(db, owner, bank_id)
    gate = documents.assert_mutations_allowed

    def changed_before_gate(session):
        with SessionLocal() as writer:
            if change.endswith("delete"):
                banks._prepare_deletion(writer, "bank" if change == "bank_delete" else "document",
                                        bank_id if change == "bank_delete" else doc_id,
                                        bank_id, None)
            elif change in {"removed", "readonly"}:
                member = writer.query(BankMember).filter_by(bank_id=bank_id,
                                                          user_id=owner.id).one()
                if change == "removed":
                    writer.delete(member)
                else:
                    member.role = "readonly"
                writer.commit()
            else:
                actor = writer.get(User, owner.id)
                if change == "disabled":
                    actor.status = "disabled"
                elif change == "auth_version":
                    actor.auth_version += 1
                else:
                    actor.role = "admin"
                writer.commit()
        return gate(session)

    monkeypatch.setattr(documents, "assert_mutations_allowed", changed_before_gate)
    background = BackgroundTasks()
    # 单文档删除不禁止题库继续上传其他资料。
    if action == "upload" and change == "document_delete":
        result = documents.queue_upload(db, background, bank_id, owner.id,
                                        "new.md", b"new material", None)
        assert result["status"] == "uploaded"
        return
    with pytest.raises(AppError):
        if action == "upload":
            documents.queue_upload(db, background, bank_id, owner.id,
                                   "new.md", b"new material", None)
        else:
            reprocess_document(doc_id, background, access, db)
    db.rollback()
    db.expire_all()
    assert background.tasks == []
    assert db.query(Document).filter_by(bank_id=bank_id).count() == 1
    assert db.get(Document, doc_id).status == ("deleting" if change.endswith("delete") else "ready")
    assert not list(settings.upload_path().rglob("*.md"))
    assert path.exists()
    if change == "bank_delete":
        operation = db.query(DeletionOperation).one()
        banks.resume_deletion(db, operation.id)
        assert db.query(Document).filter_by(bank_id=bank_id).count() == 0
        assert not path.exists()


@pytest.mark.parametrize("failure", ["write", "commit"])
def test_upload_failure_rolls_back_sql_and_removes_partial_file(
    client, teacher, db, material, monkeypatch, failure,
):
    """写文件中途失败及 SQL 提交失败均不得遗留未登记原件或后台任务。"""
    bank_id, _, _ = material
    owner = db.query(User).filter_by(account="teacher").one()
    background = BackgroundTasks()
    original = Path.write_bytes

    def partial_write(path, content):
        original(path, content[:2])
        raise OSError("fake partial write")

    def fail_commit(session):
        raise SQLAlchemyError("fake commit failure")

    if failure == "write":
        monkeypatch.setattr(Path, "write_bytes", partial_write)
    else:
        event.listen(db, "before_commit", fail_commit)
    try:
        with pytest.raises((AppError, OSError, SQLAlchemyError)):
            documents.queue_upload(db, background, bank_id, owner.id,
                                   "partial.md", b"new material", None)
    finally:
        if failure == "commit":
            event.remove(db, "before_commit", fail_commit)
    assert not list(settings.upload_path().rglob("*.md"))
    assert background.tasks == []
    assert db.query(Document).filter_by(bank_id=bank_id).count() == 1
