"""健康检查与 RAG 单元测试。"""
from app.services.rag import retrieval


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["database"] == "ok"
    assert data["redis"] == "ok"
    assert data["chroma"] == "ok"
    assert data["mineru_default_token"] is True
    assert data["siliconflow_embedding"].startswith("ok")
    assert data["siliconflow_rerank"] == "ok"


def test_rrf_prefers_chunks_in_both_lists():
    dense = [{"chunk_id": "a"}, {"chunk_id": "b"}, {"chunk_id": "c"}]
    sparse = [("c", 1.0), ("b", 2.0), ("d", 3.0)]
    fused = retrieval._rrf_fuse(dense, sparse)
    ids = [item["chunk_id"] for item in fused]
    # c 在稠密第 3、稀疏第 1，b 在稠密第 2、稀疏第 2，两者都应排在只出现一次的前面
    assert set(ids[:2]) == {"b", "c"}
    assert ids[0] in ("b", "c")
    assert "a" in ids and "d" in ids


def test_rrf_empty():
    assert retrieval._rrf_fuse([], []) == []


def test_jieba_tokenize_chinese():
    from app.services.rag.tokenizer import terms, tokenize

    tokens = tokenize("隐函数求导的基本方法")
    assert " " in tokens
    ts = terms("隐函数求导")
    assert any("求导" in t or "隐函数" in t for t in ts)
