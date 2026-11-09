"""认证密钥初始化只使用临时配置，验证不泄露、不轮换和失败不覆盖。"""
import importlib.util
import io
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

from dotenv import dotenv_values
import pytest


@pytest.fixture
def initializer(tmp_path, monkeypatch):
    """单独加载脚本，固定目标到临时后端，不读取个人配置。"""
    path = Path(__file__).resolve().parents[1] / "scripts/init_auth_secrets.py"
    spec = importlib.util.spec_from_file_location("auth_secret_initializer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "BACKEND_DIR", tmp_path)
    return module


def test_first_run_generates_distinct_secrets_and_repeat_preserves_file(
    initializer, tmp_path, capsys, monkeypatch,
):
    """真实随机生成仅写临时文件，生成值不出现在命令输出。"""
    template = '# 假配置\r\nSMTP_PASSWORD="fake-mail-password"\r\nAUTH_JWT_SECRET=\r\n'
    (tmp_path / ".env.example").write_bytes(template.encode())
    monkeypatch.setenv("AUTH_JWT_SECRET", "fake-process-key-do-not-copy-into-file")
    assert initializer.main([]) == 0
    path = tmp_path / ".env"
    original = path.read_bytes()
    values = dotenv_values(stream=io.StringIO(original.decode()), interpolate=False)
    jwt, code = values["AUTH_JWT_SECRET"], values["AUTH_CODE_SECRET"]
    assert jwt != code and len(jwt) == len(code) == 64
    assert all(c.isascii() and (c.isalnum() or c in "_-") for c in jwt + code)
    assert b'SMTP_PASSWORD="fake-mail-password"\r\n' in original
    assert (tmp_path / ".env.example").read_bytes() == template.encode()
    assert initializer.main([]) == 0
    assert path.read_bytes() == original
    output = capsys.readouterr()
    assert all(value not in output.out + output.err for value in (jwt, code, "fake-mail-password"))
    assert not list(tmp_path.glob(".env.init*"))


@pytest.mark.parametrize("empty", ['AUTH_CODE_SECRET="" # 保留注释',
                                 "export AUTH_CODE_SECRET=''", "AUTH_CODE_SECRET= # 空值",
                                 "'AUTH_CODE_SECRET'", "auth_code_secret=", ""])
def test_fill_only_missing_value_preserves_existing_configuration(
    initializer, tmp_path, monkeypatch, empty,
):
    existing = "fake-existing-jwt-value-01234567890123456789"
    content = ("\ufeff# 保留原文\r\n"
               f"export AUTH_JWT_SECRET='{existing}' # 保留密钥和注释\r\n"
               'OTHER="first\r\nsecond ${UNCHANGED}"\r\n' + empty)
    path = tmp_path / ".env"
    path.write_bytes(content.encode())
    monkeypatch.setattr(initializer.secrets, "token_urlsafe", lambda _: "C" * 64)
    assert initializer.main([]) == 0
    updated = path.read_bytes().decode()
    assert updated.startswith(content[:content.index(empty)] if empty else content)
    values = dotenv_values(stream=io.StringIO(updated.removeprefix("\ufeff")), interpolate=False)
    assert values["AUTH_JWT_SECRET"] == existing
    assert values.get("AUTH_CODE_SECRET", values.get("auth_code_secret")) == "C" * 64
    if "#" in empty:
        assert empty[empty.index("#"):] in updated
    assert initializer.main([]) == 0
    assert path.read_bytes().decode() == updated


@pytest.mark.parametrize("content", [
    'AUTH_JWT_SECRET="unterminated fake-sensitive-marker\n',
    "AUTH_JWT_SECRET=fake-short\n",
    "AUTH_JWT_SECRET=${DO_NOT_EXPAND_FAKE_PROCESS_VALUE}\n",
    "AUTH_CODE_SECRET=\nauth_code_secret=\n",
    "AUTH_JWT_SECRET=" + "S" * 40 + "\nAUTH_CODE_SECRET=" + "S" * 40 + "\n",
    "AUTH_JWT_SECRET=\nOTHER='fake-sensitive-marker\n",
])
def test_invalid_configuration_is_never_overwritten_or_exposed(
    initializer, tmp_path, content, capsys,
):
    path = tmp_path / ".env"
    path.write_bytes(content.encode())
    assert initializer.main([]) == 2
    assert path.read_bytes() == content.encode()
    output = capsys.readouterr()
    assert "fake-" not in output.out + output.err
    assert "S" * 40 not in output.out + output.err
    assert not list(tmp_path.glob(".env.init*"))


def test_failed_replace_preserves_original_and_cleans_temporary_secrets(
    initializer, tmp_path, monkeypatch, capsys,
):
    path = tmp_path / ".env"
    content = b"AUTH_JWT_SECRET=\nAUTH_CODE_SECRET=\nOTHER=fake-existing-setting\n"
    path.write_bytes(content)

    def fail_replace(*_):
        raise OSError("fake-sensitive-error-must-not-be-printed")

    monkeypatch.setattr(initializer.os, "replace", fail_replace)
    assert initializer.main([]) == 2
    assert path.read_bytes() == content
    assert not list(tmp_path.glob(".env.init*"))
    output = capsys.readouterr()
    assert "fake-" not in output.out + output.err


def test_existing_lock_refuses_second_initializer_without_removing_lock(initializer, tmp_path):
    lock = tmp_path / ".env.init.lock"
    lock.write_text("", encoding="utf-8")
    assert initializer.main([]) == 2
    assert lock.exists()
    assert not (tmp_path / ".env").exists()


@pytest.mark.skipif(os.name != "nt", reason="Windows 只读文件替换与临时文件清理")
def test_readonly_target_failure_does_not_leave_temporary_secrets(initializer, tmp_path):
    path = tmp_path / ".env"
    content = b"AUTH_JWT_SECRET=\nAUTH_CODE_SECRET=\n"
    path.write_bytes(content)
    path.chmod(stat.S_IREAD)
    try:
        assert initializer.main([]) == 2
        assert path.read_bytes() == content
        assert not list(tmp_path.glob(".env.init*"))
    finally:
        path.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_concurrent_editor_change_is_preserved(initializer, tmp_path, monkeypatch):
    path = tmp_path / ".env"
    original = b"AUTH_JWT_SECRET=\n"
    path.write_bytes(original)
    real_fsync = initializer.os.fsync

    def edit_during_write(descriptor):
        path.write_bytes(b"OTHER=fake-new-editor-setting\n")
        real_fsync(descriptor)

    monkeypatch.setattr(initializer.os, "fsync", edit_during_write)
    assert initializer.main([]) == 2
    assert path.read_bytes() == b"OTHER=fake-new-editor-setting\n"
    assert not list(tmp_path.glob(".env.init*"))


def test_help_and_invalid_arguments_do_not_read_or_write_config(initializer, tmp_path, capsys):
    assert initializer.main(["--help"]) == 0
    assert initializer.main(["--secret", "fake-cli-secret"]) == 2
    assert not list(tmp_path.iterdir())
    output = capsys.readouterr()
    assert "fake-cli-secret" not in output.out + output.err


def test_command_targets_its_backend_instead_of_current_directory(tmp_path):
    """复制脚本到临时后端，使用独立进程从其他目录运行，禁止导入应用。"""
    backend = tmp_path / "backend"
    scripts = backend / "scripts"
    scripts.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / "scripts/init_auth_secrets.py"
    shutil.copyfile(source, scripts / source.name)
    (backend / ".env.example").write_text("OTHER=fake-template\n", encoding="utf-8")
    (tmp_path / ".env").write_text("ROOT=fake-do-not-read\n", encoding="utf-8")
    # 若脚本意外导入 app，独立进程立即失败；不允许读取真实应用设置。
    (scripts / "app.py").write_text(
        "raise RuntimeError('app import forbidden')\n", encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(scripts / source.name)], cwd=tmp_path,
        capture_output=True, text=True, check=False, timeout=15,
        env={**os.environ, "PYTHON_DOTENV_DISABLED": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert (backend / ".env").exists()
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "ROOT=fake-do-not-read\n"
    assert "fake-" not in result.stdout + result.stderr
