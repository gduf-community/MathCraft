"""模型配置接口测试：读取、保存、掩码、清除、测试连接。"""
import pytest

from app.services import mineru


def test_default_model_settings(client, teacher):
    resp = client.get("/api/users/me/model-settings", headers=teacher)
    assert resp.status_code == 200
    data = resp.json()
    assert data["deepseek_model_id"] == "deepseek-flash"
    assert data["deepseek_key_configured"] is False
    assert data["mineru_using_default"] is True
    assert data["embedding_configurable"] is False
    assert data["rerank_configurable"] is False
    assert data["mineru_limits"] == {"max_file_mb": 200, "max_pages": 200}


def test_save_and_mask_keys(client, teacher):
    resp = client.put(
        "/api/users/me/model-settings",
        json={"deepseek_api_key": "sk-test-deepseek-1234", "mineru_token": "sk-test-mineru-5678"},
        headers=teacher,
    )
    assert resp.status_code == 200

    data = client.get("/api/users/me/model-settings", headers=teacher).json()
    assert data["deepseek_key_configured"] is True
    assert data["mineru_token_configured"] is True
    assert data["deepseek_key_masked"].startswith("sk-")
    assert data["deepseek_key_masked"].endswith("1234")
    # 完整密钥不回传
    assert "sk-test-deepseek-1234" not in str(data)


def test_clear_keys(client, teacher):
    client.put(
        "/api/users/me/model-settings",
        json={"deepseek_api_key": "sk-test-deepseek-1234", "mineru_token": "sk-test-mineru-5678"},
        headers=teacher,
    )
    client.put(
        "/api/users/me/model-settings",
        json={"deepseek_api_key": "", "mineru_token": ""},
        headers=teacher,
    )
    data = client.get("/api/users/me/model-settings", headers=teacher).json()
    assert data["deepseek_key_configured"] is False
    assert data["mineru_token_configured"] is False
    assert data["mineru_using_default"] is True


def test_test_deepseek_without_key(client, teacher):
    resp = client.post("/api/users/me/model-settings/test-deepseek", headers=teacher)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "DEEPSEEK_KEY_MISSING"


def test_test_deepseek_with_key(client, teacher):
    client.put(
        "/api/users/me/model-settings",
        json={"deepseek_api_key": "sk-test-deepseek-1234"},
        headers=teacher,
    )
    resp = client.post("/api/users/me/model-settings/test-deepseek", headers=teacher)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_test_mineru(client, teacher, monkeypatch):
    monkeypatch.setattr(mineru, "ping_token", lambda token: (True, "Token 有效"))
    resp = client.post("/api/users/me/model-settings/test-mineru", headers=teacher)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_test_mineru_invalid(client, teacher, monkeypatch):
    monkeypatch.setattr(mineru, "ping_token", lambda token: (False, "Token 无效"))
    resp = client.post("/api/users/me/model-settings/test-mineru", headers=teacher)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "LLM_ERROR"
