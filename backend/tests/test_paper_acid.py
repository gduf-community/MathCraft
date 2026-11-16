"""试卷关闭、历史快照及交卷并发的业务回归。"""
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from sqlalchemy import select

from app.db import SessionLocal
from app.models import AttemptAnswer, Paper, PaperAttempt, User
from app.schemas.paper import AttemptAnswerBody
from app.services import attempts, grading
from conftest import make_questions


def _personal(client, student, db, specs=None):
    user_id = client.get("/api/auth/me", headers=student).json()["user"]["id"]
    question_ids = make_questions(db, user_id, specs or [("single", "A", 5)])
    response = client.post("/api/papers", headers=student, json={
        "name": "事务练习", "questions": question_ids, "is_published": False,
    })
    assert response.status_code == 201, response.text
    paper = response.json()
    start = client.post(f"/api/papers/{paper['id']}/attempts", headers=student, json={})
    assert start.status_code == 201, start.text
    return paper, start.json(), user_id


def test_open_paper_cannot_be_deleted(client, student, db):
    paper, _, _ = _personal(client, student, db)
    response = client.delete(f"/api/papers/{paper['id']}?mode=paper", headers=student)
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "PAPER_NOT_CLOSED"


def test_closed_delete_preserves_answers_and_review(client, student, db):
    paper, start, _ = _personal(client, student, db)
    attempt_id = start["attempt"]["id"]
    question_id = start["questions"][0]["paper_question_id"]
    response = client.post(f"/api/attempts/{attempt_id}/submit", headers=student, json={
        "answers": [{"paper_question_id": question_id, "choices": ["A"]}],
    })
    assert response.status_code == 200, response.text
    assert client.post(f"/api/papers/{paper['id']}/close", headers=student).status_code == 200
    assert client.delete(f"/api/papers/{paper['id']}?mode=paper", headers=student).status_code == 204
    db.expire_all()
    assert db.get(PaperAttempt, attempt_id).score == 5
    assert db.scalar(select(AttemptAnswer).where(AttemptAnswer.attempt_id == attempt_id))
    review = client.get(f"/api/attempts/{attempt_id}/review", headers=student)
    assert review.status_code == 200, review.text
    assert len(review.json()["questions"]) == 1
    assert all(row["id"] != paper["id"] for row in client.get("/api/papers", headers=student).json())
    assert client.post(f"/api/papers/{paper['id']}/reopen", headers=student).status_code == 404


def test_removed_question_keeps_original_attempt_snapshot(client, student, db):
    paper, start, _ = _personal(client, student, db, [("single", "A", 5), ("judge", "A", 3)])
    attempt_id = start["attempt"]["id"]
    question_id = start["questions"][0]["paper_question_id"]
    assert client.post(f"/api/attempts/{attempt_id}/submit", headers=student, json={
        "answers": [{"paper_question_id": question_id, "choices": ["A"]}],
    }).status_code == 200
    assert client.post(f"/api/papers/{paper['id']}/close", headers=student).status_code == 200
    remove = client.post(f"/api/papers/{paper['id']}/questions/remove", headers=student, json={
        "paper_question_ids": [question_id],
    })
    assert remove.status_code == 200, remove.text
    assert remove.json()["question_count"] == 1
    review = client.get(f"/api/attempts/{attempt_id}/review", headers=student)
    assert review.status_code == 200, review.text
    assert len(review.json()["questions"]) == 2
    assert review.json()["attempt"]["total_score"] == 8


def test_whole_paper_delete_requires_every_publication_stopped(client, teacher, db):
    user_id = client.get("/api/auth/me", headers=teacher).json()["user"]["id"]
    ids = make_questions(db, user_id, [("single", "A", 5)])
    spaces = [client.post("/api/spaces", headers=teacher, json={
        "name": name, "capacity": 10,
    }).json() for name in ("空间甲", "空间乙")]
    paper = client.post("/api/papers", headers=teacher, json={
        "name": "多空间试卷", "questions": ids, "is_published": True,
        "space_ids": [space["id"] for space in spaces],
    }).json()
    paper_id = paper["id"]
    assert client.post(f"/api/papers/{paper_id}/close", headers=teacher).status_code == 200
    assert client.post(
        f"/api/papers/{paper_id}/publications/{spaces[0]['id']}/stop", headers=teacher,
    ).status_code == 204
    denied = client.delete(f"/api/papers/{paper_id}?mode=paper", headers=teacher)
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "PAPER_PUBLICATION_OPEN"
    assert client.post(
        f"/api/papers/{paper_id}/publications/{spaces[1]['id']}/stop", headers=teacher,
    ).status_code == 204
    assert client.delete(f"/api/papers/{paper_id}?mode=paper", headers=teacher).status_code == 204


def test_batch_delete_failure_rolls_back_all_selected_papers(client, student, db):
    first, _, _ = _personal(client, student, db)
    second, _, _ = _personal(client, student, db)
    assert client.post(f"/api/papers/{first['id']}/close", headers=student).status_code == 200
    result = client.post("/api/papers/batch-delete", headers=student, json={
        "paper_ids": [first["id"], second["id"]],
    })
    assert result.status_code == 409
    db.expire_all()
    assert not db.get(Paper, first["id"]).deleted
    assert not db.get(Paper, second["id"]).deleted


def test_slow_grading_releases_write_lock_and_rejects_second_submit(
    client, student, db, monkeypatch,
):
    paper, start, user_id = _personal(client, student, db, [("essay", "定义", 10)])
    attempt_id = start["attempt"]["id"]
    question_id = start["questions"][0]["paper_question_id"]
    monkeypatch.setattr(attempts, "get_effective_deepseek_key", lambda *_: "fake-key")
    entered = threading.Event()
    release = threading.Event()

    def slow_grade(*_):
        entered.set()
        assert release.wait(8), "测试未释放批卷"
        return 8, False, "假批卷"

    monkeypatch.setattr(grading, "grade_subjective", slow_grade)
    answers = [AttemptAnswerBody(paper_question_id=question_id, text="定义的内容")]

    def submit():
        with SessionLocal() as session:
            return attempts.submit_attempt(
                session, session.get(PaperAttempt, attempt_id), session.get(User, user_id), answers,
            )

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(submit)
        try:
            assert entered.wait(5)
            # 模型运行中，另一连接必须能提交无关写入。
            with SessionLocal() as other:
                row = other.get(Paper, paper["id"])
                row.name = "并发写入成功"
                other.commit()
            response = client.post(f"/api/attempts/{attempt_id}/submit", headers=student, json={
                "answers": [{"paper_question_id": question_id, "text": "另一份答案"}],
            })
            assert response.status_code == 409, response.text
        finally:
            release.set()
        assert future.result(timeout=10)["score"] == 8


@pytest.mark.parametrize("change", ["disable", "revoke", "close"])
def test_grading_rechecks_revocation_or_close_before_saving(
    client, student, db, monkeypatch, change,
):
    """模型期间撤销账号权限或关闭试卷，不能再发布答案与成绩。"""
    paper, start, user_id = _personal(client, student, db, [("essay", "定义", 10)])
    attempt_id = start["attempt"]["id"]
    question_id = start["questions"][0]["paper_question_id"]
    monkeypatch.setattr(attempts, "get_effective_deepseek_key", lambda *_: "fake-key")

    def grade_then_revoke(*_):
        with SessionLocal() as writer:
            if change == "close":
                writer.get(Paper, paper["id"]).closed = True
            else:
                user = writer.get(User, user_id)
                if change == "disable":
                    user.status = "disabled"
                user.auth_version += 1
            writer.commit()
        return 8, False, "假批卷"

    monkeypatch.setattr(grading, "grade_subjective", grade_then_revoke)
    response = client.post(f"/api/attempts/{attempt_id}/submit", headers=student, json={
        "answers": [{"paper_question_id": question_id, "text": "定义内容"}],
    })
    assert response.status_code == 403, response.text
    db.expire_all()
    assert db.get(PaperAttempt, attempt_id).status == "answering"
    assert db.get(PaperAttempt, attempt_id).score is None
    assert not db.query(AttemptAnswer).filter_by(attempt_id=attempt_id).first()


def test_deleted_paper_history_can_be_found_and_removed_questions_explained(
    client, teacher, student, db,
):
    """刷新后仍能从已有列表找到归档，并读取被移除题目的历史讲解和统计。"""
    from test_attempts import _setup

    space, paper = _setup(client, teacher, student, db, [("single", "A", 5), ("judge", "A", 3)])
    paper_id, space_id = paper["id"], space["id"]
    started = client.post(f"/api/papers/{paper_id}/attempts", headers=student, json={
        "space_id": space_id,
    }).json()
    question_ids = [row["paper_question_id"] for row in started["questions"]]
    assert client.post(f"/api/attempts/{started['attempt']['id']}/submit", headers=student, json={
        "answers": [{"paper_question_id": qid, "choices": ["A"]} for qid in question_ids],
    }).status_code == 200
    assert client.post(f"/api/papers/{paper_id}/close", headers=teacher).status_code == 200
    assert client.post(f"/api/papers/{paper_id}/questions/remove", headers=teacher, json={
        "paper_question_ids": [question_ids[0]],
    }).status_code == 200
    ordinary = client.get(f"/api/papers/{paper_id}", headers=teacher).json()
    assert len(ordinary["questions"]) == 1
    historical = client.get(f"/api/papers/{paper_id}?history=true", headers=teacher)
    assert historical.status_code == 200, historical.text
    assert {row["id"] for row in historical.json()["questions"]} == set(question_ids)
    assert client.get(f"/api/papers/{paper_id}?history=true", headers=student).status_code == 403
    assert client.post(
        f"/api/papers/{paper_id}/publications/{space_id}/stop", headers=teacher,
    ).status_code == 204
    assert client.delete(f"/api/papers/{paper_id}?mode=paper", headers=teacher).status_code == 204
    assert client.get(f"/api/papers/{paper_id}", headers=teacher).status_code == 404
    archived = client.get("/api/papers?include_history=true", headers=teacher).json()
    assert any(row["id"] == paper_id and row["deleted"] for row in archived)
    student_history = client.get(f"/api/spaces/{space_id}/papers", headers=student).json()
    assert any(row["id"] == paper_id and row["answered"] and row["deleted"] for row in student_history)
    assert client.get(
        f"/api/papers/{paper_id}/attempt?space_id={space_id}", headers=student,
    ).json()["attempt"]["status"] == "submitted"
    statistics = client.get(
        f"/api/papers/{paper_id}/statistics?space_id={space_id}", headers=teacher,
    )
    assert statistics.status_code == 200, statistics.text
    assert {row["paper_question_id"] for row in statistics.json()["questions"]} == set(question_ids)
    assert client.get(f"/api/papers/{paper_id}?history=true", headers=teacher).status_code == 200
