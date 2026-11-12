"""Isolated execution/commit boundaries for generation observation; no real services."""
import json
import threading
from collections import Counter
from contextlib import contextmanager, nullcontext

import pytest
from fastapi import BackgroundTasks
from sqlalchemy.orm import Session

from app.api import chat
from app.config import settings
from app.db import SessionLocal
from app.errors import AppError
from app.models import Document, GenerationBatch, User
from app.models.base import new_id
from app.schemas.question import GenerateParams, OptionItem, Question, QuestionType, TypeCount
from app.services import agent_sdk, agent_tracing, cache, generation, question_review
from app.services import generation_observation as observation
from app.services.question_review import review_questions as real_review
from app.services.rag import chat_flow, data_agent, llm, qa, question_gen, retrieval
from conftest import create_bank


@pytest.fixture
def recorded(monkeypatch):
    events = []
    roots = []

    @contextmanager
    def trace(run):
        assert observation.current_run() is run
        roots.append(run)
        yield

    monkeypatch.setattr(agent_tracing, "run_trace", trace)
    monkeypatch.setattr(agent_tracing, "stage_span", lambda *a, **k: nullcontext())
    with observation.event_sink(events.append):
        yield events, roots
    assert observation.current_run() is None


@pytest.fixture
def ready_context(client, teacher, db, monkeypatch):
    bank = create_bank(client, teacher)
    owner = db.query(User).filter_by(account="teacher").one()
    doc = Document(
        id=new_id("doc"), bank_id=bank["id"], name="隔离教材.md", format="MD",
        size_bytes=1, storage_path="fake-unused.md", status="ready", uploader_id=owner.id,
    )
    db.add(doc)
    db.commit()
    response = client.put(
        "/api/users/me/model-settings", headers=teacher,
        json={"deepseek_api_key": "fake-observation-test-key"},
    )
    assert response.status_code == 200
    monkeypatch.setattr(retrieval, "retrieve_for_generation", lambda *a, **k: [
        {"text": "合成参考材料", "metadata": {}},
    ])
    monkeypatch.setattr(chat, "detect_intent", lambda message, mode, **k: {
        "intent": mode, "confidence": "high",
    })
    session = client.post("/api/chat/sessions", headers=teacher, json={
        "bank_id": bank["id"], "document_id": doc.id,
    }).json()
    return owner.id, bank["id"], doc.id, session["session_id"]


@pytest.mark.parametrize("asynchronous", [False, True])
def test_parameterized_http_binds_owner_task_and_nested_workers(
    client, teacher, ready_context, monkeypatch, recorded, asynchronous,
):
    owner_id, bank_id, doc_id, _ = ready_context
    events, roots = recorded
    stream = llm.chat_stream
    worker_runs = []

    def tracked_stream(*args, **kwargs):
        worker_runs.append((threading.current_thread().name, observation.current_run()))
        yield from stream(*args, **kwargs)

    monkeypatch.setattr(llm, "chat_stream", tracked_stream)
    response = client.post("/api/generate/start" if asynchronous else "/api/generate",
                           headers=teacher, json={
        "bank_id": bank_id, "document_id": doc_id, "difficulty": "中", "scope": "导数",
        "source_mode": "variant_data",
        "types": [{"type": "single", "count": 2}, {"type": "judge", "count": 2}],
    })
    assert response.status_code == (202 if asynchronous else 200), response.text
    assert len(roots) == 1
    run = roots[0]
    assert run.owner_user_id == owner_id
    assert run.backend == "sdk" and run.entrypoint == "parameterized"
    assert run.task_id == (response.json()["task_id"] if asynchronous else None)
    assert run.session_id is None and run.batch_id
    assert run.sdk_trace_id.startswith("trace_")
    assert len(worker_runs) == 4
    assert all(name.startswith("qgen-batch") and active is run for name, active in worker_runs)
    assert {event.run_id for event in events} == {run.run_id}
    assert all(e.event_schema_version == 1 and e.occurred_at.endswith("Z") for e in events)
    assert len({e.event_id for e in events}) == len(events)
    assert [e.name for e in events].count("run.ended") == 1
    assert events[-1].name == "run.ended" and events[-1].metadata["status"] == "completed"
    assert events[-1].batch_id == run.batch_id
    assert "fake-observation-test-key" not in repr(events)
    assert "合成参考材料" not in repr(events)


@pytest.mark.parametrize("fail_reply", [False, True])
def test_conversation_run_covers_review_and_both_commits(
    client, teacher, ready_context, monkeypatch, recorded, fail_reply,
):
    owner_id, _, _, session_id = ready_context
    events, roots = recorded
    reviewed = []
    commits = []
    original_commit = Session.commit

    def review(db, user_id, questions, *args, **kwargs):
        reviewed.append(observation.current_run())
        return questions, question_review.ReviewStats()

    def commit(db):
        active = observation.current_run()
        if active is not None:
            commits.append(active)
            if fail_reply and len(commits) == 2:
                raise RuntimeError("synthetic_reply_commit_failure")
        original_commit(db)

    monkeypatch.setattr(question_review, "review_questions", review)
    monkeypatch.setattr(Session, "commit", commit)

    def request():
        return client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": "出两道导数选择题，中等难度，改数据"})

    if fail_reply:
        with pytest.raises(RuntimeError, match="synthetic_reply_commit_failure"):
            request()
    else:
        response = request()
        assert response.status_code == 200, response.text
    assert len(roots) == 1
    run = roots[0]
    assert run.owner_user_id == owner_id and run.session_id == session_id
    assert run.task_id is None and run.entrypoint == "conversation"
    assert reviewed == [run] and commits == [run, run]
    successes = [e.metadata["kind"] for e in events if e.name == "delivery.committed"]
    assert successes == (["batch"] if fail_reply else ["batch", "assistant_reply"])
    assert events[-1].name == "run.ended"
    assert events[-1].metadata["status"] == ("failed" if fail_reply else "completed")
    assert events[-1].batch_id == run.batch_id
    linked = [e for e in events if e.event_type == "conversation.linked"]
    assert len(linked) == (0 if fail_reply else 1)
    with SessionLocal() as db:
        assert db.get(GenerationBatch, run.batch_id).question_count == 2


@pytest.mark.parametrize("mode,switch_only", [
    ("generate", False), ("creative", False), ("qa", False), ("data", False), ("qa", True),
])
def test_followup_qa_data_and_switch_do_not_start_runs_or_check_sdk(
    client, teacher, ready_context, monkeypatch, recorded, mode, switch_only,
):
    _, _, _, session_id = ready_context
    events, roots = recorded

    def unexpected():
        raise AssertionError("An ordinary request must not enter SDK execution")

    def ordinary(*args, **kwargs):
        assert observation.current_run() is None
        return "合成答复"

    monkeypatch.setattr(agent_sdk, "ensure_available", unexpected)
    monkeypatch.setattr(chat_flow, "extract_slots", lambda *a, **k: {})
    monkeypatch.setattr(qa, "answer_question", ordinary)
    monkeypatch.setattr(data_agent, "run_data_request", lambda *a, **k: {"reply": ordinary()})
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": "继续", "mode": mode, "switch_only": switch_only})
    assert response.status_code == 200, response.text
    assert response.json()["questions"] == []
    assert not events and not roots


def test_cancel_202_is_not_run_end_and_worker_confirmation_is_cancelled(
    client, teacher, ready_context, monkeypatch, recorded,
):
    _, _, _, session_id = ready_context
    events, roots = recorded
    response = client.post(f"/api/chat/sessions/{session_id}/cancel", headers=teacher)
    assert response.status_code == 202
    assert not events and not roots

    def review(db, user_id, questions, *args, progress, **kwargs):
        cache.get_redis().set(chat._cancel_key(session_id), "1")
        assert not any(e.name == "run.ended" for e in events)
        progress(82, "合成审核检查点")
        raise AssertionError("Cancellation checkpoint must stop execution")

    monkeypatch.setattr(question_review, "review_questions", review)
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": "出两道选择题"})
    assert response.status_code == 200, response.text
    assert response.json()["batch_id"] is None
    assert events[-1].metadata["status"] == "cancelled"
    assert not any(e.event_type == "conversation.linked" for e in events)
    assert [e.metadata["kind"] for e in events if e.name == "delivery.committed"] == [
        "assistant_reply",
    ]


def test_late_cancel_request_does_not_relabel_delivered_work(
    client, teacher, ready_context, monkeypatch, recorded,
):
    _, _, _, session_id = ready_context
    events, _ = recorded
    original_commit = Session.commit

    def commit(db):
        run = observation.current_run()
        if run is not None and run.batch_id is not None:
            cache.get_redis().set(chat._cancel_key(session_id), "1")
        original_commit(db)

    monkeypatch.setattr(Session, "commit", commit)
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": "出两道选择题"})
    assert response.status_code == 200 and response.json()["batch_id"]
    assert events[-1].metadata["status"] == "completed"


def _question() -> Question:
    return Question(id="q_test", type=QuestionType.single, stem="合成原始题干",
                    options=[OptionItem(label="A", text="一"), OptionItem(label="B", text="二")],
                    answer="A", analysis="原始解析")


def test_unknown_review_release_is_not_observed_as_passed(recorded):
    events, _ = recorded
    question = _question()
    with observation.generation_scope("user_test", "parameterized"):
        question_review._apply_review(question, {"passed": True, "unknown": True})
    # The existing business release decision remains compatible, while the
    # observation describes unavailable evidence instead of quality approval.
    assert question.difficultyReview["passed"] is True
    review = next(e for e in events if e.name == "review.recorded")
    assert review.metadata["unknown"] is True and review.metadata["passed"] is False


def test_repair_and_solve_versions_do_not_reuse_stem_review_evidence(monkeypatch, recorded):
    events, roots = recorded
    monkeypatch.setattr(question_review, "load_corpus", lambda *a: [])
    monkeypatch.setattr(
        question_review, "_drop_duplicates", lambda questions, corpus: (questions, []),
    )
    calls = Counter()
    active_runs = []
    lock = threading.Lock()

    def model(messages, **kwargs):
        prompt = messages[-1]["content"]
        active_runs.append(observation.current_run())
        with lock:
            if prompt.startswith("你是独立数学审题人"):
                calls["judge"] += 1
                score = 1 if calls["judge"] <= 2 else 3
                return json.dumps({"scores": {key: score for key in question_review._SCORE_KEYS},
                                   "passed": score == 3, "methods": ["合成方法"]})
            if prompt.startswith("下面这道题没有通过"):
                calls["repair"] += 1
                return json.dumps({**_question().model_dump(), "stem": "修补后的合成题干",
                                   "options": [{"label": "A", "text": "三"}],
                                   "answer": "B", "analysis": "修补后的解析"})
            calls["solve"] += 1
            return json.dumps({"answer": "A", "analysis": "独立求解后的解析"})

    monkeypatch.setattr(llm, "chat_text", model)
    params = GenerateParams(kb_id="bank_test", doc_id="doc_test",
                            types=[TypeCount(type=QuestionType.single, count=1)])
    with observation.generation_scope("user_test", "parameterized") as run:
        with SessionLocal() as db:
            questions, stats = real_review(db, "user_test", [_question()], params, "", "fake")
        observation.record_delivered_question(questions[0])
    assert roots == [run] and all(active is run for active in active_runs)
    assert calls == {"judge": 3, "repair": 1, "solve": 1}
    assert stats.repaired == 1 and stats.solved == 1
    revisions = [e for e in events if e.name == "question.revised"]
    assert [e.metadata["version"] for e in revisions] == [1, 2, 3]
    assert all(revisions[1].metadata[f"{name}_changed"] for name in (
        "stem", "options", "answer", "analysis",
    ))
    reviews = [e for e in events if e.name == "review.recorded"]
    assert [e.metadata["question_revision_id"] for e in reviews] == [
        revisions[0].metadata["question_revision_id"], revisions[1].metadata["question_revision_id"],
    ]
    delivered = next(e for e in events if e.name == "delivery.question")
    assert delivered.metadata["question_revision_id"] == revisions[2].metadata["question_revision_id"]
    assert delivered.metadata["reviewed"] is False
    assert all(e.metadata["scope"] == "stem" for e in reviews)
    assert all(e.metadata["review_kind"] == "difficulty" for e in reviews)
    assert "合成原始题干" not in repr(events) and "独立求解后的解析" not in repr(events)


@pytest.mark.parametrize("raises", [False, True])
def test_regeneration_attempts_include_empty_and_failed_results(monkeypatch, recorded, raises):
    events, _ = recorded
    monkeypatch.setattr(settings, "review_max_regen_rounds", 2)
    monkeypatch.setattr(question_review, "load_corpus", lambda *a: [])
    monkeypatch.setattr(
        question_review, "_drop_duplicates", lambda questions, corpus: ([], questions),
    )

    def regenerate(*args):
        if raises:
            raise RuntimeError("synthetic_regeneration_failure")
        return []

    monkeypatch.setattr(question_review, "_regen", regenerate)
    params = GenerateParams(kb_id="bank_test", doc_id="doc_test",
                            types=[TypeCount(type=QuestionType.single, count=1)])
    with observation.generation_scope("user_test", "parameterized"):
        with SessionLocal() as db:
            questions, stats = real_review(db, "user_test", [_question()], params, "", "fake")
    assert not questions and stats.regenerated == 0
    starts = [e for e in events if e.name == "regeneration.started"]
    ends = [e for e in events if e.name == "regeneration.finished"]
    assert len(starts) == len(ends) == (1 if raises else 2)
    assert len({e.metadata["attempt_id"] for e in starts}) == len(starts)
    assert [e.metadata["attempt_id"] for e in starts] == [e.metadata["attempt_id"] for e in ends]
    assert {e.metadata["status"] for e in ends} == {"failed" if raises else "completed"}


def test_bad_stream_closes_before_schema_retry(monkeypatch, recorded):
    closed = []
    calls = []

    def stream(*args, **kwargs):
        calls.append(1)
        try:
            if len(calls) == 1:
                yield '{"questions":[{"type":"invalid"}]}'
            else:
                assert closed == [1]
                yield json.dumps({"questions": [_question().model_dump()]})
        finally:
            closed.append(len(calls))

    monkeypatch.setattr(llm, "chat_stream", stream)
    params = GenerateParams(kb_id="bank_test", doc_id="doc_test",
                            types=[TypeCount(type=QuestionType.single, count=1)])
    with observation.generation_scope("user_test", "parameterized"):
        questions = question_gen.generate_questions(
            params, "", api_key="fake", retrieve_fn=lambda query: [{"text": "合成材料"}],
        )
    assert len(questions) == 1 and closed == [1, 2]
    events, _ = recorded
    assert len([e for e in events if e.name == "regeneration.started"]) == 1


def test_observer_failure_preserves_business_result_and_exception(monkeypatch, recorded):
    def broken(event):
        raise RuntimeError("synthetic_sink_failure")

    @contextmanager
    def broken_trace(run):
        raise RuntimeError("synthetic_trace_failure")
        yield

    monkeypatch.setattr(agent_tracing, "run_trace", broken_trace)
    with observation.event_sink(broken):
        with observation.generation_scope("user_test", "parameterized"):
            assert observation.current_run() is not None
        original = ValueError("synthetic_business_failure")
        with pytest.raises(ValueError) as raised:
            with observation.generation_scope("user_test", "parameterized"):
                raise original
        assert raised.value is original


def test_backend_is_selected_once_and_sdk_is_checked_before_binding(monkeypatch, recorded):
    events, roots = recorded
    checked = []

    def check():
        assert observation.current_run() is None
        checked.append(True)

    monkeypatch.setattr(agent_sdk, "ensure_available", check)
    monkeypatch.setattr(settings, "generation_llm_backend", "sdk")
    with observation.generation_scope("user_test", "parameterized") as run:
        monkeypatch.setattr(settings, "generation_llm_backend", "legacy")
        assert llm._sdk_enabled() is True
        assert run.backend == "sdk"
    with observation.generation_scope("other_user", "parameterized") as legacy:
        monkeypatch.setattr(settings, "generation_llm_backend", "sdk")
        assert llm._sdk_enabled() is False
        assert legacy.backend == "legacy"
    assert checked == [True]
    assert roots == [run, legacy] and run.run_id != legacy.run_id
    assert all(e.owner_user_id == ("user_test" if e.run_id == run.run_id else "other_user")
               for e in events)


def test_missing_sdk_does_not_accept_a_run(monkeypatch, recorded):
    events, roots = recorded

    def unavailable():
        assert observation.current_run() is None
        raise RuntimeError("synthetic_runtime_unavailable")

    monkeypatch.setattr(agent_sdk, "ensure_available", unavailable)
    with pytest.raises(RuntimeError, match="synthetic_runtime_unavailable"):
        with observation.generation_scope("user_test", "parameterized"):
            raise AssertionError("SDK execution must fail closed")
    assert not events and not roots


@pytest.mark.parametrize("path", ["/api/generate", "/api/generate/start"])
def test_sdk_unavailability_is_rejected_before_http_admission(
    client, teacher, ready_context, monkeypatch, recorded, path,
):
    owner_id, bank_id, doc_id, _ = ready_context
    events, roots = recorded

    def unavailable():
        assert observation.current_run() is None
        raise AppError("AGENT_RUNTIME_UNAVAILABLE", "合成运行环境不可用", 503)

    monkeypatch.setattr(agent_sdk, "ensure_available", unavailable)
    response = client.post(path, headers=teacher, json={
        "bank_id": bank_id, "document_id": doc_id,
        "types": [{"type": "single", "count": 1}], "difficulty": "中",
    })
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "AGENT_RUNTIME_UNAVAILABLE"
    assert not events and not roots
    assert not cache.get_redis().exists(cache.PREFIX_GEN_LOCK.format(user_id=owner_id))
    assert not list(cache.get_redis().scan_iter(match=cache.PREFIX_GEN_TASK.format(task_id="*")))


def test_async_admission_is_recorded_before_background_execution(
    client, teacher, ready_context, monkeypatch, recorded,
):
    owner_id, bank_id, doc_id, _ = ready_context
    events, roots = recorded
    queued = []

    def enqueue(self, function, *args, **kwargs):
        queued.append((function, args, kwargs))

    monkeypatch.setattr(BackgroundTasks, "add_task", enqueue)
    response = client.post("/api/generate/start", headers=teacher, json={
        "bank_id": bank_id, "document_id": doc_id,
        "types": [{"type": "single", "count": 1}], "difficulty": "中",
    })
    assert response.status_code == 202 and set(response.json()) == {"task_id"}
    assert len(queued) == 1 and not roots
    assert [e.event_type for e in events] == ["run.accepted"]
    accepted = events[0]
    assert accepted.owner_user_id == owner_id
    assert accepted.task_id == response.json()["task_id"]
    function, args, kwargs = queued[0]
    admitted = kwargs["run"]
    assert function is generation.run_generation_task
    assert admitted.accepted_at == accepted.occurred_at
    assert admitted.run_id == accepted.run_id
    # A deployment setting change after admission cannot switch this execution.
    monkeypatch.setattr(settings, "generation_llm_backend", "legacy")
    function(*args, **kwargs)
    assert roots == [admitted] and admitted.backend == "sdk"
    assert [e.event_type for e in events].count("run.accepted") == 1
    assert [e.event_type for e in events].count("run.started") == 1
    assert events[-1].event_type == "run.ended"
    assert events[-1].metadata["status"] == "completed"
    assert events[-1].sdk_trace_id == accepted.sdk_trace_id
