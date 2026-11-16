"""题库权限、容量门禁及跨存储删除的定向 ACID 回归。"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from app.api.banks import add_member, transfer_bank
from app.db import Base
from app.deps import require_bank_owner, resolve_bank_access
from app.errors import AppError
from app.models import Bank, BankMember, DeletionOperation, Document, SpaceMember, StudySpace, User
from app.schemas.bank import MemberAddBody, TransferBody
from app.services import banks, rag_settings, spaces
from app.services.rag import vectorstore
from conftest import create_bank, upload_markdown
from test_document_failure_recovery import document_store


@pytest.mark.parametrize("phase", ["pending", "vectors_deleted", "sql_deleted"])
def test_rebuild_waits_for_durable_deletion_even_after_sql_cleanup(client, db, phase):
    """原件清理尚未完成时，即使资源 SQL 行已不存在也不能切换 generation。"""
    from app.models import RagSetting

    db.add(RagSetting(id=1))
    db.add(DeletionOperation(
        id="delete_gate", resource_type="bank", resource_id="removed_bank",
        bank_id="removed_bank", status=phase, generation="old", paths_json="[]",
    ))
    db.commit()
    with pytest.raises(AppError) as error:
        rag_settings.queue_rebuild(db, 0)
    assert error.value.code == "RAG_DELETION_BUSY"
    db.rollback()


def test_forged_creator_member_cannot_manage_bank(client, teacher, db):
    """成员行写着 creator 不能覆盖 banks.creator_id 的唯一所有权。"""
    bank_id = create_bank(client, teacher)["id"]
    user = db.query(User).filter_by(account="student").one()
    db.add(BankMember(id="forged", bank_id=bank_id, user_id=user.id, role="creator"))
    db.commit()
    with pytest.raises(AppError) as error:
        require_bank_owner(resolve_bank_access(db, user, bank_id))
    assert error.value.status_code == 403


def test_transfer_rechecks_cached_creator_after_other_transfer(client, teacher, db):
    """依赖鉴权后并发转让不能再使用旧创建者的 BankAccess。"""
    bank_id = create_bank(client, teacher)["id"]
    owner = db.query(User).filter_by(account="teacher").one()
    target = db.query(User).filter_by(account="student").one()
    target.role = "teacher"
    db.add(BankMember(id="target", bank_id=bank_id, user_id=target.id, role="editor"))
    db.commit()
    access = resolve_bank_access(db, owner, bank_id)
    from app.db import SessionLocal

    with SessionLocal() as writer:
        writer.query(Bank).filter_by(id=bank_id).update({"creator_id": target.id})
        writer.query(BankMember).filter_by(bank_id=bank_id, user_id=owner.id).update(
            {"role": "editor"}
        )
        writer.query(BankMember).filter_by(id="target").update({"role": "creator"})
        writer.commit()
    with pytest.raises(AppError) as error:
        transfer_bank(TransferBody(target_user_id=target.id), access, db)
    assert error.value.status_code == 403


@pytest.mark.parametrize("scope", ["document", "bank"])
def test_deleted_vectors_sql_failure_never_restores_ready(
    client, teacher, db, monkeypatch, document_store, scope,
):
    """向量成功后注入提交失败，资源应不可用且原件保留，恢复后完整删除。"""
    bank_id = create_bank(client, teacher)["id"]
    doc_id = upload_markdown(client, teacher, bank_id)["document_id"]
    doc = db.get(Document, doc_id)
    from app.config import BASE_DIR

    path = Path(doc.storage_path)
    path = path if path.is_absolute() else BASE_DIR / path
    deleted = []
    monkeypatch.setattr(vectorstore, "delete_document_chunks", lambda *a: deleted.append(scope))
    monkeypatch.setattr(vectorstore, "delete_bank_collection", lambda *a: deleted.append(scope))

    def fail_after_vectors(session):
        if deleted:
            raise SQLAlchemyError("fake SQL commit failure after vector deletion")

    event.listen(db, "before_commit", fail_after_vectors)
    try:
        with pytest.raises((AppError, SQLAlchemyError)):
            if scope == "document":
                banks.purge_document(db, doc)
            else:
                banks.purge_bank(db, db.get(Bank, bank_id))
    finally:
        event.remove(db, "before_commit", fail_after_vectors)
    db.expire_all()
    assert deleted == [scope]
    assert db.get(Document, doc_id).status == "deleting"
    assert path.exists()
    banks.recover_pending_deletions(db)
    db.expire_all()
    assert db.get(Document, doc_id) is None
    assert not path.exists()


@pytest.mark.parametrize("scope", ["document", "bank"])
def test_vector_failure_persists_intent_and_http_retry_completes(
    client, teacher, db, monkeypatch, document_store, scope,
):
    """失败返回 503 并封禁使用，调用者可再次同步删除而无需重建向量。"""
    from app.models.deletion import DeletionOperation

    bank_id = create_bank(client, teacher)["id"]
    doc_id = upload_markdown(client, teacher, bank_id)["document_id"]
    url = f"/api/banks/{bank_id}" + (f"/documents/{doc_id}" if scope == "document" else "")
    method = "delete_document_chunks" if scope == "document" else "delete_bank_collection"

    def fail(*args):
        raise vectorstore.VectorStoreError("delete", "InternalError", 14)

    monkeypatch.setattr(vectorstore, method, fail)
    assert client.delete(url, headers=teacher).status_code == 503
    db.expire_all()
    operation = db.query(DeletionOperation).one()
    assert operation.status == "pending"
    assert db.get(Document, doc_id).status == "deleting"
    assert client.get(f"/api/banks/{bank_id}/documents/{doc_id}/download",
                      headers=teacher).status_code == 404
    monkeypatch.setattr(vectorstore, method, lambda *args: None)
    assert client.delete(url, headers=teacher).status_code == 204
    db.expire_all()
    assert db.get(DeletionOperation, operation.id).status == "completed"
    assert banks.recover_pending_deletions(db) == 0


def test_sql_stage_failure_recovers_without_repeating_vectors(
    client, teacher, db, monkeypatch, document_store,
):
    """向量阶段已提交后 SQL 清理失败，恢复从 vectors_deleted 继续。"""
    from app.models.deletion import DeletionOperation

    bank_id = create_bank(client, teacher)["id"]
    doc_id = upload_markdown(client, teacher, bank_id)["document_id"]
    deleted = []
    monkeypatch.setattr(vectorstore, "delete_document_chunks", lambda *a: deleted.append(doc_id))
    original = banks._delete_material_sql

    def fail(*args):
        raise SQLAlchemyError("fake cleanup failure")

    monkeypatch.setattr(banks, "_delete_material_sql", fail)
    with pytest.raises(AppError) as error:
        banks.purge_document(db, db.get(Document, doc_id))
    assert error.value.status_code == 503
    assert db.query(DeletionOperation).one().status == "vectors_deleted"
    assert db.get(Document, doc_id).status == "deleting"
    monkeypatch.setattr(banks, "_delete_material_sql", original)
    assert banks.recover_pending_deletions(db) == 1
    assert deleted == [doc_id]
    assert db.get(Document, doc_id) is None


def test_file_cleanup_failure_is_recoverable_after_sql_success(
    client, teacher, db, monkeypatch, document_store,
):
    """SQL 清理成功后原件清理失败仍返回 503，并保留 sql_deleted 恢复清单。"""
    from app.models.deletion import DeletionOperation

    bank_id = create_bank(client, teacher)["id"]
    doc_id = upload_markdown(client, teacher, bank_id)["document_id"]
    doc = db.get(Document, doc_id)
    path = Path(doc.storage_path)
    from app.config import BASE_DIR

    path = path if path.is_absolute() else BASE_DIR / path
    original = Path.unlink

    def fail(instance, *args, **kwargs):
        if instance == path:
            raise PermissionError("fake file busy")
        return original(instance, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail)
    with pytest.raises(AppError) as error:
        banks.purge_document(db, doc)
    assert error.value.status_code == 503
    assert db.query(DeletionOperation).one().status == "sql_deleted"
    assert db.get(Document, doc_id) is None
    assert path.exists()
    monkeypatch.setattr(Path, "unlink", original)
    assert banks.recover_pending_deletions(db) == 1
    assert not path.exists()


@pytest.mark.parametrize("scope", ["document", "bank"])
def test_deletion_does_not_race_active_ingestion(
    client, teacher, db, monkeypatch, document_store, scope,
):
    """入库中的 worker 尚可能发布 ready，删除须在门禁内拒绝并保留全部数据。"""
    from app.models.deletion import DeletionOperation

    bank_id = create_bank(client, teacher)["id"]
    doc_id = upload_markdown(client, teacher, bank_id)["document_id"]
    doc = db.get(Document, doc_id)
    doc.status = "embedding"
    db.commit()
    deleted = []
    monkeypatch.setattr(vectorstore, "delete_document_chunks", lambda *a: deleted.append(doc_id))
    monkeypatch.setattr(vectorstore, "delete_bank_collection", lambda *a: deleted.append(bank_id))
    with pytest.raises(AppError) as error:
        if scope == "document":
            banks.purge_document(db, doc)
        else:
            banks.purge_bank(db, db.get(Bank, bank_id))
    assert error.value.code == "DOCUMENT_PROCESSING"
    assert error.value.status_code == 409
    assert deleted == []
    assert db.query(DeletionOperation).count() == 0
    assert db.get(Document, doc_id).status == "embedding"
    assert db.get(Bank, bank_id).status == "active"


@pytest.fixture()
def capacity_store(tmp_path):
    """真实独立 WAL 与独立连接，使两个请求争夺最后一个名额。"""
    engine = create_engine(f"sqlite:///{(tmp_path / 'capacity.db').as_posix()}",
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def configure(connection, record):
        connection.isolation_level = None
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions() as db:
        for identifier, role in [("owner", "teacher"), ("first", "student"),
                                 ("second", "student")]:
            db.add(User(id=identifier, account=identifier, role=role, identity="测试",
                        display_name=identifier, password_hash="fake-hash"))
        db.flush()
        db.add(Bank(id="bank", code="TK_CAPACITY", name="测试", creator_id="owner", capacity=2))
        db.add(StudySpace(id="space", code="SP_CAPACITY", name="测试", creator_id="owner",
                          capacity=2))
        db.flush()
        db.add(BankMember(id="bm_owner", bank_id="bank", user_id="owner", role="creator"))
        db.add(SpaceMember(id="sm_owner", space_id="space", user_id="owner", role="creator"))
        db.commit()
    try:
        yield sessions
    finally:
        engine.dispose()


@pytest.mark.parametrize("scope", ["bank", "space"])
def test_two_sessions_joining_last_slot_are_serialized(capacity_store, monkeypatch, scope):
    """并发请求都先读到资源，锁后重计数使第二个得到容量错误而非超员或 SQL 错误。"""
    sessions = capacity_store
    first_count, second_count, release = Event(), Event(), Event()
    service = banks if scope == "bank" else spaces
    original = service.member_count
    reads = []

    def paused_count(db, resource_id):
        count = original(db, resource_id)
        reads.append(count)
        if len(reads) == 1:
            first_count.set()
            assert release.wait(5)
        else:
            second_count.set()
        return count

    monkeypatch.setattr(service, "member_count", paused_count)

    def join(user_id):
        with sessions() as db:
            try:
                if scope == "bank":
                    owner = db.get(User, "owner")
                    access = resolve_bank_access(db, owner, "bank")
                    add_member(MemberAddBody(account=user_id), access, db)
                else:
                    spaces.join_space(db, db.get(User, user_id), "SP_CAPACITY")
                return "joined"
            except AppError as exc:
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(join, "first")
        assert first_count.wait(5)
        second = pool.submit(join, "second")
        try:
            # 缺少门禁时第二个请求立即读到旧计数；正确实现会等待首个事务提交。
            second_count.wait(0.2)
        finally:
            release.set()
        assert first.result(timeout=5) == "joined"
        assert second.result(timeout=5) == ("BANK_FULL" if scope == "bank" else "SPACE_FULL")
    with sessions() as db:
        assert original(db, "bank" if scope == "bank" else "space") == 2
