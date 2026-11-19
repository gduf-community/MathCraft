"""题库业务：编号生成、列表载荷、成员操作、删除清理。"""
from collections.abc import Callable
import json
import logging
from pathlib import Path
import secrets
import sqlite3
from time import sleep
from typing import TypeVar

from sqlalchemy import func
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import BASE_DIR, settings
from app.errors import AppError
from app.models import Bank, BankMember, Document, Favorite, Question, User
from app.models.base import new_id
from app.models.deletion import DeletionOperation
from app.services.auth import assert_version
from app.services.rag import fts, vectorstore
from app.services.rag_runtime import RuntimeSnapshot, use_snapshot
from app.services.rag_settings import assert_mutations_allowed, precheck_mutations_allowed
from app.deps import normalize_bank_role, resolve_deletion_access

logger = logging.getLogger(__name__)
_DELETE_ATTEMPTS = 3
T = TypeVar("T")


def _authorize_purge(
    db: Session, bank_id: str, actor: tuple[str, int] | None, *,
    document_id: str | None = None,
) -> None:
    """在门禁写锁内按原认证版本重新授权，拒绝竞争期间撤销的访问权。"""
    if actor is None:
        return
    actor_id, version = actor
    assert_version(db, actor_id, version)
    current_user = db.get(User, actor_id, populate_existing=True)
    if current_user is None:
        raise AppError("SESSION_REVOKED", "认证状态已变更，请重新登录", 401)
    # 删除重试通过精确匹配的持久操作及保留的 creator_id 授权。
    db.get(Bank, bank_id, populate_existing=True)
    db.query(BankMember).filter_by(bank_id=bank_id, user_id=actor_id).populate_existing().all()
    resolve_deletion_access(db, current_user, bank_id, document_id=document_id)


def _sqlite_lock_code(exc: Exception) -> int | None:
    """只识别 SQLite 原生锁竞争码，包含 BUSY_SNAPSHOT 等扩展码。"""
    if not isinstance(exc, OperationalError) or not isinstance(exc.orig, sqlite3.Error):
        return None
    code = getattr(exc.orig, "sqlite_errorcode", None)
    if isinstance(code, int) and code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return code
    return None


def _delete_transaction(db: Session, action: Callable[[RuntimeSnapshot], T]) -> T:
    """各持久阶段共用重建门禁；仅对原生 SQLite 写锁有限重试。"""
    for attempt in range(_DELETE_ATTEMPTS):
        stage = "gate"
        try:
            snapshot = assert_mutations_allowed(db)
            stage = "sql"
            result = action(snapshot)
            stage = "commit"
            db.commit()
            return result
        except Exception as exc:
            db.rollback()
            code = _sqlite_lock_code(exc)
            logger.warning("Delete failure stage=%s type=%s code=%s",
                           stage, type(exc).__name__, code)
            if isinstance(exc, vectorstore.VectorStoreError):
                raise
            if code is not None:
                if attempt + 1 >= _DELETE_ATTEMPTS:
                    raise AppError("DATABASE_BUSY", "数据库繁忙，请稍后重试删除", 503) from exc
                sleep(0.05 * (attempt + 1))
                continue
            if isinstance(exc, SQLAlchemyError):
                raise AppError("DELETION_PENDING", "删除未完成，请稍后重试", 503) from exc
            if isinstance(exc, AppError):
                raise
            raise AppError("DELETION_PENDING", "删除未完成，请稍后重试", 503) from exc
    raise AppError("DATABASE_BUSY", "数据库繁忙，请稍后重试删除", 503)


CODE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def generate_bank_code(db: Session) -> str:
    """10 位随机编号（TK 前缀 + 8 位随机字符），冲突时重试。"""
    while True:
        code = "TK" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not db.query(Bank.id).filter(Bank.code == code).first():
            return code


def member_count(db: Session, bank_id: str) -> int:
    return (
        db.query(func.count(BankMember.id))
        .filter(BankMember.bank_id == bank_id, BankMember.status == "active")
        .scalar()
        or 0
    )


def bank_payload(db: Session, bank: Bank, user: User) -> dict:
    member = (
        db.query(BankMember)
        .filter(BankMember.bank_id == bank.id, BankMember.user_id == user.id, BankMember.status == "active")
        .one_or_none()
    )
    creator = db.get(User, bank.creator_id)
    from app.deps import BankAccess

    deleting = bank.status != "active"
    role = "creator" if deleting and bank.creator_id == user.id else (
        normalize_bank_role(member.role) if member else "readonly"
    )
    if role == "creator" and bank.creator_id != user.id:
        role = "readonly"
    access = BankAccess(bank=bank, member=member, user=user, my_role=role) if member else None
    return {
        "id": bank.id,
        "name": bank.name,
        "code": bank.code,
        "creator": {"id": creator.id, "display_name": creator.display_name} if creator else None,
        "member_count": member_count(db, bank.id),
        "capacity": bank.capacity,
        "status": "deleting" if deleting else "active",
        "stage": "删除未完成，请继续删除以清理剩余资料" if deleting else None,
        "error_message": None,
        "source": "owned" if role == "creator" else "joined",
        "quitted": member is None and not deleting,
        **(access.capabilities() if access and not deleting else {
            "my_role": "creator" if deleting else None,
            "can_upload_document": False, "can_download_document": False,
            "can_delete_document": False, "can_manage_members": False, "can_edit_bank": False,
            "can_transfer_bank": False,
            "can_delete_bank": deleting and bank.creator_id == user.id,
        }),
    }


def member_payload(m: BankMember, u: User, me_id: str, bank: Bank) -> dict:
    role = normalize_bank_role(m.role)
    if role == "creator" and bank.creator_id != m.user_id:
        role = "readonly"
    return {
        "id": m.id,
        "user": {"id": u.id, "display_name": u.display_name, "account": u.account},
        "role": role,
        "is_creator": role == "creator",
        "is_me": u.id == me_id,
        "joined_at": m.joined_at,
    }


def create_bank(db: Session, user: User, name: str, *, commit: bool = True) -> Bank:
    """创建题库及创建者成员；组合上传可在同一事务内一起提交。"""
    bank = Bank(id=new_id("bank"), name=name, code=generate_bank_code(db), creator_id=user.id, admin_level="super")
    db.add(bank)
    db.flush()
    db.add(BankMember(id=new_id("bm"), bank_id=bank.id, user_id=user.id, role="creator", status="active"))
    if commit:
        db.commit()
        db.refresh(bank)
    else:
        db.flush()
    return bank


def _document_paths(doc: Document) -> list[str]:
    """记录当前产物及扫描件原件，SQL 删除成功后才允许清理。"""
    from app.services.documents import original_upload_path

    paths = [doc.storage_path]
    original = original_upload_path(doc)
    if original is not None:
        paths.append(original["rel"])
    simplified = settings.upload_path() / doc.bank_id / f"{doc.id}_simplified.md"
    paths.extend((simplified.as_posix(), simplified.with_suffix(".manifest.json").as_posix()))
    return paths


def _deletion_record(operation: DeletionOperation) -> tuple[list[str], dict]:
    """兼容旧路径数组；新记录额外保留原列表的最少展示信息。"""
    value = json.loads(operation.paths_json)
    paths = value.get("paths") if isinstance(value, dict) else value
    if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
        raise AppError("DELETION_PENDING", "删除文件记录无效，请检查恢复任务", 503)
    document = value.get("document", {}) if isinstance(value, dict) else {}
    return paths, document


def pending_document_payloads(db: Session, bank_id: str) -> list[dict]:
    """资料行清除后仍向有权限的原列表提供继续 DELETE 的展示载荷。"""
    items = []
    operations = db.query(DeletionOperation).filter_by(
        bank_id=bank_id, resource_type="document", status="sql_deleted",
    ).order_by(DeletionOperation.created_at.desc()).all()
    for operation in operations:
        paths, payload = _deletion_record(operation)
        if not payload:
            # 旧记录没有名称元数据；使用已持久化的路径文件名，不回传本地路径。
            name = Path(paths[0]).name if paths else operation.resource_id
            payload = {
                "id": operation.resource_id, "bank_id": bank_id, "name": name,
                "format": Path(name).suffix.lstrip(".").upper(), "size_bytes": 0,
                "page_count": None, "is_scanned": False, "chunk_count": 0,
                "ocr_status": None, "created_at": operation.created_at,
            }
        items.append({**payload, "status": "deleting", "progress": 100,
                      "stage": "资料已移除，原件清理待重试", "error_message": None})
    return items


def _prepare_deletion(
    db: Session, resource_type: str, resource_id: str, bank_id: str,
    actor: tuple[str, int] | None,
) -> str:
    """先持久化意图与不可用状态，随后才允许不可逆的向量删除。"""
    try:
        precheck_mutations_allowed(db)
        existing = db.query(DeletionOperation).filter_by(
            resource_type=resource_type, resource_id=resource_id, bank_id=bank_id,
        ).populate_existing().one_or_none()
        # 文件清理重试不再依赖 Chroma；需要访问向量时冷启动仍在门禁外。
        if existing is None or existing.status == "pending":
            vectorstore.get_client()
    except Exception:
        db.rollback()
        raise

    def prepare(snapshot: RuntimeSnapshot) -> str:
        _authorize_purge(db, bank_id, actor,
                         document_id=resource_id if resource_type == "document" else None)
        existing = db.query(DeletionOperation).filter_by(
            resource_type=resource_type, resource_id=resource_id, bank_id=bank_id,
        ).populate_existing().one_or_none()
        if existing is not None:
            return existing.id
        if resource_type == "bank":
            bank = db.get(Bank, bank_id, populate_existing=True)
            if bank is None or bank.status != "active":
                raise AppError("NOT_FOUND", "题库不存在", 404)
            docs = db.query(Document).filter_by(bank_id=bank_id).populate_existing().all()
        else:
            doc = db.get(Document, resource_id, populate_existing=True)
            if doc is None or doc.bank_id != bank_id:
                raise AppError("NOT_FOUND", "文档不存在", 404)
            docs = [doc]
        if any(doc.status not in ("ready", "failed", "deleting") for doc in docs):
            raise AppError("DOCUMENT_PROCESSING", "资料仍在入库，请等待完成后再删除", 409)
        if resource_type == "bank":
            bank.status = "deleting"
        paths = []
        for doc in docs:
            paths.extend(_document_paths(doc))
            doc.status = "deleting"
            doc.stage = "正在删除；完成前不可使用"
        record: dict = {"paths": sorted(set(paths))}
        if resource_type == "document":
            doc = docs[0]
            record["document"] = {
                "id": doc.id, "bank_id": doc.bank_id, "name": doc.name,
                "format": doc.format, "size_bytes": doc.size_bytes,
                "page_count": doc.page_count, "is_scanned": doc.is_scanned,
                "chunk_count": doc.chunk_count, "ocr_status": doc.ocr_status,
                "created_at": doc.created_at.isoformat(),
            }
        operation = DeletionOperation(
            id=new_id("del"), resource_type=resource_type, resource_id=resource_id,
            bank_id=bank_id, status="pending", generation=snapshot.generation,
            paths_json=json.dumps(record, ensure_ascii=False),
        )
        db.add(operation)
        return operation.id

    return _delete_transaction(db, prepare)


def _delete_material_sql(db: Session, operation: DeletionOperation) -> None:
    """清理资料 SQL；历史试卷快照、学生作答不在删除范围。"""
    from app.models import DocumentChunk, GenerationBatch, GenerationTask

    bank_id, resource_id = operation.bank_id, operation.resource_id
    by_bank = operation.resource_type == "bank"
    q = db.query(Question).filter(
        Question.bank_id == bank_id if by_bank else Question.document_id == resource_id,
    )
    q_ids = [row.id for row in q.with_entities(Question.id).all()]
    if q_ids:
        db.query(Favorite).filter(Favorite.question_id.in_(q_ids)).delete(synchronize_session=False)
    q.delete(synchronize_session=False)
    batches = db.query(GenerationBatch).filter(
        GenerationBatch.bank_id == bank_id if by_bank
        else GenerationBatch.document_id == resource_id,
    )
    batch_ids = [row.id for row in batches.with_entities(GenerationBatch.id).all()]
    if batch_ids:
        db.query(GenerationTask).filter(GenerationTask.batch_id.in_(batch_ids)).update(
            {"batch_id": None, "result_json": None, "review_json": None},
            synchronize_session=False,
        )
    batches.delete(synchronize_session=False)
    if by_bank:
        fts.delete_bank(db, bank_id)
        db.query(DocumentChunk).filter_by(bank_id=bank_id).delete(synchronize_session=False)
        db.query(Document).filter_by(bank_id=bank_id).delete(synchronize_session=False)
        db.query(BankMember).filter_by(bank_id=bank_id).delete(synchronize_session=False)
        db.query(Bank).filter_by(id=bank_id).update({"status": "deleted"},
                                                  synchronize_session=False)
    else:
        fts.delete_document(db, resource_id)
        db.query(DocumentChunk).filter_by(document_id=resource_id).delete(synchronize_session=False)
        db.query(Document).filter_by(id=resource_id).delete(synchronize_session=False)


def resume_deletion(db: Session, operation_id: str) -> None:
    """在共用重建门禁内幂等推进删除；异常留下已提交阶段供重试或启动恢复。"""
    operation = db.get(DeletionOperation, operation_id, populate_existing=True)
    if operation is None or operation.status == "completed":
        return
    if operation.status == "pending":
        try:
            precheck_mutations_allowed(db)
            vectorstore.get_client()
        except Exception:
            db.rollback()
            raise

    def vectors(snapshot: RuntimeSnapshot) -> None:
        operation = db.get(DeletionOperation, operation_id, populate_existing=True)
        if operation is None or operation.status != "pending":
            return
        # 只持久化 generation，不复制模型凭据；原集合名不受后续配置影响。
        with use_snapshot(RuntimeSnapshot(snapshot.config, operation.generation)):
            if operation.resource_type == "bank":
                vectorstore.delete_bank_collection(operation.bank_id)
            else:
                vectorstore.delete_document_chunks(operation.bank_id, operation.resource_id)
        operation.status = "vectors_deleted"

    def sql(snapshot: RuntimeSnapshot) -> None:
        operation = db.get(DeletionOperation, operation_id, populate_existing=True)
        if operation is None or operation.status != "vectors_deleted":
            return
        _delete_material_sql(db, operation)
        operation.status = "sql_deleted"

    def files(snapshot: RuntimeSnapshot) -> None:
        operation = db.get(DeletionOperation, operation_id, populate_existing=True)
        if operation is None or operation.status != "sql_deleted":
            return
        paths, _ = _deletion_record(operation)
        children = []
        if operation.resource_type == "bank":
            children = db.query(DeletionOperation).filter(
                DeletionOperation.bank_id == operation.bank_id,
                DeletionOperation.resource_type == "document",
                DeletionOperation.status != "completed",
            ).populate_existing().all()
            for child in children:
                child_paths, _ = _deletion_record(child)
                paths.extend(child_paths)
        for value in set(paths):
            path = Path(value)
            path = path if path.is_absolute() else BASE_DIR / path
            try:
                path.unlink(missing_ok=True)
            except OSError as exc:
                raise AppError("DELETION_PENDING", "资料已移除，原件清理待重试", 503) from exc
        for child in children:
            child.status = "completed"
        operation.status = "completed"

    _delete_transaction(db, vectors)
    _delete_transaction(db, sql)
    _delete_transaction(db, files)
    db.expire_all()


def recover_pending_deletions(db: Session | None = None) -> int:
    """启动或运维恢复入口；逐项失败隔离，返回本次完整完成的操作数量。"""
    if db is None:
        from app.db import SessionLocal

        with SessionLocal() as session:
            return recover_pending_deletions(session)
    operation_ids = [row.id for row in db.query(DeletionOperation.id).filter(
        DeletionOperation.status != "completed",
    ).order_by(DeletionOperation.created_at).all()]
    completed = 0
    for operation_id in operation_ids:
        try:
            resume_deletion(db, operation_id)
            completed += 1
        except (AppError, SQLAlchemyError, vectorstore.VectorStoreError) as exc:
            db.rollback()
            logger.warning("Deletion recovery deferred type=%s", type(exc).__name__)
    return completed


def purge_bank(db: Session, bank: Bank, *, actor: User | None = None) -> None:
    """同步删除题库；仅完整完成所有阶段后返回，失败可幂等恢复。"""
    bank_id = bank.id
    expected_actor = (actor.id, actor.auth_version) if actor is not None else None
    operation_id = _prepare_deletion(db, "bank", bank_id, bank_id, expected_actor)
    resume_deletion(db, operation_id)


def purge_document(db: Session, doc: Document, *, actor: User | None = None) -> None:
    """同步删除资料；先提交 deleting 状态，保留历史试卷和未清理原件。"""
    purge_document_by_id(db, doc.bank_id, doc.id, actor=actor)


def purge_document_by_id(
    db: Session, bank_id: str, doc_id: str, *, actor: User | None = None,
) -> None:
    """文档行删除后仍按原路径推进持久操作，完整清理成功才返回。"""
    expected_actor = (actor.id, actor.auth_version) if actor is not None else None
    operation_id = _prepare_deletion(db, "document", doc_id, bank_id, expected_actor)
    resume_deletion(db, operation_id)


def get_member_or_404(db: Session, bank_id: str, member_ref: str) -> tuple[BankMember, User]:
    """member_ref 可传 BankMember.id，也可传 user_id（v2 路径参数为 user_id）。"""
    m = (
        db.query(BankMember)
        .filter(
            BankMember.bank_id == bank_id,
            BankMember.status == "active",
            (BankMember.id == member_ref) | (BankMember.user_id == member_ref),
        )
        .one_or_none()
    )
    if m is None:
        raise AppError("NOT_FOUND", "成员不存在", status_code=404)
    u = db.get(User, m.user_id, populate_existing=True)
    if u is None:
        raise AppError("NOT_FOUND", "成员账号不存在", 404)
    return m, u
