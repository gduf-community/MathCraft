"""取消任务迁移只操作合成历史 SQLite 数据。"""
from alembic import command
import pytest
from sqlalchemy import inspect, text

from test_ops_runs_migration import historical_database as historical_database

PREVIOUS = "n9a0b1c23456"
HEAD = "o0b1c2d34567"


def test_upgrade_preserves_tasks_and_backfills_only_finished_executions(historical_database):
    config, engine, _ = historical_database
    command.upgrade(config, PREVIOUS)
    with engine.begin() as connection:
        for status in ("queued", "running", "done", "failed", "interrupted"):
            connection.execute(text(
                "INSERT INTO generation_tasks "
                "(id,user_id,bank_id,document_id,mode,params_json,run_id,status,progress,stage,"
                "created_at,updated_at) VALUES "
                "(:status,'u_owner','bank_old','doc_old','parametric','{}',:run,:status,0,"
                "'历史阶段','2026-01-01','2026-01-02')"
            ), {"status": status, "run": f"run_{status}"})
    command.upgrade(config, HEAD)
    with engine.connect() as connection:
        rows = connection.execute(text(
            "SELECT id, status, params_json, request_id, execution_finished_at "
            "FROM generation_tasks ORDER BY id"
        )).all()
        assert len(rows) == 5
        for task_id, status, params, request_id, finished in rows:
            assert task_id == status and params == "{}" and request_id is None
            assert (finished is None) == (status in ("queued", "running"))
        assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
    with pytest.raises(RuntimeError, match="拒绝有损降级"):
        command.downgrade(config, PREVIOUS)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == HEAD


def test_empty_task_schema_can_downgrade_without_touching_history(historical_database):
    config, engine, _ = historical_database
    command.upgrade(config, HEAD)
    with engine.connect() as connection:
        before = connection.execute(text("SELECT * FROM generation_batches")).all()
    command.downgrade(config, PREVIOUS)
    assert "request_id" not in {c["name"] for c in inspect(engine).get_columns("generation_tasks")}
    with engine.connect() as connection:
        assert connection.execute(text("SELECT * FROM generation_batches")).all() == before
