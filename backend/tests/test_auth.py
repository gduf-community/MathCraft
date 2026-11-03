"""认证接口测试：登录、身份校验、会话、两版改密。"""


def test_login_teacher_and_me(client, teacher):
    resp = client.get("/api/auth/me", headers=teacher)
    assert resp.status_code == 200
    assert resp.json()["user"]["role"] == "teacher"
    assert resp.json()["user"]["display_name"] == "张老师"


def test_login_student(client):
    resp = client.post("/api/auth/login", json={"account": "student", "password": "123123", "role": "student"})
    assert resp.status_code == 200
    assert resp.json()["user"]["identity"] == "学生"


def test_role_mismatch_rejected(client):
    resp = client.post("/api/auth/login", json={"account": "student", "password": "123123", "role": "teacher"})
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ROLE_MISMATCH"


def test_bad_password(client):
    resp = client.post("/api/auth/login", json={"account": "teacher", "password": "wrong", "role": "teacher"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == "INVALID_CREDENTIALS"


def test_logout_invalidates_token(client, teacher):
    assert client.get("/api/auth/me", headers=teacher).status_code == 200
    resp = client.post("/api/auth/logout", headers=teacher)
    assert resp.status_code == 204
    assert client.get("/api/auth/me", headers=teacher).status_code == 401


def test_public_change_password(client):
    """登录页修改密码：无需登录态，改密后旧密码失效、旧会话失效。"""
    token_resp = client.post("/api/auth/login", json={"account": "student", "password": "123123", "role": "student"})
    headers = {"Authorization": f"Bearer {token_resp.json()['token']}"}

    resp = client.post(
        "/api/auth/change-password",
        json={"account": "student", "old_password": "123123", "new_password": "newpass123", "role": "student"},
    )
    assert resp.status_code == 204

    # 旧会话已失效
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    # 旧密码不可登录
    assert client.post(
        "/api/auth/login", json={"account": "student", "password": "123123", "role": "student"}
    ).status_code == 401
    # 新密码可登录
    assert client.post(
        "/api/auth/login", json={"account": "student", "password": "newpass123", "role": "student"}
    ).status_code == 200


def test_public_change_password_role_mismatch(client):
    resp = client.post(
        "/api/auth/change-password",
        json={"account": "teacher", "old_password": "123123", "new_password": "abcdef", "role": "student"},
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "ROLE_MISMATCH"


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
        "/api/auth/login", json={"account": "teacher", "password": "abcdef123", "role": "teacher"}
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
