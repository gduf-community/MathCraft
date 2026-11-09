"""认证安全 HTTP 验收：实际 SQLite/FakeRedis 竞争及外部边界故障。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import jwt
import pytest
import redis
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import settings
from app.services import auth as service, cache
from test_auth import PASSWORD, bearer, csrf, delivery, issue, provision_user


def test_logout_only_revokes_current_device(client, delivery):
    first = provision_user(client, delivery, user_no="device01")
    second = client.post("/api/auth/login/account", json={"account": "device01", "password": PASSWORD, "turnstile_token": "test-challenge"}).json()
    headers = {**csrf(client), **bearer(first)}
    response = client.post("/api/auth/logout", json={}, headers=headers)
    assert response.status_code == 204, response.text
    assert "mc_refresh=" not in response.headers.get("set-cookie", "")
    assert client.get("/api/auth/me", headers=bearer(first)).status_code == 401
    assert client.get("/api/auth/me", headers=bearer(second)).status_code == 200
    assert client.post("/api/auth/refresh", json={}, headers=csrf(client)).status_code == 200


def test_logout_preserves_other_account_cookie(client, delivery):
    first = provision_user(client, delivery, email="logout-a@example.test", user_no="logout-a")
    second = provision_user(client, delivery, email="logout-b@example.test", user_no="logout-b")
    response = client.post("/api/auth/logout", json={}, headers={**csrf(client), **bearer(first)})
    assert response.status_code == 204, response.text
    assert client.get("/api/auth/me", headers=bearer(first)).status_code == 401
    assert client.get("/api/auth/me", headers=bearer(second)).status_code == 200
    refreshed = client.post("/api/auth/refresh", json={}, headers=csrf(client))
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["user"]["id"] == second["user"]["id"]


def test_logout_accepts_expired_signed_access_without_refresh(client, delivery):
    result = provision_user(client, delivery, user_no="expired-logout")
    claims = jwt.decode(result["access_token"], options={"verify_signature": False})
    claims["exp"] = service.now() - 1
    claims["iat"] = service.now() - 100
    expired = jwt.encode(claims, settings.auth_jwt_secret, algorithm="HS256")
    headers = {**csrf(client), "Authorization": "Bearer " + expired}
    response = client.post("/api/auth/logout", json={}, headers=headers)
    assert response.status_code == 204, response.text
    assert "mc_refresh=" in response.headers.get("set-cookie", "")
    assert client.get("/api/auth/me", headers=bearer(result)).status_code == 401
    assert client.post("/api/auth/logout", json={}, headers=headers).status_code == 204


def test_logout_requires_signed_bearer_and_csrf(client, delivery):
    result = provision_user(client, delivery, user_no="secure-logout")
    csrf_headers = csrf(client)
    missing = client.post("/api/auth/logout", json={}, headers=csrf_headers)
    assert missing.status_code == 401
    assert "mc_refresh=" not in missing.headers.get("set-cookie", "")
    forged = jwt.decode(result["access_token"], options={"verify_signature": False})
    bad_token = jwt.encode(forged, "fake-untrusted-signing-key-0123456789", algorithm="HS256")
    assert client.post("/api/auth/logout", json={}, headers={
        **csrf_headers, "Authorization": "Bearer " + bad_token}).status_code == 401
    assert client.post("/api/auth/logout", json={}, headers=bearer(result)).status_code == 403
    assert client.post("/api/auth/logout", json={}, headers={
        **csrf_headers, **bearer(result), "Origin": "https://untrusted.example.test"}).status_code == 403
    assert client.get("/api/auth/me", headers=bearer(result)).status_code == 200


def test_sql_failure_releases_proof_for_retry(client, delivery):
    result = provision_user(client, delivery, user_no="reset01")
    challenge, code = issue(client, delivery, purpose="reset_password")
    payload = {"email": "new@example.com", "challenge_id": challenge, "code": code,
               "new_password": "changed-password", "confirm_password": "changed-password"}
    calls = 0

    def fail_once(session):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OperationalError("injected commit fault", {}, Exception("test only"))

    event.listen(Session, "before_commit", fail_once)
    try:
        response = client.post("/api/auth/password/reset", json=payload)
        assert response.status_code == 503, response.text
        assert client.get("/api/auth/me", headers=bearer(result)).status_code == 200
        assert client.post("/api/auth/password/reset", json=payload).status_code == 204
    finally:
        event.remove(Session, "before_commit", fail_once)
    assert client.get("/api/auth/me", headers=bearer(result)).status_code == 401


def test_email_login_commit_failure_releases_proof_without_partial_session(client, delivery, db):
    from app.models import AuthProof, AuthSession

    result = provision_user(client, delivery)
    challenge, code = issue(client, delivery)
    sessions = db.query(AuthSession).count()

    def fail_session_commit(session):
        raise OperationalError("injected session failure", {}, Exception("test only"))

    event.listen(Session, "before_commit", fail_session_commit)
    try:
        response = client.post("/api/auth/login/email", json={"email": "new@example.com",
            "challenge_id": challenge, "code": code})
    finally:
        event.remove(Session, "before_commit", fail_session_commit)
    assert response.status_code == 503
    assert db.get(AuthProof, challenge) is None
    assert db.query(AuthSession).count() == sessions
    assert client.get("/api/auth/me", headers=bearer(result)).status_code == 200
    assert client.post("/api/auth/login/email", json={"email": "new@example.com",
        "challenge_id": challenge, "code": code}).status_code == 200


def test_concurrent_same_code_only_one_login(client, delivery):
    provision_user(client, delivery)
    challenge, code = issue(client, delivery)
    gate = Barrier(2)
    payload = {"email": "new@example.com", "challenge_id": challenge, "code": code}

    def submit():
        gate.wait(timeout=10)
        return client.post("/api/auth/login/email", json=payload).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: submit(), range(2)))
    assert outcomes.count(200) == 1, outcomes
    assert all(code in {200, 400, 409} for code in outcomes), outcomes


def test_concurrent_user_number_change_preserves_unique_constraint(client, delivery):
    accounts = [provision_user(client, delivery, email=email)
                for email in ("one@example.com", "two@example.com")]
    gate = Barrier(2)

    def submit(result):
        gate.wait(timeout=10)
        return client.put("/api/users/me/user-no", headers=bearer(result),
            json={"user_no": "shared001", "current_password": PASSWORD}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, accounts))
    assert sorted(outcomes) == [200, 409], outcomes


def test_code_binding_expiry_and_resend(client, delivery, monkeypatch):
    provision_user(client, delivery)
    challenge, code = issue(client, delivery)
    payload = {"email": "different@example.com", "challenge_id": challenge, "code": code}
    assert client.post("/api/auth/login/email", json=payload).status_code == 400
    issued = service.now()
    monkeypatch.setattr(service, "now", lambda: issued + settings.auth_code_ttl_seconds + 1)
    payload["email"] = "new@example.com"
    assert client.post("/api/auth/login/email", json=payload).json()["detail"]["code"] == "CODE_EXPIRED"


def test_redis_outage_fails_closed(client, delivery, monkeypatch):
    def unavailable():
        raise redis.ConnectionError("injected test outage")

    monkeypatch.setattr(cache, "get_redis", unavailable)
    response = client.post("/api/auth/email-code", json={"email": "new@example.com",
        "purpose": "login", "turnstile_token": "test-challenge"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AUTH_SERVICE_UNAVAILABLE"


def test_jwt_claims_algorithm_and_signature_rejected(client, delivery):
    result = provision_user(client, delivery)
    claims = jwt.decode(result["access_token"], settings.auth_jwt_secret,
                        algorithms=["HS256"], audience=settings.auth_jwt_audience)
    mutations = [{"iss": "wrong"}, {"aud": "wrong"}, {"type": "refresh"}, {"sub": "unknown"},
                 {"auth_version": 999}, {"sid": "unknown"}, {"iat": service.now() + 1000}]
    for change in mutations:
        invalid = jwt.encode({**claims, **change}, settings.auth_jwt_secret, algorithm="HS256")
        assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {invalid}"}).status_code == 401
    wrong_algorithm = jwt.encode(claims, settings.auth_jwt_secret, algorithm="HS384")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {wrong_algorithm}"}).status_code == 401
    wrong_key = jwt.encode(claims, "test-wrong-key-long-enough-01234567890123456789", algorithm="HS256")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {wrong_key}"}).status_code == 401


def test_cookie_attributes_and_json_boundary(client, delivery):
    result = provision_user(client, delivery)
    headers = csrf(client)
    response = client.post("/api/auth/refresh", json={}, headers=headers)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/api/auth" in cookie
    assert "domain=" not in cookie
    assert client.post("/api/auth/refresh", content="not-json",
        headers={**headers, "Content-Type": "application/json"}).status_code == 422
    assert client.get("/api/auth/me", headers=bearer(result)).status_code == 200


def test_login_old_password_cannot_cross_password_reset(client, delivery, monkeypatch):
    result = provision_user(client, delivery, user_no="race01")
    entered = Barrier(2)
    resume = Barrier(2)
    original = service.verify_password

    def paused_verify(password, hashed):
        valid = original(password, hashed)
        if password == PASSWORD:
            entered.wait(timeout=10)
            resume.wait(timeout=10)
        return valid

    challenge, code = issue(client, delivery, purpose="reset_password")
    monkeypatch.setattr(service, "verify_password", paused_verify)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.post, "/api/auth/login/account", json={"account": "race01",
            "password": PASSWORD, "turnstile_token": "test-challenge"})
        entered.wait(timeout=10)
        response = client.post("/api/auth/password/reset", json={"email": "new@example.com",
            "challenge_id": challenge, "code": code,
            "new_password": "replacement-password", "confirm_password": "replacement-password"})
        assert response.status_code == 204, response.text
        resume.wait(timeout=10)
        response = future.result(timeout=15)
    assert response.status_code == 401, response.text
    assert client.get("/api/auth/me", headers=bearer(result)).status_code == 401


def test_resend_invalidates_old_code(client, delivery, isolated_redis):
    provision_user(client, delivery)
    challenge, code = issue(client, delivery)
    for key in isolated_redis.scan_iter("auth:otp:cool:*"):
        isolated_redis.delete(key)
    replacement, replacement_code = issue(client, delivery)
    payload = {"email": "new@example.com", "challenge_id": challenge, "code": code}
    assert client.post("/api/auth/login/email", json=payload).status_code == 400
    payload.update(challenge_id=replacement, code=replacement_code)
    assert client.post("/api/auth/login/email", json=payload).status_code == 200


def test_sensitive_number_change_cannot_use_pre_reset_password(client, delivery, monkeypatch):
    result = provision_user(client, delivery, user_no="sensitive01")
    entered, resume = Barrier(2), Barrier(2)
    original = service.verify_password

    def paused_verify(password, hashed):
        valid = original(password, hashed)
        entered.wait(timeout=10)
        resume.wait(timeout=10)
        return valid

    challenge, code = issue(client, delivery, purpose="reset_password")
    monkeypatch.setattr(service, "verify_password", paused_verify)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(client.put, "/api/users/me/user-no", headers=bearer(result),
            json={"user_no": "hijacked01", "current_password": PASSWORD})
        entered.wait(timeout=10)
        response = client.post("/api/auth/password/reset", json={"email": "new@example.com",
            "challenge_id": challenge, "code": code, "new_password": "new-secret-password",
            "confirm_password": "new-secret-password"})
        assert response.status_code == 204
        resume.wait(timeout=10)
        assert future.result(timeout=15).status_code == 401


def test_concurrent_refresh_replay_revokes_family(client, delivery):
    from starlette.testclient import TestClient
    from app.main import app

    result = provision_user(client, delivery)
    cookie = client.cookies.get("mc_refresh")
    csrf_token = client.get("/api/auth/config").json()["csrf_token"]
    gate = Barrier(2)

    def refresh_once():
        with TestClient(app) as device:
            device.cookies.set("mc_refresh", cookie, path="/api/auth")
            device.cookies.set("mc_csrf", csrf_token, path="/api/auth")
            gate.wait(timeout=10)
            return device.post("/api/auth/refresh", json={}, headers={
                "Origin": "http://127.0.0.1:5173", "X-CSRF-Token": csrf_token}).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: refresh_once(), range(2)))
    assert sorted(outcomes) == [200, 401], outcomes
    assert client.get("/api/auth/me", headers=bearer(result)).status_code == 401


def test_development_account_post_requires_exact_origin_and_direct_loopback(client, db, monkeypatch):
    """同源浏览器可用 POST 发送 Origin，但不能绕过本机与白名单限制。"""
    import importlib

    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from app.api import auth as auth_routes
    from app.errors import AppError
    from app.main import app_error_handler

    with monkeypatch.context() as patch:
        patch.setattr(settings, "app_env", "development")
        patch.setattr(settings, "dev_accounts_enabled", True)
        patch.setattr(settings, "dev_teacher_user_no", "TK20240001")
        patch.setattr(settings, "dev_teacher_password", "fake-dev-password-only")
        importlib.reload(auth_routes)
        test_app = FastAPI()
        test_app.include_router(auth_routes.router)
        test_app.add_exception_handler(AppError, app_error_handler)
        try:
            with TestClient(test_app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as browser:
                path = "/api/auth/development-account?role=teacher"
                headers = {"Origin": "http://127.0.0.1:5173"}
                response = browser.post(path, json={}, headers=headers)
                assert response.status_code == 200
                assert response.json() == {"role": "teacher", "account": "teacher",
                                           "password": "fake-dev-password-only"}
                assert response.headers["cache-control"] == "no-store"
                assert browser.post(path, json={}).status_code == 403
                assert browser.post(path, json={}, headers={"Origin": "http://localhost:5173"}).status_code == 403
                assert browser.post(path, json={}, headers={**headers, "X-Forwarded-For": "127.0.0.1"}).status_code == 403
                assert browser.post(path, json={}, headers={**headers, "Host": "evil.example"}).status_code == 403
            with TestClient(test_app, base_url="http://127.0.0.1", client=("192.0.2.1", 50000)) as remote:
                assert remote.post(path, json={}, headers=headers).status_code == 403
        finally:
            patch.setattr(settings, "app_env", "test")
            patch.setattr(settings, "dev_accounts_enabled", False)
            importlib.reload(auth_routes)
