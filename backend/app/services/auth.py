"""密码、输入规范化与 SQL 可撤销 JWT 会话的公开服务。"""
import hashlib
import re
import secrets
import time
from typing import TypedDict, cast

import bcrypt
import jwt
from sqlalchemy import update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import AppError
from app.models import AuthSession, EmailChange, RefreshUse, User
from app.models.base import new_id


class AccessClaims(TypedDict):
    sub: str
    sid: str
    auth_version: int
    jti: str
    iat: int
    exp: int
    iss: str
    aud: str
    type: str


def now() -> int:
    """返回 UTC Unix 秒；测试可在时间边界注入时钟。"""
    return int(time.time())


def normalize_email(value: str) -> str:
    """邮箱仅去边空白、大小写折叠，不合并点号或加号标签。"""
    result = value.strip().lower()
    if len(result) > 128 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", result):
        raise ValueError("请输入有效邮箱")
    if any(ord(c) < 33 or ord(c) == 127 for c in result):
        raise ValueError("邮箱包含无效字符")
    return result


def normalize_user_no(value: str | None) -> str | None:
    """保留前导零及大小写；空白等同移除，不接受控制字符。"""
    result = value.strip() if value else None
    if not result:
        return None
    if len(result) > 32 or any(ord(c) < 33 or ord(c) == 127 for c in result):
        raise ValueError("学工号长度为 1–32 且不能包含空白或控制字符")
    return result


def validate_password(password: str) -> str:
    """仅新密码执行 8–64 字符、bcrypt 72 字节双重边界。"""
    if not 8 <= len(password) <= 64 or len(password.encode("utf-8")) > 72:
        raise ValueError("新密码须为 8–64 字符且 UTF-8 不超过 72 字节")
    return password


def hash_password(password: str) -> str:
    """生成 bcrypt 哈希；新密码调用方先 validate_password，兼容旧短密码。"""
    if len(password.encode("utf-8")) > 72:
        raise ValueError("密码 UTF-8 不得超过 72 字节")
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """兼容已有短密码哈希；不对登录输入应用新密码长度策略。"""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def require_auth_config() -> None:
    """认证配置不全即拒绝，不回退旧会话或不安全默认密钥。"""
    if (len(settings.auth_jwt_secret.encode()) < 32
            or not settings.auth_jwt_issuer or not settings.auth_jwt_audience):
        raise AppError("AUTH_SERVICE_UNAVAILABLE", "认证服务配置不可用", 503)


def digest_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def assert_version(db: Session, user_id: str, version: int) -> None:
    """条件写获得 SQLite 写锁；与撤销在同一事务串行化。"""
    result = db.execute(update(User).where(
        User.id == user_id, User.auth_version == version, User.status == "active",
    ).values(auth_version=User.auth_version), execution_options={"synchronize_session": False})
    if not isinstance(result, CursorResult) or result.rowcount != 1:
        raise AppError("SESSION_REVOKED", "认证状态已变更，请重新登录", 401)


def encode_access(session: AuthSession) -> str:
    require_auth_config()
    issued = now()
    claims: AccessClaims = {
        "sub": session.user_id, "sid": session.id, "auth_version": session.auth_version,
        "jti": secrets.token_urlsafe(24), "iat": issued,
        "exp": min(issued + settings.auth_access_ttl_seconds, session.expires_at),
        "iss": settings.auth_jwt_issuer, "aud": settings.auth_jwt_audience, "type": "access",
    }
    return jwt.encode(dict(claims), settings.auth_jwt_secret, algorithm="HS256")


def decode_access(token: str) -> AccessClaims:
    require_auth_config()
    try:
        payload = jwt.decode(token, settings.auth_jwt_secret, algorithms=["HS256"],
            issuer=settings.auth_jwt_issuer, audience=settings.auth_jwt_audience,
            options={"require": ["sub", "sid", "auth_version", "jti", "iat", "exp",
                                 "iss", "aud", "type"], "strict_aud": True})
        if (payload["type"] != "access"
                or any(not isinstance(payload[k], str) or not payload[k]
                       for k in ("sub", "sid", "jti"))
                or any(type(payload[k]) is not int for k in ("iat", "exp", "auth_version"))
                or payload["auth_version"] < 0 or payload["iat"] > now()
                or payload["exp"] <= now() or payload["exp"] <= payload["iat"]):
            raise ValueError("invalid claims")
        return cast(AccessClaims, payload)
    except jwt.ExpiredSignatureError as exc:
        raise AppError("ACCESS_TOKEN_EXPIRED", "访问令牌已到期", 401) from exc
    except (jwt.PyJWTError, ValueError, TypeError, KeyError) as exc:
        raise AppError("TOKEN_EXPIRED", "登录令牌无效或已到期", 401) from exc


def authenticate(db: Session, token: str) -> User:
    claims = decode_access(token)
    user = db.get(User, claims["sub"])
    session = db.get(AuthSession, claims["sid"])
    if (user is None or user.status != "active" or user.auth_version != claims["auth_version"]
            or session is None or session.user_id != user.id or session.status != "active"
            or session.auth_version != user.auth_version or session.expires_at <= now()):
        raise AppError("SESSION_REVOKED", "登录会话已撤销或到期", 401)
    return user


def create_session(db: Session, user: User, version: int) -> tuple[str, int, str]:
    """在调用者事务中创建会话；不得在校验旧凭据后读取新版本。"""
    require_auth_config()
    assert_version(db, user.id, version)
    refresh = secrets.token_urlsafe(48)
    session = AuthSession(id=new_id("as"), user_id=user.id, auth_version=version, created_at=now(),
        expires_at=now() + settings.auth_refresh_ttl_seconds, refresh_digest=digest_token(refresh))
    db.add(session)
    db.flush()
    return encode_access(session), settings.auth_access_ttl_seconds, refresh


def revoke_all(db: Session, user: User, version: int) -> None:
    """与资料/密码更新同一 SQL 事务撤销所有设备。"""
    assert_version(db, user.id, version)
    db.execute(update(User).where(User.id == user.id, User.auth_version == version)
        .values(auth_version=version + 1), execution_options={"synchronize_session": False})
    db.execute(update(AuthSession).where(AuthSession.user_id == user.id)
        .values(status="revoked"), execution_options={"synchronize_session": False})


def rotate_refresh(db: Session, refresh: str) -> tuple[str, int, str, User]:
    """CAS 轮换，保留旧摘要识别重放；绝对到期不滑动。"""
    require_auth_config()
    digest = digest_token(refresh)
    used = db.get(RefreshUse, digest)
    if used is not None:
        db.execute(update(AuthSession).where(AuthSession.id == used.session_id)
            .values(status="revoked"))
        db.commit()
        raise AppError("SESSION_REVOKED", "刷新令牌已使用，请重新登录", 401)
    session = db.query(AuthSession).filter_by(refresh_digest=digest).one_or_none()
    if session is None:
        # 轮换可能发生在第一次查 use 之后，再查一次以撤销重放族。
        used = db.get(RefreshUse, digest)
        if used is not None:
            db.execute(update(AuthSession).where(AuthSession.id == used.session_id)
                .values(status="revoked"))
            db.commit()
        raise AppError("SESSION_REVOKED", "刷新会话无效", 401)
    user = db.get(User, session.user_id)
    if (user is None or session.status != "active" or session.expires_at <= now()
            or user.status != "active" or user.auth_version != session.auth_version):
        raise AppError("SESSION_REVOKED", "刷新会话已撤销或到期", 401)
    assert_version(db, user.id, session.auth_version)
    replacement = secrets.token_urlsafe(48)
    result = db.execute(update(AuthSession).where(AuthSession.id == session.id,
        AuthSession.refresh_digest == digest, AuthSession.status == "active")
        .values(refresh_digest=digest_token(replacement)),
        execution_options={"synchronize_session": False})
    if not isinstance(result, CursorResult) or result.rowcount != 1:
        db.rollback()
        db.execute(update(AuthSession).where(AuthSession.id == session.id).values(status="revoked"))
        db.commit()
        raise AppError("SESSION_REVOKED", "并发刷新已撤销会话，请重新登录", 401)
    db.add(RefreshUse(digest=digest, session_id=session.id, expires_at=session.expires_at))
    access = encode_access(session)
    db.commit()
    return access, min(settings.auth_access_ttl_seconds, session.expires_at - now()), replacement, user


def get_change(db: Session, user: User, change_id: str) -> EmailChange:
    """校验换绑事务归属、有效期和认证版本。"""
    change = db.get(EmailChange, change_id)
    if (change is None or change.user_id != user.id or change.status != "pending"
            or change.expires_at <= now() or change.auth_version != user.auth_version
            or change.old_email != user.email_normalized):
        raise AppError("AUTH_FAILED", "邮箱变更已失效，请重新开始", 400)
    return change


def change_binding(change: EmailChange, purpose: str) -> str:
    """将验证码绑定到具体换绑事务及认证版本。"""
    return (f"{purpose}:{change.id}:{change.user_id}:{change.old_email}:"
            f"{change.new_email}:{change.auth_version}")
