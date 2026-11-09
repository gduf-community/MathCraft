"""本机管理员初始化：交互与数据库均使用假输入及临时数据库。"""
import getpass
import importlib.util
from pathlib import Path
import warnings

import pytest

from app.models import User, UserModelSetting
from app.services.auth import verify_password


@pytest.fixture
def command():
    path = Path(__file__).resolve().parents[1] / "scripts/create_admin.py"
    spec = importlib.util.spec_from_file_location("test_create_admin_command", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prompt(monkeypatch, passwords=("Fake-admin-password", "Fake-admin-password")):
    inputs = iter(["bootstrap-admin", "测试运维"])
    hidden = iter(passwords)
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr(getpass, "getpass", lambda _: next(hidden))


def test_bootstrap_creates_no_email_admin_once(client, db, command, monkeypatch, capsys):
    prompt(monkeypatch)
    assert command.main([]) == 0
    user = db.query(User).filter_by(account="bootstrap-admin").one()
    assert (user.role, user.identity, user.status) == ("admin", "管理员", "active")
    assert user.email is None and user.email_normalized is None
    assert user.password_change_recommended is True
    assert verify_password("Fake-admin-password", user.password_hash)
    assert db.get(UserModelSetting, user.id) is not None
    original = user.password_hash
    prompt(monkeypatch, ("Another-fake-password", "Another-fake-password"))
    assert command.main([]) == 2
    db.refresh(user)
    assert user.password_hash == original
    output = capsys.readouterr()
    assert "Fake-admin-password" not in output.out + output.err
    assert "Another-fake-password" not in output.out + output.err


def test_bootstrap_rejects_cli_password_without_prompt(command, monkeypatch, capsys):
    def forbidden(_):
        pytest.fail("无效命令行不能请求输入")
    monkeypatch.setattr("builtins.input", forbidden)
    assert command.main(["--password", "Fake-secret-CLI-value"]) == 2
    output = capsys.readouterr()
    assert "Fake-secret-CLI-value" not in output.out + output.err


@pytest.mark.parametrize("passwords", [
    ("Fake-admin-password", "different-password"), ("中" * 25, "中" * 25),
])
def test_bootstrap_invalid_password_never_creates(client, db, command, monkeypatch, passwords):
    prompt(monkeypatch, passwords)
    assert command.main([]) == 2
    assert db.query(User).filter_by(account="bootstrap-admin").count() == 0


def test_bootstrap_refuses_echo_fallback(client, db, command, monkeypatch):
    prompt(monkeypatch)
    def unavailable(_):
        warnings.warn("test hidden input unavailable", getpass.GetPassWarning)
        pytest.fail("密码不能降级为回显输入")
    monkeypatch.setattr(getpass, "getpass", unavailable)
    assert command.main([]) == 2
    assert db.query(User).filter_by(account="bootstrap-admin").count() == 0
