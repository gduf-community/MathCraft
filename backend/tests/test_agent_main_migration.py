"""各历史分支均可保留业务数据并升级至同一个 head。"""

from alembic import command
from alembic.script import ScriptDirectory
import pytest
from sqlalchemy import create_engine, inspect, text

from app.config import settings
from test_ops_runs_migration import migration_config


@pytest.mark.parametrize("previous", [
    "base", "o0b1c2d34567", "j5f6g7h8i900", "q2d3e4f56789", "r3e4f5a67890",
])
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
                connection.execute(text(
                    "INSERT INTO user_model_settings (user_id, updated_at) "
                    "VALUES ('legacy', '2026-01-01')"
                ))
                if previous == "r3e4f5a67890":
                    connection.execute(text(
                        "UPDATE user_model_settings SET deepseek_base_url='https://model.invalid' "
                        "WHERE user_id='legacy'"
                    ))
                if previous == "q2d3e4f56789":
                    connection.execute(text(
                        "INSERT INTO chat_sessions "
                        "(id,user_id,bank_id,document_id,created_at,updated_at) VALUES "
                        "('s','legacy','b','d','2026-01-01','2026-01-01')"
                    ))
                    connection.execute(text(
                        "INSERT INTO chat_requests (session_id,request_id,status) "
                        "VALUES ('s','r','completed')"
                    ))
                if previous == "j5f6g7h8i900":
                    connection.execute(text(
                        "UPDATE platform_llm_settings SET model='synthetic-model', "
                        "encrypted_key='synthetic-ciphertext-not-a-real-credential' WHERE id=1"
                    ))
        command.upgrade(config, "head")
        assert ScriptDirectory.from_config(config).get_heads() == ["s4f5a6b78901"]
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        assert {"platform_llm_settings", "generation_tasks", "ops_runs", "chat_requests"} <= tables
        assert "deepseek_base_url" in {
            column["name"] for column in inspector.get_columns("user_model_settings")
        }
        assert {"request_id", "execution_finished_at"} <= {
            column["name"] for column in inspector.get_columns("generation_tasks")
        }
        with engine.connect() as connection:
            assert connection.execute(text(
                "SELECT version_num FROM alembic_version"
            )).scalars().all() == ["s4f5a6b78901"]
            assert connection.execute(text("PRAGMA foreign_key_check")).all() == []
            if previous != "base":
                assert connection.execute(text(
                    "SELECT account,display_name FROM users WHERE id='legacy'"
                )).one() == ("synthetic", "合成账号")
                expected_url = "https://model.invalid" if previous == "r3e4f5a67890" else None
                assert connection.execute(text(
                    "SELECT deepseek_base_url FROM user_model_settings WHERE user_id='legacy'"
                )).scalar_one() == expected_url
            if previous == "q2d3e4f56789":
                assert connection.execute(text(
                    "SELECT status FROM chat_requests WHERE session_id='s' AND request_id='r'"
                )).scalar_one() == "completed"
            if previous == "j5f6g7h8i900":
                assert connection.execute(text(
                    "SELECT model,encrypted_key FROM platform_llm_settings WHERE id=1"
                )).one() == (
                    "synthetic-model", "synthetic-ciphertext-not-a-real-credential",
                )
    finally:
        engine.dispose()
