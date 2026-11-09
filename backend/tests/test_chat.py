"""对话出题会话测试。"""
from conftest import create_bank, upload_markdown


def _setup(client, teacher):
    bank = create_bank(client, teacher)
    doc = upload_markdown(client, teacher, bank["id"])
    client.put(
        "/api/users/me/model-settings",
        json={"deepseek_api_key": "sk-test-deepseek"},
        headers=teacher,
    )
    return bank, doc


def test_create_and_delete_chat_session(client, teacher):
    bank, doc = _setup(client, teacher)
    resp = client.post(
        "/api/chat/sessions",
        json={"bank_id": bank["id"], "document_id": doc["document_id"]},
        headers=teacher,
    )
    assert resp.status_code == 201, resp.text
    session_id = resp.json()["session_id"]
    assert resp.json()["welcome"]

    detail = client.get(f"/api/chat/sessions/{session_id}", headers=teacher).json()
    assert detail["messages"] == []

    assert client.delete(f"/api/chat/sessions/{session_id}", headers=teacher).status_code == 204
    assert client.get(f"/api/chat/sessions/{session_id}", headers=teacher).status_code == 404


def test_chat_message_generates_questions(client, teacher):
    bank, doc = _setup(client, teacher)
    session = client.post(
        "/api/chat/sessions",
        json={"bank_id": bank["id"], "document_id": doc["document_id"]},
        headers=teacher,
    ).json()
    session_id = session["session_id"]

    resp = client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"message": "帮我出 2 道选择题，范围是导数，改数据，中等难度", "existing_stems": []},
        headers=teacher,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["done"] is True
    assert len(data["questions"]) == 2
    assert data["batch_id"].startswith("batch_")
    assert data["slot_state"]["types"][0]["type"] == "single"

    detail = client.get(f"/api/chat/sessions/{session_id}", headers=teacher).json()
    assert len(detail["messages"]) == 2
    assert detail["messages"][0]["role"] == "user"
    assert detail["messages"][1]["role"] == "assistant"
    assert detail["messages"][1]["batch_id"] == data["batch_id"]

    persisted = client.get(f"/api/questions?batch_id={data['batch_id']}", headers=teacher).json()
    assert persisted["total"] == 2
    assert len(persisted["items"]) == 2
    assert persisted["items"][0]["type"] == "single"
    assert persisted["items"][0]["knowledge_point"] == "导数"


def test_chat_requires_membership(client, teacher, student):
    bank, doc = _setup(client, teacher)
    resp = client.post(
        "/api/chat/sessions",
        json={"bank_id": bank["id"], "document_id": doc["document_id"]},
        headers=student,
    )
    assert resp.status_code == 404


def test_chat_requires_deepseek_key(client, teacher, student):
    bank, doc = _setup(client, teacher)
    assert client.post(f"/api/banks/{bank['id']}/members",
                       json={"account": "student", "role": "readonly"},
                       headers=teacher).status_code == 201
    session = client.post(
        "/api/chat/sessions",
        json={"bank_id": bank["id"], "document_id": doc["document_id"]},
        headers=student,
    )
    assert session.status_code == 201
    session_id = session.json()["session_id"]

    resp = client.post(
        f"/api/chat/sessions/{session_id}/messages",
        json={"message": "出 2 道选择题，导数，改数据，中等难度", "existing_stems": []},
        headers=student,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "DEEPSEEK_KEY_MISSING"


def test_chat_cannot_access_other_session(client, teacher, student, db):
    bank, doc = _setup(client, teacher)
    session = client.post(
        "/api/chat/sessions",
        json={"bank_id": bank["id"], "document_id": doc["document_id"]},
        headers=teacher,
    ).json()
    resp = client.get(f"/api/chat/sessions/{session['session_id']}", headers=student)
    assert resp.status_code == 404
