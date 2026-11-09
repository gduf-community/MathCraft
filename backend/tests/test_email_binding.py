"""绑定/解绑通过真实 HTTP、SQL proof 与隔离 Redis 验证安全边界。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier

import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import AuthProof, AuthSession, User
from app.services import auth as service
from test_auth import PASSWORD, bearer, csrf, delivery, issue, provision_user


def binding_code(client, delivery, result, email="bound@example.test"):
    """以当前 Bearer 申请绑定码，返回提交所需请求体。"""
    response = client.post("/api/auth/email-code", headers=bearer(result), json={
        "email": email, "purpose": "email_bind", "turnstile_token": "test-challenge",
    })
    assert response.status_code == 202, response.text
    return {"email": email, "current_password": PASSWORD,
            "challenge_id": response.json()["challenge_id"], "code": delivery.messages[-1][1]}


@pytest.mark.parametrize("role", ["teacher", "student", "admin"])
@pytest.mark.parametrize("email,verified", [(None, False), ("old@example.test", False),
                                          ("old@example.test", True)])
def test_account_login_independent_of_email_and_status_enforced(client, delivery, db, role,
                                                              email, verified):
    result = provision_user(client, delivery, email=email, verified=verified, role=role)
    assert result["user"]["role"] == role
    assert result["user"]["email_verified"] is verified
    user = db.get(User, result["user"]["id"])
    user.status = "disabled"
    db.commit()
    response = client.post("/api/auth/login/account", json={
        "account": user.account, "password": PASSWORD, "turnstile_token": "test-challenge",
    })
    assert response.status_code == 401
    assert client.get("/api/auth/me", headers=bearer(result)).status_code == 401


@pytest.mark.parametrize("email,normalized,flag,timestamp,expected", [
    (None, None, True, True, False),
    (None, "old@example.test", True, False, False),
    ("old@example.test", None, True, True, False),
    ("old@example.test", "different@example.test", True, True, False),
    ("not-an-email", "not-an-email", True, True, False),
    ("old@example.test", "old@example.test", False, False, False),
    ("old@example.test", "old@example.test", True, False, True),
    ("old@example.test", "old@example.test", False, True, True),
])
def test_email_verified_boolean_matches_current_email_delivery(
    client, delivery, db, email, normalized, flag, timestamp, expected,
):
    result = provision_user(client, delivery, email=None)
    user = db.get(User, result["user"]["id"])
    user.email = email
    user.email_normalized = normalized
    user.email_verified = flag
    user.email_verified_at = datetime.now(timezone.utc) if timestamp else None
    db.commit()
    response = client.get("/api/auth/me", headers=bearer(result))
    assert response.status_code == 200
    assert response.json()["user"]["email_verified"] is expected
    target = normalized if normalized and "@" in normalized else "old@example.test"
    for purpose in ("login", "reset_password"):
        before = len(delivery.messages)
        issue(client, delivery, email=target, purpose=purpose)
        assert (len(delivery.messages) > before) is expected


@pytest.mark.parametrize("original,target", [
    (None, "bound@example.test"),
    ("legacy@example.test", "legacy@example.test"),
    ("legacy@example.test", "bound@example.test"),
])
def test_binding_verifies_email_consumes_proof_and_revokes_all_devices(
    client, delivery, db, original, target,
):
    first = provision_user(client, delivery, email=original, verified=False)
    second = client.post("/api/auth/login/account", json={
        "account": first["user"]["account"], "password": PASSWORD,
        "turnstile_token": "test-challenge",
    }).json()
    payload = binding_code(client, delivery, first, target)
    response = client.put("/api/users/me/email-binding", headers=bearer(first), json=payload)
    assert response.status_code == 204, response.text
    assert response.content == b""
    assert response.headers["cache-control"] == "no-store"
    assert db.get(AuthProof, payload["challenge_id"]).purpose == "email_bind"
    user = db.get(User, first["user"]["id"])
    assert user.email == user.email_normalized == target
    assert user.email_verified is True and user.email_verified_at is not None
    assert user.auth_version == 1
    assert all(row.status == "revoked" for row in db.query(AuthSession).filter_by(user_id=user.id))
    for device in (first, second):
        assert client.get("/api/auth/me", headers=bearer(device)).status_code == 401
    challenge, code = issue(client, delivery, email=target)
    response = client.post("/api/auth/login/email", json={
        "email": target, "challenge_id": challenge, "code": code,
    })
    assert response.status_code == 200
    assert response.json()["user"]["email_verified"] is True
    assert client.put("/api/users/me/email-binding", headers=bearer(response.json()),
                      json=payload).status_code == 409


@pytest.mark.parametrize("flag,timestamp", [(True, False), (False, True)])
def test_verified_email_cannot_bypass_double_email_change(client, delivery, db, flag, timestamp):
    result = provision_user(client, delivery)
    user = db.get(User, result["user"]["id"])
    user.email_verified = flag
    user.email_verified_at = datetime.now(timezone.utc) if timestamp else None
    db.commit()
    response = client.post("/api/auth/email-code", headers=bearer(result), json={
        "email": "bypass@example.test", "purpose": "email_bind", "turnstile_token": "test-challenge",
    })
    assert response.status_code == 409
    assert delivery.messages == []
    response = client.put("/api/users/me/email-binding", headers=bearer(result), json={
        "email": "bypass@example.test", "current_password": PASSWORD,
        "challenge_id": "fake-challenge", "code": "012345",
    })
    assert response.status_code == 409
    db.refresh(user)
    assert user.email == "new@example.com" and user.auth_version == 0
    assert client.post("/api/users/me/email-change", headers=bearer(result),
                       json={"new_email": "replacement@example.test"}).status_code == 201


def test_email_binding_requires_bearer_and_current_password(client, delivery, db):
    result = provision_user(client, delivery, email=None)
    request = {"email": "bound@example.test", "purpose": "email_bind",
               "turnstile_token": "test-challenge"}
    for headers in ({}, {"Authorization": "Bearer fake-token"}):
        assert client.post("/api/auth/email-code", headers=headers, json=request).status_code == 401
    payload = binding_code(client, delivery, result)
    assert client.put("/api/users/me/email-binding", json=payload).status_code == 401
    response = client.put("/api/users/me/email-binding", headers=bearer(result),
                          json={**payload, "current_password": "wrong-password"})
    assert response.status_code == 400
    assert db.get(AuthProof, payload["challenge_id"]) is None
    assert client.get("/api/auth/me", headers=bearer(result)).status_code == 200
    assert client.put("/api/users/me/email-binding", headers=bearer(result), json=payload).status_code == 204


@pytest.mark.parametrize("mutation", ["user", "target", "version", "email", "normalized"])
def test_binding_challenge_cannot_cross_user_version_or_email_snapshot(
    client, delivery, db, mutation,
):
    result = provision_user(client, delivery, email="legacy@example.test", verified=False)
    payload = binding_code(client, delivery, result)
    user = db.get(User, result["user"]["id"])
    if mutation == "user":
        result = provision_user(client, delivery, email=None)
    elif mutation == "target":
        payload["email"] = "another@example.test"
    elif mutation == "version":
        service.revoke_all(db, user, user.auth_version)
        db.commit()
        result = client.post("/api/auth/login/account", json={
            "account": user.account, "password": PASSWORD, "turnstile_token": "test-challenge",
        }).json()
    else:
        setattr(user, "email" if mutation == "email" else "email_normalized", "changed@example.test")
        db.commit()
    response = client.put("/api/users/me/email-binding", headers=bearer(result), json=payload)
    assert response.status_code == 400, response.text
    assert db.get(AuthProof, payload["challenge_id"]) is None
    db.expire_all()
    assert db.get(User, result["user"]["id"]).email != payload["email"]


def test_binding_rejects_login_proof(client, delivery, db):
    owner = provision_user(client, delivery, email=None)
    provision_user(client, delivery, email="bound@example.test")
    challenge, code = issue(client, delivery, email="bound@example.test")
    response = client.put("/api/users/me/email-binding", headers=bearer(owner), json={
        "email": "bound@example.test", "current_password": PASSWORD,
        "challenge_id": challenge, "code": code,
    })
    assert response.status_code == 400
    assert db.get(AuthProof, challenge) is None


def test_binding_conflict_rolls_back_proof_and_revocation_then_allows_retry(client, delivery, db):
    result = provision_user(client, delivery, email=None)
    payload = binding_code(client, delivery, result)
    other = provision_user(client, delivery, email=payload["email"])
    assert client.put("/api/users/me/email-binding", headers=bearer(result),
                      json=payload).status_code == 409
    assert db.get(AuthProof, payload["challenge_id"]) is None
    user = db.get(User, result["user"]["id"])
    assert user.email is None and user.auth_version == 0
    assert client.get("/api/auth/me", headers=bearer(result)).status_code == 200
    occupied = db.get(User, other["user"]["id"])
    occupied.email = occupied.email_normalized = None
    occupied.email_verified = False
    occupied.email_verified_at = None
    db.commit()
    assert client.put("/api/users/me/email-binding", headers=bearer(result), json=payload).status_code == 204


@pytest.mark.parametrize("operation", ["bind", "unbind"])
def test_email_change_commit_failure_is_atomic_and_retryable(client, delivery, db, operation):
    result = provision_user(client, delivery, email=None if operation == "bind" else "old@example.test")
    payload = (binding_code(client, delivery, result) if operation == "bind"
               else {"current_password": PASSWORD})
    method = "PUT" if operation == "bind" else "DELETE"
    path = "/api/users/me/email-binding" if operation == "bind" else "/api/users/me/email"

    def fail_commit(session):
        raise OperationalError("injected commit failure", {}, Exception("test only"))

    event.listen(Session, "before_commit", fail_commit)
    try:
        response = client.request(method, path, headers=bearer(result), json=payload)
    finally:
        event.remove(Session, "before_commit", fail_commit)
    assert response.status_code == 503
    user = db.get(User, result["user"]["id"])
    assert user.email == result["user"]["email"] and user.auth_version == 0
    assert client.get("/api/auth/me", headers=bearer(result)).status_code == 200
    if operation == "bind":
        assert db.get(AuthProof, payload["challenge_id"]) is None
    assert client.request(method, path, headers=bearer(result), json=payload).status_code == 204


@pytest.mark.parametrize("operation", ["bind", "unbind"])
@pytest.mark.parametrize("cookie_owner", ["self", "other", "rotated", "absent"])
def test_email_changes_clear_only_proven_owner_cookie(client, delivery, operation, cookie_owner):
    result = provision_user(client, delivery, email=None if operation == "bind" else "old@example.test")
    cookie = client.cookies.get("mc_refresh")
    if cookie_owner == "rotated":
        assert client.post("/api/auth/refresh", headers=csrf(client), json={}).status_code == 200
    elif cookie_owner == "other":
        other = provision_user(client, delivery, email="other@example.test")
        cookie = client.cookies.get("mc_refresh")
    headers = bearer(result)
    if cookie_owner != "absent":
        # 显式模拟携带 Cookie；默认 /api/auth Path 不会发送给 /api/users。
        headers["Cookie"] = f"mc_refresh={cookie}"
    if operation == "bind":
        payload = binding_code(client, delivery, result)
        response = client.put("/api/users/me/email-binding", headers=headers, json=payload)
    else:
        response = client.request("DELETE", "/api/users/me/email", headers=headers,
                                  json={"current_password": PASSWORD})
    assert response.status_code == 204, response.text
    assert response.content == b"" and response.headers["cache-control"] == "no-store"
    assert ("mc_refresh=" in response.headers.get("set-cookie", "")) is (cookie_owner in {"self", "rotated"})
    assert client.get("/api/auth/me", headers=bearer(result)).status_code == 401
    if cookie_owner == "other":
        assert client.cookies.get("mc_refresh") == cookie
        refreshed = client.post("/api/auth/refresh", headers=csrf(client), json={})
        assert refreshed.status_code == 200
        assert refreshed.json()["user"]["id"] == other["user"]["id"]


def test_unbind_clears_markers_invalidates_outstanding_codes_and_keeps_account_login(
    client, delivery, db,
):
    result = provision_user(client, delivery)
    codes = {purpose: issue(client, delivery, purpose=purpose) for purpose in ("login", "reset_password")}
    assert client.request("DELETE", "/api/users/me/email", json={"current_password": PASSWORD}).status_code == 401
    assert client.request("DELETE", "/api/users/me/email", headers=bearer(result),
                          json={"current_password": "wrong"}).status_code == 400
    response = client.request("DELETE", "/api/users/me/email", headers=bearer(result),
                              json={"current_password": PASSWORD})
    assert response.status_code == 204
    user = db.get(User, result["user"]["id"])
    assert user.email is None and user.email_normalized is None
    assert user.email_verified is False and user.email_verified_at is None
    assert user.auth_version == 1
    for purpose, (challenge, code) in codes.items():
        payload = {"email": "new@example.com", "challenge_id": challenge, "code": code}
        if purpose == "reset_password":
            payload.update(new_password="replacement-password", confirm_password="replacement-password")
        path = "/api/auth/login/email" if purpose == "login" else "/api/auth/password/reset"
        assert client.post(path, json=payload).status_code == 400
    response = client.post("/api/auth/login/account", json={
        "account": user.account, "password": PASSWORD, "turnstile_token": "test-challenge",
    })
    assert response.status_code == 200
    assert response.json()["user"]["email_verified"] is False


def test_old_login_and_reset_codes_cannot_follow_email_to_another_user_at_same_version(
    client, delivery, db, isolated_redis,
):
    """邮箱转移后版本号相同也不能把旧账号 proof 消费在新账号上。"""
    email = "transfer@example.test"
    first = provision_user(client, delivery, email=None)
    initial = binding_code(client, delivery, first, email)
    assert client.put("/api/users/me/email-binding", headers=bearer(first), json=initial).status_code == 204
    first = client.post("/api/auth/login/account", json={
        "account": first["user"]["account"], "password": PASSWORD,
        "turnstile_token": "test-challenge",
    }).json()
    assert db.get(User, first["user"]["id"]).auth_version == 1
    codes = {purpose: issue(client, delivery, email=email, purpose=purpose)
             for purpose in ("login", "reset_password")}
    # 记住公开挑战的原状态；后续只签发 email_bind，不能依靠重发废弃旧码。
    original = {purpose: isolated_redis.hgetall(f"auth:otp:challenge:{challenge}")
                for purpose, (challenge, _) in codes.items()}
    assert client.request("DELETE", "/api/users/me/email", headers=bearer(first),
                          json={"current_password": PASSWORD}).status_code == 204
    second = provision_user(client, delivery, email=None)
    # 仅清首次 email_bind 的冷却；公开 login/reset 的最新挑战必须保留不变。
    from app.services.auth_codes import _keys

    isolated_redis.delete(_keys(email, "email_bind")[0])
    replacement = binding_code(client, delivery, second, email)
    assert client.put("/api/users/me/email-binding", headers=bearer(second),
                      json=replacement).status_code == 204
    second_user = db.get(User, second["user"]["id"])
    assert second_user.auth_version == 1
    assert second_user.email_normalized == email
    unchanged_hash = second_user.password_hash
    for purpose, (challenge, code) in codes.items():
        assert isolated_redis.hgetall(f"auth:otp:challenge:{challenge}") == original[purpose]
        assert isolated_redis.get(_keys(email, purpose)[2]) == challenge
        payload = {"email": email, "challenge_id": challenge, "code": code}
        if purpose == "reset_password":
            payload.update(new_password="stolen-replacement-password",
                           confirm_password="stolen-replacement-password")
        path = "/api/auth/login/email" if purpose == "login" else "/api/auth/password/reset"
        response = client.post(path, json=payload)
        assert response.status_code == 400, response.text
        assert response.json()["detail"]["code"] == "CODE_INVALID"
        assert db.get(AuthProof, challenge) is None
    db.refresh(second_user)
    assert second_user.password_hash == unchanged_hash and second_user.auth_version == 1
    response = client.post("/api/auth/login/account", json={
        "account": second_user.account, "password": PASSWORD, "turnstile_token": "test-challenge",
    })
    assert response.status_code == 200
    assert response.json()["user"]["id"] == second_user.id
    assert response.json()["user"]["email_verified"] is True


@pytest.mark.parametrize("operation", ["bind", "unbind"])
def test_email_change_cannot_use_password_verified_before_reset(client, delivery, monkeypatch, operation):
    result = provision_user(client, delivery, email="legacy@example.test", verified=operation != "bind")
    payload = binding_code(client, delivery, result) if operation == "bind" else {"current_password": PASSWORD}
    entered, resume = Barrier(2), Barrier(2)
    original = service.verify_password

    def paused_verify(password, hashed):
        valid = original(password, hashed)
        entered.wait(timeout=10)
        resume.wait(timeout=10)
        return valid

    monkeypatch.setattr(service, "verify_password", paused_verify)
    method = "PUT" if operation == "bind" else "DELETE"
    path = "/api/users/me/email-binding" if operation == "bind" else "/api/users/me/email"
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.request, method, path, headers=bearer(result), json=payload)
        entered.wait(timeout=10)
        from app.db import SessionLocal

        with SessionLocal() as db:
            user = db.get(User, result["user"]["id"])
            service.revoke_all(db, user, user.auth_version)
            user.password_hash = service.hash_password("replacement-password")
            db.commit()
        resume.wait(timeout=10)
        assert future.result(timeout=15).status_code == 401
