"""认证路由共享的 HTTP Cookie 响应辅助函数。"""
from fastapi import Request, Response
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AuthSession, RefreshUse
from app.services.auth import digest_token


def clear_refresh(response: Response) -> None:
    """清除当前浏览器刷新 Cookie，不承载认证业务逻辑。"""
    response.delete_cookie("mc_refresh", path="/api/auth", httponly=True,
                          secure=settings.app_env == "production", samesite="lax")
    response.headers["Cache-Control"] = "no-store"


def refresh_belongs_to_user(request: Request, db: Session, user_id: str) -> bool:
    """仅识别请求携带的当前或已轮换 Cookie 所属账号，不信任调用方账号声明。"""
    token = request.cookies.get("mc_refresh")
    if not token:
        return False
    digest = digest_token(token)
    session = db.query(AuthSession).filter_by(refresh_digest=digest).one_or_none()
    if session is None:
        used = db.get(RefreshUse, digest)
        session = db.get(AuthSession, used.session_id) if used else None
    return session is not None and session.user_id == user_id
