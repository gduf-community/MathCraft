"""验证外部认证适配器的失败边界，不连接 SMTP 或 Cloudflare。"""
import logging
import smtplib

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.errors import AppError
from app.main import app
from app.models import AuthProof, AuthSession, User
from app.services import auth_codes, auth_delivery


@pytest.mark.parametrize("role", ["teacher", "student", "admin"])
def test_local_optional_turnstile_preserves_password_sessions_and_roles(
    client, db, monkeypatch, role,
):
    """本机临时免人机验证仍要求真实密码、启用账号及有效会话。"""
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "turnstile_enabled", False)
    monkeypatch.setattr(settings, "turnstile_site_key", "")
    monkeypatch.setattr(settings, "turnstile_secret_key", "")
    monkeypatch.setattr(settings, "turnstile_allowed_hostnames", "")
    monkeypatch.setitem(app.dependency_overrides, auth_delivery.get_turnstile_verifier,
                        auth_delivery.get_turnstile_verifier)

    def forbidden(*args, **kwargs):
        pytest.fail("本机免验证不得请求 Cloudflare")

    monkeypatch.setattr(auth_delivery.httpx, "post", forbidden)
    user = db.query(User).filter_by(account="teacher").one()
    user.role = role
    user.identity = {"teacher": "教师", "student": "学生", "admin": "管理员"}[role]
    user.email = None
    user.email_normalized = None
    user.email_verified = False
    user.email_verified_at = None
    db.commit()
    with TestClient(app, client=("127.0.0.1", 47000)) as local:
        config = local.get("/api/auth/config").json()
        assert config["turnstile_enabled"] is False
        assert config["available"] is True
        assert local.get("/api/auth/me").status_code == 401
        assert local.post("/api/auth/login/account", json={
            "account": "teacher", "password": "wrong-password",
        }).status_code == 401
        response = local.post("/api/auth/login/account", json={
            "account": "teacher", "password": "123123", "turnstile_token": "",
        })
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["user"]["role"] == role
        assert result["user"]["email_verified"] is False
        headers = {"Authorization": f"Bearer {result['access_token']}"}
        assert local.get("/api/auth/me", headers=headers).status_code == 200
        assert local.post("/api/auth/email-code", json={
            "email": "unknown@example.test", "purpose": "login",
        }).status_code == 202
        user.status = "disabled"
        db.commit()
        assert local.get("/api/auth/me", headers=headers).status_code == 401
        assert local.post("/api/auth/login/account", json={
            "account": "teacher", "password": "123123",
        }).status_code == 401


def test_optional_turnstile_does_not_apply_to_remote_peers(client, monkeypatch):
    """非本机来源即使打开开发开关也必须验证，不能伪造转发头绕过。"""
    monkeypatch.setattr(settings, "app_env", "development")
    monkeypatch.setattr(settings, "turnstile_enabled", False)
    monkeypatch.setattr(settings, "turnstile_site_key", "")
    monkeypatch.setattr(settings, "turnstile_secret_key", "")
    monkeypatch.setattr(settings, "turnstile_allowed_hostnames", "")
    monkeypatch.setitem(app.dependency_overrides, auth_delivery.get_turnstile_verifier,
                        auth_delivery.get_turnstile_verifier)
    with TestClient(app, client=("203.0.113.10", 47000)) as remote:
        headers = {"X-Forwarded-For": "127.0.0.1", "X-Real-IP": "127.0.0.1"}
        config = remote.get("/api/auth/config", headers=headers).json()
        assert config["turnstile_enabled"] is True
        assert config["available"] is False
        response = remote.post("/api/auth/login/account", headers=headers, json={
            "account": "teacher", "password": "123123", "turnstile_token": "",
        })
        assert response.status_code == 503, response.text


@pytest.mark.parametrize("address", ["127.0.0.1", "::1"])
def test_optional_turnstile_accepts_both_loopback_families(monkeypatch, address):
    """IPv4/IPv6 本机地址均无需外部票据，生产环境仍拒绝免验证配置。"""
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setattr(settings, "app_env", "test")
    monkeypatch.setattr(settings, "turnstile_enabled", False)
    auth_delivery.CloudflareTurnstileVerifier().verify("", "password_login", address)
    with pytest.raises(ValidationError, match="生产环境禁止关闭人机验证"):
        Settings(_env_file=None, app_env="production", turnstile_enabled=False)


def test_enabled_turnstile_rejects_empty_proof_before_network(monkeypatch, delivery_config):
    """恢复开关后空票据不能通过，也不访问远端验证服务。"""
    monkeypatch.setattr(settings, "turnstile_enabled", True)

    def forbidden(*args, **kwargs):
        pytest.fail("空票据不得请求 Cloudflare")

    monkeypatch.setattr(auth_delivery.httpx, "post", forbidden)
    with pytest.raises(AppError) as error:
        auth_delivery.CloudflareTurnstileVerifier().verify("", "password_login", "127.0.0.1")
    assert error.value.code == "TURNSTILE_FAILED"


@pytest.fixture()
def delivery_config(monkeypatch):
    """所有配置均为明确假值，禁止读取个人配置。"""
    for name, value in {
        "app_env": "test", "turnstile_site_key": "fake-site-key",
        "turnstile_secret_key": "fake-secret-key",
        "turnstile_allowed_hostnames": "mathcraft.example.test",
        "smtp_host": "smtp.example.test", "smtp_port": 587,
        "smtp_username": "fake-mail-user", "smtp_password": "fake-mail-password",
        "smtp_from": "noreply@example.test", "smtp_tls_mode": "starttls",
    }.items():
        monkeypatch.setattr(settings, name, value)


def test_siteverify_checks_server_action_and_hostname(monkeypatch, delivery_config):
    """只接受服务端实际返回的 hostname/action，而非前端成功标记。"""
    seen = []

    def post(url, *, data, timeout):
        seen.append((url, data, timeout))
        return httpx.Response(200, json={"success": True,
            "hostname": "mathcraft.example.test", "action": "password_login"},
            request=httpx.Request("POST", url))

    monkeypatch.setattr(auth_delivery.httpx, "post", post)
    auth_delivery.CloudflareTurnstileVerifier().verify("fake-token", "password_login", "127.0.0.1")
    url, data, timeout = seen[0]
    assert url == "https://challenges.cloudflare.com/turnstile/v0/siteverify"
    assert data["response"] == "fake-token" and data["remoteip"] == "127.0.0.1"
    assert data["secret"] == "fake-secret-key" and data["idempotency_key"]
    assert timeout > 0


@pytest.mark.parametrize("payload", [
    {"success": False},
    {"success": True, "hostname": "attacker.example.test", "action": "password_login"},
    {"success": True, "hostname": "mathcraft.example.test", "action": "login"},
    {"success": "true", "hostname": "mathcraft.example.test", "action": "password_login"},
    [], None,
])
def test_siteverify_rejects_wrong_or_malformed_results(monkeypatch, delivery_config, payload):
    def post(url, **kwargs):
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))

    monkeypatch.setattr(auth_delivery.httpx, "post", post)
    with pytest.raises(AppError) as error:
        auth_delivery.CloudflareTurnstileVerifier().verify("fake-token", "password_login", "127.0.0.1")
    assert error.value.status_code in (400, 503)


@pytest.mark.parametrize("mode", ["timeout", "http", "invalid_json"])
def test_siteverify_transport_failure_is_closed(monkeypatch, delivery_config, mode):
    def post(url, **kwargs):
        if mode == "timeout":
            raise httpx.ReadTimeout("fake transport failure")
        return httpx.Response(503 if mode == "http" else 200, content=b"not-json",
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(auth_delivery.httpx, "post", post)
    with pytest.raises(AppError) as error:
        auth_delivery.CloudflareTurnstileVerifier().verify("fake-token", "password_login", "127.0.0.1")
    assert error.value.status_code == 503
    assert "fake-token" not in str(error.value)


@pytest.mark.parametrize("mode", ["missing", "production_test_key"])
def test_siteverify_configuration_rejects_before_network(monkeypatch, delivery_config, mode):
    if mode == "missing":
        monkeypatch.setattr(settings, "turnstile_secret_key", "")
    else:
        monkeypatch.setattr(settings, "app_env", "production")
        monkeypatch.setattr(settings, "turnstile_site_key", "1x00000000000000000000AA")

    def forbidden(*args, **kwargs):
        pytest.fail("无效配置不得访问 Siteverify")

    monkeypatch.setattr(auth_delivery.httpx, "post", forbidden)
    with pytest.raises(AppError) as error:
        auth_delivery.CloudflareTurnstileVerifier().verify("fake-token", "password_login", "127.0.0.1")
    assert error.value.status_code == 503


@pytest.mark.parametrize("tls_mode", ["starttls", "tls"])
def test_smtp_tls_precedes_login_and_message(monkeypatch, delivery_config, tls_mode):
    monkeypatch.setattr(settings, "smtp_tls_mode", tls_mode)
    steps = []
    messages = []

    class FakeSMTP:
        def __init__(self, host, port, **kwargs):
            assert host == "smtp.example.test" and port == 587
            assert kwargs["timeout"] > 0
            steps.append("implicit_tls" if "context" in kwargs else "connect")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            steps.append("closed")

        def starttls(self, *, context):
            assert context is not None
            steps.append("starttls")

        def login(self, username, password):
            assert "starttls" in steps or "implicit_tls" in steps
            steps.append("login")

        def send_message(self, message):
            steps.append("send")
            messages.append(message)

    monkeypatch.setattr(auth_delivery.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(auth_delivery.smtplib, "SMTP_SSL", FakeSMTP)
    auth_delivery.SMTPMailSender().send_code("person@example.test", "012345", "login")
    assert steps[-3:] == ["login", "send", "closed"]
    assert messages[0]["To"] == "person@example.test"
    assert "012345" in messages[0].get_content()


def test_smtp_failure_does_not_expose_credentials(monkeypatch, delivery_config):
    def fail(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"fake-mail-password")

    monkeypatch.setattr(auth_delivery.smtplib, "SMTP", fail)
    with pytest.raises(AppError) as error:
        auth_delivery.SMTPMailSender().send_code("person@example.test", "012345", "login")
    assert error.value.status_code == 503
    assert "fake-mail-password" not in str(error.value)


def consume_public_code(
    client: TestClient, purpose: str, email: str, challenge: str,
) -> httpx.Response:
    """以已知正确假验证码尝试业务消费，证明未激活挑战不能产生认证效果。"""
    payload = {"email": email, "challenge_id": challenge, "code": "012345"}
    if purpose == "login":
        return client.post("/api/auth/login/email", json=payload)
    return client.post("/api/auth/password/reset", json={
        **payload, "new_password": "fake-new-password-123",
        "confirm_password": "fake-new-password-123",
    })


@pytest.mark.parametrize("purpose", ["login", "reset_password"])
@pytest.mark.parametrize("failure", ["transport", "adapter"])
def test_private_code_smtp_failure_matches_unknown_email(
    client, isolated_redis, monkeypatch, caplog, db, purpose, failure,
):
    """公开发码统一受理；正确但未投递的验证码也不能注册、登录或重置。"""
    email = "teacher@example.test"
    secret = "fake-sensitive-smtp-detail"
    attempts = []

    class FailingMail:
        def send_code(self, recipient, code, requested_purpose):
            attempts.append((recipient, code, requested_purpose))
            message = f"{recipient} {code} {secret}"
            if failure == "adapter":
                raise AppError("EMAIL_SERVICE_UNAVAILABLE", message, 503)
            raise OSError(message)

    monkeypatch.setattr(auth_codes, "generate_code", lambda: "012345")
    app.dependency_overrides[auth_delivery.get_mail_sender] = lambda: FailingMail()
    caplog.set_level(logging.WARNING, logger="app.services.auth_codes")
    try:
        responses = []
        consumption_errors = []
        original_users = {user.id: user.password_hash for user in db.query(User).all()}
        original_sessions = db.query(AuthSession).count()
        original_proofs = db.query(AuthProof).count()
        for recipient in (email, "missing@example.test"):
            response = client.post("/api/auth/email-code", json={
                "email": recipient, "purpose": purpose,
                "turnstile_token": "test-turnstile-token",
            })
            assert response.status_code == 202, response.text
            responses.append(response.json())
            challenge_key = f"auth:otp:challenge:{response.json()['challenge_id']}"
            assert isolated_redis.hget(challenge_key, "state") in ("pending", b"pending")
            assert 0 < isolated_redis.ttl(challenge_key) <= settings.auth_code_ttl_seconds
            retry = client.post("/api/auth/email-code", json={
                "email": recipient, "purpose": purpose,
                "turnstile_token": "test-turnstile-token",
            })
            assert retry.status_code == 429
            assert int(retry.headers["retry-after"]) > 0
            errors = []
            for _ in range(settings.auth_code_max_attempts + 1):
                consumed = consume_public_code(
                    client, purpose, recipient, response.json()["challenge_id"],
                )
                assert consumed.status_code == 400, consumed.text
                errors.append(consumed.json()["detail"]["code"])
                assert "mc_refresh=" not in consumed.headers.get("set-cookie", "")
            consumption_errors.append(errors)
        assert len(attempts) == 1
        assert attempts[0] == (
            email, "012345", purpose,
        )
        assert responses[0].keys() == responses[1].keys()
        assert responses[0]["expires_in"] == responses[1]["expires_in"]
        assert responses[0]["retry_after"] == responses[1]["retry_after"]
        assert responses[0]["challenge_id"] != responses[1]["challenge_id"]
        challenge = responses[0]["challenge_id"]
        assert consumption_errors[0] == consumption_errors[1]
        assert consumption_errors[0] == (
            ["CODE_INVALID"] * (settings.auth_code_max_attempts - 1)
            + ["CODE_ATTEMPTS_EXCEEDED"] * 2
        )
        db.expire_all()
        assert {user.id: user.password_hash for user in db.query(User).all()} == original_users
        assert db.query(AuthSession).count() == original_sessions
        assert db.query(AuthProof).count() == original_proofs
        records = [r for r in caplog.records if r.name == "app.services.auth_codes"]
        assert len(records) == 1
        assert records[0].levelno >= logging.WARNING
        assert records[0].exc_info is None
        for sensitive in (email, "missing@example.test", secret, "012345", challenge,
                          settings.auth_code_secret):
            assert sensitive not in caplog.text
        for accepted in responses:
            assert secret not in str(accepted)
            assert email not in str(accepted)
            assert "missing@example.test" not in str(accepted)
    finally:
        app.dependency_overrides.pop(auth_delivery.get_mail_sender, None)


@pytest.mark.parametrize("purpose", ["email_change_old", "email_change_new"])
def test_explicit_code_smtp_failure_stays_unavailable(
    client, isolated_redis, monkeypatch, caplog, purpose,
):
    """已登录双邮箱换绑仍明确 503，失败挑战不可激活且保留重发限额。"""
    email = "new@example.test"
    extra = {}
    headers = {}
    if purpose.startswith("email_change_"):
        signed_in = client.post("/api/auth/login/account", json={
            "account": "teacher", "password": "123123",
            "turnstile_token": "test-turnstile-token",
        })
        assert signed_in.status_code == 200, signed_in.text
        headers = {"Authorization": f"Bearer {signed_in.json()['access_token']}"}
        change = client.post("/api/users/me/email-change", headers=headers,
                             json={"new_email": email})
        assert change.status_code == 201, change.text
        extra["change_id"] = change.json()["change_id"]
        if purpose == "email_change_old":
            email = "teacher@example.test"
    attempts = []

    class FailingMail:
        def send_code(self, recipient, code, requested_purpose):
            attempts.append((recipient, code, requested_purpose))
            raise OSError(f"{recipient} {code} fake-sensitive-smtp-detail")

    app.dependency_overrides[auth_delivery.get_mail_sender] = lambda: FailingMail()
    caplog.set_level(logging.WARNING, logger="app.services.auth_codes")
    try:
        payload = {"email": email, "purpose": purpose,
                   "turnstile_token": "test-turnstile-token", **extra}
        response = client.post("/api/auth/email-code", headers=headers, json=payload)
        assert response.status_code == 503, response.text
        assert response.json()["detail"]["code"] == "EMAIL_SERVICE_UNAVAILABLE"
        assert not list(isolated_redis.scan_iter("auth:otp:challenge:*"))
        assert len(attempts) == 1
        assert client.post("/api/auth/email-code", headers=headers,
                           json=payload).status_code == 429
        records = [r for r in caplog.records if r.name == "app.services.auth_codes"]
        assert len(records) == 1 and records[0].exc_info is None
        for sensitive in (email, attempts[0][1], "fake-sensitive-smtp-detail",
                          settings.auth_code_secret):
            assert sensitive not in response.text
            assert sensitive not in caplog.text
    finally:
        app.dependency_overrides.pop(auth_delivery.get_mail_sender, None)


@pytest.mark.parametrize("purpose", ["login", "reset_password"])
@pytest.mark.parametrize("smtp_fails", [False, True])
def test_private_email_delivery_starts_after_http_response(
    client, isolated_redis, purpose, smtp_fails,
):
    """SMTP 成功或超时都不能延迟 202；不存在的邮箱使用同一响应路径。"""
    body_sent = False
    attempts = []
    response_completed_at_delivery = []

    async def observed_app(scope, receive, send):
        async def observed_send(message):
            nonlocal body_sent
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                body_sent = True
            await send(message)
        await app(scope, receive, observed_send)

    class ObservedMail:
        def send_code(self, email, code, requested_purpose):
            response_completed_at_delivery.append(body_sent)
            attempts.append((email, requested_purpose))
            if smtp_fails:
                raise TimeoutError("fake SMTP timeout")

    app.dependency_overrides[auth_delivery.get_mail_sender] = lambda: ObservedMail()
    try:
        with TestClient(observed_app) as observed_client:
            for recipient in ("teacher@example.test", "missing@example.test"):
                body_sent = False
                response = observed_client.post("/api/auth/email-code", json={
                    "email": recipient, "purpose": purpose,
                    "turnstile_token": "test-turnstile-token",
                })
                assert response.status_code == 202, response.text
                challenge_key = f"auth:otp:challenge:{response.json()['challenge_id']}"
                eligible = recipient.startswith("teacher")
                if smtp_fails or not eligible:
                    assert isolated_redis.hget(challenge_key, "state") in ("pending", b"pending")
                else:
                    assert isolated_redis.hget(challenge_key, "state") in ("active", b"active")
                assert 0 < isolated_redis.ttl(challenge_key) <= settings.auth_code_ttl_seconds
        expected_recipient = "teacher@example.test"
        assert attempts == [(expected_recipient, purpose)]
        assert response_completed_at_delivery == [True], "SMTP 必须在 HTTP 响应完成后执行"
    finally:
        app.dependency_overrides.pop(auth_delivery.get_mail_sender, None)
