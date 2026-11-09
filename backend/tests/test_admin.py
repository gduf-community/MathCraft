from app.models import User
from app.models.base import new_id
from app.services.auth import hash_password


def admin_headers(client, db):
    db.add(
        User(
            id=new_id("u"),
            account="admin",
            password_hash=hash_password("12345678"),
            role="admin",
            identity="管理员",
            display_name="管理员",
            status="active",
        )
    )
    db.commit()
    resp = client.post("/api/auth/login/account", json={
        "account": "admin", "password": "12345678",
        "turnstile_token": "test-turnstile-token",
    })
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_admin_can_create_and_filter_accounts(client, db):
    headers = admin_headers(client, db)

    created = client.post(
        "/api/admin/accounts",
        json={"account": "teacher2", "display_name": "李老师", "role": "teacher", "password": "12345678"},
        headers=headers,
    )

    assert created.status_code == 201, created.text
    assert created.json()["role"] == "teacher"
    listed = client.get("/api/admin/accounts?query=teacher2&role=teacher", headers=headers)
    assert listed.status_code == 200
    assert [row["account"] for row in listed.json()] == ["teacher2"]


def test_admin_cannot_disable_last_admin(client, db):
    headers = admin_headers(client, db)
    admin_id = db.query(User).filter(User.account == "admin").one().id

    response = client.post(f"/api/admin/accounts/{admin_id}/disable", headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "LAST_ADMIN"


def test_teacher_cannot_use_admin_api(client, teacher):
    response = client.get("/api/admin/accounts", headers=teacher)

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "FORBIDDEN"
