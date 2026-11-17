"""交卷输入、缓存授权状态及作答响应契约的回归。"""
import json
from datetime import datetime, timezone

import pytest
from fastapi.encoders import jsonable_encoder

from app.db import SessionLocal
from app.errors import AppError
from app.models import (
    AttemptAnswer, Paper, PaperAttempt, PaperPublication, SpaceMember, StudySpace, User,
)
from app.schemas.paper import AttemptAnswerBody
from app.services import attempts, papers
from app.services import grading
from test_attempts import _setup
from test_paper_acid import _personal


@pytest.mark.parametrize(
    "invalid", ["unknown", "source", "foreign", "outside_snapshot", "duplicate", "conflicting"],
)
def test_invalid_answers_preserve_retake_and_saved_answers(client, student, db, invalid):
    """错误 ID 和重复答案不能把带预填答案的重做静默交成空白卷。"""
    paper, started, _ = _personal(client, student, db, [("single", "A", 5), ("judge", "A", 3)])
    question_id = started["questions"][0]["paper_question_id"]
    assert client.put(
        f"/api/papers/{paper['id']}", headers=student, json={"allow_retake": True},
    ).status_code == 200
    assert client.post(
        f"/api/attempts/{started['attempt']['id']}/submit", headers=student,
        json={"answers": [{"paper_question_id": question_id, "choices": ["A"]}]},
    ).status_code == 200
    retake = client.post(
        f"/api/papers/{paper['id']}/attempts", headers=student, json={},
    ).json()
    attempt_id = retake["attempt"]["id"]
    invalid_id = "pq_missing"
    if invalid == "source":
        invalid_id = paper["questions"][0]["source_question_id"]
    elif invalid == "foreign":
        _, other, _ = _personal(client, student, db)
        invalid_id = other["questions"][0]["paper_question_id"]
    elif invalid == "outside_snapshot":
        invalid_id = retake["questions"][1]["paper_question_id"]
        db.get(PaperAttempt, attempt_id).question_ids_json = json.dumps([question_id])
        db.commit()
    submitted_answers = [{"paper_question_id": invalid_id, "choices": ["B"]}]
    if invalid in {"duplicate", "conflicting"}:
        submitted_answers = [
            {"paper_question_id": question_id, "choices": ["A"]},
            {"paper_question_id": question_id, "choices": ["B" if invalid == "conflicting" else "A"]},
        ]
    elif invalid == "foreign":
        submitted_answers.insert(0, {"paper_question_id": question_id, "choices": ["A"]})

    def saved_answers():
        db.expire_all()
        return [
            (a.id, a.paper_question_id, a.choices_json, a.text_answer, a.score, a.is_correct)
            for a in db.query(AttemptAnswer).filter_by(attempt_id=attempt_id).order_by(AttemptAnswer.id)
        ]

    original_answers = saved_answers()
    response = client.post(
        f"/api/attempts/{attempt_id}/submit", headers=student, json={"answers": submitted_answers},
    )
    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == (
        "DUPLICATE_ANSWER" if invalid in {"duplicate", "conflicting"} else "INVALID_PAPER_QUESTION"
    )
    assert saved_answers() == original_answers
    attempt = db.get(PaperAttempt, attempt_id)
    assert attempt.status == "answering"
    assert attempt.grading_run_id is None
    assert attempt.score is None
    assert attempt.submitted_at is None


@pytest.mark.parametrize("change", ["stop", "close", "dissolve", "remove_member"])
def test_start_rechecks_access_after_precheck(client, teacher, student, db, monkeypatch, change):
    """入口预检查后发生的停止、关闭或撤权，必须在写入门禁内生效。"""
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)])
    student_id = client.get("/api/auth/me", headers=student).json()["user"]["id"]
    lock_paper = attempts.lock_paper

    def change_before_lock(session, paper_id):
        with SessionLocal() as writer:
            if change == "stop":
                writer.query(PaperPublication).filter_by(paper_id=paper_id).one().stopped = True
            elif change == "close":
                writer.get(Paper, paper_id).closed = True
            elif change == "dissolve":
                writer.get(StudySpace, space["id"]).status = "dissolved"
            else:
                writer.query(SpaceMember).filter_by(
                    space_id=space["id"], user_id=student_id,
                ).one().status = "removed"
            writer.commit()
        return lock_paper(session, paper_id)

    monkeypatch.setattr(attempts, "lock_paper", change_before_lock)
    response = client.post(
        f"/api/papers/{paper['id']}/attempts", headers=student, json={"space_id": space["id"]},
    )
    expected = {
        "stop": (403, "PAPER_STOPPED"), "close": (403, "PAPER_CLOSED"),
        "dissolve": (404, "SPACE_NOT_FOUND"), "remove_member": (403, "NOT_SPACE_MEMBER"),
    }
    status, code = expected[change]
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code
    assert db.query(PaperAttempt).filter_by(paper_id=paper["id"]).count() == 0


def test_submit_rechecks_cached_publication_before_saving(client, teacher, student, db, monkeypatch):
    """即使 Session 持有旧发布实体，批卷期间的停止也不能被绕过。"""
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)])
    start = client.post(
        f"/api/papers/{paper['id']}/attempts", headers=student, json={"space_id": space["id"]},
    ).json()
    attempt_id = start["attempt"]["id"]
    student_id = client.get("/api/auth/me", headers=student).json()["user"]["id"]
    grade_objective = grading.grade_objective

    def stop_while_grading(row, choices):
        with SessionLocal() as writer:
            writer.query(PaperPublication).filter_by(paper_id=paper["id"]).one().stopped = True
            writer.commit()
        return grade_objective(row, choices)

    monkeypatch.setattr(grading, "grade_objective", stop_while_grading)
    with SessionLocal() as session:
        publication = session.query(PaperPublication).filter_by(paper_id=paper["id"]).one()
        with pytest.raises(AppError) as caught:
            attempts.submit_attempt(
                session, session.get(PaperAttempt, attempt_id), session.get(User, student_id),
                [AttemptAnswerBody(paper_question_id=start["questions"][0]["paper_question_id"],
                                   choices=["A"])],
            )
        assert caught.value.code == "PAPER_STOPPED"
        assert publication.stopped is True
    db.expire_all()
    assert db.get(PaperAttempt, attempt_id).status == "answering"
    assert db.query(AttemptAnswer).filter_by(attempt_id=attempt_id).count() == 0


@pytest.mark.parametrize("allow_review", [True, False])
def test_attempt_response_models_preserve_payloads(client, teacher, student, db, allow_review):
    """响应校验保留原字段、空值及答案权限，空间列表与服务载荷一致。"""
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)])
    assert client.put(
        f"/api/papers/{paper['id']}", headers=teacher, json={"allow_review": allow_review},
    ).status_code == 200
    paper_row = db.get(Paper, paper["id"])
    space_row = db.get(StudySpace, space["id"])
    url = f"/api/papers/{paper['id']}/attempt?space_id={space['id']}"
    preview = client.get(url, headers=student)
    assert preview.status_code == 200, preview.text
    assert preview.json() == jsonable_encoder(attempts.preview_payload(db, paper_row, space_row))
    start = client.post(
        f"/api/papers/{paper['id']}/attempts", headers=student, json={"space_id": space["id"]},
    )
    assert start.status_code == 201, start.text
    attempt_id = start.json()["attempt"]["id"]
    attempt = db.get(PaperAttempt, attempt_id)
    assert start.json() == jsonable_encoder(attempts.attempt_payload(db, attempt, paper_row, space_row))
    submit = client.post(
        f"/api/attempts/{attempt_id}/submit", headers=student,
        json={"answers": [{"paper_question_id": start.json()["questions"][0]["paper_question_id"],
                           "choices": ["A"]}]},
    )
    assert submit.status_code == 200, submit.text
    detail = {"paper_question_id": start.json()["questions"][0]["paper_question_id"],
              "score": 5, "is_correct": True}
    if allow_review:
        detail.update(answer="A", analysis="测试解析")
    assert submit.json() == {"attempt_id": attempt_id, "score": 5, "total_score": 5, "detail": [detail]}
    db.expire_all()
    expected = jsonable_encoder(attempts.attempt_payload(db, attempt, paper_row, space_row))
    assert client.get(url, headers=student).json() == expected
    review = client.get(f"/api/attempts/{attempt_id}/review", headers=student)
    if allow_review:
        assert review.status_code == 200, review.text
        assert review.json() == expected
    else:
        assert review.status_code == 403
    student_id = client.get("/api/auth/me", headers=student).json()["user"]["id"]
    assert client.get(f"/api/spaces/{space['id']}/papers", headers=student).json() == jsonable_encoder(
        papers.space_papers(db, space_row, db.get(User, student_id)),
    )


def test_attempt_routes_publish_response_contracts(client):
    """实际路由必须把作答和空间试卷的嵌套字段暴露到 OpenAPI。"""
    paths = client.get("/openapi.json").json()["paths"]
    for path, method, status in [
        ("/api/papers/{paper_id}/attempt", "get", "200"),
        ("/api/papers/{paper_id}/attempts", "post", "201"),
        ("/api/attempts/{attempt_id}/submit", "post", "200"),
        ("/api/attempts/{attempt_id}/review", "get", "200"),
    ]:
        schema = paths[path][method]["responses"][status]["content"]["application/json"]["schema"]
        assert "$ref" in schema, (path, schema)
    schema = paths["/api/spaces/{space_id}/papers"]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert "$ref" in schema["items"]


def test_grading_progress_and_nullable_deadline_keep_response_fields(client, student, db):
    """批卷进度和单边时间窗可读取，空成绩、时间及个人空间字段不被省略。"""
    paper, start, _ = _personal(client, student, db)
    attempt = db.get(PaperAttempt, start["attempt"]["id"])
    attempt.status = "grading"
    db.get(Paper, paper["id"]).exam_start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.commit()
    response = client.get(f"/api/papers/{paper['id']}/attempt", headers=student)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["attempt"]["status"] == "grading"
    assert data["attempt"]["score"] is None
    assert data["attempt"]["submitted_at"] is None
    assert data["space"] is None
    assert data["paper"]["exam_window"]["end"] is None
    assert data["paper"]["exam_window"]["start"].startswith("2020-01-01")
    assert "answer" not in data["questions"][0]


def test_intentional_blank_submission_remains_supported(client, student, db):
    """缺答与非法题目是两种输入；明确空白交卷仍按快照逐题计零分。"""
    _, start, _ = _personal(client, student, db)
    attempt_id = start["attempt"]["id"]
    response = client.post(f"/api/attempts/{attempt_id}/submit", headers=student, json={"answers": []})
    assert response.status_code == 200, response.text
    assert response.json()["score"] == 0
    assert len(response.json()["detail"]) == len(start["questions"])
