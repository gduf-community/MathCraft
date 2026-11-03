"""学习空间业务：编号、列表载荷、成员操作、解散。"""
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.deps import SpaceAccess
from app.errors import AppError
from app.models import SpaceMember, StudySpace, User
from app.models.base import new_id


def generate_space_code(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"SP{year}"
    base = db.query(func.count(StudySpace.id)).filter(StudySpace.code.like(f"{prefix}%")).scalar() or 0
    seq = base + 1
    while True:
        code = f"{prefix}{seq:04d}"
        if not db.query(StudySpace.id).filter(StudySpace.code == code).first():
            return code
        seq += 1


def member_count(db: Session, space_id: str) -> int:
    return (
        db.query(func.count(SpaceMember.id))
        .filter(SpaceMember.space_id == space_id, SpaceMember.status == "active")
        .scalar()
        or 0
    )


def student_count(db: Session, space_id: str) -> int:
    return (
        db.query(func.count(SpaceMember.id))
        .filter(
            SpaceMember.space_id == space_id,
            SpaceMember.status == "active",
            SpaceMember.role == "member",
        )
        .scalar()
        or 0
    )


def space_payload(db: Session, space: StudySpace, user: User) -> dict:
    member = (
        db.query(SpaceMember)
        .filter(
            SpaceMember.space_id == space.id,
            SpaceMember.user_id == user.id,
            SpaceMember.status == "active",
        )
        .one_or_none()
    )
    creator = db.get(User, space.creator_id)
    access = SpaceAccess(
        space=space,
        member=member,
        user=user,
        my_role=member.role if member else "member",
    )
    member_rows = (
        db.query(SpaceMember, User)
        .join(User, User.id == SpaceMember.user_id)
        .filter(SpaceMember.space_id == space.id, SpaceMember.status == "active")
        .order_by(SpaceMember.joined_at)
        .all()
    )
    return {
        "id": space.id,
        "name": space.name,
        "code": space.code,
        "creator": {"id": creator.id, "display_name": creator.display_name} if creator else None,
        "member_count": member_count(db, space.id),
        "student_count": student_count(db, space.id),
        "capacity": space.capacity,
        "status": space.status,
        "members": [u.display_name for _m, u in member_rows],
        **access.capabilities(),
    }


def member_payload(m: SpaceMember, u: User, me_id: str) -> dict:
    return {
        "id": m.id,
        "user": {"id": u.id, "display_name": u.display_name, "account": u.account},
        "role": m.role,
        "is_creator": m.role == "creator",
        "is_me": u.id == me_id,
        "joined_at": m.joined_at,
    }


def ensure_unique_name(db: Session, user_id: str, name: str, exclude_space_id: str | None = None) -> None:
    """同一教师名下不允许重名空间（排除解散的与自身）。"""
    q = db.query(StudySpace.id).filter(
        StudySpace.creator_id == user_id,
        StudySpace.status == "active",
        StudySpace.name == name,
    )
    if exclude_space_id:
        q = q.filter(StudySpace.id != exclude_space_id)
    if q.first() is not None:
        raise AppError("SPACE_NAME_EXISTS", "已存在同名学习空间，请换一个名称", status_code=409)


def create_space(db: Session, user: User, name: str, capacity: int) -> StudySpace:
    ensure_unique_name(db, user.id, name)
    space = StudySpace(
        id=new_id("sp"),
        name=name,
        code=generate_space_code(db),
        creator_id=user.id,
        capacity=capacity,
        status="active",
    )
    db.add(space)
    db.flush()
    db.add(SpaceMember(id=new_id("sm"), space_id=space.id, user_id=user.id, role="creator", status="active"))
    db.commit()
    db.refresh(space)
    return space


def dissolve_space(db: Session, space: StudySpace) -> None:
    space.status = "dissolved"
    db.query(SpaceMember).filter(SpaceMember.space_id == space.id).update({"status": "removed"})
    db.commit()


def get_active_member(db: Session, space_id: str, user_id: str) -> SpaceMember | None:
    return (
        db.query(SpaceMember)
        .filter(
            SpaceMember.space_id == space_id,
            SpaceMember.user_id == user_id,
            SpaceMember.status == "active",
        )
        .one_or_none()
    )


def remove_member(db: Session, space_id: str, user_id: str) -> None:
    member = get_active_member(db, space_id, user_id)
    if member is None:
        raise AppError("NOT_FOUND", "成员不存在", status_code=404)
    if member.role == "creator":
        raise AppError("FORBIDDEN", "不能移出创建者", status_code=403)
    member.status = "removed"
    db.commit()
