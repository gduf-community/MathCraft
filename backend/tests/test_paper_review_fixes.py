"""发布历史与催交状态门禁的行为、并发回归。"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app.db import SessionLocal
from app.errors import AppError
from app.models import Paper, PaperAttempt, PaperPublication, PaperUrge, StudySpace, User
from app.services import papers
from test_attempts import _setup


def _remove(client, teacher, paper_id, space_id, route):
    if route == "publication":
        return client.delete(
            f"/api/papers/{paper_id}/publications/{space_id}", headers=teacher,
        )
    body = {"space_ids": []} if route == "spaces" else {"is_published": False}
    return client.put(f"/api/papers/{paper_id}", headers=teacher, json=body)


@pytest.mark.parametrize("route", ["publication", "spaces", "unpublish"])
@pytest.mark.parametrize("attempt_status", ["answering", "grading", "submitted"])
def test_publication_with_any_attempt_cannot_be_removed(
    client, teacher, student, db, route, attempt_status,
):
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)])
    started = client.post(f"/api/papers/{paper['id']}/attempts", headers=student,
                          json={"space_id": space["id"]})
    assert started.status_code == 201, started.text
    attempt_id = started.json()["attempt"]["id"]
    attempt = db.get(PaperAttempt, attempt_id)
    attempt.status = attempt_status
    db.commit()
    assert client.post(f"/api/papers/{paper['id']}/publications/{space['id']}/stop",
                       headers=teacher).status_code == 204

    response = _remove(client, teacher, paper["id"], space["id"], route)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "PAPER_HAS_ATTEMPTS"
    db.expire_all()
    assert db.query(PaperPublication).filter_by(paper_id=paper["id"]).count() == 1
    assert db.get(Paper, paper["id"]).status == "published"
    assert db.get(PaperAttempt, attempt_id).status == attempt_status
    assert client.get(f"/api/spaces/{space['id']}/papers", headers=teacher).status_code == 200
    assert client.get(f"/api/papers/{paper['id']}/statistics?space_id={space['id']}",
                      headers=teacher).status_code == 200


@pytest.mark.parametrize("route", ["publication", "spaces", "unpublish"])
def test_empty_publication_requires_stop_then_can_be_removed(
    client, teacher, student, db, route,
):
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)])
    denied = _remove(client, teacher, paper["id"], space["id"], route)
    assert denied.status_code == 409, denied.text
    assert denied.json()["detail"]["code"] == "PAPER_PUBLICATION_OPEN"
    assert client.post(f"/api/papers/{paper['id']}/publications/{space['id']}/stop",
                       headers=teacher).status_code == 204
    removed = _remove(client, teacher, paper["id"], space["id"], route)
    assert removed.status_code in (200, 204), removed.text
    db.expire_all()
    assert db.query(PaperPublication).filter_by(paper_id=paper["id"]).count() == 0
    assert db.get(Paper, paper["id"]).status == "draft"


@pytest.mark.parametrize("route", ["publication", "spaces"])
@pytest.mark.parametrize("attempt_status", ["answering", "grading", "submitted"])
def test_other_space_attempt_does_not_block_empty_publication_removal(
    client, teacher, student, db, route, attempt_status,
):
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)])
    other_space = client.post("/api/spaces", headers=teacher,
                              json={"name": "另一空间", "capacity": 10}).json()
    assert client.post(f"/api/papers/{paper['id']}/publish", headers=teacher,
                       json={"space_ids": [other_space["id"]]}).status_code == 200
    started = client.post(f"/api/papers/{paper['id']}/attempts", headers=student,
                          json={"space_id": space["id"]})
    assert started.status_code == 201, started.text
    attempt_id = started.json()["attempt"]["id"]
    db.get(PaperAttempt, attempt_id).status = attempt_status
    db.commit()
    db.expire_all()
    assert db.get(PaperAttempt, attempt_id).space_id == space["id"]
    assert db.get(PaperAttempt, attempt_id).space_id != other_space["id"]
    assert client.post(f"/api/papers/{paper['id']}/publications/{other_space['id']}/stop",
                       headers=teacher).status_code == 204
    if route == "publication":
        response = _remove(client, teacher, paper["id"], other_space["id"], route)
    else:
        response = client.put(f"/api/papers/{paper['id']}", headers=teacher,
                              json={"space_ids": [space["id"]]})
    assert response.status_code in (200, 204), response.text
    db.expire_all()
    assert db.query(PaperPublication).filter_by(
        paper_id=paper["id"], space_id=other_space["id"],
    ).count() == 0
    assert db.query(PaperPublication).filter_by(
        paper_id=paper["id"], space_id=space["id"],
    ).count() == 1
    assert db.get(PaperAttempt, attempt_id).status == attempt_status
    assert db.get(Paper, paper["id"]).status == "published"


@pytest.mark.parametrize("state,code", [
    ("closed", "PAPER_CLOSED"), ("deleted", "PAPER_NOT_FOUND"),
    ("stopped", "PAPER_STOPPED"),
])
def test_urge_rejects_unavailable_paper(client, teacher, student, db, state, code):
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)])
    if state == "stopped":
        db.query(PaperPublication).filter_by(paper_id=paper["id"]).one().stopped = True
    else:
        setattr(db.get(Paper, paper["id"]), state, True)
    db.commit()
    response = client.post(f"/api/papers/{paper['id']}/publications/{space['id']}/urge",
                           headers=teacher)
    assert response.status_code == (404 if state == "deleted" else 403), response.text
    assert response.json()["detail"]["code"] == code
    assert db.query(PaperUrge).count() == 0


@pytest.mark.parametrize("state", ["closed", "stopped", "removed"])
def test_urge_rechecks_state_changed_after_initial_read(
    client, teacher, student, db, state,
):
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)])
    cached_paper = db.get(Paper, paper["id"])
    cached_space = db.get(StudySpace, space["id"])
    cached_pub = db.query(PaperPublication).filter_by(paper_id=paper["id"]).one()
    owner = db.get(User, cached_paper.owner_id)
    with SessionLocal() as writer:
        if state == "closed":
            papers.set_closed(writer, writer.get(Paper, paper["id"]), True)
        else:
            pub = writer.get(PaperPublication, cached_pub.id)
            papers.set_publication_stopped(writer, pub, True)
            if state == "removed":
                papers.remove_publication(writer, writer.get(Paper, paper["id"]), pub)

    with pytest.raises(AppError) as error:
        papers.urge_paper(db, cached_paper, cached_space, owner)
    assert error.value.code == {
        "closed": "PAPER_CLOSED", "stopped": "PAPER_STOPPED", "removed": "PAPER_NOT_PUBLISHED",
    }[state]
    db.rollback()
    assert db.query(PaperUrge).count() == 0


def test_concurrent_urges_create_one_notification(client, teacher, student, db):
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)])
    owner_id = paper["owner_id"]
    barrier = Barrier(2)

    def urge():
        with SessionLocal() as session:
            row = session.get(Paper, paper["id"])
            group = session.get(StudySpace, space["id"])
            owner = session.get(User, owner_id)
            barrier.wait(timeout=10)
            try:
                papers.urge_paper(session, row, group, owner)
                return "created"
            except AppError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: urge(), range(2)))
    assert sorted(results) == ["URGE_COOLDOWN", "created"]
    assert db.query(PaperUrge).count() == 1
