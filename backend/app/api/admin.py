"""平台管理员账号管理与平台信息接口。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import require_admin
from app.errors import AppError
from app.models import Bank, Document, GenerationBatch, Paper, User, UserModelSetting
from app.models.base import new_id
from app.schemas.admin import (
    AccountCreateBody, AccountDisplayNameBody, AccountListItem, AccountPasswordBody, PlatformOverview,
)
from app.services import auth as auth_service

router = APIRouter(prefix="/api/admin", tags=["admin"])
ROLE_LABELS = {"admin": "管理员", "teacher": "教师", "student": "学生"}


def _account_item(user: User) -> dict:
    return {
        "id": user.id,
        "account": user.account,
        "display_name": user.display_name,
        "role": user.role,
        "identity": user.identity,
        "status": user.status,
        "created_at": user.created_at,
        "password_change_recommended": user.password_change_recommended,
    }


def _get_account(db: Session, user_id: str) -> User:
    user = (db.query(User).filter(User.id == user_id).populate_existing()
            .with_for_update().one_or_none())
    if user is None:
        raise AppError("NOT_FOUND", "账号不存在", status_code=404)
    return user


def _ensure_admin_count(db: Session, target: User) -> None:
    if target.role == "admin" and target.status == "active":
        active_ids = (db.query(User.id).filter(User.role == "admin", User.status == "active")
                      .with_for_update().all())
        if len(active_ids) <= 1:
            raise AppError("LAST_ADMIN", "不能禁用最后一个可用管理员", status_code=409)


def _lock_admin_write(db: Session, admin: User) -> None:
    """所有管理员写操作共享数据库锁，并在锁内重新验证发起者。

    SQLite 的无值变更 UPDATE 获取数据库写锁；行锁数据库锁定同一组管理员。
    包含禁用管理员使恢复也参与串行化。锁一直持有到操作提交或回滚，
    必须在目标账号读取、最后管理员计数及任何写入之前调用。
    """
    actor_id, version = admin.id, admin.auth_version
    db.execute(
        update(User).where(User.role == "admin").values(
            auth_version=User.auth_version, updated_at=User.updated_at,
        ), execution_options={"synchronize_session": False},
    )
    auth_service.assert_version(db, actor_id, version)


@router.get("/accounts", response_model=list[AccountListItem])
def list_accounts(
    query: str = Query(default=""),
    role: str | None = Query(default=None, pattern="^(admin|teacher|student)$"),
    status: str | None = Query(default=None, pattern="^(active|disabled)$"),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(User)
    if query.strip():
        text = f"%{query.strip()}%"
        q = q.filter((User.account.ilike(text)) | (User.display_name.ilike(text)))
    if role:
        q = q.filter(User.role == role)
    if status:
        q = q.filter(User.status == status)
    return [_account_item(user) for user in q.order_by(User.created_at.desc()).all()]


@router.post("/accounts", status_code=201, response_model=AccountListItem)
def create_account(
    body: AccountCreateBody,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _lock_admin_write(db, _admin)
    account = body.account.strip()
    if db.query(User).filter(User.account == account).first() is not None:
        raise AppError("ACCOUNT_EXISTS", "登录账号已存在", status_code=409)
    user = User(
        id=new_id("u"),
        account=account,
        password_hash=auth_service.hash_password(body.password),
        role=body.role,
        identity=ROLE_LABELS[body.role],
        display_name=body.display_name.strip(),
        status="active",
        password_change_recommended=True,
    )
    try:
        db.add(user)
        db.flush()
        db.add(UserModelSetting(user_id=user.id))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("ACCOUNT_EXISTS", "登录账号已存在", status_code=409) from exc
    db.refresh(user)
    return _account_item(user)


@router.patch("/accounts/{user_id}", response_model=AccountListItem)
def update_account(
    user_id: str,
    body: AccountDisplayNameBody,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _lock_admin_write(db, _admin)
    user = _get_account(db, user_id)
    user.display_name = body.display_name.strip()
    db.commit()
    db.refresh(user)
    return _account_item(user)


@router.post("/accounts/{user_id}/reset-password", status_code=204)
def reset_password(
    user_id: str,
    body: AccountPasswordBody,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _lock_admin_write(db, _admin)
    user = _get_account(db, user_id)
    auth_service.revoke_all(db, user, user.auth_version, allow_disabled=True)
    user.password_hash = auth_service.hash_password(body.password)
    user.password_change_recommended = True
    db.commit()
    return None


@router.post("/accounts/{user_id}/disable", status_code=204)
def disable_account(
    user_id: str,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _lock_admin_write(db, _admin)
    user = _get_account(db, user_id)
    _ensure_admin_count(db, user)
    if user.status == "active":
        auth_service.revoke_all(db, user, user.auth_version)
    user.status = "disabled"
    db.commit()
    return None


@router.post("/accounts/{user_id}/restore", status_code=204)
def restore_account(
    user_id: str,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _lock_admin_write(db, _admin)
    user = _get_account(db, user_id)
    user.status = "active"
    db.commit()
    return None


@router.get("/overview", response_model=PlatformOverview)
def overview(_admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    account_rows = db.query(User.role, User.status, func.count(User.id)).group_by(User.role, User.status).all()
    accounts = {f"{role}_{status}": count for role, status, count in account_rows}
    resources = {
        "banks": db.query(Bank).filter(Bank.status == "active").count(),
        "documents": db.query(Document).count(),
        "papers": db.query(Paper).count(),
    }
    task_rows = (db.query(GenerationBatch)
                 .order_by(GenerationBatch.created_at.desc(), GenerationBatch.id.desc())
                 .limit(50).all())
    status_counts = dict(db.query(
        GenerationBatch.status, func.count(GenerationBatch.id),
    ).group_by(GenerationBatch.status).all())
    tasks = [
        {
            "id": row.id,
            "type": row.mode,
            "status": row.status,
            "created_at": row.created_at,
            "completed_at": None,
        }
        for row in task_rows
    ]
    return {
        "admin_contact": settings.admin_contact,
        "accounts": accounts,
        "resources": resources,
        "task_status_counts": dict(status_counts),
        "task_scope": "persisted_generation_batches",
        "task_total": sum(status_counts.values()),
        "recent_task_limit": 50,
        "tasks": tasks,
    }
