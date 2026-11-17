"""学习空间接口（v2 5.9）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import (
    SpaceAccess,
    get_current_user,
    get_space_access,
    require_space_creator,
    require_student,
    require_teacher,
)
from app.errors import AppError
from app.models import SpaceMember, StudySpace, User
from app.schemas.space import SpaceCreateBody, SpaceJoinBody, SpacePaperRead, SpaceUpdateBody
from app.services import papers, spaces

router = APIRouter(prefix="/api/spaces", tags=["spaces"])


@router.get("")
def list_spaces(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if user.role == "teacher":
        rows = (
            db.query(StudySpace)
            .filter(StudySpace.creator_id == user.id, StudySpace.status == "active")
            .order_by(StudySpace.created_at.desc())
            .all()
        )
    else:
        rows = (
            db.query(StudySpace)
            .join(SpaceMember, SpaceMember.space_id == StudySpace.id)
            .filter(
                SpaceMember.user_id == user.id,
                SpaceMember.status == "active",
                StudySpace.status == "active",
            )
            .order_by(StudySpace.created_at.desc())
            .all()
        )
    return [spaces.space_payload(db, s, user) for s in rows]


@router.post("", status_code=201)
def create_space(
    body: SpaceCreateBody,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    space = spaces.create_space(db, user, body.name.strip(), body.capacity)
    return spaces.space_payload(db, space, user)


@router.post("/join")
def join_space(
    body: SpaceJoinBody,
    user: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    space = spaces.join_space(db, user, body.code.strip().upper())
    return spaces.space_payload(db, space, user)


@router.get("/{space_id}")
def get_space(access: SpaceAccess = Depends(get_space_access), db: Session = Depends(get_db)):
    return spaces.space_payload(db, access.space, access.user)


@router.put("/{space_id}")
def update_space(
    body: SpaceUpdateBody,
    access: SpaceAccess = Depends(require_space_creator),
    db: Session = Depends(get_db),
):
    spaces.ensure_unique_name(db, access.user.id, body.name.strip(), exclude_space_id=access.space.id)
    access.space.name = body.name.strip()
    db.commit()
    return spaces.space_payload(db, access.space, access.user)


@router.delete("/{space_id}", status_code=204)
def dissolve_space(
    access: SpaceAccess = Depends(require_space_creator),
    db: Session = Depends(get_db),
):
    spaces.dissolve_space(db, access.space)
    return None


@router.post("/{space_id}/leave", status_code=204)
def leave_space(
    access: SpaceAccess = Depends(get_space_access),
    user: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    if access.is_creator:
        raise AppError("FORBIDDEN", "创建者不能退出空间，请解散空间", status_code=403)
    access.member.status = "left"
    db.commit()
    return None


@router.get("/{space_id}/members")
def list_members(
    access: SpaceAccess = Depends(get_space_access),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(SpaceMember, User)
        .join(User, User.id == SpaceMember.user_id)
        .filter(SpaceMember.space_id == access.space.id, SpaceMember.status == "active")
        .order_by(SpaceMember.joined_at)
        .all()
    )
    return [spaces.member_payload(m, u, access.user.id) for m, u in rows]


@router.delete("/{space_id}/members/{user_id}", status_code=204)
def remove_member(
    user_id: str,
    access: SpaceAccess = Depends(require_space_creator),
    db: Session = Depends(get_db),
):
    if user_id == access.user.id:
        raise AppError("FORBIDDEN", "不能移出自己", status_code=403)
    spaces.remove_member(db, access.space.id, user_id)
    return None


@router.get("/{space_id}/papers", response_model=list[SpacePaperRead])
def list_space_papers(
    access: SpaceAccess = Depends(get_space_access),
    db: Session = Depends(get_db),
):
    return papers.space_papers(db, access.space, access.user)
