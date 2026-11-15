"""仅供 V2 查询测试的独立临时表，不注册到应用 Base 或生产模型。"""
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, create_engine
from sqlalchemy.orm import Session

NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)


def run_row(run_id: str = "run_fixture", **changes: object) -> dict[str, object]:
    """合成摘要包含禁止出现在查询响应的额外列，以验证显式投影。"""
    row: dict[str, object] = {
        "run_id": run_id, "entrypoint": "parameterized", "owner_user_id": "u_teacher",
        "session_id": None, "task_id": "task_fixture", "bank_id": None,
        "document_id": None, "batch_id": None, "status": "unknown",
        "requested_count": None, "delivered_count": None, "error_code": None,
        "accepted_at": NOW, "started_at": None, "finished_at": None, "last_observed_at": None,
        "private_body": "synthetic-private-body-never-return",
    }
    row.update(changes)
    return row


@pytest.fixture
def ledger(tmp_path) -> Iterator[tuple[Session, Table]]:
    """每个用例独立 SQLite；不复用应用 metadata，不运行 Alembic。"""
    metadata = MetaData()
    table = Table(
        "ops_runs", metadata,
        Column("run_id", String(128), primary_key=True),
        *(Column(name, String(128)) for name in (
            "entrypoint", "owner_user_id", "session_id", "task_id", "bank_id", "document_id",
            "batch_id", "status", "error_code", "private_body",
        )),
        Column("requested_count", Integer), Column("delivered_count", Integer),
        *(Column(name, DateTime(timezone=True)) for name in (
            "accepted_at", "started_at", "finished_at", "last_observed_at",
        )),
    )
    engine = create_engine(f"sqlite:///{(tmp_path / 'ops-test-only.db').as_posix()}")
    metadata.create_all(engine)
    with Session(engine) as db:
        yield db, table
    engine.dispose()


def seed(ledger: tuple[Session, Table], *rows: dict[str, object]) -> None:
    """只向当前用例的临时表写入合成数据。"""
    db, table = ledger
    db.execute(table.insert(), list(rows))
    db.commit()
