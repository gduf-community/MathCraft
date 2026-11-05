import pytest

from conftest import _reset_database
from app.db import SessionLocal
from app.models import User
from app.models.base import new_id
from app.services.bootstrap import InitialAccount, initialize_accounts
from app.services.auth import hash_password, verify_password


@pytest.fixture()
def bootstrap_db():
    _reset_database()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _specs(admin: InitialAccount) -> list[InitialAccount]:
    return [
        admin,
        InitialAccount("bootstrap-teacher", "教师密码", "teacher", "初始教师"),
        InitialAccount("bootstrap-student", "学生密码", "student", "初始学生"),
    ]


def test_initialize_accounts_creates_three_missing_accounts(bootstrap_db):
    result = initialize_accounts(bootstrap_db, _specs(InitialAccount("bootstrap-admin", "管理员密码", "admin", "平台管理员")))

    assert result.created == ["bootstrap-admin", "bootstrap-teacher", "bootstrap-student"]
    assert bootstrap_db.query(User).filter(User.account == "bootstrap-admin", User.role == "admin").one()


def test_initialize_accounts_is_idempotent_and_preserves_existing_state(bootstrap_db):
    first = InitialAccount("bootstrap-admin", "初始密码", "admin", "平台管理员")
    initialize_accounts(bootstrap_db, _specs(first))
    user = bootstrap_db.query(User).filter(User.account == first.account).one()
    old_hash = user.password_hash
    user.status = "disabled"
    bootstrap_db.commit()

    result = initialize_accounts(bootstrap_db, _specs(InitialAccount(first.account, "新密码", "admin", "新名称")))

    assert result.created == []
    assert result.skipped == [first.account, "bootstrap-teacher", "bootstrap-student"]
    assert user.status == "disabled"
    assert user.display_name == first.display_name
    assert verify_password(first.password, user.password_hash)
    assert user.password_hash == old_hash


def test_initialize_accounts_rejects_duplicate_accounts(bootstrap_db):
    specs = [
        InitialAccount("same-account", "密码1", "admin", "管理员"),
        InitialAccount("same-account", "密码2", "teacher", "教师"),
        InitialAccount("student-account", "密码3", "student", "学生"),
    ]

    with pytest.raises(ValueError, match="重复"):
        initialize_accounts(bootstrap_db, specs)


def test_initialize_accounts_rejects_existing_role_conflict(bootstrap_db):
    bootstrap_db.add(User(
        id=new_id("u"),
        account="teacher",
        password_hash=hash_password("123123"),
        role="teacher",
        identity="教师",
        display_name="张老师",
        status="active",
    ))
    bootstrap_db.commit()
    specs = [
        InitialAccount("teacher", "新密码", "admin", "管理员"),
        InitialAccount("bootstrap-teacher", "教师密码", "teacher", "初始教师"),
        InitialAccount("bootstrap-student", "学生密码", "student", "初始学生"),
    ]

    with pytest.raises(ValueError, match="角色"):
        initialize_accounts(bootstrap_db, specs)
