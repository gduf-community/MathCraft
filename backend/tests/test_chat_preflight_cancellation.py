"""意图识别与闲聊在同一运行取消边界内，取消不会触发后续请求或降级回复。"""

from threading import Event

import pytest
from sqlalchemy import func, select

from app.api import chat
from app.db import SessionLocal
from app.models import ChatMessage, ChatSession, GenerationBatch, OpsRun
from app.services.generation_cancellation import GenerationCanceled
from app.services.rag import intent, llm, memory
from test_generation_runs import post_chat
from test_generation_runs import resources as resources


@pytest.mark.parametrize("stage", ["intent", "smalltalk"])
@pytest.mark.parametrize("timing", ["before", "during", "exception"])
def test_preflight_cancellation_reaches_model_and_bypasses_fallback(monkeypatch, stage, timing):
    canceled = Event()
    calls = []

    def check():
        if canceled.is_set():
            raise GenerationCanceled()

    def model(*args, **kwargs):
        calls.append("model")
        assert kwargs["cancel_check"] is check
        if timing == "exception":
            raise GenerationCanceled()
        canceled.set()
        return {"intent": "smalltalk", "confidence": "high"} if stage == "intent" else "你好"

    if timing == "before":
        canceled.set()
    monkeypatch.setattr(intent, "chat_json", model)
    monkeypatch.setattr(llm, "chat_text", model)
    with pytest.raises(GenerationCanceled):
        if stage == "intent":
            intent.detect_intent("你好", "generate", cancel_check=check)
        else:
            memory.answer_casually("generate", "合成文档", [], "你好", cancel_check=check)
    assert calls == ([] if timing == "before" else ["model"])


def test_cancel_during_intent_does_not_start_smalltalk_or_persist_turn(
    client, teacher, resources, monkeypatch,
):
    def detect(*args, **kwargs):
        with SessionLocal.begin() as db:
            session = db.get(ChatSession, resources["session_id"])
            session.canceled_run_id = session.run_id
            session.run_status = "canceled"
        return {"intent": "smalltalk", "confidence": "high"}

    def forbidden(*args, **kwargs):
        pytest.fail("意图识别期间取消后不得开始闲聊模型请求")

    monkeypatch.setattr(chat, "detect_intent", detect)
    monkeypatch.setattr(chat, "answer_casually", forbidden)
    response = post_chat(client, teacher, resources, message="你好")
    assert response.status_code == 200, response.text
    assert response.json()["questions"] == []
    assert response.json()["batch_id"] is None
    assert response.json()["done"] is False
    with SessionLocal() as db:
        assert db.get(ChatSession, resources["session_id"]).run_status == "canceled"
        for model in (ChatMessage, GenerationBatch, OpsRun):
            assert db.scalar(select(func.count()).select_from(model)) == 0
