"""题库与成员接口（v2 文档 5.3）。学生与教师共用，差异只来自题库内角色。"""
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from sqlalchemy import and_, exists, or_, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import (
    BankAccess,
    DeletionAccess,
    get_bank_access,
    get_current_user,
    lock_bank_access,
    require_bank_deletion_owner,
    require_bank_owner,
    require_teacher,
)
from app.errors import AppError
from app.models import Bank, BankMember, DeletionOperation, User
from app.models.base import new_id
from app.schemas.auth import ErrorResponse
from app.schemas.bank import (
    BankCreateBody, BankResponse, BankUpdateBody, MemberAddBody, MemberRoleBody, TransferBody,
)
from app.services import banks as bank_service
from app.services import documents as doc_service
from app.services.model_settings import get_effective_deepseek_key, get_effective_mineru_token
from app.services.rag_settings import assert_mutations_allowed

router = APIRouter(prefix="/api/banks", tags=["banks"])


@router.get("", response_model=list[BankResponse])
def list_banks(
    scope: str = "all",
    keyword: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """题库列表：scope=owned / joined / all，按名称模糊过滤。"""
    q = (
        db.query(Bank)
        .filter(or_(
            and_(Bank.status == "active", exists().where(
                BankMember.bank_id == Bank.id, BankMember.user_id == user.id,
                BankMember.status == "active",
            )),
            and_(Bank.creator_id == user.id, Bank.status.in_(("deleting", "deleted")),
                 exists().where(
                     DeletionOperation.bank_id == Bank.id,
                     DeletionOperation.resource_type == "bank",
                     DeletionOperation.resource_id == Bank.id,
                     DeletionOperation.status != "completed",
                 )),
        ))
    )
    if scope == "owned":
        q = q.filter(Bank.creator_id == user.id)
    elif scope == "joined":
        q = q.filter(Bank.creator_id != user.id)
    banks = q.order_by(Bank.created_at.desc()).all()
    if keyword.strip():
        banks = [b for b in banks if keyword.strip() in b.name]
    return [bank_service.bank_payload(db, b, user) for b in banks]


@router.post("", status_code=201)
def create_bank(
    body: BankCreateBody,
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    bank = bank_service.create_bank(db, user, body.name.strip())
    return bank_service.bank_payload(db, bank, user)


@router.post("/with-document", status_code=201)
def create_bank_with_document(
    background: BackgroundTasks,
    name: str = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(require_teacher),
    db: Session = Depends(get_db),
):
    """新建题库并上传首个文档：题库与文档一次创建，入库异步进行，立即返回预计耗时。"""
    content = file.file.read()
    assert_mutations_allowed(db)
    bank = bank_service.create_bank(db, user, name.strip(), commit=False)
    document = doc_service.queue_upload(
        db, background, bank.id, user.id,
        file.filename or "", content,
        get_effective_mineru_token(db, user.id),
        deepseek_api_key=get_effective_deepseek_key(db, user.id),
    )
    return {"bank": bank_service.bank_payload(db, bank, user), "document": document}


@router.post("/join")
def join_bank_by_code():
    """知识库／题库不再通过编号加入。"""
    raise AppError("BANK_JOIN_DISABLED", "请联系题库创建者添加成员", status_code=404)


@router.get("/{bank_id}")
def get_bank(access: BankAccess = Depends(get_bank_access), db: Session = Depends(get_db)):
    return bank_service.bank_payload(db, access.bank, access.user)


@router.put("/{bank_id}")
def update_bank(
    body: BankUpdateBody,
    access: BankAccess = Depends(require_bank_owner),
    db: Session = Depends(get_db),
):
    access = lock_bank_access(db, access, owner_required=True)
    if body.name is not None:
        access.bank.name = body.name.strip()
    db.commit()
    return bank_service.bank_payload(db, access.bank, access.user)


@router.delete("/{bank_id}", status_code=204, responses={
    503: {
        "model": ErrorResponse,
        "description": "删除未完成；资源保持不可用并保留恢复记录与待清理原件，可重试删除",
    },
})
def delete_bank(
    access: DeletionAccess = Depends(require_bank_deletion_owner),
    db: Session = Depends(get_db),
):
    bank_service.purge_bank(db, access.bank, actor=access.user)
    return None


@router.post("/{bank_id}/quit", status_code=204)
def quit_bank(
    access: BankAccess = Depends(get_bank_access),
    db: Session = Depends(get_db),
):
    access = lock_bank_access(db, access, owner_required=False)
    if access.is_owner:
        raise AppError("FORBIDDEN", "创建者不能退出题库，请先转让或删除", status_code=403)
    access.member.status = "quit"
    db.commit()
    return None


@router.post("/{bank_id}/members", status_code=201)
def add_member(
    body: MemberAddBody,
    access: BankAccess = Depends(require_bank_owner),
    db: Session = Depends(get_db),
):
    access = lock_bank_access(db, access, owner_required=True)
    target = db.query(User).filter(User.account == body.account.strip()).populate_existing().one_or_none()
    if target is None:
        raise AppError("USER_NOT_FOUND", "未找到该登录账号", status_code=404)
    member = (
        db.query(BankMember)
        .filter(BankMember.bank_id == access.bank.id, BankMember.user_id == target.id)
        .populate_existing().one_or_none()
    )
    if target.role not in {"teacher", "student"} or target.status != "active":
        raise AppError("FORBIDDEN", "只能添加启用的教师或学生账号", status_code=403)
    if member is not None and member.status == "active":
        raise AppError("ALREADY_IN_BANK", "该账号已是题库成员", status_code=409)
    if bank_service.member_count(db, access.bank.id) >= access.bank.capacity:
        raise AppError("BANK_FULL", "该题库人数已满", status_code=409)
    if member is None:
        member = BankMember(id=new_id("bm"), bank_id=access.bank.id, user_id=target.id, role=body.role, status="active")
        db.add(member)
    else:
        member.role = body.role
        member.status = "active"
        member.joined_at = datetime.now(timezone.utc)
    db.commit()
    return bank_service.member_payload(member, target, access.user.id, access.bank)


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
    access = lock_bank_access(db, access, owner_required=True)
    m, _u = bank_service.get_member_or_404(db, access.bank.id, member_id)
    if m.user_id == access.bank.creator_id:
        raise AppError("FORBIDDEN", "创建者的角色不可修改", status_code=403)
    if _u.role not in {"teacher", "student"} or _u.status != "active":
        raise AppError("FORBIDDEN", "该账号不能获得教学权限", status_code=403)
    m.role = body.role
    db.commit()
    return None


@router.delete("/{bank_id}/members/{member_id}", status_code=204)
def remove_member(
    member_id: str,
    access: BankAccess = Depends(require_bank_owner),
    db: Session = Depends(get_db),
):
    access = lock_bank_access(db, access, owner_required=True)
    m, u = bank_service.get_member_or_404(db, access.bank.id, member_id)
    if m.user_id == access.bank.creator_id:
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
    access = lock_bank_access(db, access, owner_required=True)
    m, u = bank_service.get_member_or_404(db, access.bank.id, body.target_user_id)
    if m.user_id == access.member.user_id:
        raise AppError("FORBIDDEN", "不能转让给自己", status_code=400)
    # 新创建者接管资源，原创建者降为可编辑成员
    # creator_id 同步转移，保证双方看到的"创建者"标签一致
    if u.role != "teacher" or u.status != "active":
        raise AppError("FORBIDDEN", "只能转让给启用的教师", status_code=403)
    result = db.execute(update(Bank).where(
        Bank.id == access.bank.id, Bank.creator_id == access.user.id, Bank.status == "active",
    ).values(creator_id=m.user_id, admin_level="super"),
        execution_options={"synchronize_session": False})
    if not isinstance(result, CursorResult) or result.rowcount != 1:
        raise AppError("FORBIDDEN", "题库创建者已变更，请刷新后重试", 403)
    db.query(BankMember).filter(
        BankMember.bank_id == access.bank.id, BankMember.role.in_(("creator", "owner")),
    ).update({"role": "editor"}, synchronize_session="fetch")
    m.role = "creator"
    access.member.role = "editor"
    db.commit()
    db.expire_all()
    return None
