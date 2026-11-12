"""SQLAlchemy 会话；SQLite 使用 WAL、外键、写锁等待和内存临时存储。"""
from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    """全部 ORM 模型的公共基类。"""


def _is_sqlite(url: str) -> bool:
    return url.startswith("sqlite")


engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite(settings.database_url) else {},
    pool_pre_ping=True,
)

if _is_sqlite(settings.database_url):

    @event.listens_for(engine, "connect")
    def _sqlite_pragma(dbapi_conn, _record):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        # FTS5 删除可能创建临时结构；避免依赖 Windows 服务进程的临时目录权限。
        # 仅临时结构使用内存，数据库与 WAL 仍持久化到原有磁盘路径。
        cur.execute("PRAGMA temp_store=MEMORY")
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, class_=Session)

# FTS5 虚拟表与 document_chunks 同步维护（插入/删除在服务层同一事务内完成）
FTS_CREATE_SQL = """
CREATE VIRTUAL TABLE IF NOT EXISTS document_chunks_fts USING fts5(
    chunk_id UNINDEXED,
    bank_id UNINDEXED,
    document_id UNINDEXED,
    tokens,
    tokenize='unicode61'
)
"""


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
