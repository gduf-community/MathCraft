"""认证接口测试：统一登录、身份校验、会话与改密。"""

from app.models import User
from app.services.auth import hash_password


def test_login_teacher_and_me(client, teacher):
    resp = client.get("/api/auth/me", headers=teacher)
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "teacher"
    assert resp.json()["user"]["display_name"] == "张老师"


def test_login_student(client):
    resp = client.post("/api/auth/login", json={"account": "student", "password": "123123"})
    assert resp.status_code == 200
    assert resp.json()["user"]["identity"] == "学生"


def test_login_identifies_admin_without_role_parameter(client, db):
    db.add(
        User(
            id="u_admin_test",
            account="admin.test",
            password_hash=hash_password("123123"),
            role="admin",
            identity="\u7ba1\u7406\u5458",
            display_name="\u5e73\u53f0\u7ba1\u7406\u5458",
            status="active",
        )
    )
    db.commit()

    resp = client.post("/api/auth/login", json={"account": "admin.test", "password": "123123"})

    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "admin"
    assert resp.json()["user"]["identity"] == "\u7ba1\u7406\u5458"


def test_bad_password(client):
    resp = client.post("/api/auth/login", json={"account": "teacher", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "INVALID_CREDENTIALS"


def test_login_rejects_invalid_account_format(client):
    resp = client.post(
        "/api/auth/login", json={"account": "teacher account", "password": "123123"}
    )

    assert resp.status_code == 422


def test_logout_invalidates_token(client, teacher):
    assert client.get("/api/auth/me", headers=teacher).status_code == 200
    resp = client.post("/api/auth/logout", headers=teacher)
    assert resp.status_code == 204
    assert client.get("/api/auth/me", headers=teacher).status_code == 401


def test_public_change_password(client):
    """登录页修改密码：无需登录态，改密后旧密码失效、旧会话失效。"""
    token_resp = client.post("/api/auth/login", json={"account": "student", "password": "123123"})
    headers = {"Authorization": f"Bearer {token_resp.json()['token']}"}

    resp = client.post(
        "/api/auth/change-password",
        json={"account": "student", "old_password": "123123", "new_password": "newpass123"},
    )
    assert resp.status_code == 204

    # 旧会话已失效
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    # 旧密码不可登录
    assert client.post(
        "/api/auth/login", json={"account": "student", "password": "123123"}
    ).status_code == 401
    # 新密码可登录
    assert client.post(
        "/api/auth/login", json={"account": "student", "password": "newpass123"}
    ).status_code == 200


def test_disabled_account_cannot_use_existing_session(client, teacher, db):
    db.query(User).filter(User.account == "teacher").one().status = "disabled"
    db.commit()

    resp = client.get("/api/auth/me", headers=teacher)

    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ACCOUNT_DISABLED"


def test_public_change_password_does_not_require_role(client):
    resp = client.post(
        "/api/auth/change-password",
        json={"account": "teacher", "old_password": "123123", "new_password": "abcdef"},
    )
    assert resp.status_code == 204


def test_logout_only_invalidates_current_device(client, auth):
    first = auth("teacher")
    second = auth("teacher")

    assert client.post("/api/auth/logout", headers=first).status_code == 204
    assert client.get("/api/auth/me", headers=first).status_code == 401
    assert client.get("/api/auth/me", headers=second).status_code == 200


def test_logged_in_change_password(client, teacher):
    resp = client.put(
        "/api/auth/password",
        json={"old_password": "123123", "new_password": "abcdef123"},
        headers=teacher,
    )
    assert resp.status_code == 204
    # 改密会清理全部会话
    assert client.get("/api/auth/me", headers=teacher).status_code == 401
    assert client.post(
        "/api/auth/login", json={"account": "teacher", "password": "abcdef123"}
    ).status_code == 200


def test_logged_in_change_password_wrong_old(client, teacher):
    resp = client.put(
        "/api/auth/password",
        json={"old_password": "wrong", "new_password": "abcdef123"},
        headers=teacher,
    )
    assert resp.status_code == 400


def test_unauthenticated_requests(client):
    assert client.get("/api/banks").status_code == 401
    assert client.get("/api/auth/me", headers={"Authorization": "Bearer bad"}).status_code == 401
