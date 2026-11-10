"""题库业务：编号生成、列表载荷、成员操作、删除清理。"""
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import BASE_DIR
from app.errors import AppError
from app.models import Bank, BankMember, Document, Favorite, Question, User
from app.models.base import new_id
from app.services.rag import fts, vectorstore
from app.services.rag_settings import assert_mutations_allowed
from app.deps import normalize_bank_role


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


def purge_bank(db: Session, bank: Bank) -> None:
    """向量删除成功后提交题库 SQL 清理，最后删除文件。

    向量故障会回滚 SQL 并保留文件，允许重试。SQL、Chroma 与文件系统不具备
    跨存储原子性：向量已删而 SQL 提交失败时，SQL/文件保留但需重新解析恢复向量；
    提交后文件清理失败可能遗留文件，不会回滚已完成的 SQL/向量删除。
    """
    try:
        assert_mutations_allowed(db)
        bank_id = bank.id
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
        bank.status = "deleted"
        # SQL 仍在事务内；向量异常时回滚，禁止提前删除任何文件。
        vectorstore.delete_bank_collection(bank_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
    for path in paths:
        path = path if path.is_absolute() else BASE_DIR / path
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


def purge_document(db: Session, doc: Document) -> None:
    """向量删除成功后提交文档 SQL 清理，最后删除文件。

    向量故障会回滚 SQL 并保留文件以便重试；SQL/Chroma/文件系统无法原子提交。
    向量已删而 SQL 提交失败时，保留的文档需重新解析恢复向量；提交后文件清理
    失败可能遗留文件。历史试卷快照不在本次清理范围内。
    """
    from app.models import DocumentChunk, GenerationBatch

    try:
        assert_mutations_allowed(db)
        bank_id, doc_id = doc.bank_id, doc.id
        path = Path(doc.storage_path)
        fts.delete_document(db, doc_id)
        db.query(DocumentChunk).filter_by(document_id=doc_id).delete(synchronize_session=False)
        q_ids = [row[0] for row in db.query(Question.id).filter_by(document_id=doc_id).all()]
        if q_ids:
            db.query(Favorite).filter(Favorite.question_id.in_(q_ids)).delete(
                synchronize_session=False
            )
        db.query(Question).filter_by(document_id=doc_id).delete(synchronize_session=False)
        db.query(GenerationBatch).filter_by(document_id=doc_id).delete(synchronize_session=False)
        db.delete(doc)
        vectorstore.delete_document_chunks(bank_id, doc_id)
        db.commit()
    except Exception:
        db.rollback()
        raise
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
