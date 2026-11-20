"""两条已发布迁移链均可保留历史数据并升级至同一个 head。"""

from alembic import command
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, inspect, text

from app.config import settings
from test_ops_runs_migration import migration_config


@pytest.mark.parametrize("previous", ["base", "o0b1c2d34567", "j5f6g7h8i900"])
def test_upgrade_from_each_branch_preserves_history(tmp_path, monkeypatch, previous):
    url = f"sqlite:///{(tmp_path / 'branches.sqlite').as_posix()}"
    monkeypatch.setattr(settings, "database_url", url)
    config = migration_config()
    command.upgrade(config, previous)
    engine = create_engine(url)
    try:
        if previous != "base":
            with engine.begin() as connection:
                connection.execute(text(
                    "INSERT INTO users (id,account,password_hash,role,identity,display_name,"
                    "status,created_at,updated_at) VALUES "
                    "('legacy','synthetic','synthetic-hash','teacher','教师','合成账号',"
                    "'active','2026-01-01','2026-01-01')"
                ))
                if previous == "j5f6g7h8i900":
                    connection.execute(text(
                        "UPDATE platform_llm_settings SET model='synthetic-model', "
                        "encrypted_key='synthetic-ciphertext-not-a-real-credential' WHERE id=1"
                    ))
        command.upgrade(config, "head")
        assert ScriptDirectory.from_config(config).get_heads() == ["q2d3e4f56789"]
        tables = inspect(engine).get_table_names()
        assert {"platform_llm_settings", "generation_tasks", "ops_runs"} <= set(tables)
        assert {"request_id", "execution_finished_at"} <= {
            column["name"] for column in inspect(engine).get_columns("generation_tasks")
        }
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT version_num FROM alembic_version"
            )).scalars().all() == ["q2d3e4f56789"]
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            if previous != "base":
                assert connection.execute(text(
                    "SELECT account,display_name FROM users WHERE id='legacy'"
                )).one() == ("synthetic", "合成账号")
            if previous == "j5f6g7h8i900":
                assert connection.execute(text(
                    "SELECT model,encrypted_key FROM platform_llm_settings WHERE id=1"
                )).one() == (
                    "synthetic-model", "synthetic-ciphertext-not-a-real-credential",
                )
    finally:
        engine.dispose()
