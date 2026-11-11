"""数据管理确认必须执行预览的目标集合，并隔离账号、重放和并发。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

import pytest

from app.db import SessionLocal
from app.errors import AppError
from app.models import (
    Favorite, FavoriteGroup, Paper, PaperAttempt, Question, SpaceMember, StudySpace, User,
)
from app.models.base import new_id
from app.services.rag import data_agent
from conftest import make_questions


@pytest.fixture
def owner(client, db):
    return db.query(User).filter_by(account="teacher").one()


def _papers(db, owner_id, count):
    papers = [Paper(id=new_id("p"), name=f"试卷 {i}", owner_id=owner_id)
              for i in range(count)]
    db.add_all(papers)
    db.commit()
    return [paper.id for paper in papers]


def _preview(db, owner, monkeypatch, **overrides):
    dsl = {"entity": "papers", "action": "delete", **overrides}
    monkeypatch.setattr(data_agent, "chat_json", lambda *a, **kw: dsl)
    return data_agent.run_data_request(db, owner, "管理我的数据", "fake-model-key")["confirm"]


@pytest.mark.parametrize("action,limit", [("delete", None), ("update", 2)])
def test_confirmation_uses_preview_ids_including_limit_and_later_inserts(
    owner, db, monkeypatch, action, limit,
):
    ids = _papers(db, owner.id, 55 if limit is None else 5)
    dsl = {"action": action, "set_name": "新名称"}
    if limit is not None:
        dsl["limit"] = limit
    confirm = _preview(db, owner, monkeypatch, **dsl)
    expected = limit or 50
    assert confirm["affected"] == expected
    late_id = _papers(db, owner.id, 1)[0]
    reply = data_agent.execute_confirmed(db, owner, confirm["id"], True)
    db.expire_all()
    assert str(expected) in reply
    assert db.get(Paper, late_id).name == "试卷 0"
    remaining = db.query(Paper).filter(Paper.id.in_(ids)).all()
    if action == "delete":
        assert len(remaining) == len(ids) - expected
    else:
        assert sum(p.name == "新名称" for p in remaining) == expected


def test_confirmation_preserves_filter_operator(owner, db, monkeypatch):
    ids = _papers(db, owner.id, 4)
    # like/eq 的含义必须与预览完全一致，不能执行时改成 SQL LIKE。
    db.get(Paper, ids[0]).name = "目标"
    db.get(Paper, ids[1]).name = "目标副本"
    db.commit()
    confirm = _preview(db, owner, monkeypatch,
                       filters=[{"field": "name", "op": "eq", "value": "目标"}])
    assert confirm["affected"] == 1
    data_agent.execute_confirmed(db, owner, confirm["id"], True)
    assert db.get(Paper, ids[1]) is not None
    assert db.query(Paper).count() == 3


def test_confirmation_preserves_preview_sort_selection(owner, db, monkeypatch):
    ids = _papers(db, owner.id, 3)
    confirm = _preview(db, owner, monkeypatch, order_by="-name", limit=1)
    assert "试卷 2" in confirm["samples"][0]
    data_agent.execute_confirmed(db, owner, confirm["id"], True)
    db.expire_all()
    assert db.get(Paper, ids[2]) is None
    assert db.get(Paper, ids[0]) is not None
    assert db.get(Paper, ids[1]) is not None


def test_hardest_favorite_confirmation_selects_older_hard_question(owner, db, monkeypatch):
    qids = make_questions(db, owner.id, [("single", "A", 5)] * 2)
    group = FavoriteGroup(id=new_id("fg"), user_id=owner.id, name="难度排序")
    db.add(group)
    db.flush()
    old = datetime.now(timezone.utc) - timedelta(days=1)
    hard = db.get(Question, qids[0])
    hard.stem, hard.difficulty_score = "较旧高难题", 4.9
    easy = db.get(Question, qids[1])
    easy.stem, easy.difficulty_score = "最新简单题", 1.0
    fav_hard = Favorite(id=new_id("fav"), user_id=owner.id, question_id=hard.id,
                        group_id=group.id, created_at=old)
    fav_easy = Favorite(id=new_id("fav"), user_id=owner.id, question_id=easy.id,
                        group_id=group.id)
    db.add_all([fav_hard, fav_easy])
    db.commit()
    hard_id, easy_id = fav_hard.id, fav_easy.id
    confirm = _preview(db, owner, monkeypatch, entity="favorites",
                       order_by="-difficulty_score", limit=1)
    assert "较旧高难题" in confirm["samples"][0]
    data_agent.execute_confirmed(db, owner, confirm["id"], True)
    db.expire_all()
    assert db.get(Favorite, hard_id) is None
    assert db.get(Favorite, easy_id) is not None


def test_unknown_sort_field_is_rejected_before_confirmation(owner, db, monkeypatch):
    _papers(db, owner.id, 2)
    with pytest.raises(AppError) as error:
        _preview(db, owner, monkeypatch, order_by="-unknown_column", limit=1)
    assert error.value.code == "DATA_ORDER"


def _aggregate_dataset(db, owner, entity, count):
    """构造超过历史 ORM 上限的完整所属数据集，含较旧的数值极值。"""
    student = db.query(User).filter_by(account="student").one()
    old = datetime.now(timezone.utc) - timedelta(days=1)
    if entity == "papers":
        _papers(db, owner.id, count)
        _papers(db, student.id, 3)
        return
    if entity in ("favorites", "questions"):
        qids = make_questions(db, owner.id, [("single", "A", 5)] * count)
        make_questions(db, student.id, [("single", "A", 5)] * 3)
        db.query(Question).filter(Question.id.in_(qids)).update({"difficulty_score": 1.0})
        db.get(Question, qids[0]).difficulty_score = 5.0
        db.get(Question, qids[0]).created_at = old
        if entity == "favorites":
            group = FavoriteGroup(id=new_id("fg"), user_id=owner.id, name="全部收藏")
            db.add(group)
            db.flush()
            db.add_all([Favorite(id=new_id("fav"), user_id=owner.id, question_id=qid,
                                 group_id=group.id, created_at=old if i == 0 else None)
                        for i, qid in enumerate(qids)])
        db.commit()
        return
    if entity == "spaces":
        db.add_all([StudySpace(id=new_id("sp"), name=f"空间{i}", code=new_id("SP"),
                               creator_id=owner.id, capacity=30) for i in range(count)])
        db.add(StudySpace(id=new_id("sp"), name="他人空间", code=new_id("SP"),
                          creator_id=student.id, capacity=30))
        db.commit()
        return
    paper_id = _papers(db, owner.id, 1)[0]
    space = StudySpace(id=new_id("sp"), name="统计空间", code=new_id("SP"),
                       creator_id=owner.id, capacity=30)
    db.add(space)
    db.flush()
    db.add_all([PaperAttempt(id=new_id("att"), paper_id=paper_id, space_id=space.id,
                             student_id=student.id, status="submitted", total_score=100,
                             score=100 if i == 0 else 0,
                             started_at=old if i == 0 else datetime.now(timezone.utc))
                for i in range(count)])
    db.commit()


@pytest.mark.parametrize("entity,count", [("papers", 205), ("favorites", 405),
                                          ("questions", 405), ("spaces", 105),
                                          ("attempts", 405)])
@pytest.mark.parametrize("limit", [None, 20])
def test_count_uses_all_owned_rows_beyond_orm_caps(owner, db, monkeypatch, entity, count, limit):
    _aggregate_dataset(db, owner, entity, count)
    dsl = {"entity": entity, "action": "select", "aggregate": "count"}
    if limit is not None:
        dsl["limit"] = limit
    monkeypatch.setattr(data_agent, "chat_json", lambda *a, **kw: dsl)
    result = data_agent.run_data_request(db, owner, "统计所有数据", "fake-key")
    assert result["reply"].startswith(f"共 {count} 条记录。")


@pytest.mark.parametrize("entity,field,expected", [
    ("favorites", "difficulty_score", "1.01"),
    ("questions", "difficulty_score", "1.01"), ("attempts", "score", "0.25"),
])
def test_numeric_aggregates_include_old_rows_beyond_orm_caps(
    owner, db, monkeypatch, entity, field, expected,
):
    _aggregate_dataset(db, owner, entity, 405)
    for aggregate, summary in [(f"avg:{field}", f"平均 {expected}"),
                               (f"max:{field}", "100.0" if field == "score" else "5.0"),
                               (f"min:{field}", "0.0" if field == "score" else "1.0")]:
        monkeypatch.setattr(data_agent, "chat_json", lambda *a, **kw: {
            "entity": entity, "action": "select", "aggregate": aggregate, "limit": 1,
        })
        result = data_agent.run_data_request(db, owner, "统计数据", "fake-key")
        assert summary in result["reply"].splitlines()[0]


def test_filtered_and_multi_entity_counts_use_complete_sets(owner, db, monkeypatch):
    _aggregate_dataset(db, owner, "papers", 205)
    ids = [paper.id for paper in db.query(Paper).filter_by(owner_id=owner.id).all()]
    db.query(Paper).filter(Paper.id.in_(ids[:60])).update({"name": "目标试卷"})
    db.commit()
    query = {"entity": "papers", "aggregate": "count", "limit": 1,
             "filters": [{"field": "name", "op": "eq", "value": "目标试卷"}]}
    for dsl in (query, {"entities": [query]}):
        monkeypatch.setattr(data_agent, "chat_json", lambda *a, **kw: dsl)
        result = data_agent.run_data_request(db, owner, "统计目标", "fake-key")
        assert "共 60 条记录。" in result["reply"]


def test_student_space_count_includes_all_memberships(owner, db, monkeypatch):
    _aggregate_dataset(db, owner, "spaces", 105)
    student = db.query(User).filter_by(account="student").one()
    spaces = db.query(StudySpace).filter_by(creator_id=owner.id).all()
    db.add_all([SpaceMember(id=new_id("sm"), space_id=space.id, user_id=student.id,
                            role="member") for space in spaces])
    db.commit()
    monkeypatch.setattr(data_agent, "chat_json", lambda *a, **kw: {
        "entity": "spaces", "aggregate": "count", "limit": 20,
    })
    result = data_agent.run_data_request(db, student, "我的空间数量", "fake-key")
    assert result["reply"].startswith("共 105 条记录。")


def test_favorite_confirmation_uses_preview_order_and_limit(owner, db, monkeypatch):
    question_ids = make_questions(db, owner.id, [("single", "A", 5)] * 4)
    group = FavoriteGroup(id=new_id("fg"), user_id=owner.id, name="预览组")
    db.add(group)
    db.flush()
    favorites = [Favorite(id=new_id("fav"), user_id=owner.id, question_id=qid,
                          group_id=group.id) for qid in question_ids]
    db.add_all(favorites)
    db.commit()
    confirm = _preview(db, owner, monkeypatch, entity="favorites", limit=2,
                       filters=[{"field": "group", "op": "like", "value": "预览"}])
    assert confirm["affected"] == 2
    data_agent.execute_confirmed(db, owner, confirm["id"], True)
    assert db.query(Favorite).count() == 2


def test_foreign_account_does_not_consume_confirmation(owner, db, monkeypatch, isolated_redis):
    _papers(db, owner.id, 1)
    other = db.query(User).filter_by(account="student").one()
    confirm = _preview(db, owner, monkeypatch)
    with pytest.raises(AppError) as error:
        data_agent.execute_confirmed(db, other, confirm["id"], True)
    assert error.value.code == "CONFIRM_FORBIDDEN"
    assert isolated_redis.exists(data_agent._confirm_key(confirm["id"]))
    data_agent.execute_confirmed(db, owner, confirm["id"], True)
    assert db.query(Paper).count() == 0


def test_confirmation_rechecks_ownership(owner, db, monkeypatch):
    paper_id = _papers(db, owner.id, 1)[0]
    confirm = _preview(db, owner, monkeypatch)
    other = db.query(User).filter_by(account="student").one()
    db.get(Paper, paper_id).owner_id = other.id
    db.commit()
    data_agent.execute_confirmed(db, owner, confirm["id"], True)
    db.expire_all()
    assert db.get(Paper, paper_id) is not None


@pytest.mark.parametrize("accepted", [True, False])
def test_confirmation_is_single_use(owner, db, monkeypatch, accepted):
    _papers(db, owner.id, 1)
    confirm = _preview(db, owner, monkeypatch)
    data_agent.execute_confirmed(db, owner, confirm["id"], accepted)
    with pytest.raises(AppError) as error:
        data_agent.execute_confirmed(db, owner, confirm["id"], True)
    assert error.value.code == "CONFIRM_EXPIRED"
    assert db.query(Paper).count() == (0 if accepted else 1)


def test_expired_confirmation_cannot_mutate(owner, db, monkeypatch, isolated_redis):
    _papers(db, owner.id, 1)
    confirm = _preview(db, owner, monkeypatch)
    key = data_agent._confirm_key(confirm["id"])
    assert 0 < isolated_redis.ttl(key) <= data_agent.CONFIRM_TTL_SECONDS
    isolated_redis.pexpire(key, 0)
    with pytest.raises(AppError) as error:
        data_agent.execute_confirmed(db, owner, confirm["id"], True)
    assert error.value.code == "CONFIRM_EXPIRED"
    assert db.query(Paper).count() == 1


def test_concurrent_confirmations_execute_only_once(owner, db, monkeypatch, isolated_redis):
    _papers(db, owner.id, 1)
    confirm = _preview(db, owner, monkeypatch)
    owner_id = owner.id
    key = data_agent._confirm_key(confirm["id"])
    barrier = Barrier(2)
    original_get = isolated_redis.get

    def simultaneous_get(name):
        value = original_get(name)
        if name == key:
            barrier.wait(timeout=10)
        return value

    monkeypatch.setattr(isolated_redis, "get", simultaneous_get)

    def execute():
        with SessionLocal() as session:
            try:
                return data_agent.execute_confirmed(
                    session, session.get(User, owner_id), confirm["id"], True,
                )
            except AppError as error:
                return error.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: execute(), range(2)))
    assert results.count("CONFIRM_EXPIRED") == 1
    assert sum("已删除 1" in result for result in results) == 1


@pytest.mark.parametrize("action,entity", [("truncate", "papers"), ("delete", "questions")])
def test_unsupported_mutation_has_no_confirmation(owner, db, monkeypatch, action, entity):
    monkeypatch.setattr(data_agent, "chat_json", lambda *a, **kw: {
        "action": action, "entity": entity,
    })
    result = data_agent.run_data_request(db, owner, "操作数据", "fake-model-key")
    assert "confirm" not in result
