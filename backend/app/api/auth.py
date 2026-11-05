"""认证接口：登录、当前用户、登出、修改密码（登录页公开版 + 已登录版）。"""
from fastapi import APIRouter, Depends
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


def _find_user_by_account(db: Session, account: str) -> User | None:
    return db.query(User).filter(User.account == account).one_or_none()


@router.post("/login")
def login(body: LoginBody, db: Session = Depends(get_db)):
    user = _find_user_by_account(db, body.account.strip())
    if user is None or not auth_service.verify_password(body.password, user.password_hash):
        raise AppError("INVALID_CREDENTIALS", "账号或密码不正确", status_code=401)
    if user.status != "active":
        raise AppError("ACCOUNT_DISABLED", "该账号已被禁用，请联系管理员", status_code=403)
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
