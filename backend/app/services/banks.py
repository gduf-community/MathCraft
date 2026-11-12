"""题库业务：编号生成、列表载荷、成员操作、删除清理。"""
from collections.abc import Callable
from datetime import datetime, timezone
import logging
from pathlib import Path
import sqlite3
from time import sleep

from sqlalchemy import func
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.errors import AppError
from app.models import Bank, BankMember, Document, Favorite, Question, User
from app.models.base import new_id
from app.services.auth import assert_version
from app.services.rag import fts, vectorstore
from app.services.rag_runtime import use_snapshot
from app.services.rag_settings import assert_mutations_allowed, precheck_mutations_allowed
from app.deps import normalize_bank_role, resolve_bank_access

logger = logging.getLogger(__name__)
_DELETE_ATTEMPTS = 3


def _authorize_purge(
    db: Session, bank_id: str, actor: tuple[str, int] | None, *, owner_required: bool,
) -> None:
    """在门禁写锁内按原认证版本重新授权，拒绝竞争期间撤销的访问权。"""
    if actor is None:
        return
    actor_id, version = actor
    assert_version(db, actor_id, version)
    current_user = db.get(User, actor_id, populate_existing=True)
    if current_user is None:
        raise AppError("SESSION_REVOKED", "认证状态已变更，请重新登录", 401)
    # resolve_bank_access 使用身份缓存；先刷新请求依赖可能已缓存的三个对象。
    db.get(Bank, bank_id, populate_existing=True)
    db.query(BankMember).filter_by(bank_id=bank_id, user_id=actor_id).populate_existing().all()
    access = resolve_bank_access(db, current_user, bank_id)
    if owner_required:
        if not access.is_owner or access.bank.creator_id != actor_id:
            raise AppError("FORBIDDEN", "该操作仅题库创建者可用", 403)
    elif not access.is_admin:
        raise AppError("FORBIDDEN", "该操作需要题库管理员权限", 403)


def _sqlite_lock_code(exc: Exception) -> int | None:
    """只识别 SQLite 原生锁竞争码，包含 BUSY_SNAPSHOT 等扩展码。"""
    if not isinstance(exc, OperationalError) or not isinstance(exc.orig, sqlite3.Error):
        return None
    code = getattr(exc.orig, "sqlite_errorcode", None)
    if isinstance(code, int) and code & 0xFF in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
        return code
    return None


def _purge_with_retry(
    db: Session,
    delete_sql: Callable[[], list[Path]],
    delete_vectors: Callable[[], None],
) -> list[Path]:
    """预热后执行门禁内删除；仅 SQL 锁竞争可回滚整个事务并有限重试。"""
    try:
        precheck_mutations_allowed(db)
        # 原生客户端冷启动可能很慢，不能占用应用 SQL 写锁。
        vectorstore.get_client()
    except Exception:
        db.rollback()
        raise
    attempt = 0
    while True:
        stage = "gate"
        try:
            # 直接使用已锁配置行的快照，禁止向量操作另开 SQLSession。
            with use_snapshot(assert_mutations_allowed(db)):
                stage = "sql"
                paths = delete_sql()
                stage = "vector"
                delete_vectors()
                stage = "commit"
                db.commit()
            return paths
        except Exception as exc:
            db.rollback()
            code = _sqlite_lock_code(exc)
            logger.warning("Delete failure stage=%s type=%s code=%s",
                           stage, type(exc).__name__, code)
            if stage == "vector" or code is None:
                raise
            attempt += 1
            if attempt >= _DELETE_ATTEMPTS:
                raise AppError("DATABASE_BUSY", "数据库繁忙，请稍后重试删除", 503) from exc
            # 退避前已释放旧事务及其 WAL 快照；下一轮重新读取全部删除对象。
            sleep(0.05 * attempt)


def generate_bank_code(db: Session) -> str:
    """TK + 年份 + 4 位序号；序号按当年已有题库数递增，冲突时步进重试。"""
    year = datetime.now(timezone.utc).year
    prefix = f"TK{year}"
    base = db.query(func.count(Bank.id)).filter(Bank.code.like(f"{prefix}%")).scalar() or 0
    seq = base + 1
    while True:
        code = f"{prefix}{seq:04d}"
        if not db.query(Bank.id).filter(Bank.code == code).first():
            return code
        seq += 1


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

    role = normalize_bank_role(member.role) if member else "readonly"
    access = BankAccess(bank=bank, member=member, user=user, my_role=role) if member else None
    return {
        "id": bank.id,
        "name": bank.name,
        "code": bank.code,
        "creator": {"id": creator.id, "display_name": creator.display_name} if creator else None,
        "member_count": member_count(db, bank.id),
        "capacity": bank.capacity,
        "source": "owned" if role == "creator" else "joined",
        "quitted": member is None,
        **(access.capabilities() if access else {
            "my_role": None, "can_upload_document": False, "can_download_document": False,
            "can_delete_document": False, "can_manage_members": False, "can_edit_bank": False,
            "can_transfer_bank": False, "can_delete_bank": False,
        }),
    }


def member_payload(m: BankMember, u: User, me_id: str, bank: Bank) -> dict:
    role = normalize_bank_role(m.role)
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


def purge_bank(db: Session, bank: Bank, *, actor: User | None = None) -> None:
    """向量删除成功后提交题库 SQL 清理，最后删除文件。

    向量故障会回滚 SQL 并保留文件，允许重试。SQL、Chroma 与文件系统不具备
    跨存储原子性：向量已删而 SQL 提交失败时，SQL/文件保留但需重新解析恢复向量；
    提交后文件清理失败可能遗留文件，不会回滚已完成的 SQL/向量删除。
    HTTP 调用须传 actor，每次尝试在门禁写锁内重新验证账号和创建者权限。
    """
    bank_id = bank.id
    expected_actor = (actor.id, actor.auth_version) if actor is not None else None

    def delete_sql() -> list[Path]:
        _authorize_purge(db, bank_id, expected_actor, owner_required=True)
        current = db.get(Bank, bank_id, populate_existing=True)
        if current is None:
            raise AppError("NOT_FOUND", "题库不存在", 404)
        paths = [Path(d.storage_path) for d in db.query(Document).filter_by(bank_id=bank_id)]
        q_ids = [row[0] for row in db.query(Question.id).filter_by(bank_id=bank_id).all()]
        if q_ids:
            db.query(Favorite).filter(Favorite.question_id.in_(q_ids)).delete(
                synchronize_session=False
            )
        db.query(Question).filter_by(bank_id=bank_id).delete(synchronize_session=False)
        fts.delete_bank(db, bank_id)
        db.query(Document).filter_by(bank_id=bank_id).delete(synchronize_session=False)
        db.query(BankMember).filter_by(bank_id=bank_id).delete(synchronize_session=False)
        current.status = "deleted"
        return paths

    paths = _purge_with_retry(db, delete_sql, lambda: vectorstore.delete_bank_collection(bank_id))
    for path in paths:
        path = path if path.is_absolute() else BASE_DIR / path
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def purge_document(db: Session, doc: Document, *, actor: User | None = None) -> None:
    """向量删除成功后提交文档 SQL 清理，最后删除文件。

    向量故障会回滚 SQL 并保留文件以便重试；SQL/Chroma/文件系统无法原子提交。
    向量已删而 SQL 提交失败时，保留的文档需重新解析恢复向量；提交后文件清理
    失败可能遗留文件。历史试卷快照不在本次清理范围内。
    HTTP 调用须传 actor，每次尝试在门禁写锁内重新验证账号和资料编辑权限。
    """
    from app.models import DocumentChunk, GenerationBatch

    bank_id, doc_id = doc.bank_id, doc.id
    expected_actor = (actor.id, actor.auth_version) if actor is not None else None

    def delete_sql() -> list[Path]:
        _authorize_purge(db, bank_id, expected_actor, owner_required=False)
        current = db.get(Document, doc_id, populate_existing=True)
        if current is None or current.bank_id != bank_id:
            raise AppError("NOT_FOUND", "文档不存在", 404)
        path = Path(current.storage_path)
        fts.delete_document(db, doc_id)
        db.query(DocumentChunk).filter_by(document_id=doc_id).delete(synchronize_session=False)
        q_ids = [row[0] for row in db.query(Question.id).filter_by(document_id=doc_id).all()]
        if q_ids:
            db.query(Favorite).filter(Favorite.question_id.in_(q_ids)).delete(
                synchronize_session=False
            )
        db.query(Question).filter_by(document_id=doc_id).delete(synchronize_session=False)
        db.query(GenerationBatch).filter_by(document_id=doc_id).delete(synchronize_session=False)
        db.delete(current)
        return [path]

    [path] = _purge_with_retry(
        db, delete_sql, lambda: vectorstore.delete_document_chunks(bank_id, doc_id),
    )
    path = path if path.is_absolute() else BASE_DIR / path
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


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
    u = db.get(User, m.user_id)
    return m, u
