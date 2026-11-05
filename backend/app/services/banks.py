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


def create_bank(db: Session, user: User, name: str) -> Bank:
    bank = Bank(id=new_id("bank"), name=name, code=generate_bank_code(db), creator_id=user.id, admin_level="super")
    db.add(bank)
    db.flush()
    db.add(BankMember(id=new_id("bm"), bank_id=bank.id, user_id=user.id, role="creator", status="active"))
    db.commit()
    db.refresh(bank)
    return bank


def purge_bank(db: Session, bank: Bank) -> None:
    """删除题库：成员/文档/切片/FTS/向量/题目/收藏一并清理，题库行置 deleted。"""
    bank_id = bank.id
    # 题目与收藏
    q_ids = [row[0] for row in db.query(Question.id).filter(Question.bank_id == bank_id).all()]
    if q_ids:
        db.query(Favorite).filter(Favorite.question_id.in_(q_ids)).delete(synchronize_session=False)
    db.query(Question).filter(Question.bank_id == bank_id).delete(synchronize_session=False)
    # 文档与切片
    fts.delete_bank(db, bank_id)
    docs = db.query(Document).filter(Document.bank_id == bank_id).all()
    for d in docs:
        p = Path(d.storage_path)
        if not p.is_absolute():
            p = BASE_DIR / p
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    db.query(Document).filter(Document.bank_id == bank_id).delete(synchronize_session=False)
    db.query(BankMember).filter(BankMember.bank_id == bank_id).delete(synchronize_session=False)
    bank.status = "deleted"
    db.commit()
    # 向量库 collection 整体删除
    vectorstore.delete_bank_collection(bank_id)


def purge_document(db: Session, doc: Document) -> None:
    """删除单个文档：文件、chunk、FTS、向量、批次与题目（历史试卷快照后续步骤处理）。"""
    from app.models import DocumentChunk, GenerationBatch

    fts.delete_document(db, doc.id)
    db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete(synchronize_session=False)
    q_ids = [row[0] for row in db.query(Question.id).filter(Question.document_id == doc.id).all()]
    if q_ids:
        db.query(Favorite).filter(Favorite.question_id.in_(q_ids)).delete(synchronize_session=False)
    db.query(Question).filter(Question.document_id == doc.id).delete(synchronize_session=False)
    db.query(GenerationBatch).filter(GenerationBatch.document_id == doc.id).delete(synchronize_session=False)
    db.delete(doc)
    db.commit()
    vectorstore.delete_document_chunks(doc.bank_id, doc.id)
    p = Path(doc.storage_path)
    if not p.is_absolute():
        p = BASE_DIR / p
    try:
        p.unlink(missing_ok=True)
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
