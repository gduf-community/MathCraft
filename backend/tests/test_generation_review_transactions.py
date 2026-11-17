"""审核连接释放和取消目标运行的确定性并发回归。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import sessionmaker

from app.api import chat
from app.db import Base, SessionLocal
from app.models import Bank, ChatSession, User
from app.models.base import new_id
from app.schemas.question import GenerateParams, Question, TypeCount
from app.services import question_review
from app.services.question_review import review_questions as real_review
from conftest import create_bank
from test_generation_acid import fake_chat, fake_generation, resources, session_for


def review_params():
    return GenerateParams(kb_id="fake-bank", doc_id="fake-doc", difficulty="中",
                          types=[TypeCount(type="single", count=1)])


def review_question():
    return Question(type="single", score=5, difficulty="中", stem="审核连接释放测试题",
                    options=[], answer="A", analysis="测试解析")


def stub_review_models(monkeypatch):
    monkeypatch.setattr(
        question_review, "_drop_duplicates", lambda questions, corpus, **kwargs: (questions, []),
    )
    monkeypatch.setattr(question_review, "evaluate", lambda *a, **k: {"passed": True, "total": 2.5})
    monkeypatch.setattr(question_review, "_solve_all", lambda *a, **k: None)


def test_fifteen_reviews_leave_pool_connections_for_progress(tmp_path, monkeypatch):
    """全部审核完成语料查询后，同时另开进度 Session，不能耗尽 15 个连接。"""
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'review-pool.db').as_posix()}",
        connect_args={"check_same_thread": False}, pool_size=15, max_overflow=0,
        pool_timeout=0.3,
    )
    factory = sessionmaker(bind=engine, autoflush=False)
    Base.metadata.create_all(engine)
    ready = Barrier(15)
    stub_review_models(monkeypatch)

    def run(_):
        with factory() as review_db:
            def progress(percent, stage):
                if percent == 78:
                    ready.wait(timeout=10)
                with factory() as progress_db:
                    assert progress_db.scalar(select(1)) == 1

            result, _stats = real_review(
                review_db, "fake-owner", [review_question()], review_params(), "fake.md",
                "fake-review-key", progress=progress,
            )
            return len(result)

    try:
        with ThreadPoolExecutor(max_workers=15) as pool:
            assert list(pool.map(run, range(15))) == [1] * 15
        assert engine.pool.checkedout() == 0
    finally:
        engine.dispose()


@pytest.mark.parametrize("change", ["new", "dirty", "deleted", "flushed"])
def test_review_refuses_business_transaction_without_rolling_it_back(
    client, teacher, db, monkeypatch, change,
):
    bank = create_bank(client, teacher)
    row = db.get(Bank, bank["id"])
    if change == "new":
        row = Bank(id=new_id("bank"), name="待提交记录", code=new_id("TEST"),
                   creator_id=row.creator_id)
        db.add(row)
    elif change == "deleted":
        db.delete(row)
    else:
        row.name = "待提交更新"
        if change == "flushed":
            db.flush()
    row_id = row.id
    stub_review_models(monkeypatch)
    with pytest.raises(InvalidRequestError, match="transaction"):
        real_review(db, "fake-owner", [review_question()], review_params(), "fake.md", "fake-key")
    assert db.in_transaction()
    db.commit()
    with SessionLocal() as other:
        persisted = other.get(Bank, row_id)
        if change == "deleted":
            assert persisted is None
        else:
            assert persisted.name == ("待提交记录" if change == "new" else "待提交更新")


def test_old_cancel_does_not_cancel_run_started_after_its_read(
    client, teacher, db, monkeypatch,
):
    user_id, body = resources(client, teacher, db)
    session_id = session_for(client, teacher, body)
    old_run = chat._begin_run(db, session_id, user_id).run_id
    successor = []
    with SessionLocal() as cancel_db:
        user = cancel_db.get(User, user_id)
        original_rollback = cancel_db.rollback

        def finish_a_and_start_b():
            original_rollback()
            with SessionLocal() as other:
                other.get(ChatSession, session_id).run_status = "done"
                other.commit()
                successor.append(chat._begin_run(other, session_id, user_id).run_id)

        monkeypatch.setattr(cancel_db, "rollback", finish_a_and_start_b)
        assert chat.cancel_generation(session_id, user=user, db=cancel_db) == {"canceled": True}
    with SessionLocal() as other:
        session = other.get(ChatSession, session_id)
        assert successor and successor[0] != old_run
        assert session.run_id == successor[0]
        assert session.run_status == "running"
        assert session.canceled_run_id != successor[0]


@pytest.mark.parametrize("route", ["async", "sync", "chat"])
def test_generation_entrypoints_release_review_transaction_before_models(
    client, teacher, db, monkeypatch, route,
):
    _, body = resources(client, teacher, db)
    session_id = session_for(client, teacher, body)
    fake_generation(monkeypatch)

    def check_chat_snapshots(ctx):
        assert ctx.session.bank_id == body["bank_id"]
        assert ctx.user.id
        assert not ctx.db.in_transaction()

    fake_chat(monkeypatch, check_chat_snapshots, questions=True)
    stub_review_models(monkeypatch)
    original_load = question_review.load_corpus
    review_sessions = []

    def load(review_db, *args):
        review_sessions.append(review_db)
        return original_load(review_db, *args)

    def duplicate_model(questions, corpus, **kwargs):
        assert review_sessions and not review_sessions[-1].in_transaction()
        return questions, []

    monkeypatch.setattr(question_review, "load_corpus", load)
    monkeypatch.setattr(question_review, "_drop_duplicates", duplicate_model)
    monkeypatch.setattr(question_review, "review_questions", real_review)
    if route == "chat":
        response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                               json={"message": "出题"})
        assert response.status_code == 200, response.text
        assert response.json()["batch_id"] and len(response.json()["questions"]) == 1
    elif route == "async":
        started = client.post("/api/generate/start", headers=teacher, json=body)
        assert started.status_code == 202, started.text
        response = client.get(f"/api/generate/progress/{started.json()['task_id']}", headers=teacher)
        assert response.status_code == 200 and response.json()["error"] is None
        assert response.json()["done"] and len(response.json()["questions"]) == 1
    else:
        response = client.post("/api/generate", headers=teacher, json=body)
        assert response.status_code == 200 and len(response.json()) == 1
    assert len(review_sessions) == 1
