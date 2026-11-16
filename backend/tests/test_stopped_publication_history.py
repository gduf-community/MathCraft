"""空间停止后的历史回退、重做保留及历史题号一致性回归。"""
import json

from app.models import AttemptAnswer, PaperAttempt
from test_attempts import _setup


def _start(client, student, paper_id, space_id):
    response = client.post(
        f"/api/papers/{paper_id}/attempts", headers=student, json={"space_id": space_id},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _submit(client, student, started, choices):
    return client.post(
        f"/api/attempts/{started['attempt']['id']}/submit", headers=student,
        json={"answers": [{"paper_question_id": started["questions"][0]["paper_question_id"],
                           "choices": choices}]},
    )


def _saved_answers(db, attempt_id):
    db.expire_all()
    return [
        (row.id, row.paper_question_id, row.choices_json, row.text_answer, row.score)
        for row in db.query(AttemptAnswer).filter_by(attempt_id=attempt_id)
        .order_by(AttemptAnswer.id)
    ]


def test_stopped_space_reads_submission_without_discarding_retake(
    client, teacher, student, db,
):
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)])
    paper_id, space_id = paper["id"], space["id"]
    assert client.put(f"/api/papers/{paper_id}", headers=teacher,
                      json={"allow_retake": True}).status_code == 200
    submitted = _start(client, student, paper_id, space_id)
    assert _submit(client, student, submitted, ["A"]).status_code == 200
    retake = _start(client, student, paper_id, space_id)
    retake_id = retake["attempt"]["id"]
    original_answers = _saved_answers(db, retake_id)
    url = f"/api/papers/{paper_id}/attempt?space_id={space_id}"
    assert client.get(url, headers=student).json()["attempt"]["id"] == retake_id

    assert client.post(f"/api/papers/{paper_id}/publications/{space_id}/stop",
                       headers=teacher).status_code == 204
    history = client.get(url, headers=student)
    assert history.status_code == 200, history.text
    assert history.json()["attempt"]["id"] == submitted["attempt"]["id"]
    assert history.json()["attempt"]["status"] == "submitted"
    assert history.json()["attempt"]["score"] == 5
    assert history.json()["paper"]["closed"] is False
    assert history.json()["paper"]["stopped"] is True
    listed = client.get(f"/api/spaces/{space_id}/papers", headers=student).json()
    assert next(row for row in listed if row["id"] == paper_id)["answered"] is True

    denied = _submit(client, student, retake, ["B"])
    assert denied.status_code == 403, denied.text
    assert denied.json()["detail"]["code"] == "PAPER_STOPPED"
    assert _saved_answers(db, retake_id) == original_answers
    assert db.get(PaperAttempt, retake_id).status == "answering"
    assert db.get(PaperAttempt, retake_id).score is None
    assert db.get(PaperAttempt, retake_id).submitted_at is None
    assert db.get(PaperAttempt, submitted["attempt"]["id"]).score == 5

    assert client.post(f"/api/papers/{paper_id}/publications/{space_id}/resume",
                       headers=teacher).status_code == 204
    resumed = client.get(url, headers=student)
    assert resumed.status_code == 200, resumed.text
    assert resumed.json()["attempt"]["id"] == retake_id
    listed = client.get(f"/api/spaces/{space_id}/papers", headers=student).json()
    assert next(row for row in listed if row["id"] == paper_id)["answered"] is False
    assert _submit(client, student, retake, ["B"]).status_code == 200


def test_stopped_history_and_open_retake_are_scoped_to_current_space(
    client, teacher, student, db,
):
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)])
    paper_id = paper["id"]
    assert client.put(f"/api/papers/{paper_id}", headers=teacher,
                      json={"allow_retake": True}).status_code == 200
    submitted = _start(client, student, paper_id, space["id"])
    assert _submit(client, student, submitted, ["A"]).status_code == 200
    retake = _start(client, student, paper_id, space["id"])
    other = client.post("/api/spaces", headers=teacher,
                        json={"name": "仅有未提交作答", "capacity": 10}).json()
    assert client.post("/api/spaces/join", headers=student,
                       json={"code": other["code"]}).status_code == 200
    assert client.post(f"/api/papers/{paper_id}/publish", headers=teacher,
                       json={"space_ids": [other["id"]]}).status_code == 200
    other_attempt = _start(client, student, paper_id, other["id"])
    assert client.post(f"/api/papers/{paper_id}/publications/{other['id']}/stop",
                       headers=teacher).status_code == 204

    blocked = client.get(f"/api/papers/{paper_id}/attempt?space_id={other['id']}",
                         headers=student)
    assert blocked.status_code == 403, blocked.text
    assert blocked.json()["detail"]["code"] == "PAPER_STOPPED"
    listed = client.get(f"/api/spaces/{other['id']}/papers", headers=student).json()
    assert next(row for row in listed if row["id"] == paper_id)["answered"] is False
    open_attempt = client.get(f"/api/papers/{paper_id}/attempt?space_id={space['id']}",
                              headers=student)
    assert open_attempt.status_code == 200, open_attempt.text
    assert open_attempt.json()["attempt"]["id"] == retake["attempt"]["id"]
    listed = client.get(f"/api/spaces/{space['id']}/papers", headers=student).json()
    assert next(row for row in listed if row["id"] == paper_id)["answered"] is False

    assert client.post(f"/api/papers/{paper_id}/publications/{space['id']}/stop",
                       headers=teacher).status_code == 204
    history = client.get(f"/api/papers/{paper_id}/attempt?space_id={space['id']}",
                         headers=student)
    assert history.status_code == 200, history.text
    assert history.json()["attempt"]["id"] == submitted["attempt"]["id"]
    db.expire_all()
    assert db.get(PaperAttempt, other_attempt["attempt"]["id"]).status == "answering"
    assert db.get(PaperAttempt, retake["attempt"]["id"]).status == "answering"


def test_history_preserves_question_numbers_after_unattempted_first_question_removed(
    client, teacher, student, db,
):
    space, paper = _setup(client, teacher, student, db,
                          [("single", "A", 5), ("judge", "A", 3), ("single", "A", 5)])
    paper_id = paper["id"]
    first_id = paper["questions"][0]["paper_question_id"]
    assert client.post(f"/api/papers/{paper_id}/close", headers=teacher).status_code == 200
    removed = client.post(f"/api/papers/{paper_id}/questions/remove", headers=teacher,
                          json={"paper_question_ids": [first_id]})
    assert removed.status_code == 200, removed.text
    assert [row["no"] for row in removed.json()["questions"]] == [1, 2]
    assert client.post(f"/api/papers/{paper_id}/reopen", headers=teacher).status_code == 200
    started = _start(client, student, paper_id, space["id"])
    assert _submit(client, student, started, ["A"]).status_code == 200
    db.expire_all()
    attempt = db.get(PaperAttempt, started["attempt"]["id"])
    assert first_id not in json.loads(attempt.question_ids_json)
    ordinary = client.get(f"/api/papers/{paper_id}", headers=teacher)
    assert ordinary.status_code == 200, ordinary.text
    assert [row["no"] for row in ordinary.json()["questions"]] == [1, 2]

    history = client.get(f"/api/papers/{paper_id}?history=true", headers=teacher)
    review = client.get(f"/api/attempts/{attempt.id}/review", headers=student)
    statistics = client.get(f"/api/papers/{paper_id}/statistics?space_id={space['id']}",
                            headers=teacher)
    for response in (history, review, statistics):
        assert response.status_code == 200, response.text
        assert [row["no"] for row in response.json()["questions"]] == [2, 3]
        assert [row["paper_question_id"] for row in response.json()["questions"]] == [
            row["paper_question_id"] for row in started["questions"]
        ]
