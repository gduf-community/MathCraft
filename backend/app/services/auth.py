"""认证服务：密码哈希、token 会话（Redis）。"""
import secrets

import bcrypt
import redis

from app.config import settings
from app.services import cache


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_session(r: redis.Redis, user_id: str) -> tuple[str, int]:
    """创建登录会话，返回 (token, expires_in 秒)。"""
    token = f"mc_{secrets.token_urlsafe(32)}"
    ttl = settings.session_ttl_seconds
    pipe = r.pipeline()
    pipe.set(cache.PREFIX_AUTH_TOKEN + token, user_id, ex=ttl)
    pipe.sadd(cache.PREFIX_AUTH_USER_TOKENS.format(user_id=user_id), token)
    pipe.expire(cache.PREFIX_AUTH_USER_TOKENS.format(user_id=user_id), ttl)
    pipe.execute()
    return token, ttl


def resolve_token(r: redis.Redis, token: str) -> str | None:
    return r.get(cache.PREFIX_AUTH_TOKEN + token)


def destroy_session(r: redis.Redis, token: str) -> None:
    user_id = r.get(cache.PREFIX_AUTH_TOKEN + token)
    pipe = r.pipeline()
    pipe.delete(cache.PREFIX_AUTH_TOKEN + token)
    if user_id:
        pipe.srem(cache.PREFIX_AUTH_USER_TOKENS.format(user_id=user_id), token)
    pipe.execute()


def destroy_user_sessions(r: redis.Redis, user_id: str) -> int:
    """改密后强制下线：删除该用户全部 token。"""
    key = cache.PREFIX_AUTH_USER_TOKENS.format(user_id=user_id)
    tokens = list(r.smembers(key))
    pipe = r.pipeline()
    for t in tokens:
        pipe.delete(cache.PREFIX_AUTH_TOKEN + t)
    pipe.delete(key)
    pipe.execute()
    return len(tokens)
