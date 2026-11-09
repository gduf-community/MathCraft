"""提醒迁移只对合成 SQLite 执行，验证保留账号与可逆性。"""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_reminder_migration_preserves_users_and_defaults_false(monkeypatch):
    path = Path(__file__).resolve().parents[1] / (
        "alembic/versions/f2b3c4d5e678_password_change_recommended.py"
    )
    spec = importlib.util.spec_from_file_location("test_reminder_revision", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "g2b3c4d5e678"
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE users (id TEXT PRIMARY KEY, account TEXT)"))
            connection.execute(text("INSERT INTO users VALUES ('fake-id', 'fake-account')"))
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            assert connection.execute(text(
                "SELECT id, account, password_change_recommended FROM users"
            )).one() == ("fake-id", "fake-account", 0)
            migration.downgrade()
            assert [c["name"] for c in inspect(connection).get_columns("users")] == ["id", "account"]
            assert connection.execute(text("SELECT id, account FROM users")).one() == (
                "fake-id", "fake-account",
            )
    finally:
        engine.dispose()
