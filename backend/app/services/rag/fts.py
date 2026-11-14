"""FTS5 BM25 稀疏检索。tokens 由 jieba 预分词写入；查询侧同样分词后按 OR 组合。"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.services.rag.tokenizer import terms


def insert_rows(db: Session, rows: list[dict]) -> None:
    """rows: [{"chunk_id","bank_id","document_id","tokens"}]，与 chunk 写入同一事务调用。"""
    for r in rows:
        db.execute(
            text(
                "INSERT INTO document_chunks_fts (chunk_id, bank_id, document_id, tokens) "
                "VALUES (:chunk_id, :bank_id, :document_id, :tokens)"
            ),
            r,
        )


def delete_document(db: Session, document_id: str) -> None:
    db.execute(
        text("DELETE FROM document_chunks_fts WHERE document_id = :d"),
        {"d": document_id},
    )


def delete_bank(db: Session, bank_id: str) -> None:
    db.execute(
        text("DELETE FROM document_chunks_fts WHERE bank_id = :b"),
        {"b": bank_id},
    )


def _match_expr(query: str) -> str | None:
    ts = terms(query)
    if not ts:
        return None
    # 词项用双引号包裹成短语，避免被当作 FTS5 操作符
    return " OR ".join('"' + t.replace('"', '""') + '"' for t in ts)


def search(
    bank_id: str,
    query: str,
    top_k: int,
    document_id: str | None = None,
    db: Session | None = None,
) -> list[tuple[str, float]]:
    """仅检索 ready 文档的现存切片，返回按相关性降序的 [(chunk_id, 正向得分)]。"""
    match = _match_expr(query)
    if not match:
        return []
    own = db is None
    session = db or SessionLocal()
    try:
        sql = (
            "SELECT document_chunks_fts.chunk_id, bm25(document_chunks_fts) AS s "
            "FROM document_chunks_fts "
            "JOIN document_chunks c ON c.id = document_chunks_fts.chunk_id "
            "AND c.document_id = document_chunks_fts.document_id "
            "AND c.bank_id = document_chunks_fts.bank_id "
            "JOIN documents d ON d.id = c.document_id AND d.bank_id = c.bank_id "
            "WHERE document_chunks_fts MATCH :m AND document_chunks_fts.bank_id = :b "
            "AND d.status = 'ready'"
        )
        params: dict = {"m": match, "b": bank_id}
        if document_id:
            sql += " AND d.id = :d"
            params["d"] = document_id
        sql += " ORDER BY s LIMIT :k"
        params["k"] = top_k
        rows = session.execute(text(sql), params).fetchall()
        # bm25() 返回负值（越小越相关），翻转为正向得分
        return [(r[0], -float(r[1])) for r in rows]
    finally:
        if own:
            session.close()
