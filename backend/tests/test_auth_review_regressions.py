"""审查 I01/I02/I05/I06/I07/I08/I15/I20 回归，仅使用公共隔离夹具及假值。"""
import asyncio
import traceback

import pytest
from pydantic import ValidationError
from sqlalchemy import event

from app.api import users
from app.config import Settings, settings
from app.db import SessionLocal
from app.errors import AppError
from app.models import AuthProof, AuthSession, EmailChange, RefreshUse, User, UserModelSetting
from app.services import auth as service, auth_codes
from app.services.model_settings import get_setting
from test_auth import PASSWORD, bearer, csrf, delivery, issue, provision_user


def test_settings_failure_does_not_render_other_credentials():
    fake_key = "short-fake-key"
    fake_mail_password = "fake-mail-secret-must-not-appear"
    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None, auth_jwt_secret=fake_key, smtp_password=fake_mail_password)
    rendered = "".join(traceback.format_exception(error.value))
    assert "fake-mail-secret-must-not-appear" not in rendered
    assert "short-fake-key" not in rendered


def test_email_login_requires_proof_before_disclosing_role_or_status(client, delivery, db):
    result = provision_user(client, delivery, email="known@example.test")
    payload = {"email": "known@example.test", "challenge_id": "unissued-fake-challenge",
               "code": "111111"}
    responses = [client.post("/api/auth/login/email", json=payload)]
    user = db.get(User, result["user"]["id"])
    user.status = "disabled"
    db.commit()
    responses.append(client.post("/api/auth/login/email", json=payload))
    responses.append(client.post("/api/auth/login/email", json={
        **payload, "email": "unknown@example.test"}))
    assert all(response.status_code == 400 for response in responses)
    assert all(response.json() == responses[0].json() for response in responses)


def test_login_unknown_and_mail_failure_keep_same_challenge_errors(
    client, delivery, isolated_redis,
):
    provision_user(client, delivery, email="occupied@example.test")
    for key in isolated_redis.scan_iter("auth:otp:cool:*"):
        isolated_redis.delete(key)
    delivery.fail = True
    errors = []
    for email in ("occupied@example.test", "mail-failure@example.test"):
        challenge, _ = issue(client, delivery, email=email)
        codes = []
        for _ in range(settings.auth_code_max_attempts):
            response = client.post("/api/auth/login/email", json={
                "email": email, "challenge_id": challenge, "code": "111111",
            })
            assert response.status_code == 400
            codes.append(response.json()["detail"]["code"])
        errors.append(codes)
    assert errors[0] == errors[1]
    assert errors[0][0] == "CODE_INVALID"
    assert errors[0][-1] == "CODE_ATTEMPTS_EXCEEDED"


@pytest.mark.parametrize("operation", ["change", "reset", "email"])
@pytest.mark.parametrize("other_account", [False, True])
def test_security_change_preserves_other_account_refresh_cookie(
    client, delivery, operation, other_account,
):
    first = provision_user(client, delivery, email="owner-a@example.test")
    second = provision_user(client, delivery, email="owner-b@example.test") if other_account else first
    cookie = client.cookies.get("mc_refresh")
    password = {"new_password": "replacement-test-password",
                "confirm_password": "replacement-test-password"}
    if operation == "change":
        response = client.put("/api/auth/password", headers=bearer(first),
                              json={**password, "old_password": PASSWORD})
    elif operation == "reset":
        challenge, code = issue(client, delivery, email="owner-a@example.test",
                                purpose="reset_password")
        response = client.post("/api/auth/password/reset", json={
            **password, "email": "owner-a@example.test", "challenge_id": challenge, "code": code,
        })
    else:
        change = client.post("/api/users/me/email-change", headers=bearer(first),
                             json={"new_email": "replacement@example.test"}).json()["change_id"]
        challenges = []
        for email, purpose in (("owner-a@example.test", "email_change_old"),
                               ("replacement@example.test", "email_change_new")):
            issued = client.post("/api/auth/email-code", headers=bearer(first), json={
                "email": email, "purpose": purpose, "change_id": change,
                "turnstile_token": "test-challenge",
            })
            assert issued.status_code == 202
            challenges.append((issued.json()["challenge_id"], delivery.messages[-1][1]))
        response = client.put("/api/users/me/email", headers=bearer(first), json={
            "change_id": change, "old_challenge_id": challenges[0][0],
            "old_code": challenges[0][1], "new_challenge_id": challenges[1][0],
            "new_code": challenges[1][1],
        })
    assert response.status_code == 204, response.text
    assert client.get("/api/auth/me", headers=bearer(first)).status_code == 401
    if other_account:
        assert client.cookies.get("mc_refresh") == cookie
        assert "mc_refresh=" not in response.headers.get("set-cookie", "")
        refreshed = client.post("/api/auth/refresh", json={}, headers=csrf(client))
        assert refreshed.status_code == 200
        assert refreshed.json()["user"]["id"] == second["user"]["id"]
    elif operation != "email":
        assert client.cookies.get("mc_refresh") is None
    else:
        # /api/users 不携带 Path=/api/auth 的 Cookie；无归属证据不得删除共享 Cookie。
        assert "mc_refresh=" not in response.headers.get("set-cookie", "")
        assert client.post("/api/auth/refresh", json={}, headers=csrf(client)).status_code == 401


def test_password_change_recognizes_rotated_cookie_owner(client, delivery):
    result = provision_user(client, delivery)
    previous = client.cookies.get("mc_refresh")
    assert client.post("/api/auth/refresh", json={}, headers=csrf(client)).status_code == 200
    client.cookies.set("mc_refresh", previous, domain="testserver.local", path="/api/auth")
    response = client.put("/api/auth/password", headers=bearer(result), json={
        "old_password": PASSWORD, "new_password": "replacement-test-password",
        "confirm_password": "replacement-test-password",
    })
    assert response.status_code == 204
    assert client.cookies.get("mc_refresh") is None


def test_missing_settings_creation_keeps_version_lock_until_final_commit(client, delivery, db):
    result = provision_user(client, delivery)
    user_id = result["user"]["id"]
    row = db.get(UserModelSetting, user_id)
    db.delete(row)
    db.commit()
    commits = []

    def record_commit(session):
        commits.append(session)

    event.listen(db, "after_commit", record_commit)
    try:
        service.assert_version(db, user_id, 0)
        row = get_setting(db, user_id)
        row.deepseek_api_key = "fake-test-key-only"
        assert commits == []
        # 整体回滚必须同时撤回首次创建及密钥写入。
        db.rollback()
        assert db.get(UserModelSetting, user_id) is None
    finally:
        event.remove(db, "after_commit", record_commit)
    with SessionLocal() as stale:
        stale_user = stale.get(User, user_id)
        user = db.get(User, user_id)
        service.revoke_all(db, user, user.auth_version)
        db.commit()
        with pytest.raises(AppError) as error:
            users.save_model_settings(
                users.ModelSettingsBody(deepseek_api_key="fake-stale-key"), stale_user, stale,
            )
        assert error.value.status_code == 401
    assert db.get(UserModelSetting, user_id) is None


def test_avatar_read_is_bounded_before_rejection(monkeypatch):
    monkeypatch.setattr(settings, "max_avatar_mb", 1)
    reads = []

    class OversizedUpload:
        content_type = "image/png"

        async def read(self, size=-1):
            reads.append(size)
            assert 0 < size <= 1024 * 1024 + 1
            return b"x" * size

    with pytest.raises(AppError) as error:
        asyncio.run(users.upload_avatar(OversizedUpload(), None, None))
    assert error.value.status_code == 422
    assert reads == [1024 * 1024 + 1]


def test_expired_records_cleanup_preserves_live_replay_evidence(client, delivery, db, monkeypatch):
    result = provision_user(client, delivery)
    cookie = client.cookies.get("mc_refresh")
    service.rotate_refresh(db, cookie)
    active = db.query(AuthSession).filter_by(user_id=result["user"]["id"]).one()
    active_id = active.id
    expired = AuthSession(id="as_expired_test", user_id=active.user_id, auth_version=0,
                          created_at=service.now() - 10, expires_at=service.now() - 1,
                          refresh_digest="expired-test-digest")
    db.add(expired)
    db.flush()
    db.add(RefreshUse(digest="expired-use-test", session_id=expired.id,
                      expires_at=expired.expires_at))
    db.add(EmailChange(id="ec_expired_test", user_id=active.user_id,
                       old_email="a@example.test", new_email="b@example.test",
                       auth_version=0, expires_at=service.now() - 1))
    db.commit()
    service.cleanup_expired_records(db)
    db.commit()
    db.expire_all()
    assert db.get(AuthSession, "as_expired_test") is None
    assert db.get(EmailChange, "ec_expired_test") is None
    assert db.get(RefreshUse, "expired-use-test") is None
    assert db.get(RefreshUse, service.digest_token(cookie)) is not None
    with pytest.raises(AppError):
        service.rotate_refresh(db, cookie)
    assert db.get(AuthSession, active_id).status == "revoked"
    expires = active.expires_at
    monkeypatch.setattr(service, "now", lambda: expires)
    service.cleanup_expired_records(db)
    db.commit()
    db.expire_all()
    assert db.get(AuthSession, active_id) is None
    assert db.query(RefreshUse).count() == 0


def test_proof_cleanup_checks_live_challenge_even_after_ttl_configuration_change(
    client, db, isolated_redis,
):
    consumed = service.now() - settings.auth_code_ttl_seconds - 10
    for challenge in ("expired-test-proof", "live-test-proof"):
        db.add(AuthProof(challenge_id=challenge, purpose="login", consumed_at=consumed))
    db.commit()
    isolated_redis.hset("auth:otp:challenge:live-test-proof", mapping={"state": "verified"})
    auth_codes.cleanup_expired_proofs(db)
    db.commit()
    assert db.get(AuthProof, "expired-test-proof") is None
    assert db.get(AuthProof, "live-test-proof") is not None


def test_profile_null_clears_phone_and_omission_preserves_it(client, delivery):
    result = provision_user(client, delivery)
    headers = bearer(result)
    assert client.put("/api/users/me", headers=headers, json={"phone": "13800000000"}).status_code == 200
    renamed = client.put("/api/users/me", headers=headers, json={"display_name": "改名"})
    assert renamed.json()["phone"] == "13800000000"
    cleared = client.put("/api/users/me", headers=headers, json={"phone": None})
    assert cleared.status_code == 200
    assert cleared.json()["phone"] is None
    assert client.get("/api/auth/me", headers=headers).json()["user"]["phone"] is None


def test_first_visit_without_refresh_cookie_is_unauthenticated(client):
    response = client.post("/api/auth/refresh", json={}, headers=csrf(client))
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "SESSION_REVOKED"


@pytest.mark.parametrize("role", ["admin", "teacher", "student"])
def test_provisioned_account_login_uses_revocable_sql_session(client, delivery, db, role):
    user = User(id="u_provisioned_test", account="legacy@example.account", role=role,
                identity={"admin": "管理员", "teacher": "教师", "student": "学生"}[role],
                display_name="管理员开通", password_hash=service.hash_password(PASSWORD))
    db.add(user)
    db.commit()
    payload = {"account": user.account, "password": PASSWORD, "turnstile_token": "test-challenge"}
    response = client.post("/api/auth/login/account", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["user"]["role"] == role
    assert client.get("/api/auth/me", headers=bearer(response.json())).status_code == 200
    user.email = "unverified@example.test"
    db.commit()
    assert client.post("/api/auth/login/account", json=payload).status_code == 200
    user.email = None
    user.email_normalized = "unverified@example.test"
    db.commit()
    assert client.post("/api/auth/login/account", json=payload).status_code == 200
    user.email_normalized = None
    user.status = "disabled"
    db.commit()
    assert client.post("/api/auth/login/account", json=payload).status_code == 401
