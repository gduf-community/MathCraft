"""外部认证边界：SMTP 与固定 action/hostname 的 Turnstile 校验。"""
import ipaddress
import smtplib
import ssl
import uuid
from email.message import EmailMessage
from typing import Protocol

import httpx

from app.config import settings
from app.errors import AppError


class MailSender(Protocol):
    def send_code(self, email: str, code: str, purpose: str) -> None: ...


class TurnstileVerifier(Protocol):
    def verify(self, token: str, action: str, remote_ip: str) -> None: ...


class SMTPMailSender:
    def send_code(self, email: str, code: str, purpose: str) -> None:
        """同步路由线程池调用；认证、TLS、超时缺失均拒绝。"""
        if not all((settings.smtp_host, settings.smtp_username,
                    settings.smtp_password, settings.smtp_from)):
            raise AppError("EMAIL_SERVICE_UNAVAILABLE", "邮件服务不可用", 503)
        message = EmailMessage()
        message["From"] = settings.smtp_from
        message["To"] = email
        message["Subject"] = "MathCraft 邮箱验证码"
        message.set_content(f"您的验证码为 {code}，有效期 {settings.auth_code_ttl_seconds // 60} 分钟。"
                            "如非本人操作，请忽略本邮件。")
        try:
            context = ssl.create_default_context()
            if settings.smtp_tls_mode == "tls":
                connection = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port,
                    timeout=settings.smtp_timeout_seconds, context=context)
            else:
                connection = smtplib.SMTP(settings.smtp_host, settings.smtp_port,
                    timeout=settings.smtp_timeout_seconds)
            with connection:
                if settings.smtp_tls_mode == "starttls":
                    connection.starttls(context=context)
                connection.login(settings.smtp_username, settings.smtp_password)
                connection.send_message(message)
        except (smtplib.SMTPException, OSError, ValueError) as exc:
            raise AppError("EMAIL_SERVICE_UNAVAILABLE", "邮件发送失败，请稍后重试", 503) from exc


def turnstile_required(remote_ip: str) -> bool:
    """仅显式关闭的开发/测试环境本机请求可省略人机验证。"""
    if settings.turnstile_enabled or settings.app_env not in {"development", "test"}:
        return True
    try:
        return not ipaddress.ip_address(remote_ip).is_loopback
    except ValueError:
        return True


class CloudflareTurnstileVerifier:
    def verify(self, token: str, action: str, remote_ip: str) -> None:
        """按有效开关验证票据，不改变账号密码或会话授权要求。"""
        if not turnstile_required(remote_ip):
            return
        allowed = {h.strip() for h in settings.turnstile_allowed_hostnames.split(",") if h.strip()}
        if not settings.turnstile_secret_key or not settings.turnstile_site_key or not allowed:
            raise AppError("AUTH_SERVICE_UNAVAILABLE", "人机验证配置不可用", 503)
        if settings.app_env == "production" and (
            settings.turnstile_site_key.startswith(("1x", "2x", "3x"))
            or settings.turnstile_secret_key.startswith(("1x", "2x", "3x"))
        ):
            raise AppError("AUTH_SERVICE_UNAVAILABLE", "生产人机验证配置不可用", 503)
        if not token.strip():
            raise AppError("TURNSTILE_FAILED", "请先完成人机验证", 400)
        try:
            response = httpx.post("https://challenges.cloudflare.com/turnstile/v0/siteverify",
                data={"secret": settings.turnstile_secret_key, "response": token,
                      "remoteip": remote_ip, "idempotency_key": str(uuid.uuid4())},
                timeout=settings.turnstile_timeout_seconds)
            response.raise_for_status()
            result = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise AppError("AUTH_SERVICE_UNAVAILABLE", "人机验证服务不可用", 503) from exc
        if (not isinstance(result, dict) or result.get("success") is not True
                or result.get("hostname") not in allowed or result.get("action") != action):
            raise AppError("TURNSTILE_FAILED", "人机验证失败，请重新验证", 400)


def get_mail_sender() -> MailSender:
    """FastAPI 依赖替换点：假服务仅实现 send_code(email, code, purpose)。"""
    return SMTPMailSender()


def get_turnstile_verifier() -> TurnstileVerifier:
    """FastAPI 依赖替换点：失败抛 AppError，成功返回 None。"""
    return CloudflareTurnstileVerifier()
