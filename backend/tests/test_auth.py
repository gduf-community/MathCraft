"""HTTP 接缝验证认证闭环；SMTP/Siteverify 仅在外部依赖边界替换。"""
import pytest

from app.main import app
from app.services.auth_delivery import get_mail_sender, get_turnstile_verifier

ORIGIN = "http://127.0.0.1:5173"
PASSWORD = "safe-test-password-123"


@pytest.fixture()
def delivery():
    class FakeMail:
        fail = False
        messages = []

        def send_code(self, email, code, purpose):
            if self.fail:
                raise OSError("test transport failure")
            self.messages.append((email, code, purpose))

    class FakeVerifier:
        def verify(self, token, action, remote_ip):
            from app.errors import AppError
            if token != "test-challenge":
                raise AppError("TURNSTILE_FAILED", "验证失败", 400)

    mail = FakeMail()
    app.dependency_overrides[get_mail_sender] = lambda: mail
    app.dependency_overrides[get_turnstile_verifier] = lambda: FakeVerifier()
    yield mail
    app.dependency_overrides.pop(get_mail_sender, None)
    app.dependency_overrides.pop(get_turnstile_verifier, None)


def issue(client, delivery, email="new@example.com", purpose="login", **extra):
    response = client.post("/api/auth/email-code", json={"email": email, "purpose": purpose,
        "turnstile_token": "test-challenge", **extra})
    assert response.status_code == 202, response.text
    code = next((m[1] for m in reversed(delivery.messages) if m[0] == email.strip().lower()), "000000")
    return response.json()["challenge_id"], code


def provision_user(client, delivery, email="new@example.com", role="teacher", user_no=None,
                   *, verified=True, account=None):
    """直接在隔离数据库准备受控账号，通过真实账号登录取得会话。"""
    from datetime import datetime, timezone

    from app.db import SessionLocal
    from app.models import User, UserModelSetting
    from app.models.base import new_id
    from app.services.auth import hash_password, normalize_email

    with SessionLocal() as db:
        user = User(
            id=new_id("u"), account=account or user_no or new_id("account"),
            email=normalize_email(email) if email else None,
            email_normalized=normalize_email(email) if email else None,
            email_verified=verified if email else False,
            email_verified_at=datetime.now(timezone.utc) if email and verified else None,
            password_hash=hash_password(PASSWORD), display_name="新用户", role=role,
            identity={"teacher": "教师", "student": "学生", "admin": "管理员"}[role],
            user_no=user_no, auth_version=0, status="active",
        )
        db.add(user)
        db.flush()
        db.add(UserModelSetting(user_id=user.id))
        db.commit()
        login_account = user.account
    response = client.post("/api/auth/login/account", json={
        "account": login_account, "password": PASSWORD, "turnstile_token": "test-challenge",
    })
    assert response.status_code == 200, response.text
    return response.json()


def bearer(result):
    return {"Authorization": f"Bearer {result['access_token']}"}


def csrf(client):
    response = client.get("/api/auth/config")
    return {"Origin": ORIGIN, "X-CSRF-Token": response.json()["csrf_token"]}


def test_account_login_and_removed_legacy_routes(client, delivery):
    result = provision_user(client, delivery, email="  NEW@Example.com ")
    assert result["token_type"] == "bearer"
    assert result["user"]["email"] == "new@example.com"
    assert result["user"]["email_verified"] is True
    assert result["user"]["user_no"] is None
    assert client.get("/api/auth/me", headers=bearer(result)).json()["user"]["id"] == result["user"]["id"]
    assert client.cookies.get("mc_refresh")
    for path in ("/api/auth/login", "/api/auth/change-password", "/api/auth/register", "/api/auth/login/password"):
        assert client.post(path, json={}).status_code == 404
    assert client.post("/api/auth/email-code", json={
        "email": "new@example.com", "purpose": "register", "turnstile_token": "test-challenge",
    }).status_code == 422
    assert client.get("/api/auth/config").json()["methods"] == ["account_password", "email_code"]


@pytest.mark.parametrize("role", ["teacher", "student", "admin"])
def test_two_login_methods_infer_role_and_reject_role_input(client, delivery, role):
    result = provision_user(client, delivery, role=role, user_no="001Ab")
    body = {"account": result["user"]["account"], "password": PASSWORD,
            "turnstile_token": "test-challenge"}
    response = client.post("/api/auth/login/account", json=body)
    assert response.status_code == 200
    assert response.json()["user"]["role"] == role
    assert client.post("/api/auth/login/account", json={**body, "role": "student"}).status_code == 422
    challenge, code = issue(client, delivery)
    email_body = {"email": "new@example.com", "challenge_id": challenge, "code": code}
    assert client.post("/api/auth/login/email", json={**email_body, "role": role}).status_code == 422
    response = client.post("/api/auth/login/email", json=email_body)
    assert response.status_code == 200
    assert response.json()["user"]["role"] == role
    assert client.post("/api/auth/login/email", json=email_body).status_code == 400


def test_refresh_rotation_replay_and_csrf(client, delivery):
    result = provision_user(client, delivery)
    old_refresh = client.cookies.get("mc_refresh")
    assert client.post("/api/auth/refresh", json={}).status_code == 403
    headers = csrf(client)
    assert client.post("/api/auth/refresh", json={}, headers={**headers, "Origin": "https://evil.example"}).status_code == 403
    response = client.post("/api/auth/refresh", json={}, headers=headers)
    assert response.status_code == 200, response.text
    assert client.cookies.get("mc_refresh") != old_refresh
    client.cookies.set("mc_refresh", old_refresh, domain="testserver.local", path="/api/auth")
    assert client.post("/api/auth/refresh", json={}, headers=headers).status_code == 401
    assert client.get("/api/auth/me", headers=bearer(result)).status_code == 401


def test_password_change_revokes_access_and_refresh(client, delivery):
    result = provision_user(client, delivery)
    response = client.put("/api/auth/password", headers=bearer(result), json={"old_password": PASSWORD,
        "new_password": "new-password-123", "confirm_password": "new-password-123"})
    assert response.status_code == 204, response.text
    assert client.get("/api/auth/me", headers=bearer(result)).status_code == 401
    assert client.cookies.get("mc_refresh") is None


def test_code_attempt_budget_and_smtp_failure(client, delivery, monkeypatch):
    provision_user(client, delivery)
    challenge, actual = issue(client, delivery)
    wrong = "111111" if actual != "111111" else "222222"
    payload = {"email": "new@example.com", "challenge_id": challenge, "code": wrong}
    for _ in range(5):
        assert client.post("/api/auth/login/email", json=payload).status_code == 400
    payload["code"] = actual
    assert client.post("/api/auth/login/email", json=payload).json()["detail"]["code"] == "CODE_ATTEMPTS_EXCEEDED"
    provision_user(client, delivery, email="failed@example.com")
    delivery.fail = True
    monkeypatch.setattr("app.services.auth_codes.generate_code", lambda: "012345")
    request = {"email": "failed@example.com", "purpose": "login", "turnstile_token": "test-challenge"}
    response = client.post("/api/auth/email-code", json=request)
    assert response.status_code == 202
    for private in ("failed@example.com", "012345", "test transport failure"):
        assert private not in response.text
    failed = client.post("/api/auth/login/email", json={"email": "failed@example.com",
        "challenge_id": response.json()["challenge_id"], "code": "012345"})
    assert failed.status_code == 400
    assert failed.json()["detail"]["code"] == "CODE_INVALID"
    response = client.post("/api/auth/email-code", json=request)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) > 0


def test_validation_never_echoes_secrets(client, delivery):
    response = client.post("/api/auth/login/account", json={"password": "DO-NOT-ECHO"})
    assert response.status_code == 422
    assert "DO-NOT-ECHO" not in response.text


def test_reset_unregistered_never_creates_account(client, delivery):
    challenge, code = issue(client, delivery, email="missing@example.com", purpose="reset_password")
    assert delivery.messages == []
    response = client.post("/api/auth/password/reset", json={"email": "missing@example.com",
        "challenge_id": challenge, "code": code, "new_password": PASSWORD, "confirm_password": PASSWORD})
    assert response.status_code == 400


def test_legacy_token_rejected(client):
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer mc_old"}).status_code == 401


def test_openapi_validation_error_matches_redacted_http_detail(client):
    """动态契约必须描述全局脱敏错误，而不是 FastAPI 默认错误数组。"""
    spec = app.openapi()
    response = client.post("/api/auth/login/account", json={"password": "DO-NOT-ECHO"})
    assert response.status_code == 422
    assert response.json() == {"detail": {
        "code": "VALIDATION_ERROR", "message": "请求字段格式错误或包含不允许的字段"}}
    assert "DO-NOT-ECHO" not in response.text
    errors = []
    for path, operations in spec["paths"].items():
        for method, operation in operations.items():
            error = operation.get("responses", {}).get("422")
            if error is not None:
                schema = error["content"]["application/json"]["schema"]
                errors.append((path, method))
                assert schema == {"$ref": "#/components/schemas/ErrorResponse"}, (path, method)
    assert errors
    components = spec["components"]["schemas"]
    detail = components["ErrorResponse"]["properties"]["detail"]
    assert detail == {"$ref": "#/components/schemas/ErrorDetail"}
    assert set(components["ErrorDetail"]["required"]) == {"code", "message"}


def test_openapi_auth_responses_are_typed_and_preserve_nullable_user_fields():
    """消费方可依赖完整响应结构、null 资料及受限身份。"""
    spec = app.openapi()
    expected = {
        ("/api/auth/config", "get", "200"): "AuthConfig",
        ("/api/auth/email-code", "post", "202"): "EmailCodeResult",
        ("/api/auth/login/email", "post", "200"): "LoginResult",
        ("/api/auth/login/account", "post", "200"): "LoginResult",
        ("/api/auth/refresh", "post", "200"): "LoginResult",
        ("/api/auth/me", "get", "200"): "CurrentUserResult",
        ("/api/users/me", "put", "200"): "UserPayload",
        ("/api/users/me/email-change", "post", "201"): "EmailChangeResult",
        ("/api/users/me/user-no", "put", "200"): "UserPayload",
    }
    for (path, method, status), model in expected.items():
        schema = spec["paths"][path][method]["responses"][status]["content"]["application/json"]["schema"]
        assert schema == {"$ref": f"#/components/schemas/{model}"}, (path, method)
    user = spec["components"]["schemas"]["UserPayload"]
    assert user["properties"]["role"]["enum"] == ["teacher", "student", "admin"]
    assert "RegisterBody" not in spec["components"]["schemas"]
    assert "role" not in spec["components"]["schemas"]["EmailLoginBody"]["properties"]
    assert user["properties"]["email_verified"]["type"] == "boolean"
    assert "email_verified" in user["required"]
    assert user["properties"]["identity"]["enum"] == ["教师", "学生", "管理员"]
    for name in ("gender", "phone", "email", "user_no", "school", "avatar_url"):
        assert {"type": "null"} in user["properties"][name]["anyOf"]
        assert name in user["required"]
    for path, method in (("/api/auth/logout", "post"), ("/api/auth/password/reset", "post"),
                         ("/api/auth/password", "put"), ("/api/users/me/email", "put"),
                         ("/api/users/me/email", "delete"), ("/api/users/me/email-binding", "put")):
        assert "content" not in spec["paths"][path][method]["responses"]["204"]


def test_openapi_cookie_auth_declares_security_inputs(client):
    """刷新依赖必需刷新 Cookie，退出依赖必需访问凭证但允许无刷新 Cookie。"""
    spec = app.openapi()
    for path in ("/api/auth/refresh", "/api/auth/logout"):
        operation = spec["paths"][path]["post"]
        parameters = {(item["in"], item["name"]): item for item in operation["parameters"]}
        for location, name in (("header", "Origin"), ("header", "X-CSRF-Token"),
                               ("cookie", "mc_csrf")):
            assert parameters[(location, name)]["required"], (path, name)
        refresh = parameters[("cookie", "mc_refresh")]
        assert refresh["required"] is False
        if path.endswith("logout"):
            assert parameters[("header", "Authorization")]["required"]
    headers = csrf(client)
    missing_cookie = client.post("/api/auth/refresh", json={}, headers=headers)
    assert missing_cookie.status_code == 401
    assert missing_cookie.json()["detail"]["code"] == "SESSION_REVOKED"
    missing_csrf = client.post("/api/auth/logout", json={})
    assert missing_csrf.status_code == 403
