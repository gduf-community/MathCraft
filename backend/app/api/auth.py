"""认证闭环：注册、两种登录、刷新、撤销及密码恢复。"""
import ipaddress
import secrets
from datetime import datetime, timezone
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Header, Request, Response
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.auth_http import clear_refresh
from app.config import settings
from app.db import get_db
from app.deps import get_current_user, get_token
from app.errors import AppError
from app.models import AuthSession, RefreshUse, User, UserModelSetting
from app.models.base import new_id
from app.schemas.auth import (
    AuthConfig,
    CurrentUserResult,
    DevelopmentAccount,
    EmailCodeBody,
    EmailCodeResult,
    EmailLoginBody,
    EmptyBody,
    LoginResult,
    PasswordBody,
    PasswordLoginBody,
    RegisterBody,
    ResetPasswordBody,
    Role,
)
from app.services import auth as service
from app.services import auth_codes
from app.services.auth_delivery import (MailSender, TurnstileVerifier,
    get_mail_sender, get_turnstile_verifier)
from app.services.model_settings import user_payload

router = APIRouter(prefix="/api/auth", tags=["auth"])
REFRESH_COOKIE = "mc_refresh"
CSRF_COOKIE = "mc_csrf"
Mail = Annotated[MailSender, Depends(get_mail_sender)]
Verifier = Annotated[TurnstileVerifier, Depends(get_turnstile_verifier)]


def remote_ip(request: Request) -> str:
    """仅使用 ASGI peer；可信代理应由服务器显式配置，忽略任意转发头。"""
    return request.client.host if request.client else "unknown"


def check_cookie_request(
    request: Request,
    origin: str | None = Header(default=None, alias="Origin",
        description="可信前端来源；缺失或不可信时返回 403。"),
    csrf: str | None = Header(default=None, alias="X-CSRF-Token",
        description="必须与 mc_csrf Cookie 一致；缺失或不匹配时返回 403。"),
    cookie: str | None = Cookie(default=None, alias=CSRF_COOKIE,
        description="由认证配置接口设置的双提交 CSRF Cookie；缺失时返回 403。"),
) -> None:
    """声明 Cookie 请求契约，同时保留现有来源与 CSRF 拒绝语义。"""
    origin = request.headers.get("origin")
    csrf = request.headers.get("x-csrf-token", "")
    cookie = request.cookies.get(CSRF_COOKIE, "")
    if (origin not in settings.cors_origin_list()
            or request.headers.get("content-type", "").split(";")[0].strip() != "application/json"
            or not csrf or not cookie or not secrets.compare_digest(csrf, cookie)):
        raise AppError("AUTH_FAILED", "请求来源或 CSRF 校验失败", 403)


def set_refresh(response: Response, refresh: str) -> None:
    response.set_cookie(REFRESH_COOKIE, refresh, max_age=settings.auth_refresh_ttl_seconds,
        httponly=True, secure=settings.app_env == "production", samesite="lax", path="/api/auth")
    response.headers["Cache-Control"] = "no-store"


def login_result(db: Session, response: Response, user: User, version: int) -> dict:
    access, expires, refresh = service.create_session(db, user, version)
    db.commit()
    set_refresh(response, refresh)
    return {"access_token": access, "token_type": "bearer", "expires_in": expires,
            "user": user_payload(user)}


def check_user(user: User | None, role: str) -> User:
    if user is None or user.status != "active" or not (user.email_verified or user.email_verified_at):
        raise AppError("AUTH_FAILED", "账号或凭据不正确", 401)
    if user.role != role:
        raise AppError("ROLE_MISMATCH", "账号身份不匹配", 403)
    return user


def code_binding(email: str, purpose: str, version: int | None = None) -> str:
    return f"{purpose}:{email}:{version if version is not None else '-'}"


@router.get("/config", response_model=AuthConfig)
def auth_config(response: Response):
    csrf = secrets.token_urlsafe(32)
    response.set_cookie(CSRF_COOKIE, csrf, httponly=False, secure=settings.app_env == "production",
                        samesite="lax", path="/api/auth")
    response.headers["Cache-Control"] = "no-store"
    return {"site_key": settings.turnstile_site_key, "csrf_token": csrf,
            "methods": ["email_code", "user_no_password"],
            "development_accounts_enabled": (settings.app_env == "development"
                                              and settings.dev_accounts_enabled),
            "available": bool(settings.auth_jwt_secret and settings.auth_code_secret
                              and settings.turnstile_site_key)}


@router.post("/email-code", status_code=202, response_model=EmailCodeResult)
def email_code(body: EmailCodeBody, request: Request, sender: Mail, verifier: Verifier,
               background_tasks: BackgroundTasks,
               db: Session = Depends(get_db)):
    service.require_auth_config()
    verifier.verify(body.turnstile_token, "email_code", remote_ip(request))
    email = body.email
    binding = code_binding(email, body.purpose)
    deliver = True
    if body.purpose.startswith("email_change_"):
        authorization = request.headers.get("authorization", "")
        if not authorization.startswith("Bearer ") or not body.change_id:
            raise AppError("TOKEN_EXPIRED", "换绑发码需要有效登录态", 401)
        user = service.authenticate(db, authorization[7:].strip())
        change = service.get_change(db, user, body.change_id)
        email = change.old_email if body.purpose == "email_change_old" else change.new_email
        if body.email != email:
            raise AppError("AUTH_FAILED", "收件人与邮箱变更事务不匹配", 400)
        binding = service.change_binding(change, body.purpose)
    elif body.purpose in {"login", "reset_password"}:
        user = db.query(User).filter_by(email_normalized=email).one_or_none()
        deliver = bool(user and (user.email_verified or user.email_verified_at) and user.status == "active")
        binding = code_binding(email, body.purpose, user.auth_version if user else -1)
    elif body.purpose == "register":
        deliver = db.query(User).filter_by(email_normalized=email).first() is None
    return auth_codes.issue(
        email, body.purpose, binding, remote_ip(request), sender, deliver, background_tasks,
    )


@router.post("/register", status_code=201, response_model=LoginResult)
def register(body: RegisterBody, response: Response, db: Session = Depends(get_db)):
    service.require_auth_config()
    auth_codes.verify(db, body.email, "register", code_binding(body.email, "register"),
                      body.challenge_id, body.code)
    user = User(id=new_id("u"), account=secrets.token_urlsafe(24), email=body.email,
        email_normalized=body.email, email_verified=True,
        email_verified_at=datetime.now(timezone.utc), password_hash=service.hash_password(body.password),
        role=body.role, identity="教师" if body.role == "teacher" else "学生",
        display_name=body.display_name, user_no=body.user_no, auth_version=0)
    try:
        db.add(user)
        db.flush()
        db.add(UserModelSetting(user_id=user.id))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if db.query(User).filter_by(email_normalized=body.email).first():
            raise AppError("EMAIL_IN_USE", "邮箱已被使用", 409) from exc
        raise AppError("USER_NO_IN_USE", "学工号已被使用", 409) from exc
    try:
        return login_result(db, response, user, 0)
    except Exception as exc:
        db.rollback()
        raise AppError("AUTH_SERVICE_UNAVAILABLE", "账号已创建，请登录", 503,
                       account_created=True) from exc


@router.post("/login/email", response_model=LoginResult)
def login_email(body: EmailLoginBody, response: Response, db: Session = Depends(get_db)):
    user = check_user(db.query(User).filter_by(email_normalized=body.email).one_or_none(), body.role)
    version = user.auth_version
    auth_codes.verify(db, body.email, "login", code_binding(body.email, "login", version),
                      body.challenge_id, body.code)
    return login_result(db, response, user, version)


@router.post("/login/password", response_model=LoginResult)
def login_password(body: PasswordLoginBody, request: Request, response: Response,
                   verifier: Verifier, db: Session = Depends(get_db)):
    service.require_auth_config()
    verifier.verify(body.turnstile_token, "password_login", remote_ip(request))
    user = db.query(User).filter_by(user_no=body.user_no).one_or_none()
    version = user.auth_version if user else -1
    if user is None or not service.verify_password(body.password, user.password_hash):
        raise AppError("AUTH_FAILED", "账号或凭据不正确", 401)
    user = check_user(user, body.role)
    return login_result(db, response, user, version)


@router.get("/me", response_model=CurrentUserResult)
def me(user: User = Depends(get_current_user)):
    return {"user": user_payload(user)}


@router.post("/refresh", response_model=LoginResult,
             dependencies=[Depends(check_cookie_request)])
def refresh(
    body: EmptyBody,
    request: Request,
    response: Response,
    mc_refresh: str = Cookie(alias=REFRESH_COOKIE),
    db: Session = Depends(get_db),
):
    check_cookie_request(request)
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise AppError("SESSION_REVOKED", "刷新会话不存在", 401)
    access, expires, replacement, user = service.rotate_refresh(db, token)
    set_refresh(response, replacement)
    return {"access_token": access, "token_type": "bearer", "expires_in": expires,
            "user": user_payload(user)}


@router.post("/logout", status_code=204, response_model=None,
             dependencies=[Depends(check_cookie_request)])
def logout(
    body: EmptyBody,
    request: Request,
    response: Response,
    token: str = Depends(get_token),
    mc_refresh: str | None = Cookie(default=None, alias=REFRESH_COOKIE),
    db: Session = Depends(get_db),
):
    # 注销以本标签签名 access 中的 sid 为准；共享 Cookie 不能选定撤销对象。
    claims = service.decode_access(token, allow_expired=True)
    session = db.get(AuthSession, claims["sid"])
    if (session is None or session.user_id != claims["sub"]
            or session.auth_version != claims["auth_version"]):
        raise AppError("SESSION_REVOKED", "登录会话不存在", 401)
    cookie_sid = None
    if mc_refresh:
        digest = service.digest_token(mc_refresh)
        cookie_session = db.query(AuthSession).filter_by(refresh_digest=digest).one_or_none()
        used = db.get(RefreshUse, digest)
        cookie_sid = cookie_session.id if cookie_session else used.session_id if used else None
    db.execute(update(AuthSession).where(AuthSession.id == session.id).values(status="revoked"))
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    if cookie_sid == session.id:
        clear_refresh(response)


@router.post("/password/reset", status_code=204, response_model=None)
def reset_password(body: ResetPasswordBody, response: Response, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(email_normalized=body.email).one_or_none()
    if user is None or not (user.email_verified or user.email_verified_at) or user.status != "active":
        raise AppError("CODE_INVALID", "邮箱或验证码无效", 400)
    version = user.auth_version
    auth_codes.verify(db, body.email, "reset_password", code_binding(body.email, "reset_password", version),
                      body.challenge_id, body.code)
    service.revoke_all(db, user, version)
    user.password_hash = service.hash_password(body.new_password)
    db.commit()
    clear_refresh(response)


@router.put("/password", status_code=204, response_model=None)
def change_password(body: PasswordBody, response: Response,
                    user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    version = user.auth_version
    if not service.verify_password(body.old_password, user.password_hash):
        raise AppError("AUTH_FAILED", "原密码不正确", 400)
    service.revoke_all(db, user, version)
    user.password_hash = service.hash_password(body.new_password)
    db.commit()
    clear_refresh(response)


def loopback(value: str) -> bool:
    try:
        return ipaddress.ip_address(value).is_loopback
    except ValueError:
        return value == "localhost"


# 生产根本不挂载开发凭据端点。
if settings.app_env == "development" and settings.dev_accounts_enabled:
    @router.get("/development-account", response_model=DevelopmentAccount)
    @router.post("/development-account", response_model=DevelopmentAccount)
    def development_account(role: Role, request: Request, response: Response):
        origin = request.headers.get("origin", "")
        if (not loopback(remote_ip(request)) or not loopback(request.url.hostname or "")
                or origin not in settings.cors_origin_list()
                or not loopback(urlsplit(origin).hostname or "")
                or any(h in request.headers for h in ("forwarded", "x-forwarded-for", "x-real-ip"))):
            raise AppError("AUTH_FAILED", "开发账号仅允许本机直连", 403)
        response.headers["Cache-Control"] = "no-store"
        user_no = getattr(settings, f"dev_{role}_user_no")
        password = getattr(settings, f"dev_{role}_password")
        if not user_no or not password:
            raise AppError("AUTH_SERVICE_UNAVAILABLE", "开发账号配置不完整", 503)
        return {"role": role, "user_no": user_no, "password": password}
