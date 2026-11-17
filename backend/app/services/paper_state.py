"""试卷写入门禁；在 SQLite 与行锁数据库中保护同一份试卷。"""
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import Paper


def lock_paper(db: Session, paper_id: str, *, include_deleted: bool = False) -> Paper:
    """先取得写入权，再刷新已缓存实体；调用方负责提交或回滚。"""
    db.execute(
        update(Paper).where(Paper.id == paper_id).values(updated_at=Paper.updated_at),
        execution_options={"synchronize_session": False},
    )
    paper = db.get(Paper, paper_id, populate_existing=True)
    if paper is None or (paper.deleted and not include_deleted):
        raise AppError("PAPER_NOT_FOUND", "试卷不存在或已被删除", 404)
    return paper
