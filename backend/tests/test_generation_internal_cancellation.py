"""Deterministic cancellation regressions using fake models and worker events."""

import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event, Lock

import pytest

from app.db import SessionLocal
from app.schemas.question import Difficulty, GenerateParams, Question, QuestionType, TypeCount
from app.services import question_review
from app.services.generation_cancellation import GenerationCanceled
from app.services.question_review import review_questions as real_review
from app.services.rag import question_gen
from app.services.rag_runtime import RuntimeConfig, RuntimeSnapshot, use_snapshot


def _params(count: int = 1) -> GenerateParams:
    return GenerateParams(
        kb_id="fake-bank", doc_id="fake-document",
        types=[TypeCount(type=QuestionType.blank, count=count)],
    )


def _question() -> Question:
    return Question(type=QuestionType.blank, stem="求函数 x 的导数", answer="1", analysis="旧解析")


def _cancel_check(canceled: Event):
    def check() -> None:
        if canceled.is_set():
            raise GenerationCanceled("test cancellation")

    return check


def test_generation_canceled_on_model_return_does_not_retry_or_refill(monkeypatch):
    canceled = Event()
    calls = []

    def stream(*args, **kwargs):
        calls.append("model")
        canceled.set()
        yield '{"questions": [{"stem": "missing required fields"}]}'

    monkeypatch.setattr(question_gen.llm, "chat_stream", stream)
    with pytest.raises(GenerationCanceled):
        question_gen.generate_questions(
            _params(), "fake.pdf", retrieve_fn=lambda _: [{"text": "fake context"}],
            cancel_check=_cancel_check(canceled),
        )
    assert calls == ["model"]


def test_generation_cancellation_waits_for_started_worker_and_skips_queue(monkeypatch):
    canceled, started, release, finished = Event(), Event(), Event(), Event()
    calls = []

    def stream(*args, **kwargs):
        calls.append("model")
        started.set()
        assert release.wait(5)
        finished.set()
        yield json.dumps({"questions": [_question().model_dump(mode="json")]})

    monkeypatch.setattr(question_gen, "GEN_BATCH_WORKERS", 1)
    monkeypatch.setattr(question_gen, "_plan_points", lambda *a, **k: [])
    monkeypatch.setattr(question_gen.llm, "chat_stream", stream)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            question_gen.generate_questions, _params(3), "fake.pdf",
            retrieve_fn=lambda _: [{"text": "fake context"}],
            cancel_check=_cancel_check(canceled),
        )
        try:
            assert started.wait(5)
            canceled.set()
            assert not future.done()
        finally:
            release.set()
        with pytest.raises(GenerationCanceled):
            future.result(timeout=5)
    assert finished.is_set()
    assert calls == ["model"]


def test_review_json_cancellation_prevents_retry(monkeypatch):
    canceled = Event()
    calls = []

    def chat(*args, **kwargs):
        calls.append("model")
        canceled.set()
        return "invalid json"

    monkeypatch.setattr(question_review.llm, "chat_text", chat)
    with pytest.raises(GenerationCanceled):
        question_review._chat_json_low([], None, cancel_check=_cancel_check(canceled))
    assert calls == ["model"]


@pytest.mark.parametrize("phase", ["evaluate", "repair", "regenerate", "solve"])
@pytest.mark.parametrize("raise_directly", [False, True])
def test_review_cancellation_propagates_across_fallbacks(monkeypatch, phase, raise_directly):
    canceled = Event()
    calls = []

    def chat(messages, **kwargs):
        prompt = messages[-1]["content"]
        kind = "evaluate" if prompt.startswith("你是独立数学审题人") else "repair"
        if len(messages) > 1:
            kind = "solve"
        calls.append(kind)
        if kind == phase:
            canceled.set()
            if raise_directly:
                raise GenerationCanceled("direct model cancellation")
        if kind == "evaluate":
            return json.dumps({
                "scores": dict.fromkeys(question_review._SCORE_KEYS, 3),
                "passed": phase == "solve",
            })
        if kind == "repair":
            return json.dumps(_question().model_dump(mode="json"))
        return json.dumps({"answer": "1", "analysis": "fake analysis"})

    def regenerate(*args, **kwargs):
        calls.append("regenerate")
        assert kwargs["cancel_check"] is not None
        raise GenerationCanceled("regeneration canceled")

    monkeypatch.setattr(question_review, "load_corpus", lambda *a: [])
    monkeypatch.setattr(question_review, "_drop_duplicates", lambda qs, *a, **k: (qs, []))
    monkeypatch.setattr(question_review.llm, "chat_text", chat)
    monkeypatch.setattr(question_review.llm, "chat_json", lambda *a, **k: json.loads(chat(*a, **k)))
    monkeypatch.setattr(question_gen, "generate_questions", regenerate)
    monkeypatch.setattr(question_review, "_THINK_WORKERS", 1)
    with SessionLocal() as db, pytest.raises(GenerationCanceled):
        real_review(
            db, "fake-user", [_question()], _params(), "fake.pdf", None,
            cancel_check=_cancel_check(canceled),
        )
    assert phase in calls
    last = calls.index(phase)
    assert calls[last:] == [phase]


def test_solve_cancellation_joins_active_worker_and_skips_queued_models(monkeypatch):
    canceled, started, release, finished = Event(), Event(), Event(), Event()
    calls = []

    def chat(*args, **kwargs):
        calls.append("solve")
        started.set()
        assert release.wait(5)
        finished.set()
        return json.dumps({"answer": "1", "analysis": "fake analysis"})

    monkeypatch.setattr(question_review, "_THINK_WORKERS", 1)
    monkeypatch.setattr(question_review.llm, "chat_json", lambda *a, **k: json.loads(chat(*a, **k)))
    stats = question_review.ReviewStats()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            question_review._solve_all, [_question() for _ in range(3)], None, stats,
            cancel_check=_cancel_check(canceled),
        )
        try:
            assert started.wait(5)
            canceled.set()
            assert not future.done()
        finally:
            release.set()
        with pytest.raises(GenerationCanceled):
            future.result(timeout=5)
    assert finished.is_set()
    assert calls == ["solve"]
    assert stats.solved == 0


@pytest.mark.parametrize("stage", ["retrieval", "planning"])
def test_generation_cancellation_before_dispatch_stops_models(monkeypatch, stage):
    canceled = Event()
    calls = []

    def retrieve(_):
        calls.append("retrieval")
        if stage == "retrieval":
            canceled.set()
        return [{"text": "fake context"}]

    def plan(*args, **kwargs):
        calls.append("planning")
        canceled.set()
        return {}

    def stream(*args, **kwargs):
        pytest.fail("canceled generation must not dispatch a model")

    monkeypatch.setattr(question_gen.llm, "chat_json", plan)
    monkeypatch.setattr(question_gen.llm, "chat_stream", stream)
    with pytest.raises(GenerationCanceled):
        question_gen.generate_questions(
            _params(2), "fake.pdf", retrieve_fn=retrieve,
            cancel_check=_cancel_check(canceled),
        )
    assert calls == (["retrieval"] if stage == "retrieval" else ["retrieval", "planning"])


@pytest.mark.parametrize("service", ["generation", "judges"])
def test_cancellation_joins_other_active_model_before_return(monkeypatch, service):
    canceled, first_started, second_started = Event(), Event(), Event()
    release_first, release_second, observed, second_finished = Event(), Event(), Event(), Event()
    model_lock = Lock()

    def check() -> None:
        if canceled.is_set():
            observed.set()
            raise GenerationCanceled("test cancellation")

    def model(*args, **kwargs):
        with model_lock:
            first = not first_started.is_set()
            if first:
                first_started.set()
        if first:
            assert second_started.wait(5)
            assert release_first.wait(5)
            canceled.set()
        else:
            second_started.set()
            assert release_second.wait(5)
            second_finished.set()
        return json.dumps({"questions": [_question().model_dump(mode="json")]})

    def stream(*args, **kwargs):
        yield model(*args, **kwargs)

    monkeypatch.setattr(question_gen, "_plan_points", lambda *a, **k: [])
    monkeypatch.setattr(question_gen.llm, "chat_stream", stream)
    monkeypatch.setattr(question_review.llm, "chat_text", model)
    with ThreadPoolExecutor(max_workers=1) as pool:
        if service == "generation":
            future = pool.submit(
                question_gen.generate_questions, _params(2), "fake.pdf",
                retrieve_fn=lambda _: [{"text": "fake context"}], cancel_check=check,
            )
        else:
            future = pool.submit(
                question_review.evaluate, _question(), Difficulty.mid, "", None,
                cancel_check=check,
            )
        try:
            assert second_started.wait(5)
            release_first.set()
            assert observed.wait(5)
            with pytest.raises(TimeoutError):
                future.result(timeout=0.1)
            assert not second_finished.is_set()
        finally:
            release_first.set()
            release_second.set()
        with pytest.raises(GenerationCanceled):
            future.result(timeout=5)
    assert second_finished.is_set()


def test_duplicate_cancellation_stops_next_embedding_call(monkeypatch):
    canceled = Event()
    calls = []

    def embed(texts):
        calls.append(list(texts))
        canceled.set()
        return [[1.0] for _ in texts]

    monkeypatch.setattr(question_review.embeddings, "embed_texts", embed)
    with use_snapshot(RuntimeSnapshot(RuntimeConfig())), pytest.raises(GenerationCanceled):
        question_review._drop_duplicates(
            [_question()], ["fake old question"], cancel_check=_cancel_check(canceled),
        )
    assert calls == [["fake old question"]]


def test_cancellation_does_not_leak_into_unbound_calls(monkeypatch):
    canceled = Event()
    canceled.set()
    monkeypatch.setattr(question_review.llm, "chat_text", lambda *a, **k: "{}")
    with pytest.raises(GenerationCanceled):
        question_review._chat_json_low([], None, cancel_check=_cancel_check(canceled))
    assert question_review._chat_json_low([], None) == {}


@pytest.mark.parametrize("phase", ["planning", "judge", "repair", "solve"])
def test_direct_cancellation_exception_is_never_downgraded(monkeypatch, phase):
    def chat(*args, **kwargs):
        raise GenerationCanceled("direct cancellation")

    def check() -> None:
        return None

    monkeypatch.setattr(question_review.llm, "chat_text", chat)
    monkeypatch.setattr(question_gen.llm, "chat_json", chat)
    with pytest.raises(GenerationCanceled, match="direct cancellation"):
        if phase == "planning":
            question_gen._plan_points("", "填空题", "中", 2, [], None, cancel_check=check)
        elif phase == "judge":
            question_review._judge_once(_question(), Difficulty.mid, "", None, cancel_check=check)
        elif phase == "repair":
            question_review._repair(_question(), {}, Difficulty.mid, None, cancel_check=check)
        else:
            question_review._solve_all(
                [_question()], None, question_review.ReviewStats(), cancel_check=check,
            )
