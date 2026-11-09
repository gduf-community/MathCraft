"""Alembic 环境：连接串取自 app.config.settings，元数据取自 app.models。"""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool

from app.config import settings
from app.db import Base
import app.models  # noqa: F401  确保全部模型注册到 Base.metadata

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    if connectable.dialect.name == "sqlite":
        # sqlite3 legacy transaction mode does not BEGIN for DDL. Explicit BEGIN
        # makes batch table rebuilds and the revision marker one atomic transaction.
        @event.listens_for(connectable, "connect")
        def disable_implicit_begin(dbapi_connection, connection_record):
            dbapi_connection.isolation_level = None

        @event.listens_for(connectable, "begin")
        def begin_sqlite(connection):
            connection.exec_driver_sql("BEGIN IMMEDIATE")

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True,
                          transactional_ddl=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
