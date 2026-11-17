"""对话出题会话测试。"""
import pytest

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


@pytest.mark.parametrize("mode", ["generate", "creative", "qa", "data"])
def test_history_detail_restores_mode_without_changing_slots(client, teacher, db, mode):
    from app.models import ChatSession

    bank, doc = _setup(client, teacher)
    session = client.post(
        "/api/chat/sessions",
        json={"bank_id": bank["id"], "document_id": doc["document_id"]},
        headers=teacher,
    ).json()
    row = db.get(ChatSession, session["session_id"])
    row.mode = mode
    row.slot_state_json = '{"scope":"导数","difficulty":"高"}'
    db.commit()

    response = client.get(f"/api/chat/sessions/{row.id}", headers=teacher)
    assert response.status_code == 200, response.text
    assert response.json()["mode"] == mode
    db.refresh(row)
    assert row.mode == mode
    assert row.slot_state_json == '{"scope":"导数","difficulty":"高"}'


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
    # 任务交付即清题型数量槽位：难度与范围保留作语境，types 不残留到下一轮
    assert data["slot_state"]["types"] == []
    assert data["slot_state"]["difficulty"] == "中"
    assert data["slot_state"]["scope"] == "导数"

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


def test_delivered_round_clears_type_slots_for_next_request(client, teacher, monkeypatch):
    """已交付任务的题型数量槽位在交付时清空：换题型的下一轮严格按新数量出题。

    回归背景：旧实现里 compute:5 残留在槽位中，下一轮请求 12 道选择题时
    merge 把两个题型累加，实际生成 5+12=17 道。
    """
    from app.services.rag import chat_flow, slots as rag_slots

    bank, doc = _setup(client, teacher)
    session = client.post(
        "/api/chat/sessions",
        json={"bank_id": bank["id"], "document_id": doc["document_id"]},
        headers=teacher,
    ).json()
    url = f"/api/chat/sessions/{session['session_id']}/messages"

    calls: list[list[tuple[str, int]]] = []
    real_generate = chat_flow.generate_questions

    def spy_generate(params, *args, **kwargs):
        calls.append([(t.type.value, t.count) for t in params.types])
        return real_generate(params, *args, **kwargs)

    monkeypatch.setattr(chat_flow, "generate_questions", spy_generate)
    monkeypatch.setattr(rag_slots, "chat_json", lambda *a, **kw: {
        "types": [{"type": "compute", "count": 2}], "scope": "导数",
        "difficulty": "中", "mixed_difficulty": False,
    })
    resp = client.post(
        url,
        json={"message": "帮我出 2 道计算题，范围是导数，中等难度", "existing_stems": []},
        headers=teacher,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["done"] is True
    assert calls == [[("compute", 2)]]

    monkeypatch.setattr(rag_slots, "chat_json", lambda *a, **kw: {
        "types": [{"type": "single", "count": 3}], "scope": "导数",
        "difficulty": "低", "mixed_difficulty": False,
    })
    resp = client.post(
        url,
        json={"message": "帮我生成 3 道选择题，难度低", "existing_stems": []},
        headers=teacher,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["done"] is True
    # 第二轮只包含新请求的题型数量，旧任务题型不再累加
    assert calls == [[("compute", 2)], [("single", 3)]]
    assert len(data["questions"]) == 3


def test_unknown_intent_gets_conversational_reply(client, teacher, monkeypatch):
    """非出题消息（如「我刚刚说了什么」）基于短期记忆自然回应，不机械追问槽位。"""
    bank, doc = _setup(client, teacher)
    session = client.post(
        "/api/chat/sessions",
        json={"bank_id": bank["id"], "document_id": doc["document_id"]},
        headers=teacher,
    ).json()
    url = f"/api/chat/sessions/{session['session_id']}/messages"

    # 第一轮正常出题，给短期记忆积累素材
    resp = client.post(
        url,
        json={"message": "帮我出 2 道计算题，范围是导数，中等难度", "existing_stems": []},
        headers=teacher,
    )
    assert resp.status_code == 200 and resp.json()["done"] is True

    captured: dict = {}

    def fake_casually(mode, doc_name, history, message, api_key=None, **kwargs):
        captured["history_texts"] = [h.get("text") for h in history]
        captured["message"] = message
        captured["mode"] = mode
        return "你刚才让我生成 2 道中等难度的导数计算题。"

    monkeypatch.setattr("app.api.chat.answer_casually", fake_casually)
    monkeypatch.setattr("app.api.chat.detect_intent", lambda *a, **k: {
        "intent": "unknown", "confidence": "low", "need_confirm": True,
        "suggested_template": "none", "slots": {}, "reason": "测试桩",
    })
    resp = client.post(
        url,
        json={"message": "我刚刚说了什么", "existing_stems": []},
        headers=teacher,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["done"] is True
    assert "2 道" in data["reply"]
    # 自由对话拿到了短期记忆与当前消息
    assert any("计算题" in text for text in captured["history_texts"])
    assert captured["message"] == "我刚刚说了什么"
    assert captured["mode"] == "generate"


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


def test_reply_count_refills_after_review_drops(client, teacher, monkeypatch):
    """审核剔除后自动补齐：最终数量严格达标，回复按审核后的真实道数汇报。"""
    bank, doc = _setup(client, teacher)
    session = client.post(
        "/api/chat/sessions",
        json={"bank_id": bank["id"], "document_id": doc["document_id"]},
        headers=teacher,
    ).json()

    from app.services import question_review

    def drop_one(db, user_id, questions, *args, **kwargs):
        kept = questions[:1]
        stats = question_review.ReviewStats(duplicates=len(questions) - 1)
        return kept, stats

    monkeypatch.setattr(question_review, "review_questions", drop_one)
    resp = client.post(
        f"/api/chat/sessions/{session['session_id']}/messages",
        json={"message": "帮我出 2 道选择题，范围是导数，改数据，中等难度", "existing_stems": []},
        headers=teacher,
    )
    data = resp.json()
    # 审核每轮只放行 1 道，补齐循环自动补出，最终严格达到要求的 2 道
    assert len(data["questions"]) == 2
    assert "共 2 道" in data["reply"]

    latest = client.get(
        f"/api/generate/batches/latest?bank_id={bank['id']}&document_id={doc['document_id']}",
        headers=teacher,
    ).json()
    assert len(latest["questions"]) == 2


def test_build_result_reply_variants():
    from app.services import question_review
    from app.services.rag.chat_flow import build_result_reply

    assert "共 3 道" in build_result_reply(3, 3)
    short = build_result_reply(1, 3, question_review.ReviewStats(duplicates=2))
    assert "实际生成 1 道" in short and "再补 2 道" in short
    assert "没有可入库" in build_result_reply(0, 3)
