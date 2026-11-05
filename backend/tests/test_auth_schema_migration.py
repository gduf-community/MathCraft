"""认证迁移只处理合成 SQLite 数据，不打开真实数据库。"""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

MIGRATION = Path(__file__).parents[1] / "alembic/versions/f1a2b3c4d567_auth_sessions_and_email_verification.py"


def migration():
    spec = importlib.util.spec_from_file_location("auth_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(connection):
    connection.execute(text("CREATE TABLE users (id VARCHAR(40) PRIMARY KEY, email VARCHAR(128), "
                            "user_no VARCHAR(32), role VARCHAR(16), identity VARCHAR(16))"))


def test_migration_preserves_ids_and_never_verifies_historical_email(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    with engine.begin() as connection:
        prepare(connection)
        connection.execute(text("INSERT INTO users VALUES ('stable-user', ' Legacy@Example.com ', "
                                "' 001Aa ', 'teacher', '教师')"))
        with Operations.context(MigrationContext.configure(connection)):
            migration().upgrade()
        row = connection.execute(text("SELECT id, email_normalized, email_verified, "
                                      "email_verified_at, user_no FROM users")).one()
        assert tuple(row) == ("stable-user", "legacy@example.com", 0, None, "001Aa")
    engine.dispose()


def test_migration_blocks_normalized_email_collision(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'collision.db'}")
    with engine.begin() as connection:
        prepare(connection)
        connection.execute(text("INSERT INTO users VALUES "
            "('one','A@example.com','001','student','学生'),"
            "('two','a@example.com','002','teacher','教师')"))
        with Operations.context(MigrationContext.configure(connection)):
            with pytest.raises(RuntimeError, match="历史账号"):
                migration().upgrade()
    engine.dispose()
