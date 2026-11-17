"""对话试卷删除复用业务服务，并保留历史与批量事务原子性。"""
import pytest

from app.db import SessionLocal
from app.errors import AppError
from app.models import Paper, PaperAttempt, PaperPublication, PaperQuestion, User
from app.models.base import new_id
from app.services.rag import data_agent
from test_attempts import _setup


def _preview(db, owner, monkeypatch, mode=None):
    dsl = {"entity": "papers", "action": "delete"}
    if mode is not None:
        dsl["mode"] = mode
    monkeypatch.setattr(data_agent, "chat_json", lambda *args, **kwargs: dsl)
    return data_agent.run_data_request(db, owner, "删除我的试卷", None)


def test_default_chat_delete_only_hides_published_record(
    client, teacher, student, db, monkeypatch,
):
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)])
    started = client.post(f"/api/papers/{paper['id']}/attempts", headers=student,
                          json={"space_id": space["id"]}).json()
    attempt_id = started["attempt"]["id"]
    question_id = started["questions"][0]["paper_question_id"]
    assert client.post(f"/api/attempts/{attempt_id}/submit", headers=student,
                       json={"answers": [{"paper_question_id": question_id,
                                          "choices": ["A"]}]}).status_code == 200
    owner = db.get(User, paper["owner_id"])
    preview = _preview(db, owner, monkeypatch)
    assert "组卷记录" in preview["reply"]
    assert "已发布" in preview["reply"]
    data_agent.execute_confirmed(db, owner, preview["confirm"]["id"], True)

    db.expire_all()
    row = db.get(Paper, paper["id"])
    assert row is not None and not row.deleted and not row.saved_to_records
    assert db.query(PaperPublication).filter_by(paper_id=row.id).count() == 1
    assert db.get(PaperAttempt, attempt_id).status == "submitted"
    assert client.get(f"/api/attempts/{attempt_id}/review", headers=student).status_code == 200
    listed = client.get(f"/api/spaces/{space['id']}/papers", headers=student).json()
    assert any(item["id"] == row.id and item["answered"] for item in listed)


@pytest.mark.parametrize("state,expected", [
    ("open", "PAPER_NOT_CLOSED"), ("publication_open", "PAPER_PUBLICATION_OPEN"),
    ("grading", "GRADING_BUSY"),
])
def test_explicit_whole_delete_obeys_existing_gates(
    client, teacher, student, db, monkeypatch, state, expected,
):
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)])
    row = db.get(Paper, paper["id"])
    owner = db.get(User, row.owner_id)
    row.closed = state != "open"
    if state == "grading":
        db.query(PaperPublication).filter_by(paper_id=row.id).one().stopped = True
        db.add(PaperAttempt(id=new_id("att"), paper_id=row.id, space_id=space["id"],
                            student_id=db.query(User).filter_by(account="student").one().id,
                            status="grading", total_score=5))
    db.commit()
    preview = _preview(db, owner, monkeypatch, "paper")
    assert "整卷删除" in preview["reply"]
    assert "所有" in preview["reply"] and "历史" in preview["reply"]
    with pytest.raises(AppError) as error:
        data_agent.execute_confirmed(db, owner, preview["confirm"]["id"], True)
    assert error.value.code == expected
    db.expire_all()
    assert not db.get(Paper, row.id).deleted


def test_whole_chat_delete_retains_questions_and_attempts(
    client, teacher, student, db, monkeypatch,
):
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)])
    started = client.post(f"/api/papers/{paper['id']}/attempts", headers=student,
                          json={"space_id": space["id"]}).json()
    row = db.get(Paper, paper["id"])
    row.closed = True
    db.query(PaperPublication).filter_by(paper_id=row.id).one().stopped = True
    db.commit()
    owner = db.get(User, row.owner_id)
    preview = _preview(db, owner, monkeypatch, "paper")
    data_agent.execute_confirmed(db, owner, preview["confirm"]["id"], True)
    db.expire_all()
    assert db.get(Paper, paper["id"]).deleted
    assert db.get(PaperAttempt, started["attempt"]["id"]) is not None
    assert db.query(PaperQuestion).filter_by(paper_id=paper["id"]).count() == 1
    assert db.query(PaperPublication).filter_by(paper_id=paper["id"]).count() == 1


@pytest.mark.parametrize("mode", [None, "paper"])
def test_multi_paper_confirmation_rolls_back_earlier_deletes(
    client, db, monkeypatch, mode,
):
    owner = db.query(User).filter_by(account="teacher").one()
    first = Paper(id="paper_review_a", name="先删除", owner_id=owner.id, closed=True)
    second = Paper(id="paper_review_z", name="未关闭", owner_id=owner.id)
    db.add_all([first, second])
    db.commit()
    preview = _preview(db, owner, monkeypatch, mode)
    with pytest.raises(AppError) as error:
        data_agent.execute_confirmed(db, owner, preview["confirm"]["id"], True)
    assert error.value.code == "PAPER_NOT_CLOSED"
    # 服务失败后，同一 session 的后续提交也不能提交上一份试卷的部分删除。
    db.commit()
    with SessionLocal() as reader:
        assert not reader.get(Paper, first.id).deleted
        assert not reader.get(Paper, second.id).deleted


def test_batch_delete_uses_only_preview_ids_and_preserves_rows(client, db, monkeypatch):
    owner = db.query(User).filter_by(account="teacher").one()
    rows = [Paper(id=new_id("paper"), name=f"批量试卷 {i}", owner_id=owner.id, closed=True)
            for i in range(3)]
    db.add_all(rows)
    db.commit()
    dsl = {"entity": "papers", "action": "delete", "mode": "paper",
           "order_by": "name", "limit": 2}
    monkeypatch.setattr(data_agent, "chat_json", lambda *args, **kwargs: dsl)
    preview = data_agent.run_data_request(db, owner, "整卷删除前两份试卷", None)
    late = Paper(id=new_id("paper"), name="后加入", owner_id=owner.id, closed=True)
    db.add(late)
    db.commit()

    data_agent.execute_confirmed(db, owner, preview["confirm"]["id"], True)

    with SessionLocal() as reader:
        assert reader.get(Paper, rows[0].id).deleted
        assert reader.get(Paper, rows[1].id).deleted
        assert not reader.get(Paper, rows[2].id).deleted
        assert not reader.get(Paper, late.id).deleted


def test_batch_commit_failure_rolls_back_all_selected_papers(client, db, monkeypatch):
    owner = db.query(User).filter_by(account="teacher").one()
    rows = [Paper(id=new_id("paper"), name=f"故障试卷 {i}", owner_id=owner.id, closed=True)
            for i in range(2)]
    db.add_all(rows)
    db.commit()
    preview = _preview(db, owner, monkeypatch, "paper")
    original_commit = db.commit

    def fail_commit():
        raise RuntimeError("模拟提交故障")

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="模拟提交故障"):
        data_agent.execute_confirmed(db, owner, preview["confirm"]["id"], True)
    original_commit()
    with SessionLocal() as reader:
        assert all(not reader.get(Paper, row.id).deleted for row in rows)


def test_default_draft_delete_requires_close(client, db, monkeypatch):
    owner = db.query(User).filter_by(account="teacher").one()
    row = Paper(id=new_id("paper"), name="草稿", owner_id=owner.id)
    db.add(row)
    db.commit()
    preview = _preview(db, owner, monkeypatch)
    assert "草稿" in preview["reply"] and "关闭" in preview["reply"]
    with pytest.raises(AppError) as error:
        data_agent.execute_confirmed(db, owner, preview["confirm"]["id"], True)
    assert error.value.code == "PAPER_NOT_CLOSED"
