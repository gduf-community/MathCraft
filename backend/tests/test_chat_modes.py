"""四模式 HTTP 回归：图片边界、待续图片、历史会话授权和确认绑定。"""
import base64
import importlib
from unittest.mock import Mock

import pytest
from pydantic import ValidationError

from app.api import chat
from app.models import BankMember, Document, Paper, User
from app.models.base import new_id
from app.schemas.api import ChatMessageBody
from app.services import cache
from app.services.rag import data_agent, slots
from conftest import create_bank

PNG = "data:image/png;base64," + (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a5ZkAAAAASUVORK5CYII="
)


@pytest.fixture
def chat_context(client, teacher, db):
    bank = create_bank(client, teacher)
    owner = db.query(User).filter_by(account="teacher").one()
    doc = Document(id=new_id("doc"), bank_id=bank["id"], name="隔离教材.md", format="MD",
                   size_bytes=1, storage_path="fake-document-unused.md", status="ready",
                   uploader_id=owner.id)
    db.add(doc)
    db.commit()
    client.put("/api/users/me/model-settings", headers=teacher,
               json={"deepseek_api_key": "fake-deepseek-for-chat-tests"})
    response = client.post("/api/chat/sessions", headers=teacher,
                           json={"bank_id": bank["id"], "document_id": doc.id})
    assert response.status_code == 201, response.text
    return bank, doc, response.json()["session_id"], owner


@pytest.mark.parametrize("message,images", [("", []), ("   \n", []), ("", [""]),
                                           ("", ["https://example.test/image.png"]),
                                           ("", ["data:image/png;base64,not base64!"]),
                                           ("", ["data:image/png;charset=utf-8,YQ=="]),
                                           ("", ["data:image/svg+xml;base64,YQ=="])])
def test_empty_or_invalid_image_messages_are_rejected(message, images):
    with pytest.raises(ValidationError):
        ChatMessageBody(message=message, images=images)


@pytest.mark.parametrize("mode", ["generate", "creative"])
def test_image_only_message_reaches_multimodal_extractor(
    client, teacher, chat_context, monkeypatch, mode,
):
    _, _, session_id, _ = chat_context
    extract = Mock(return_value={})
    monkeypatch.setattr(slots, "chat_json", extract)
    monkeypatch.setattr(chat, "detect_intent", lambda *a, **kw: {
        "intent": mode, "confidence": "high",
    })
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": "", "images": [PNG], "mode": mode})
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == mode
    assert response.json()["questions"] == []
    content = extract.call_args.args[0][-1]["content"]
    assert {"type": "image_url", "image_url": {"url": PNG}} in content


def test_empty_message_is_rejected_before_model_calls(client, teacher, chat_context, monkeypatch):
    _, _, session_id, _ = chat_context
    detect = Mock()
    monkeypatch.setattr(chat, "detect_intent", detect)
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": " \t", "images": []})
    assert response.status_code == 422
    detect.assert_not_called()


def test_image_limits():
    assert len(ChatMessageBody(message="", images=[PNG] * 4).images) == 4
    with pytest.raises(ValidationError):
        ChatMessageBody(message="", images=[PNG] * 5)
    oversized = "data:image/png;base64," + base64.b64encode(b"x" * (5 * 1024 * 1024 + 1)).decode()
    with pytest.raises(ValidationError):
        ChatMessageBody(message="", images=[oversized])
    assert ChatMessageBody(message="文字消息").message == "文字消息"


@pytest.mark.parametrize("mode,module,target",
                         [("generate", "chat_flow", "handle_chat"),
                          ("creative", "chat_flow", "handle_creative"),
                          ("qa", "qa", "answer_question"),
                          ("data", "data_agent", "run_data_request")])
def test_each_mode_dispatches_to_its_own_service(
    client, teacher, chat_context, monkeypatch, mode, module, target,
):
    _, _, session_id, _ = chat_context
    result = "假答疑" if mode == "qa" else {
        "reply": "假回复", "questions": [], "done": True, "slot_state": {},
    }
    service = Mock(return_value=result)
    monkeypatch.setattr(importlib.import_module(f"app.services.rag.{module}"), target, service)
    monkeypatch.setattr(chat, "detect_intent", lambda *a, **kw: {
        "intent": mode, "confidence": "high",
    })
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": "当前模式测试", "mode": mode})
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == mode
    service.assert_called_once()


def test_mode_switch_continues_image_only_pending_request(
    client, teacher, chat_context, monkeypatch,
):
    _, _, session_id, _ = chat_context
    monkeypatch.setattr(chat, "detect_intent", lambda *a, **kw: {
        "intent": "creative", "confidence": "high", "reason": "图片创新题",
    })
    extract = Mock(return_value={})
    monkeypatch.setattr(slots, "chat_json", extract)
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": "", "images": [PNG]})
    assert response.json()["kind"] == "mode_mismatch"
    extract.assert_not_called()
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": "切换创新命题", "mode": "creative", "switch_only": True})
    assert response.status_code == 200, response.text
    assert "接着处理" in response.json()["reply"]
    content = extract.call_args.args[0][-1]["content"]
    assert {"type": "image_url", "image_url": {"url": PNG}} in content


def test_new_normal_message_discards_old_pending_delete(
    client, teacher, chat_context, monkeypatch,
):
    _, _, session_id, _ = chat_context
    detect = Mock(side_effect=[
        {"intent": "data", "confidence": "high", "reason": "删除试卷"},
        {"intent": "generate", "confidence": "high"},
        {"intent": "data", "confidence": "high"},
    ])
    monkeypatch.setattr(chat, "detect_intent", detect)
    monkeypatch.setattr(slots, "chat_json", Mock(return_value={}))
    data_service = Mock(return_value={"reply": "不应执行旧删除", "questions": [], "done": True})
    monkeypatch.setattr(data_agent, "run_data_request", data_service)
    endpoint = f"/api/chat/sessions/{session_id}/messages"
    first = client.post(endpoint, headers=teacher,
                        json={"message": "删除我的试卷", "images": [PNG]})
    assert first.json()["kind"] == "mode_mismatch"
    second = client.post(endpoint, headers=teacher, json={"message": "先出导数题"})
    assert second.status_code == 200, second.text
    third = client.post(endpoint, headers=teacher,
                        json={"message": "切到数据管理", "mode": "data", "switch_only": True})
    assert third.status_code == 200, third.text
    assert "接着处理" not in third.json()["reply"]
    data_service.assert_not_called()
    state = cache.get_redis()
    assert state.hget(chat._slot_key(session_id), "pending_message") is None
    assert state.hget(chat._slot_key(session_id), "pending_images") is None


def _data_preview(client, headers, session_id, monkeypatch):
    monkeypatch.setattr(chat, "detect_intent", lambda *a, **kw: {
        "intent": "data", "confidence": "high",
    })
    monkeypatch.setattr(data_agent, "chat_json", lambda *a, **kw: {
        "entity": "papers", "action": "delete",
    })
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=headers,
                           json={"message": "删除我的试卷", "mode": "data"})
    assert response.status_code == 200, response.text
    return response.json()["confirm"]["id"]


def test_confirmation_is_bound_to_original_session(
    client, teacher, chat_context, db, monkeypatch,
):
    bank, doc, session_id, owner = chat_context
    paper_id = new_id("p")
    db.add(Paper(id=paper_id, owner_id=owner.id, name="待确认试卷"))
    db.commit()
    confirm_id = _data_preview(client, teacher, session_id, monkeypatch)
    other = client.post("/api/chat/sessions", headers=teacher,
                        json={"bank_id": bank["id"], "document_id": doc.id}).json()["session_id"]
    body = {"confirm_id": confirm_id, "accepted": True}
    denied = client.post(f"/api/chat/sessions/{other}/confirm", headers=teacher, json=body)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "CONFIRM_FORBIDDEN"
    assert db.get(Paper, paper_id) is not None
    accepted = client.post(f"/api/chat/sessions/{session_id}/confirm", headers=teacher, json=body)
    assert accepted.status_code == 200, accepted.text
    db.expire_all()
    assert db.get(Paper, paper_id) is None


def test_revoked_bank_membership_blocks_messages_and_confirmations(
    client, teacher, student, chat_context, db, monkeypatch,
):
    bank, doc, _, _ = chat_context
    assert client.post(f"/api/banks/{bank['id']}/members", headers=teacher,
                       json={"account": "student", "role": "readonly"}).status_code == 201
    client.put("/api/users/me/model-settings", headers=student,
               json={"deepseek_api_key": "fake-student-model-key"})
    owner = db.query(User).filter_by(account="student").one()
    paper_id = new_id("p")
    db.add(Paper(id=paper_id, owner_id=owner.id, name="学生试卷"))
    db.commit()
    session_id = client.post("/api/chat/sessions", headers=student,
                             json={"bank_id": bank["id"], "document_id": doc.id}).json()["session_id"]
    confirm_id = _data_preview(client, student, session_id, monkeypatch)
    db.query(BankMember).filter_by(bank_id=bank["id"], user_id=owner.id).delete()
    db.commit()
    assert client.get(f"/api/chat/sessions/{session_id}", headers=student).status_code == 404
    assert client.post(f"/api/chat/sessions/{session_id}/messages", headers=student,
                       json={"message": "继续"}).status_code == 404
    denied = client.post(f"/api/chat/sessions/{session_id}/confirm", headers=student,
                         json={"confirm_id": confirm_id, "accepted": True})
    assert denied.status_code == 404
    assert db.get(Paper, paper_id) is not None
    assert cache.get_redis().exists(data_agent._confirm_key(confirm_id))
