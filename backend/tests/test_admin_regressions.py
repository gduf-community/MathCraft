"""管理员审查回归：真实临时 SQL 会话，不连接网络或真实 Redis。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.orm import Session

from app.api import admin
from app.db import SessionLocal
from app.errors import AppError
from app.models import AuthSession, GenerationBatch, User
from app.schemas.admin import AccountCreateBody, AccountPasswordBody
from app.services import auth


@pytest.fixture
def administrator(client, db):
    """通过临时数据库建两个管理员，返回真实 SQL 访问令牌。"""
    users = [User(
        id=f"admin-regression-{index}", account=f"admin-regression-{index}",
        role="admin", identity="管理员", display_name="测试管理员",
        status="active", password_hash=auth.hash_password("test-password"),
    ) for index in range(2)]
    db.add_all(users)
    db.commit()
    token, _, _ = auth.create_session(db, users[0], users[0].auth_version)
    db.commit()
    return users[0], {"Authorization": f"Bearer {token}"}


@pytest.mark.parametrize("password", ["中" * 25, "a" * 65, "short12"])
@pytest.mark.parametrize("schema", [AccountCreateBody, AccountPasswordBody])
def test_password_boundaries_reject_before_hash(schema, password):
    values = {"password": password}
    if schema is AccountCreateBody:
        values.update(account="test", display_name="测试", role="teacher")
    with pytest.raises(ValidationError):
        schema(**values)


def test_utf8_password_boundary_accepts_72_bytes():
    assert AccountPasswordBody(password="中" * 24).password == "中" * 24


def test_create_without_email_and_persist_change_reminder(client, db, administrator):
    _, headers = administrator
    result = client.post("/api/admin/accounts", headers=headers, json={
        "account": "managed-teacher", "display_name": "新教师", "role": "teacher",
        "password": "initial-password",
    })
    assert result.status_code == 201, result.text
    assert result.json()["password_change_recommended"] is True
    user = db.get(User, result.json()["id"])
    assert user.email is None and user.email_normalized is None
    assert user.password_change_recommended is True
    login = client.post("/api/auth/login/account", json={
        "account": "managed-teacher", "password": "initial-password",
        "turnstile_token": "test-turnstile-token",
    })
    assert login.status_code == 200, login.text
    assert login.json()["user"]["password_change_recommended"] is True


@pytest.mark.parametrize("action", ["create", "reset"])
def test_overlong_utf8_password_is_http_validation_error(client, administrator, action):
    actor, headers = administrator
    if action == "create":
        path = "/api/admin/accounts"
        body = {"account": "invalid-password", "display_name": "测试", "role": "teacher",
                "password": "中" * 25}
    else:
        path = f"/api/admin/accounts/{actor.id}/reset-password"
        body = {"password": "中" * 25}
    response = client.post(path, headers=headers, json=body)
    assert response.status_code == 422
    assert client.get("/api/admin/accounts", headers=headers).status_code == 200


def test_reset_disabled_account_preserves_disabled_status(client, db, administrator):
    _, headers = administrator
    target = db.get(User, "admin-regression-1")
    assert client.post(f"/api/admin/accounts/{target.id}/disable", headers=headers).status_code == 204
    db.refresh(target)
    version = target.auth_version
    response = client.post(f"/api/admin/accounts/{target.id}/reset-password", headers=headers,
                           json={"password": "replacement-password"})
    assert response.status_code == 204, response.text
    db.refresh(target)
    assert target.status == "disabled"
    assert target.auth_version == version + 1
    assert auth.verify_password("replacement-password", target.password_hash)


def test_reset_revokes_old_session_and_late_login(client, db, administrator):
    actor, headers = administrator
    old_version = actor.auth_version
    result = client.post(f"/api/admin/accounts/{actor.id}/reset-password", headers=headers,
                         json={"password": "replacement-password"})
    assert result.status_code == 204, result.text
    assert client.get("/api/admin/accounts", headers=headers).status_code == 401
    db.refresh(actor)
    assert actor.auth_version == old_version + 1
    assert actor.password_change_recommended is True
    assert auth.verify_password("replacement-password", actor.password_hash)
    assert db.query(AuthSession).filter_by(user_id=actor.id, status="active").count() == 0
    with pytest.raises(AppError):
        auth.create_session(db, actor, old_version)
    db.rollback()


def test_disable_restore_cannot_resurrect_sessions(client, db, administrator):
    actor, headers = administrator
    target = db.get(User, "admin-regression-1")
    token, _, _ = auth.create_session(db, target, target.auth_version)
    db.commit()
    assert client.post(f"/api/admin/accounts/{target.id}/disable", headers=headers).status_code == 204
    assert client.post(f"/api/admin/accounts/{target.id}/restore", headers=headers).status_code == 204
    old_headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/admin/accounts", headers=old_headers).status_code == 401


def test_password_and_revocation_rollback_together(client, db, administrator):
    actor, _ = administrator
    version, original_hash = actor.auth_version, actor.password_hash

    def fail_commit(session):
        raise RuntimeError("injected isolated commit failure")

    with SessionLocal() as transaction:
        request_actor = transaction.get(User, actor.id)
        event.listen(transaction, "before_commit", fail_commit)
        with pytest.raises(RuntimeError, match="injected"):
            admin.reset_password(actor.id, AccountPasswordBody(password="replacement-password"),
                                 request_actor, transaction)
        transaction.rollback()
    db.refresh(actor)
    assert actor.auth_version == version
    assert actor.password_hash == original_hash
    assert db.query(AuthSession).filter_by(user_id=actor.id, status="active").count() == 1


def test_concurrent_self_disable_leaves_one_active_admin(client, db, administrator):
    barrier = Barrier(2)

    def disable_self(user_id: str) -> str:
        with SessionLocal() as transaction:
            actor = transaction.get(User, user_id)
            barrier.wait(timeout=10)
            try:
                admin.disable_account(user_id, actor, transaction)
                return "disabled"
            except AppError as exc:
                transaction.rollback()
                return exc.code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(disable_self, ["admin-regression-0", "admin-regression-1"]))
    assert sorted(results) == ["LAST_ADMIN", "disabled"]
    db.expire_all()
    assert db.query(User).filter_by(role="admin", status="active").count() == 1


def test_stale_admin_cannot_mutate_after_revocation(client, db, administrator):
    actor, _ = administrator
    with SessionLocal() as stale:
        stale_actor = stale.get(User, actor.id)
        auth.revoke_all(db, actor, actor.auth_version)
        db.commit()
        with pytest.raises(AppError) as error:
            admin.restore_account("admin-regression-1", stale_actor, stale)
        assert error.value.code == "SESSION_REVOKED"
        stale.rollback()


def test_overview_counts_all_batches_and_never_invents_completion(client, db, administrator):
    actor, headers = administrator
    db.add_all([GenerationBatch(
        id=f"admin-batch-{index}", user_id=actor.id, bank_id="test-bank",
        document_id="test-document", mode="parametric", status="done",
    ) for index in range(51)])
    db.commit()
    result = client.get("/api/admin/overview", headers=headers)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["task_total"] == 51
    assert body["task_status_counts"] == {"done": 51}
    assert body["task_scope"] == "persisted_generation_batches"
    assert body["recent_task_limit"] == 50
    assert len(body["tasks"]) == 50
    assert all(item["completed_at"] is None for item in body["tasks"])
