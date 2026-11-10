"""站内通知服务：入库完成时给题库全体成员写通知。"""
from sqlalchemy.orm import Session

from app.models import BankMember, Document, Notification
from app.models.base import new_id


def notify_bank_ingest_done(db: Session, doc: Document, ok: bool, message: str) -> None:
    """文档入库成功或失败时，给题库全体有效成员各写一条站内通知。"""
    from app.models import Bank

    bank = db.get(Bank, doc.bank_id)
    if bank is None:
        return
    if ok:
        title = "文档入库完成"
        body = f"题库「{bank.name}」的文档「{doc.name}」已完成解析入库，可以开始使用"
        kind = "bank_ready"
    else:
        title = "文档入库失败"
        body = f"题库「{bank.name}」的文档「{doc.name}」入库失败：{message}"
        kind = "bank_failed"
    members = (
        db.query(BankMember)
        .filter(BankMember.bank_id == doc.bank_id, BankMember.status == "active")
        .all()
    )
    for member in members:
        db.add(Notification(
            id=new_id("nt"), user_id=member.user_id, kind=kind,
            title=title, body=body, bank_id=doc.bank_id, document_name=doc.name,
        ))
    db.commit()
