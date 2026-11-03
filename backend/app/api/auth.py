"""认证接口：登录、当前用户、登出、修改密码（登录页公开版 + 已登录版）。"""
from fastapi import APIRouter, Depends
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, get_token
from app.errors import AppError
from app.models import User
from app.schemas.auth import ChangePasswordBody, LoginBody, PasswordBody
from app.services import auth as auth_service
from app.services import cache
from app.services.model_settings import user_payload

router = APIRouter(prefix="/api/auth", tags=["auth"])

ROLE_LABEL = {"student": "学生", "teacher": "教师"}


def _find_user_by_account(db: Session, account: str) -> User | None:
    return (
        db.query(User)
        .filter(
            or_(
                User.account == account,
                User.user_no == account,
                User.phone == account,
                User.email == account,
            )
        )
        .one_or_none()
    )


@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = _find_user_by_account(db, body.account.strip())
    if user is None or not auth_service.verify_password(body.password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "账号或密码不正确", status_code=401)
    if user.status != "active":
        raise AppError("ACCOUNT_DISABLED", "该账号已被禁用，请联系管理员", status_code=403)
    if user.role != body.role:
        raise AppError(
            "ROLE_MISMATCH",
            f"该账号是{ROLE_LABEL[user.role]}身份，请切换到{'老师' if user.role == 'teacher' else '学生'}标签登录",
            status_code=403,
        )
    token, expires_in = auth_service.create_session(cache.get_redis(), user.id)
    return {"token": token, "expires_in": expires_in, "user": user_payload(user)}


@router.get("/me")
def me(user: User = Depends(get_current_user)):
    return {"user": user_payload(user)}


@router.post("/logout", status_code=204)
def logout(token: str = Depends(get_token), _user: User = Depends(get_current_user)):
    auth_service.destroy_session(cache.get_redis(), token)
    return None


@router.post("/change-password", status_code=204)
def change_password_public(body: ChangePasswordBody, db: Session = Depends(get_db)):
    """登录页修改密码：账号 + 原密码验证，无需登录态。"""
    user = _find_user_by_account(db, body.account.strip())
    if user is None or not auth_service.verify_password(body.old_password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "账号或原密码不正确", status_code=401)
    if user.status != "active":
        raise AppError("ACCOUNT_DISABLED", "该账号已被禁用，请联系管理员", status_code=403)
    if user.role != body.role:
        raise AppError(
            "ROLE_MISMATCH",
            f"该账号是{ROLE_LABEL[user.role]}身份，请切换到{'老师' if user.role == 'teacher' else '学生'}标签后修改",
            status_code=403,
        )
    user.password_hash = auth_service.hash_password(body.new_password)
    db.commit()
    auth_service.destroy_user_sessions(cache.get_redis(), user.id)
    return None


@router.put("/password", status_code=204)
def change_password_logged_in(
    body: PasswordBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not auth_service.verify_password(body.old_password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "原密码不正确", status_code=400)
    user.password_hash = auth_service.hash_password(body.new_password)
    db.commit()
    auth_service.destroy_user_sessions(cache.get_redis(), user.id)
    return None
