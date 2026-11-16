"""平台凭据的权限、加密持久化与并发主密钥创建回归。"""

from concurrent.futures import ThreadPoolExecutor

from cryptography.fernet import Fernet
import pytest

from app.models import User, UserModelSetting
from app.models.platform_llm import PlatformLlmSetting
from app.services import model_settings, secure_store
from app.services.rag import llm
from app.config import settings
from test_admin import admin_headers


@pytest.fixture
def secret_file(tmp_path, monkeypatch):
    path = tmp_path / "credentials" / "secret.key"
    monkeypatch.setattr(secure_store, "_SECRET_FILE", path)
    secure_store._fernet.cache_clear()
    try:
        yield path
    finally:
        secure_store._fernet.cache_clear()


def test_concurrent_initialization_publishes_one_complete_key(secret_file):
    with ThreadPoolExecutor(max_workers=8) as pool:
        instances = list(pool.map(lambda _: secure_store._fernet.__wrapped__(), range(24)))
    persisted = Fernet(secret_file.read_bytes())
    for instance in instances:
        assert persisted.decrypt(instance.encrypt(b"synthetic-value")) == b"synthetic-value"
    assert list(secret_file.parent.glob(".secret-*")) == []


def test_malformed_existing_key_is_not_overwritten(secret_file):
    secret_file.parent.mkdir(parents=True)
    secret_file.write_bytes(b"synthetic-invalid-key")
    with pytest.raises(ValueError):
        secure_store.encrypt_secret("synthetic-value")
    assert secret_file.read_bytes() == b"synthetic-invalid-key"


@pytest.mark.parametrize("method", ["get", "put"])
def test_platform_credentials_require_admin(client, teacher, method):
    kwargs = {"json": {}} if method == "put" else {}
    endpoint = getattr(client, method)
    assert endpoint("/api/admin/llm-settings", **kwargs).status_code == 401
    assert endpoint("/api/admin/llm-settings", headers=teacher, **kwargs).status_code == 403


def test_platform_key_roundtrip_keep_and_clear(client, db, secret_file):
    headers = admin_headers(client, db)
    key = "synthetic-platform-key-for-isolated-tests"
    body = {"api_key": key, "base_url": "https://model.example.invalid/v1",
            "model": "synthetic-model", "display_name": "合成模型"}
    response = client.put("/api/admin/llm-settings", json=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["configured"] is True
    assert key not in response.text
    db.expire_all()
    row = db.get(PlatformLlmSetting, 1)
    cipher = row.encrypted_key
    assert cipher != key and secure_store.decrypt_secret(cipher) == key
    assert llm.get_platform_llm() == (key, body["base_url"], body["model"])
    secure_store._fernet.cache_clear()
    assert secure_store.decrypt_secret(cipher) == key
    response = client.put("/api/admin/llm-settings", headers=headers,
                          json={**body, "api_key": secure_store.MASK_PLACEHOLDER})
    assert response.status_code == 200
    db.expire_all()
    assert db.get(PlatformLlmSetting, 1).encrypted_key == cipher
    response = client.put("/api/admin/llm-settings", json={"api_key": ""}, headers=headers)
    assert response.status_code == 200 and response.json()["configured"] is False
    assert llm.get_platform_llm() is None
    db.expire_all()
    assert db.get(PlatformLlmSetting, 1).encrypted_key == ""


@pytest.mark.parametrize("personal,platform,expected", [
    ("synthetic-personal", "synthetic-platform", "synthetic-personal"),
    ("", "synthetic-platform", "synthetic-platform"),
    ("", "", "synthetic-deployment"),
])
def test_effective_credentials_do_not_skip_platform(
    client, teacher, db, monkeypatch, personal, platform, expected,
):
    user = db.query(User).filter(User.account == "teacher").one()
    setting = db.get(UserModelSetting, user.id)
    setting.deepseek_api_key = personal
    db.commit()
    monkeypatch.setattr(settings, "deepseek_api_key", "synthetic-deployment")
    monkeypatch.setattr(llm, "get_platform_llm", lambda: (
        platform, "https://model.example.invalid/v1", "synthetic-model"
    ) if platform else None)
    assert model_settings.require_deepseek_key(db, user.id) == expected
