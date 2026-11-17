"""对话改名确认在执行时重检试卷状态、归属及批次事务边界。"""
import pytest
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.errors import AppError
from app.models import Paper, User
from app.services import papers
from app.services.rag import data_agent


@pytest.fixture
def owner(client, db: Session) -> User:
    return db.query(User).filter_by(account="teacher").one()


def _papers(db: Session, owner: User, count: int = 2) -> list[Paper]:
    rows = [Paper(id=f"rename_gate_{i}", owner_id=owner.id, name=f"原名 {i}", closed=True)
            for i in range(count)]
    db.add_all(rows)
    db.commit()
    return rows


def _preview(db: Session, owner: User, monkeypatch: pytest.MonkeyPatch, **overrides) -> str:
    dsl = {"entity": "papers", "action": "update", "set_name": "新名称",
           "order_by": "-name", **overrides}
    monkeypatch.setattr(data_agent, "chat_json", lambda *args, **kwargs: dsl)
    return data_agent.run_data_request(db, owner, "修改试卷名称", None)["confirm"]["id"]


def _assert_names(expected: dict[str, str]) -> None:
    with SessionLocal() as reader:
        assert {paper_id: reader.get(Paper, paper_id).name for paper_id in expected} == expected


@pytest.mark.parametrize("count", [1, 2])
def test_rename_preview_then_whole_delete_rejects_entire_batch(
    owner, db, monkeypatch, isolated_redis, count,
):
    rows = _papers(db, owner, count)
    expected = {row.id: row.name for row in rows}
    confirm_id = _preview(db, owner, monkeypatch)
    deleted_id = rows[-1].id
    # 用另一个真实会话删除，保留执行会话中的旧实体，验证写门禁确实刷新状态。
    with SessionLocal() as writer:
        papers.delete_paper(writer, writer.get(Paper, deleted_id), mode="paper")
    assert not rows[-1].deleted

    with pytest.raises(AppError) as error:
        data_agent.execute_confirmed(db, owner, confirm_id, True)

    assert error.value.code == "PAPER_NOT_FOUND"
    assert error.value.status_code == 404
    assert not isolated_redis.exists(data_agent._confirm_key(confirm_id))
    # 后续提交也不能带出失败批次的改名。
    db.commit()
    _assert_names(expected)
    with SessionLocal() as reader:
        assert reader.get(Paper, deleted_id).deleted
    with pytest.raises(AppError) as replay:
        data_agent.execute_confirmed(db, owner, confirm_id, True)
    assert replay.value.code == "CONFIRM_EXPIRED"


def test_rename_locks_in_id_order_and_only_updates_preview_targets(owner, db, monkeypatch):
    rows = _papers(db, owner, 3)
    other = db.query(User).filter_by(account="student").one()
    foreign = Paper(id="rename_gate_foreign", owner_id=other.id, name="其他账号")
    db.add(foreign)
    db.commit()
    confirm_id = _preview(db, owner, monkeypatch, limit=2)
    late = Paper(id="rename_gate_late", owner_id=owner.id, name="预览后新建")
    db.add(late)
    db.commit()
    from app.services.paper_state import lock_paper

    locked_ids: list[str] = []

    def record_lock(session: Session, paper_id: str) -> Paper:
        locked_ids.append(paper_id)
        return lock_paper(session, paper_id)

    monkeypatch.setattr(data_agent, "lock_paper", record_lock)
    reply = data_agent.execute_confirmed(db, owner, confirm_id, True)

    assert locked_ids == [rows[1].id, rows[2].id]
    assert reply == "已把 2 份试卷改名为「新名称」。"
    _assert_names({rows[0].id: "原名 0", rows[1].id: "新名称", rows[2].id: "新名称",
                   foreign.id: "其他账号", late.id: "预览后新建"})


@pytest.mark.parametrize("at_lock", [False, True])
def test_rename_rechecks_owner_before_and_after_lock(owner, db, monkeypatch, at_lock):
    rows = _papers(db, owner)
    other = db.query(User).filter_by(account="student").one()
    other_id = other.id
    target_id = rows[-1].id
    confirm_id = _preview(db, owner, monkeypatch)

    def transfer() -> None:
        with SessionLocal() as writer:
            writer.get(Paper, target_id).owner_id = other_id
            writer.commit()

    if at_lock:
        from app.services.paper_state import lock_paper

        def transfer_before_lock(session: Session, paper_id: str) -> Paper:
            # 在首个写锁前模拟候选查询之后归属变化，避免测试自身持锁等待。
            if paper_id == rows[0].id:
                transfer()
            return lock_paper(session, paper_id)

        monkeypatch.setattr(data_agent, "lock_paper", transfer_before_lock)
    else:
        transfer()

    reply = data_agent.execute_confirmed(db, owner, confirm_id, True)

    assert reply == "已把 1 份试卷改名为「新名称」。"
    _assert_names({rows[0].id: "新名称", target_id: "原名 1"})
    with SessionLocal() as reader:
        assert reader.get(Paper, target_id).owner_id == other_id


def test_rename_commit_failure_rolls_back_entire_batch(owner, db, monkeypatch, isolated_redis):
    rows = _papers(db, owner)
    expected = {row.id: row.name for row in rows}
    confirm_id = _preview(db, owner, monkeypatch)
    original_commit = db.commit

    def fail_commit() -> None:
        db.flush()
        raise RuntimeError("模拟改名提交故障")

    monkeypatch.setattr(db, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="模拟改名提交故障"):
        data_agent.execute_confirmed(db, owner, confirm_id, True)

    original_commit()
    _assert_names(expected)
    assert not isolated_redis.exists(data_agent._confirm_key(confirm_id))


@pytest.mark.parametrize("accepted", [False, True])
def test_rename_confirmation_remains_single_use(owner, db, monkeypatch, accepted):
    row = _papers(db, owner, 1)[0]
    confirm_id = _preview(db, owner, monkeypatch)

    data_agent.execute_confirmed(db, owner, confirm_id, accepted)

    _assert_names({row.id: "新名称" if accepted else "原名 0"})
    with pytest.raises(AppError) as error:
        data_agent.execute_confirmed(db, owner, confirm_id, True)
    assert error.value.code == "CONFIRM_EXPIRED"
