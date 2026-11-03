"""个人资料、头像与密码修改测试。"""
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
            "email": "zhang@example.com",
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


def test_password_change_reflected(client, teacher):
    assert client.put(
        "/api/auth/password",
        json={"old_password": "123123", "new_password": "abc123456"},
        headers=teacher,
    ).status_code == 204
    assert client.post(
        "/api/auth/login", json={"account": "teacher", "password": "abc123456", "role": "teacher"}
    ).status_code == 200
