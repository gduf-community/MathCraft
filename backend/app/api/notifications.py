"""站内通知接口：列表 + 未读数 + 标记已读 + 单条删除。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import AppError
from app.models import Notification, User
from app.schemas.notifications import NotificationReadBody

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


def _payload(n: Notification) -> dict:
    return {
        "id": n.id,
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "bank_id": n.bank_id,
        "document_name": n.document_name,
        "read": bool(n.read),
        "created_at": n.created_at,
    }


@router.get("")
def list_notifications(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user.id)
        .order_by(Notification.created_at.desc())
        .limit(50)
        .all()
    )
    unread = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read.is_(False))
        .count()
    )
    return {"unread_count": unread, "items": [_payload(n) for n in rows]}


@router.post("/read", status_code=204)
def mark_notifications_read(
    body: NotificationReadBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Notification).filter(
        Notification.user_id == user.id, Notification.read.is_(False)
    )
    if body.ids:
        q = q.filter(Notification.id.in_(body.ids))
    q.update({"read": True}, synchronize_session=False)
    db.commit()
    return None


@router.delete("/{notification_id}", status_code=204)
def delete_notification(
    notification_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除单条通知：仅本人可删。"""
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user.id:
        raise AppError("NOTIFICATION_NOT_FOUND", "通知不存在", status_code=404)
    db.delete(n)
    db.commit()
    return None
