"""学习空间业务：编号、列表载荷、成员操作、解散。"""
import secrets

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.deps import SpaceAccess, lock_resource
from app.errors import AppError
from app.models import SpaceMember, StudySpace, User
from app.models.base import new_id
from app.services.auth import assert_version


CODE_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def generate_space_code(db: Session) -> str:
    """生成 10 位随机编号（SP 前缀 + 8 位随机字符），编号同时作为邀请凭据。"""
    while True:
        code = "SP" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
        if not db.query(StudySpace.id).filter(StudySpace.code == code).first():
            return code


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
    if member is None:
        raise AppError("SPACE_NOT_FOUND", "学习空间不存在或你不是该空间成员", 404)
    creator = db.get(User, space.creator_id)
    access = SpaceAccess(
        space=space,
        member=member,
        user=user,
        my_role=member.role,
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


def join_space(db: Session, user: User, code: str) -> StudySpace:
    """在空间写锁内重读账号与容量，并原子提交成员关系。"""
    actor_id, version = user.id, user.auth_version
    space = db.query(StudySpace).filter_by(code=code, status="active").one_or_none()
    if space is None:
        raise AppError("SPACE_CODE_NOT_FOUND", "未找到该编号的学习空间", 404)
    space_id = space.id
    lock_resource(db, StudySpace, space_id)
    assert_version(db, actor_id, version)
    current_user = db.get(User, actor_id, populate_existing=True)
    if current_user is None or current_user.role != "student":
        raise AppError("FORBIDDEN", "该操作仅学生可用", 403)
    space = db.get(StudySpace, space_id, populate_existing=True)
    if space is None or space.status != "active" or space.code != code:
        raise AppError("SPACE_CODE_NOT_FOUND", "未找到该编号的学习空间", 404)
    existing = db.query(SpaceMember).filter_by(
        space_id=space_id, user_id=actor_id,
    ).populate_existing().one_or_none()
    if existing is not None and existing.status == "removed":
        raise AppError("SPACE_JOIN_FORBIDDEN", "已被移出该空间，请联系创建者", 403)
    if existing is not None and existing.status == "active":
        raise AppError("ALREADY_IN_SPACE", "你已在该学习空间中", 409)
    if member_count(db, space_id) >= space.capacity:
        raise AppError("SPACE_FULL", "该学习空间人数已满", 409)
    if existing is None:
        db.add(SpaceMember(id=new_id("sm"), space_id=space_id, user_id=actor_id,
                           role="member", status="active"))
    else:
        existing.status = "active"
        existing.role = "member"
    db.commit()
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
