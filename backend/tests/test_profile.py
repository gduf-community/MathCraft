"""个人资料、头像与密码修改测试。"""
from test_auth import delivery  # noqa: F401
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_update_profile(client, teacher):
    resp = client.put(
        "/api/users/me",
        json={
            "display_name": "张教授",
            "gender": "女",
            "phone": "13900000000",
            "school": "中山大学",
        },
        headers=teacher,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["display_name"] == "张教授"
    assert data["gender"] == "女"
    assert data["phone"] == "13900000000"
    assert data["school"] == "中山大学"

    me = client.get("/api/auth/me", headers=teacher).json()["user"]
    assert me["display_name"] == "张教授"


def test_update_profile_invalid_phone(client, teacher):
    resp = client.put("/api/users/me", json={"phone": "12345"}, headers=teacher)
    assert resp.status_code == 422


def test_duplicate_phone_rejected(client, teacher, student):
    client.put("/api/users/me", json={"phone": "13800000002"}, headers=student)
    resp = client.put("/api/users/me", json={"phone": "13800000002"}, headers=teacher)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "DUPLICATE_FIELD"


def test_upload_avatar(client, teacher):
    resp = client.post(
        "/api/users/me/avatar",
        files={"file": ("avatar.png", PNG_BYTES, "image/png")},
        headers=teacher,
    )
    assert resp.status_code == 200, resp.text
    url = resp.json()["avatar_url"]
    assert url.startswith("/media/")

    media = client.get(url)
    assert media.status_code == 200
    assert media.content == PNG_BYTES

    me = client.get("/api/auth/me", headers=teacher).json()["user"]
    assert me["avatar_url"] == url


def test_upload_avatar_rejects_non_image(client, teacher):
    resp = client.post(
        "/api/users/me/avatar",
        files={"file": ("avatar.txt", b"hello", "text/plain")},
        headers=teacher,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "UNSUPPORTED_FORMAT"


def test_profile_rejects_security_fields(client, delivery):
    from test_auth import bearer, register

    result = register(client, delivery)
    for field, value in [("email", "bypass@example.com"), ("user_no", "123"),
                         ("role", "student"), ("email_verified", True), ("auth_version", 9)]:
        response = client.put("/api/users/me", json={field: value}, headers=bearer(result))
        assert response.status_code == 422
    assert client.get("/api/auth/me", headers=bearer(result)).json()["user"]["email"] == "new@example.com"


def test_user_number_change_requires_password_and_is_unique(client, delivery):
    from test_auth import PASSWORD, bearer, register

    first = register(client, delivery)
    second = register(client, delivery, email="other@example.com", user_no="001")
    assert client.put("/api/users/me/user-no", headers=bearer(first),
        json={"user_no": "002", "current_password": "wrong"}).status_code == 400
    assert client.put("/api/users/me/user-no", headers=bearer(first),
        json={"user_no": "001", "current_password": PASSWORD}).status_code == 409
    response = client.put("/api/users/me/user-no", headers=bearer(first),
        json={"user_no": "002", "current_password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["user_no"] == "002"
    assert client.put("/api/users/me/user-no", headers=bearer(first),
        json={"user_no": None, "current_password": PASSWORD}).status_code == 200
    assert client.get("/api/auth/me", headers=bearer(second)).status_code == 200


def test_email_change_requires_both_codes_and_revokes_sessions(client, delivery):
    from test_auth import bearer, issue, register

    result = register(client, delivery)
    headers = bearer(result)
    response = client.post("/api/users/me/email-change", headers=headers,
                           json={"new_email": "changed@example.com"})
    assert response.status_code == 201
    change = response.json()["change_id"]
    codes = []
    for email, purpose in [("new@example.com", "email_change_old"),
                           ("changed@example.com", "email_change_new")]:
        response = client.post("/api/auth/email-code", headers=headers, json={"email": email,
            "purpose": purpose, "change_id": change, "turnstile_token": "test-challenge"})
        assert response.status_code == 202, response.text
        codes.append((response.json()["challenge_id"], delivery.messages[-1][1]))
    payload = {"change_id": change, "old_challenge_id": codes[0][0], "old_code": codes[0][1],
               "new_challenge_id": codes[1][0], "new_code": codes[1][1]}
    wrong = dict(payload, new_code="111111" if codes[1][1] != "111111" else "222222")
    assert client.put("/api/users/me/email", headers=headers, json=wrong).status_code == 400
    assert client.get("/api/auth/me", headers=headers).json()["user"]["email"] == "new@example.com"
    assert client.put("/api/users/me/email", headers=headers, json=payload).status_code == 204
    assert client.get("/api/auth/me", headers=headers).status_code == 401
    challenge, code = issue(client, delivery, "changed@example.com", "login")
    assert client.post("/api/auth/login/email", json={"email": "changed@example.com",
        "challenge_id": challenge, "code": code, "role": "teacher"}).status_code == 200
