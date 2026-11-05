"""验证外部认证适配器的失败边界，不连接 SMTP 或 Cloudflare。"""
import logging
import smtplib

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.errors import AppError
from app.main import app
from app.services import auth_codes, auth_delivery


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
    {"success": True, "hostname": "mathcraft.example.test", "action": "register"},
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
    auth_delivery.SMTPMailSender().send_code("person@example.test", "012345", "register")
    assert steps[-3:] == ["login", "send", "closed"]
    assert messages[0]["To"] == "person@example.test"
    assert "012345" in messages[0].get_content()


def test_smtp_failure_does_not_expose_credentials(monkeypatch, delivery_config):
    def fail(*args, **kwargs):
        raise smtplib.SMTPAuthenticationError(535, b"fake-mail-password")

    monkeypatch.setattr(auth_delivery.smtplib, "SMTP", fail)
    with pytest.raises(AppError) as error:
        auth_delivery.SMTPMailSender().send_code("person@example.test", "012345", "register")
    assert error.value.status_code == 503
    assert "fake-mail-password" not in str(error.value)


@pytest.mark.parametrize("purpose", ["login", "reset_password"])
@pytest.mark.parametrize("failure", ["transport", "adapter"])
def test_private_code_smtp_failure_matches_unknown_email(
    client, isolated_redis, monkeypatch, caplog, purpose, failure,
):
    """HTTP 成功外形与冷却相同，失败码不可登录/重置，日志不泄露标识。"""
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
        for recipient in (email, "missing@example.test"):
            response = client.post("/api/auth/email-code", json={
                "email": recipient, "purpose": purpose,
                "turnstile_token": "test-turnstile-token",
            })
            assert response.status_code == 202, response.text
            responses.append(response.json())
            assert not isolated_redis.exists(
                f"auth:otp:challenge:{response.json()['challenge_id']}"
            )
            retry = client.post("/api/auth/email-code", json={
                "email": recipient, "purpose": purpose,
                "turnstile_token": "test-turnstile-token",
            })
            assert retry.status_code == 429
        assert len(attempts) == 1
        assert responses[0].keys() == responses[1].keys()
        assert responses[0]["expires_in"] == responses[1]["expires_in"]
        assert responses[0]["retry_after"] == responses[1]["retry_after"]
        assert responses[0]["challenge_id"] != responses[1]["challenge_id"]
        challenge = responses[0]["challenge_id"]
        if purpose == "login":
            consumed = client.post("/api/auth/login/email", json={
                "email": email, "challenge_id": challenge, "code": "012345",
                "role": "teacher",
            })
        else:
            consumed = client.post("/api/auth/password/reset", json={
                "email": email, "challenge_id": challenge, "code": "012345",
                "new_password": "fake-new-password-123",
                "confirm_password": "fake-new-password-123",
            })
        assert consumed.status_code == 400, consumed.text
        assert consumed.json()["detail"]["code"] in {"CODE_EXPIRED", "CODE_INVALID"}
        records = [r for r in caplog.records if r.name == "app.services.auth_codes"]
        assert len(records) == 1
        assert records[0].levelno >= logging.WARNING
        assert records[0].exc_info is None
        for sensitive in (email, "missing@example.test", secret, "012345", challenge,
                          settings.auth_code_secret):
            assert sensitive not in caplog.text
    finally:
        app.dependency_overrides.pop(auth_delivery.get_mail_sender, None)


@pytest.mark.parametrize("purpose", ["register", "email_change_old", "email_change_new"])
def test_explicit_code_smtp_failure_stays_unavailable(
    client, isolated_redis, monkeypatch, caplog, purpose,
):
    """注册/双邮箱换绑仍明确 503，失败挑战不可激活且继续保留重发限额。"""
    email = "new@example.test"
    extra = {}
    headers = {}
    if purpose != "register":
        signed_in = client.post("/api/auth/login/password", json={
            "user_no": "TK20240001", "password": "123123", "role": "teacher",
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

    async def observed_app(scope, receive, send):
        async def observed_send(message):
            nonlocal body_sent
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                body_sent = True
            await send(message)
        await app(scope, receive, observed_send)

    class ObservedMail:
        def send_code(self, email, code, requested_purpose):
            assert body_sent, "SMTP 必须在 HTTP 响应完成后执行，不能按账号存在性延迟响应"
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
                if smtp_fails or recipient.startswith("missing"):
                    assert not isolated_redis.exists(challenge_key)
                else:
                    assert isolated_redis.hget(challenge_key, "state") in ("active", b"active")
        assert attempts == [("teacher@example.test", purpose)]
    finally:
        app.dependency_overrides.pop(auth_delivery.get_mail_sender, None)
