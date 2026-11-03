"""混合检索：稠密（bge-m3，可用 HyDE 文本）+ 稀疏（FTS5 BM25，原始查询）→ RRF 融合 → 重排。

流程与默认参数见 v2 文档 6.5：
  dense_top_k=20, sparse_top_k=20, fused_top_k=12, rerank_top_k=6, rrf_k=60
重排失败降级为融合顺序；稀疏为空只走向量；稠密为空只走稀疏；双空返回空。
"""
from sqlalchemy import text as sql_text

from app.config import settings
from app.db import SessionLocal
from app.services.rag import embeddings, fts, rerank, vectorstore


def _rrf_fuse(dense_hits: list[dict], sparse_hits: list[tuple[str, float]]) -> list[dict]:
    """RRF：score = Σ 1/(k + rank)，按 chunk_id 去重累加。"""
    k = settings.rrf_k
    scores: dict[str, float] = {}
    for rank, hit in enumerate(dense_hits, 1):
        cid = hit["chunk_id"]
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    for rank, (cid, _bm25) in enumerate(sparse_hits, 1):
        scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
    return [
        {"chunk_id": cid, "rrf": s}
        for cid, s in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    ][: settings.fused_top_k]


def _fetch_chunks(chunk_ids: list[str]) -> dict[str, dict]:
    """从 SQLite 取 chunk 详情（文本、题型、章节、文档名）。"""
    if not chunk_ids:
        return {}
    db = SessionLocal()
    try:
        placeholders = ", ".join(f":i{n}" for n in range(len(chunk_ids)))
        params = {f"i{n}": cid for n, cid in enumerate(chunk_ids)}
        rows = db.execute(
            sql_text(
                "SELECT c.id, c.text, c.chunk_type, c.section, c.document_id, d.name AS doc_name "
                "FROM document_chunks c LEFT JOIN documents d ON d.id = c.document_id "
                f"WHERE c.id IN ({placeholders})"
            ),
            params,
        ).fetchall()
        return {
            r[0]: {
                "chunk_id": r[0],
                "text": r[1],
                "chunk_type": r[2] or "general",
                "section": r[3] or "",
                "document_id": r[4],
                "doc_name": r[5] or "",
            }
            for r in rows
        }
    finally:
        db.close()


def hybrid_retrieve(
    bank_id: str,
    query: str,
    document_id: str | None = None,
    hyde_text: str | None = None,
    dense_top_k: int | None = None,
    sparse_top_k: int | None = None,
    fused_top_k: int | None = None,
    rerank_top_k: int | None = None,
) -> dict:
    """完整混合检索，返回 dense / sparse / fused / reranked 四段结果（检索测试接口用）。"""
    dense_k = dense_top_k or settings.dense_top_k
    sparse_k = sparse_top_k or settings.sparse_top_k
    fused_k = fused_top_k or settings.fused_top_k
    rerank_k = rerank_top_k or settings.rerank_top_k

    # 稠密：HyDE 假设段落优先（v2 6.4），无 HyDE 用原始查询
    dense_query = hyde_text or query
    dense_hits: list[dict] = []
    try:
        vec = embeddings.embed_one(dense_query)
        dense_hits = vectorstore.search(bank_id, vec, top_k=dense_k, doc_id=document_id)
    except embeddings.EmbeddingError:
        dense_hits = []

    # 稀疏：BM25，始终用原始查询
    sparse_hits: list[tuple[str, float]] = []
    try:
        sparse_hits = fts.search(bank_id, query, top_k=sparse_k, document_id=document_id)
    except Exception:
        sparse_hits = []

    fused = _rrf_fuse(dense_hits, sparse_hits)[:fused_k]
    chunk_map = _fetch_chunks([f["chunk_id"] for f in fused])

    reranked: list[dict] = []
    if fused:
        ordered = [chunk_map.get(f["chunk_id"]) for f in fused]
        ordered = [c for c in ordered if c]
        try:
            rr = rerank.rerank(query, [c["text"] for c in ordered], top_n=rerank_k)
            for item in rr:
                c = dict(ordered[item["index"]])
                c["score"] = item["score"]
                reranked.append(c)
        except rerank.RerankError:
            reranked = [dict(c) for c in ordered[:rerank_k]]

    return {
        "hyde": hyde_text,
        "dense": dense_hits,
        "sparse": [{"chunk_id": cid, "bm25": s, **chunk_map.get(cid, {})} for cid, s in sparse_hits],
        "fused": [{**chunk_map.get(f["chunk_id"], {}), "rrf": f["rrf"]} for f in fused if f["chunk_id"] in chunk_map],
        "reranked": reranked,
    }


def retrieve_for_generation(bank_id: str, query: str, document_id: str | None, hyde_text: str | None) -> list[dict]:
    """出题用入口：返回重排后的最终参考片段。"""
    result = hybrid_retrieve(bank_id, query, document_id=document_id, hyde_text=hyde_text)
    return result["reranked"]
