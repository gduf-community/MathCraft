"""请求级依赖：当前用户、平台身份、题库权限（v2 文档 2.7）。"""
from dataclasses import dataclass

from fastapi import Depends, Header
from sqlalchemy.orm import Session

from app.db import get_db
from app.errors import AppError
from app.models import Bank, BankMember, Paper, SpaceMember, StudySpace, User
from app.services import auth as auth_service


def get_token(authorization: str | None = Header(default=None, alias="Authorization")) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise AppError("TOKEN_EXPIRED", "未登录或令牌格式错误", status_code=401)
    return authorization[len("Bearer ") :].strip()


def get_current_user(token: str = Depends(get_token), db: Session = Depends(get_db)) -> User:
    return auth_service.authenticate(db, token)


def require_teacher(user: User = Depends(get_current_user)) -> User:
    if user.role != "teacher":
        raise AppError("FORBIDDEN", "该操作仅教师可用", status_code=403)
    return user


def require_student(user: User = Depends(get_current_user)) -> User:
    if user.role != "student":
        raise AppError("FORBIDDEN", "该操作仅学生可用", status_code=403)
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != "admin":
        raise AppError("FORBIDDEN", "需要管理员权限", status_code=403)
    return user


@dataclass
class BankAccess:
    bank: Bank
    member: BankMember
    user: User
    my_role: str            # creator / editor / readonly

    @property
    def is_owner(self) -> bool:
        return self.my_role == "creator"

    @property
    def is_admin(self) -> bool:
        return self.my_role in ("creator", "editor")

    @property
    def is_super_admin(self) -> bool:
        return self.my_role == "creator"

    def capabilities(self) -> dict:
        return {
            "my_role": self.my_role,
            "can_upload_document": self.is_admin,
            "can_download_document": True,
            "can_delete_document": self.is_admin,
            "can_manage_members": self.is_owner,
            "can_edit_bank": self.is_owner,
            "can_transfer_bank": self.is_owner,
            "can_delete_bank": self.is_owner,
        }


def normalize_bank_role(role: str) -> str:
    return {"owner": "creator", "admin": "readonly", "member": "readonly"}.get(role, role)


def resolve_bank_access(db: Session, user: User, bank_id: str) -> BankAccess:
    """在非路径参数场景（如 bank_id 位于请求体）手动解析题库权限。"""
    if user.role not in {"teacher", "student"}:
        raise AppError("FORBIDDEN", "管理员账号不具备教学资源权限", status_code=403)
    bank = db.get(Bank, bank_id)
    if bank is None or bank.status != "active":
        raise AppError("BANK_NOT_FOUND", "题库不存在或已被删除", status_code=404)
    member = (
        db.query(BankMember)
        .filter(BankMember.bank_id == bank_id, BankMember.user_id == user.id, BankMember.status == "active")
        .one_or_none()
    )
    if member is None:
        raise AppError("BANK_NOT_FOUND", "题库不存在或你不是该题库成员", status_code=404)
    return BankAccess(bank=bank, member=member, user=user, my_role=normalize_bank_role(member.role))


def get_bank_access(
    bank_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> BankAccess:
    """题库成员校验：非成员 404（不暴露他人题库存在性）。"""
    return resolve_bank_access(db, user, bank_id)


def require_bank_admin(access: BankAccess = Depends(get_bank_access)) -> BankAccess:
    if not access.is_admin:
        raise AppError("FORBIDDEN", "该操作需要题库管理员权限", status_code=403)
    return access


def require_bank_super_admin(access: BankAccess = Depends(get_bank_access)) -> BankAccess:
    if not access.is_super_admin:
        raise AppError("FORBIDDEN", "该操作需要超级管理员权限", status_code=403)
    return access


def require_bank_owner(access: BankAccess = Depends(get_bank_access)) -> BankAccess:
    if not access.is_owner:
        raise AppError("FORBIDDEN", "该操作仅题库创建者可用", status_code=403)
    return access


@dataclass
class SpaceAccess:
    space: StudySpace
    member: SpaceMember
    user: User
    my_role: str            # creator / member

    @property
    def is_creator(self) -> bool:
        return self.my_role == "creator"

    def capabilities(self) -> dict:
        return {
            "my_role": self.my_role,
            "can_edit_space": self.is_creator,
            "can_dissolve_space": self.is_creator,
            "can_remove_member": self.is_creator,
            "can_publish_paper": self.is_creator and self.user.role == "teacher",
            "can_answer_paper": self.my_role == "member" and self.user.role == "student",
            "can_leave_space": self.my_role == "member" and self.user.role == "student",
        }


def resolve_space_access(db: Session, user: User, space_id: str) -> SpaceAccess:
    space = db.get(StudySpace, space_id)
    if space is None or space.status != "active":
        raise AppError("SPACE_NOT_FOUND", "学习空间不存在或已解散", status_code=404)
    member = (
        db.query(SpaceMember)
        .filter(SpaceMember.space_id == space_id, SpaceMember.user_id == user.id, SpaceMember.status == "active")
        .one_or_none()
    )
    if member is None:
        raise AppError("SPACE_NOT_FOUND", "学习空间不存在或你不是该空间成员", status_code=404)
    return SpaceAccess(space=space, member=member, user=user, my_role=member.role)


def get_space_access(
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> SpaceAccess:
    return resolve_space_access(db, user, space_id)


def require_space_member(access: SpaceAccess = Depends(get_space_access)) -> SpaceAccess:
    return access


def require_space_creator(access: SpaceAccess = Depends(get_space_access)) -> SpaceAccess:
    if not access.is_creator:
        raise AppError("FORBIDDEN", "该操作仅空间创建者可用", status_code=403)
    return access


def require_paper_owner(
    paper_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Paper:
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise AppError("PAPER_NOT_FOUND", "试卷不存在或已被删除", status_code=404)
    if paper.owner_id != user.id:
        raise AppError("FORBIDDEN", "只能操作自己创建的试卷", status_code=403)
    return paper
