"""验证外部认证适配器的失败边界，不连接 SMTP 或 Cloudflare。"""
import smtplib

import httpx
import pytest

from app.config import settings
from app.errors import AppError
from app.services import auth_delivery


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
