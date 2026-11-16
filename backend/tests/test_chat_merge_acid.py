"""聊天合并的事务、补齐配额与审批消费回归。"""
import json

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import chat
from app.db import SessionLocal
from app.models import BankMember, ChatMessage, ChatSession, GenerationBatch, OpsRun, Paper, User
from app.models import Question as SavedQuestion
from app.schemas.question import GenerateParams, Question, QuestionType, TypeCount
from app.services import cache, generation, question_review
from app.services.rag import chat_flow, data_agent, question_gen, slots
from test_generation_runs import post_chat
from test_generation_runs import resources as resources


def _question(stem: str, kind: str = "single") -> Question:
    return Question(type=QuestionType(kind), stem=stem, answer="A", analysis="合成解析")


def test_refill_uses_per_type_deficits_cumulative_stems_stats_and_percentages():
    params = GenerateParams(
        kb_id="fake-bank", doc_id="fake-doc", source_mode="original", scope="导数",
        types=[TypeCount(type=QuestionType.single, count=2),
               TypeCount(type=QuestionType.blank, count=1)],
    )
    calls, percents = [], []
    reviewed = []

    def review(pool, review_params, stems):
        reviewed.append(({item.type: item.count for item in review_params.types}, list(stems)))
        return pool, question_review.ReviewStats(duplicates=1, repaired=2, solved=len(pool))

    def generate(refill_params, stems, progress):
        calls.append((refill_params, list(stems)))
        for percent in (0, 50, 100):
            progress(percent, "补齐")
        if len(calls) == 1:
            return [_question("首题"), _question("填空补题", "blank")]
        return [_question("单选补题"), _question("多余单选")]

    accepted, stats, canceled = chat_flow.review_with_refill(
        [_question("首题"), _question("多余填空", "blank")], params, 3, ["已有题"],
        lambda pool, p, stems: review(
            [q for q in pool if q.stem != "多余填空"], p, stems,
        ), generate, progress_cb=lambda percent, stage: percents.append(percent),
    )
    assert not canceled
    assert [(q.type.value, q.stem) for q in accepted] == [
        ("single", "首题"), ("blank", "填空补题"), ("single", "单选补题"),
    ]
    assert [{tc.type.value: tc.count for tc in call[0].types} for call in calls] == [
        {"single": 1, "blank": 1}, {"single": 1},
    ]
    assert all(call[0].source_mode == "original" for call in calls)
    assert {"已有题", "首题", "多余填空", "填空补题"} <= set(calls[-1][1])
    assert reviewed[-1][0] == {QuestionType.single: 1}
    assert stats.duplicates == 4 and stats.repaired == 6 and stats.solved == 5
    assert percents == sorted(percents) and min(percents) >= 0 and max(percents) <= 100


@pytest.mark.parametrize("phase", ["review", "generate"])
def test_refill_propagates_cancellation_without_partial_delivery(phase):
    params = GenerateParams(kb_id="fake-bank", doc_id="fake-doc",
                            types=[TypeCount(type=QuestionType.single, count=2)])

    def review(*args):
        if phase == "review":
            raise chat_flow.ChatCanceled
        return [], question_review.ReviewStats()

    def generate(*args):
        raise chat_flow.ChatCanceled

    with pytest.raises(chat_flow.ChatCanceled):
        chat_flow.review_with_refill([_question("合成题")], params, 2, [], review, generate)


def test_smalltalk_sql_failure_rolls_back_messages_and_slot_state(
    client, teacher, resources, monkeypatch,
):
    with SessionLocal.begin() as db:
        db.get(ChatSession, resources["session_id"]).slot_state_json = '{"scope":"旧范围"}'
    monkeypatch.setattr(chat, "detect_intent", lambda *a, **k: {
        "intent": "smalltalk", "confidence": "high",
    })
    monkeypatch.setattr(chat, "answer_casually", lambda *a, **k: "合成闲聊回复")
    original_commit = Session.commit

    def fail_messages(db):
        if any(isinstance(row, ChatSession) and row.run_status == "done"
               for row in db.identity_map.values()):
            raise SQLAlchemyError("synthetic message commit failure")
        return original_commit(db)

    monkeypatch.setattr(Session, "commit", fail_messages)
    response = post_chat(client, teacher, resources, message="你好")
    assert response.status_code == 503
    with SessionLocal() as db:
        session = db.get(ChatSession, resources["session_id"])
        assert session.slot_state_json == '{"scope":"旧范围"}'
        assert session.run_status == "failed"
        assert db.scalar(select(func.count()).select_from(ChatMessage)) == 0
        assert db.scalar(select(func.count()).select_from(OpsRun)) == 0


def _approval(client, teacher, resources, monkeypatch, action):
    with SessionLocal.begin() as db:
        paper = Paper(id="synthetic-approval-paper", owner_id=resources["owner"],
                      name="审批原名", closed=True)
        db.add(paper)
    monkeypatch.setattr(chat, "detect_intent", lambda *a, **k: {
        "intent": "data", "confidence": "high",
    })
    monkeypatch.setattr(data_agent, "chat_json", lambda *a, **k: {
        "action": action, "entity": "papers", "mode": "paper", "set_name": "审批新名",
        "explanation": "合成审批影响说明",
    })
    response = post_chat(client, teacher, resources, mode="data", message="操作我的试卷")
    assert response.status_code == 200, response.text
    return response.json()["confirm"]["id"]


@pytest.mark.parametrize("action", ["update", "delete"])
def test_approval_business_and_messages_rollback_together_and_require_new_preview(
    client, teacher, resources, monkeypatch, action,
):
    confirm_id = _approval(client, teacher, resources, monkeypatch, action)
    key = data_agent._confirm_key(confirm_id)
    snapshot = json.loads(cache.get_redis().get(key))
    assert snapshot["mode"] == "paper"
    assert snapshot["thread_id"] == resources["session_id"]
    assert snapshot["samples"] and snapshot["sealed_at"] and snapshot["explanation"]
    original_commit = Session.commit

    def fail_messages(db):
        if any(isinstance(row, ChatMessage) for row in db.new):
            db.flush()
            raise SQLAlchemyError("synthetic confirmation message failure")
        return original_commit(db)

    monkeypatch.setattr(Session, "commit", fail_messages)
    endpoint = f"/api/chat/sessions/{resources['session_id']}/confirm"
    response = client.post(endpoint, headers=teacher,
                           json={"confirm_id": confirm_id, "accepted": True})
    assert response.status_code == 503
    with SessionLocal() as db:
        paper = db.get(Paper, "synthetic-approval-paper")
        assert paper.name == "审批原名" and not paper.deleted
        assert db.scalar(select(func.count()).select_from(ChatMessage)) == 2
    assert not cache.get_redis().exists(key)
    replay = client.post(endpoint, headers=teacher,
                         json={"confirm_id": confirm_id, "accepted": True})
    assert replay.status_code == 400
    assert replay.json()["detail"]["code"] == "CONFIRM_EXPIRED"


def test_chat_with_scope_uses_original_query_and_shares_review_run_identity(
    client, teacher, resources, monkeypatch,
):
    with SessionLocal.begin() as db:
        db.get(ChatSession, resources["session_id"]).slot_state_json = '{"scope":"导数"}'

    def forbidden_hyde(*args, **kwargs):
        pytest.fail("对话链路不得调用 HyDE")

    monkeypatch.setattr(generation, "get_cached_hyde", forbidden_hyde)
    observed = []

    def review(db, owner, pool, params, doc_name, key, hyde, **kwargs):
        assert not db.in_transaction()
        kwargs["cancel_check"]()
        with SessionLocal() as reader:
            session = reader.get(ChatSession, resources["session_id"])
            ledger = reader.get(OpsRun, session.run_id)
            observed.append((session.run_id, ledger.owner_user_id, ledger.session_id))
        assert hyde is None
        return pool, question_review.ReviewStats()

    monkeypatch.setattr(question_review, "review_questions", review)
    response = post_chat(client, teacher, resources)
    assert response.status_code == 200, response.text
    assert len(response.json()["questions"]) == 2
    assert observed[0][1:] == (resources["owner"], resources["session_id"])


def test_history_lists_only_current_owner_and_hides_revoked_material(
    client, teacher, student, resources,
):
    bank_id = resources["bank_id"]
    assert client.post(f"/api/banks/{bank_id}/members", headers=teacher,
                       json={"account": "student", "role": "readonly"}).status_code == 201
    response = client.post("/api/chat/sessions", headers=student, json={
        "bank_id": bank_id, "document_id": resources["document_id"],
    })
    student_session = response.json()["session_id"]
    items = client.get("/api/chat/sessions", headers=student).json()["items"]
    assert [item["session_id"] for item in items] == [student_session]
    assert [item["session_id"] for item in client.get(
        "/api/chat/sessions", headers=teacher,
    ).json()["items"]] == [resources["session_id"]]
    with SessionLocal.begin() as db:
        student_id = db.scalar(select(User.id).where(User.account == "student"))
        db.query(BankMember).filter_by(bank_id=bank_id, user_id=student_id).delete()
    response = client.get("/api/chat/sessions", headers=student)
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []


def test_creative_refill_retains_source_scope_image_directive_and_run(
    client, teacher, resources, monkeypatch,
):
    monkeypatch.setattr(chat, "detect_intent", lambda *a, **k: {
        "intent": "creative", "confidence": "high",
    })
    monkeypatch.setattr(slots, "chat_json", lambda *a, **k: {
        "types": [{"type": "single", "count": 1}], "scope": "图像导数",
        "source_mode": "original", "difficulty": "中", "image_note": "参考图片的切线构型",
    })
    captured = []

    def generate(params, doc_name, **kwargs):
        captured.append((params, kwargs))
        kwargs["cancel_check"]()
        return [_question(f"合成创新题{len(captured)}")]

    reviews = []

    def review(db, owner, questions, params, *args, **kwargs):
        reviews.append(params)
        kwargs["cancel_check"]()
        return (questions if len(reviews) > 1 else []), question_review.ReviewStats()

    monkeypatch.setattr(chat_flow, "generate_questions", generate)
    monkeypatch.setattr(question_gen, "generate_questions", generate)
    monkeypatch.setattr(question_review, "review_questions", review)
    response = post_chat(client, teacher, resources, mode="creative")
    assert response.status_code == 200, response.text
    assert len(response.json()["questions"]) == 1
    assert len(captured) == 2
    for params, kwargs in captured:
        assert params.source_mode == "new" and params.scope == "图像导数"
        assert "参考图片的切线构型" in kwargs["directive"]
        assert kwargs["hyde_text"] is None
    assert all(params.source_mode == "new" for params in reviews)
    with SessionLocal() as db:
        batch = db.get(GenerationBatch, response.json()["batch_id"])
        assert json.loads(batch.params_json)["source_mode"] == "new"
        assert db.scalar(select(func.count()).select_from(OpsRun)) == 1


def test_original_refill_shortage_keeps_need_confirm_classification(
    client, teacher, resources, monkeypatch,
):
    monkeypatch.setattr(question_review, "review_questions", lambda *a, **k: (
        [], question_review.ReviewStats(duplicates=2),
    ))

    def insufficient(*args, **kwargs):
        raise question_gen.NeedConfirmError("选择题", 0, 2)

    monkeypatch.setattr(question_gen, "generate_questions", insufficient)
    response = post_chat(client, teacher, resources)
    assert response.status_code == 200, response.text
    assert response.json()["questions"] == [] and response.json()["batch_id"] is None
    assert not response.json()["done"] and "原题只有 0 道" in response.json()["reply"]
    with SessionLocal() as db:
        ledger = db.scalar(select(OpsRun))
        assert ledger.status == "failed" and ledger.error_code == "NEED_CONFIRM"
        assert db.scalar(select(func.count()).select_from(GenerationBatch)) == 0


@pytest.mark.parametrize("punctuation", [".", "?", "，"])
def test_chat_refill_rejects_punctuation_variants_before_delivery_and_persistence(
    client, teacher, resources, monkeypatch, punctuation,
):
    stem = "求函数 $f(x)=x^2$ 的导数？"
    unique_stem = "求函数 $g(x)=x^3$ 在 $x=2$ 处的切线斜率？"
    monkeypatch.setattr(chat_flow, "generate_questions", lambda *a, **k: [
        _question(stem), _question("首轮未通过审核的合成题"),
    ])
    reviews = []

    def review(db, owner, pool, params, *args, **kwargs):
        reviews.append(list(pool))
        return (pool[:1] if len(reviews) == 1 else pool), question_review.ReviewStats()

    refills = []

    def generate(params, doc_name, **kwargs):
        kwargs["cancel_check"]()
        refills.append(list(kwargs["existing_stems"]))
        assert sum(item.count for item in params.types) == 1
        return [_question(stem[:-1] + punctuation), _question(unique_stem)]

    monkeypatch.setattr(question_review, "review_questions", review)
    monkeypatch.setattr(question_gen, "generate_questions", generate)
    response = post_chat(client, teacher, resources)
    assert response.status_code == 200, response.text
    result = response.json()
    assert [question["stem"] for question in result["questions"]] == [stem, unique_stem]
    assert len(refills) == 1 and stem in refills[0]
    with SessionLocal() as db:
        saved = db.scalars(select(SavedQuestion).where(
            SavedQuestion.batch_id == result["batch_id"],
        )).all()
        assert {question.stem for question in saved} == {stem, unique_stem}
        batch = db.get(GenerationBatch, result["batch_id"])
        assert batch.question_count == 2
        ledger = db.scalar(select(OpsRun))
        assert ledger.status == "completed" and ledger.delivered_count == 2


@pytest.mark.parametrize("phase", ["initial", "refill"])
def test_chat_generation_value_error_is_safe_in_response_history_and_ledger(
    client, teacher, resources, monkeypatch, phase,
):
    private_detail = "synthetic-private-generation-detail"

    def reject(*args, **kwargs):
        raise ValueError(private_detail)

    if phase == "initial":
        monkeypatch.setattr(chat_flow, "generate_questions", reject)
    else:
        monkeypatch.setattr(question_review, "review_questions", lambda *a, **k: (
            [], question_review.ReviewStats(),
        ))
        monkeypatch.setattr(question_gen, "generate_questions", reject)
    response = post_chat(client, teacher, resources)
    assert response.status_code == 200, response.text
    assert response.json()["reply"] == "模型调用失败，请稍后重试"
    assert private_detail not in response.text
    detail = client.get(f"/api/chat/sessions/{resources['session_id']}", headers=teacher)
    assert detail.status_code == 200 and private_detail not in detail.text
    with SessionLocal() as db:
        ledger = db.scalar(select(OpsRun))
        assert ledger.status == "failed" and ledger.error_code == "GENERATION_ERROR"
        assert ledger.delivered_count == 0 and ledger.batch_id is None
        assert db.scalar(select(func.count()).select_from(GenerationBatch)) == 0
