"""认证测试隔离契约：配置、凭据、Redis 和真实网络均受限制。"""
import socket
import sys

import fakeredis
import pytest

from app.config import Settings
from app.services import cache


def test_settings_never_load_env_files_or_inherited_delivery_secrets(tmp_path, monkeypatch):
    """显式提供假环境文件也不能突破测试配置隔离。"""
    sentinel = tmp_path / "synthetic.env"
    sentinel.write_text("SMTP_PASSWORD=fake-file-password\n", encoding="utf-8")
    monkeypatch.setenv("SMTP_PASSWORD", "fake-inherited-password")
    monkeypatch.setenv("TURNSTILE_SECRET_KEY", "fake-inherited-turnstile")
    configured = Settings(_env_file=sentinel)
    assert configured.smtp_password == ""
    assert configured.turnstile_secret_key == ""
    assert configured.app_env == "test"
    assert not hasattr(sys.modules["app.local_secrets"], "__file__")


def test_redis_is_in_memory_and_network_is_denied(isolated_redis):
    """所有缓存操作只使用当前测试的 FakeRedis，遗漏替身时拒绝网络。"""
    assert isinstance(cache.get_redis(), fakeredis.FakeRedis)
    assert cache.get_redis() is isolated_redis
    isolated_redis.set("isolated-proof", "fake-value")
    assert isolated_redis.get("isolated-proof") == "fake-value"
    with pytest.raises(AssertionError, match="测试禁止真实网络"):
        socket.create_connection(("example.invalid", 443))


def test_socketpair_is_allowed_without_allowing_loopback_services():
    """Windows 事件循环的内部管道可用，普通本机服务连接仍被拒绝。"""
    left, right = socket.socketpair()
    with left, right:
        left.sendall(b"fake-pipe-message")
        assert right.recv(64) == b"fake-pipe-message"
    with socket.socket() as client:
        with pytest.raises(AssertionError, match="测试禁止真实网络"):
            client.connect(("127.0.0.1", 6379))
