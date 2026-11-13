"""实际 Alembic 升级与数据库约束：只迁移测试创建的合成 SQLite。"""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import CheckConstraint, create_engine, event, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models import Bank, Document, GenerationBatch, OpsRun, User
from app.models.ops_run import RunEntrypoint
from app.services.ops_runs import RunLedger

PREVIOUS = "i4d5e6f7a890"
HEAD = "j5e6f7a8b901"
NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)


def migration_config() -> Config:
    backend = Path(__file__).resolve().parents[1]
    # 仍执行真实 env.py，但不加载 CLI 日志 ini，避免禁用当前 pytest 进程的 logger。
    config = Config()
    config.set_main_option("script_location", str(backend / "alembic"))
    return config


@pytest.fixture
def historical_database(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'migration.sqlite').as_posix()}"
    monkeypatch.setattr(settings, "database_url", url)
    config = migration_config()
    command.upgrade(config, PREVIOUS)
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection: sqlite3.Connection, _record) -> None:
        connection.execute("PRAGMA foreign_keys=ON")

    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with sessions.begin() as db:
        db.add(User(id="u_owner", account="synthetic-owner", password_hash="synthetic-hash",
                    role="teacher", identity="教师", display_name="历史合成账号"))
        db.flush()
        db.add(Bank(id="bank_old", name="历史合成题库", code="synthetic-bank", creator_id="u_owner"))
        db.flush()
        db.add(Document(id="doc_old", bank_id="bank_old", name="synthetic.md", format="MD",
                        size_bytes=1, storage_path="synthetic/unused", uploader_id="u_owner"))
        db.flush()
        db.add(GenerationBatch(id="batch_old", user_id="u_owner", bank_id="bank_old",
                               document_id="doc_old", mode="parametric", question_count=0,
                               status="done"))
    yield config, engine, sessions
    engine.dispose()


def historical_rows(engine) -> dict:
    """逐表比较迁移前已有业务记录，包括旧批次与平台配置。"""
    with engine.connect() as connection:
        return {
            name: connection.execute(text(f'SELECT * FROM "{name}"')).all()
            for name in inspect(connection).get_table_names()
            if name not in {"alembic_version", "ops_runs"}
        }


def test_upgrade_preserves_all_existing_tables_rows_and_does_not_backfill(historical_database):
    config, engine, _sessions = historical_database
    before = historical_rows(engine)
    directory = ScriptDirectory.from_config(config)
    assert directory.get_current_head() == HEAD
    assert directory.get_revision(HEAD).down_revision == PREVIOUS
    command.upgrade(config, "head")
    assert historical_rows(engine) == before
    with engine.connect() as connection:
        assert connection.execute(select(OpsRun)).all() == []
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    command.downgrade(config, PREVIOUS)
    assert "ops_runs" not in inspect(engine).get_table_names()
    assert historical_rows(engine) == before


def test_nonempty_ledger_downgrade_preserves_history_and_revision(historical_database):
    config, engine, sessions = historical_database
    command.upgrade(config, "head")
    run_id = RunLedger(sessions).accept(entrypoint=RunEntrypoint.PARAMETERIZED,
                                        owner_user_id="u_owner", bank_id="bank_old",
                                        document_id="doc_old", requested_count=1)
    before = historical_rows(engine)
    with pytest.raises(RuntimeError, match="运行台账非空"):
        command.downgrade(config, PREVIOUS)
    assert historical_rows(engine) == before
    with sessions() as db:
        assert db.get(OpsRun, run_id).status == "accepted"
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD


def test_migration_and_orm_metadata_have_matching_storage_contract(historical_database):
    config, engine, _sessions = historical_database
    command.upgrade(config, "head")
    inspector = inspect(engine)
    actual_columns = inspector.get_columns("ops_runs")
    expected = OpsRun.__table__
    assert [(c["name"], c["nullable"]) for c in actual_columns] == [
        (c.name, c.nullable) for c in expected.columns
    ]
    actual_checks = {c["name"]: c["sqltext"] for c in inspector.get_check_constraints("ops_runs")}
    expected_checks = {c.name: str(c.sqltext) for c in expected.constraints
                       if isinstance(c, CheckConstraint)}
    assert actual_checks == expected_checks
    assert {tuple(c["column_names"]) for c in inspector.get_unique_constraints("ops_runs")} == {
        ("task_id",), ("batch_id",),
    }
    assert {i["name"]: tuple(i["column_names"]) for i in inspector.get_indexes("ops_runs")} == {
        index.name: tuple(column.name for column in index.columns) for index in expected.indexes
    }
    foreign_keys = inspector.get_foreign_keys("ops_runs")
    assert len(foreign_keys) == 1
    assert foreign_keys[0]["constrained_columns"] == ["owner_user_id"]
    assert foreign_keys[0]["options"]["ondelete"] == "RESTRICT"


def test_database_rejects_invalid_fields_and_state_shapes(historical_database):
    config, engine, _sessions = historical_database
    command.upgrade(config, "head")
    base = dict(run_id="run_invalid", entrypoint="parameterized", owner_user_id="u_owner",
                bank_id="bank_old", document_id="doc_old", status="accepted", requested_count=2,
                accepted_at=NOW, last_observed_at=NOW)
    invalid = [
        {"entrypoint": "qa"}, {"status": "succeeded"}, {"requested_count": 0},
        {"requested_count": -1}, {"requested_count": 1.5},
        {"delivered_count": -1}, {"delivered_count": 0}, {"run_id": ""},
        {"run_id": "x" * 41}, {"bank_id": ""}, {"document_id": ""},
        {"task_id": ""}, {"task_id": "x" * 41},
        {"owner_user_id": None}, {"owner_user_id": "u_missing"}, {"bank_id": None},
        {"document_id": None}, {"accepted_at": None}, {"last_observed_at": None},
        {"entrypoint": "conversation"}, {"session_id": "chat_wrong"},
        {"status": "running"}, {"batch_id": "batch_old"}, {"error_code": "raw-exception-text"},
        {"started_at": NOW}, {"last_observed_at": NOW - timedelta(seconds=1)},
        {"status": "failed", "error_code": "MODEL_ERROR", "delivered_count": 0},
        {"status": "failed", "finished_at": NOW, "delivered_count": 0},
        {"status": "failed", "finished_at": NOW, "error_code": "MODEL_ERROR"},
        {"status": "canceled", "finished_at": NOW, "delivered_count": 0},
        {"status": "unknown", "error_code": "OUTCOME_UNKNOWN", "finished_at": NOW},
        {"status": "completed", "started_at": NOW, "finished_at": NOW, "delivered_count": 2},
        {"status": "completed", "started_at": NOW, "finished_at": NOW, "batch_id": "batch_old"},
        {"status": "completed", "finished_at": NOW,
         "batch_id": "batch_old", "delivered_count": 2},
    ]
    with engine.begin() as connection:
        for changes in invalid:
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(OpsRun.__table__.insert().values(**(base | changes)))
        connection.execute(OpsRun.__table__.insert().values(**base))
        # 同一任务或同一保存批次不能被重复计作两次运行。
        connection.execute(OpsRun.__table__.update().values(task_id="task_unique"))
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(OpsRun.__table__.insert().values(
                **(base | {"run_id": "run_other", "task_id": "task_unique"})
            ))
        saved = base | dict(status="completed", started_at=NOW, finished_at=NOW,
                            delivered_count=0, batch_id="batch_old")
        connection.execute(OpsRun.__table__.update().values(**saved))
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(OpsRun.__table__.insert().values(
                **(saved | {"run_id": "run_other"})
            ))
