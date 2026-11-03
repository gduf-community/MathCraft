"""学生催交通知：列表（含未读角标数）、清除红点、单条已读与删除。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_student
from app.models import User
from app.services import papers

router = APIRouter(prefix="/api/urges", tags=["urges"])


@router.get("")
def my_urges(
    user: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """学生在其所在空间的催交记录，最早在前；unread_count 用于红点角标。"""
    return papers.urge_feed(db, user)


@router.post("/clear", status_code=204)
def clear_urges(
    user: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    papers.clear_urge_badge(db, user)
    return None


@router.post("/{urge_id}/read", status_code=204)
def read_urge(
    urge_id: str,
    user: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    """单条催交标记已读：角标消除该条。"""
    papers.mark_urge_read(db, user, urge_id)
    return None


@router.delete("/{urge_id}", status_code=204)
def delete_urge(
    urge_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除单条催交记录：创建教师或空间在读学生可删。"""
    papers.remove_urge(db, user, urge_id)
    return None
