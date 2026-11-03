"""题库与成员接口（v2 文档 5.3）。学生与教师共用，差异只来自题库内角色。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import (
    BankAccess,
    get_bank_access,
    get_current_user,
    require_bank_admin,
    require_bank_owner,
)
from app.errors import AppError
from app.models import Bank, BankMember, User
from app.models.base import new_id
from app.schemas.bank import BankCreateBody, BankJoinBody, BankUpdateBody, MemberRoleBody, TransferBody
from app.services import banks as bank_service

router = APIRouter(prefix="/api/banks", tags=["banks"])


@router.get("")
def list_banks(
    scope: str = "all",
    keyword: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """题库列表：scope=owned / joined / all，按名称模糊过滤。"""
    q = (
        db.query(Bank)
        .join(BankMember, BankMember.bank_id == Bank.id)
        .filter(Bank.status == "active", BankMember.user_id == user.id, BankMember.status == "active")
    )
    if scope == "owned":
        q = q.filter(BankMember.role == "owner")
    elif scope == "joined":
        q = q.filter(BankMember.role != "owner")
    banks = q.order_by(Bank.created_at.desc()).all()
    if keyword.strip():
        banks = [b for b in banks if keyword.strip() in b.name]
    return [bank_service.bank_payload(db, b, user) for b in banks]


@router.post("", status_code=201)
def create_bank(
    body: BankCreateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    bank = bank_service.create_bank(db, user, body.name.strip())
    return bank_service.bank_payload(db, bank, user)


@router.post("/join")
def join_bank_by_code(
    body: BankJoinBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按编号加入题库。"""
    code = body.code.strip().upper()
    bank = db.query(Bank).filter(Bank.code == code, Bank.status == "active").one_or_none()
    if bank is None:
        raise AppError("BANK_CODE_NOT_FOUND", "未找到该编号的题库，请确认后重试", status_code=404)
    member = (
        db.query(BankMember)
        .filter(BankMember.bank_id == bank.id, BankMember.user_id == user.id)
        .one_or_none()
    )
    if member and member.status == "active":
        raise AppError("ALREADY_IN_BANK", "你已在该题库中", status_code=409)
    if bank_service.member_count(db, bank.id) >= bank.capacity:
        raise AppError("BANK_FULL", "该题库人数已满", status_code=409)
    if member:
        member.status = "active"
        member.joined_at = datetime.now(timezone.utc)
    else:
        db.add(BankMember(id=new_id("bm"), bank_id=bank.id, user_id=user.id, role="member", status="active"))
    db.commit()
    return bank_service.bank_payload(db, bank, user)


@router.get("/{bank_id}")
def get_bank(access: BankAccess = Depends(get_bank_access), db: Session = Depends(get_db)):
    return bank_service.bank_payload(db, access.bank, access.user)


@router.put("/{bank_id}")
def update_bank(
    body: BankUpdateBody,
    access: BankAccess = Depends(require_bank_owner),
    db: Session = Depends(get_db),
):
    if body.name is not None:
        access.bank.name = body.name.strip()
    if body.admin_level is not None:
        access.bank.admin_level = body.admin_level
    db.commit()
    return bank_service.bank_payload(db, access.bank, access.user)


@router.delete("/{bank_id}", status_code=204)
def delete_bank(
    access: BankAccess = Depends(require_bank_owner),
    db: Session = Depends(get_db),
):
    bank_service.purge_bank(db, access.bank)
    return None


@router.post("/{bank_id}/quit", status_code=204)
def quit_bank(
    access: BankAccess = Depends(get_bank_access),
    db: Session = Depends(get_db),
):
    if access.is_owner:
        raise AppError("FORBIDDEN", "创建者不能退出题库，请先转让或删除", status_code=403)
    access.member.status = "quit"
    db.commit()
    return None


@router.get("/{bank_id}/members")
def list_members(
    access: BankAccess = Depends(get_bank_access),
    db: Session = Depends(get_db),
):
    members = (
        db.query(BankMember, User)
        .join(User, User.id == BankMember.user_id)
        .filter(BankMember.bank_id == access.bank.id, BankMember.status == "active")
        .order_by(BankMember.joined_at)
        .all()
    )
    return [
        bank_service.member_payload(m, u, access.member.user_id, access.bank)
        for m, u in members
    ]


@router.put("/{bank_id}/members/{member_id}/role", status_code=204)
def set_member_role(
    member_id: str,
    body: MemberRoleBody,
    access: BankAccess = Depends(require_bank_owner),
    db: Session = Depends(get_db),
):
    m, _u = bank_service.get_member_or_404(db, access.bank.id, member_id)
    if m.role == "owner":
        raise AppError("FORBIDDEN", "创建者的角色不可修改", status_code=403)
    m.role = body.role
    db.commit()
    return None


@router.delete("/{bank_id}/members/{member_id}", status_code=204)
def remove_member(
    member_id: str,
    access: BankAccess = Depends(require_bank_owner),
    db: Session = Depends(get_db),
):
    m, u = bank_service.get_member_or_404(db, access.bank.id, member_id)
    if m.role == "owner":
        raise AppError("FORBIDDEN", "不能移出创建者", status_code=403)
    if m.user_id == access.member.user_id:
        raise AppError("FORBIDDEN", "不能移出自己，请使用退出题库", status_code=403)
    db.delete(m)
    db.commit()
    return None


@router.post("/{bank_id}/transfer", status_code=204)
def transfer_bank(
    body: TransferBody,
    access: BankAccess = Depends(require_bank_owner),
    db: Session = Depends(get_db),
):
    m, u = bank_service.get_member_or_404(db, access.bank.id, body.target_user_id)
    if m.user_id == access.member.user_id:
        raise AppError("FORBIDDEN", "不能转让给自己", status_code=400)
    if m.role == "owner":
        raise AppError("FORBIDDEN", "该成员已是创建者", status_code=400)
    # 新创建者升 owner，原创建者降 admin；题库管理员级别置 super（v2 5.3 转让规则）
    # creator_id 同步转移，保证双方看到的"创建者"标签一致
    m.role = "owner"
    access.member.role = "admin"
    access.bank.creator_id = m.user_id
    access.bank.admin_level = "super"
    db.commit()
    return None
