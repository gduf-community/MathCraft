"""Redis Lua 原子验证码与 SQL 唯一 proof；SQL 回滚后可安全重试。"""
import hashlib
import hmac
import secrets

import redis
from sqlalchemy.orm import Session

from app.config import settings
from app.errors import AppError
from app.models import AuthProof
from app.services import auth, cache
from app.services.auth_delivery import MailSender

ISSUE = """
local cool = redis.call('TTL', KEYS[1])
if cool > 0 then return cool end
local e = tonumber(redis.call('GET', KEYS[2]) or '0')
local ip = tonumber(redis.call('GET', KEYS[3]) or '0')
if e >= tonumber(ARGV[1]) or ip >= tonumber(ARGV[2]) then return 3600 end
redis.call('SET', KEYS[1], '1', 'EX', ARGV[3])
redis.call('INCR', KEYS[2]); if e == 0 then redis.call('EXPIRE', KEYS[2], 3600) end
redis.call('INCR', KEYS[3]); if ip == 0 then redis.call('EXPIRE', KEYS[3], 3600) end
redis.call('SET', KEYS[4], ARGV[4], 'EX', ARGV[5])
redis.call('HSET', KEYS[5], 'digest', ARGV[6], 'binding', ARGV[7],
           'attempts', 0, 'state', 'pending', 'expires', ARGV[8])
redis.call('EXPIRE', KEYS[5], ARGV[5])
return 0
"""
ACTIVATE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
 redis.call('HSET', KEYS[2], 'state', 'active'); return 1
end
redis.call('DEL', KEYS[2]); return 0
"""
VERIFY = """
if redis.call('EXISTS', KEYS[2]) == 0 then return -1 end
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return -2 end
if redis.call('HGET', KEYS[2], 'binding') ~= ARGV[2] then return -2 end
if tonumber(redis.call('HGET', KEYS[2], 'expires')) <= tonumber(ARGV[5]) then return -1 end
local state = redis.call('HGET', KEYS[2], 'state')
if state ~= 'active' and state ~= 'verified' then return -2 end
local attempts = tonumber(redis.call('HGET', KEYS[2], 'attempts'))
if attempts >= tonumber(ARGV[4]) then return -3 end
if redis.call('HGET', KEYS[2], 'digest') ~= ARGV[3] then
 attempts = redis.call('HINCRBY', KEYS[2], 'attempts', 1)
 if attempts >= tonumber(ARGV[4]) then return -3 end
 return -2
end
redis.call('HSET', KEYS[2], 'state', 'verified'); return 1
"""


def generate_code() -> str:
    """密码学随机六位码；测试可替换此随机性边界。"""
    return f"{secrets.randbelow(1000000):06d}"


def _hmac(value: str) -> str:
    if len(settings.auth_code_secret.encode()) < 32:
        raise AppError("AUTH_SERVICE_UNAVAILABLE", "验证码服务配置不可用", 503)
    return hmac.new(settings.auth_code_secret.encode(), value.encode(), hashlib.sha256).hexdigest()


def _keys(email: str, purpose: str) -> tuple[str, str, str]:
    scope = _hmac(f"{email}:{purpose}")
    return f"auth:otp:cool:{scope}", f"auth:otp:hour:{scope}", f"auth:otp:latest:{scope}"


def issue(email: str, purpose: str, binding: str, ip: str,
          sender: MailSender, deliver: bool = True) -> dict[str, str | int]:
    """先保留限额和 pending challenge，邮件成功后才允许消费。"""
    challenge = secrets.token_urlsafe(32)
    code = generate_code()
    cool, hour, latest = _keys(email, purpose)
    challenge_key = f"auth:otp:challenge:{challenge}"
    digest = _hmac(f"{challenge}:{code}")
    try:
        r = cache.get_redis()
        retry = int(r.eval(ISSUE, 5, cool, hour, f"auth:otp:ip:{_hmac(ip)}", latest,
            challenge_key, settings.auth_code_email_hour_limit, settings.auth_code_ip_hour_limit,
            settings.auth_code_retry_seconds, challenge, settings.auth_code_ttl_seconds,
            digest, binding, auth.now() + settings.auth_code_ttl_seconds))
        if retry:
            raise AppError("RATE_LIMITED", "验证码发送过频，请稍后重试", 429, retry_after=retry)
        if deliver:
            try:
                sender.send_code(email, code, purpose)
            except Exception as exc:
                r.delete(challenge_key)
                raise AppError("EMAIL_SERVICE_UNAVAILABLE", "邮件发送失败，请稍后重试", 503) from exc
            r.eval(ACTIVATE, 2, latest, challenge_key, challenge)
        else:
            r.delete(challenge_key)
    except redis.RedisError as exc:
        raise AppError("AUTH_SERVICE_UNAVAILABLE", "验证码服务不可用", 503) from exc
    return {"challenge_id": challenge, "expires_in": settings.auth_code_ttl_seconds,
            "retry_after": settings.auth_code_retry_seconds}


def verify(db: Session, email: str, purpose: str, binding: str,
           challenge: str, code: str) -> None:
    """Redis 原子校验；SQL 唯一键是最终消费点，不预先永久消费 Redis。"""
    _, _, latest = _keys(email, purpose)
    try:
        result = int(cache.get_redis().eval(VERIFY, 2, latest,
            f"auth:otp:challenge:{challenge}", challenge, binding,
            _hmac(f"{challenge}:{code}"), settings.auth_code_max_attempts, auth.now()))
    except redis.RedisError as exc:
        raise AppError("AUTH_SERVICE_UNAVAILABLE", "验证码服务不可用", 503) from exc
    errors = {-1: ("CODE_EXPIRED", "验证码已过期"),
              -2: ("CODE_INVALID", "验证码无效"),
              -3: ("CODE_ATTEMPTS_EXCEEDED", "验证码错误次数已用尽")}
    if result != 1:
        error, message = errors.get(result, errors[-2])
        raise AppError(error, message, 400)
    if db.get(AuthProof, challenge) is not None:
        raise AppError("CODE_INVALID", "验证码已使用", 400)
    db.add(AuthProof(challenge_id=challenge, purpose=purpose, consumed_at=auth.now()))
    db.flush()
