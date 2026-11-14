"""真实入库与检索路由的发布边界回归；仅使用临时存储和假模型。"""

import sqlite3

import chromadb
import pytest
from chromadb.config import Settings
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.models import Document, DocumentChunk
from app.services.rag import embeddings, fts, rerank, retrieval, vectorstore
from conftest import create_bank, upload_markdown


@pytest.fixture()
def retrieval_store(monkeypatch, tmp_path):
    """隔离原生向量存储，SQL/FTS 沿用 conftest 的临时数据库。"""
    native = chromadb.PersistentClient(
        path=str(tmp_path / "retrieval-chroma"),
        settings=Settings(anonymized_telemetry=False),
    )
    monkeypatch.setattr(vectorstore, "_client", native)


@pytest.mark.parametrize("mode", ["dense", "sparse", "hybrid", "hybrid_rerank"])
@pytest.mark.parametrize("document_scope", [False, True], ids=["bank", "document"])
def test_ingestion_only_publishes_ready_chunks(
    client, teacher, db, monkeypatch, retrieval_store, mode, document_scope,
):
    """SQL/FTS 已提交时仍隐藏 processing/failed 切片，ready 对照始终可见。"""
    bank_id = create_bank(client, teacher)["id"]
    ready_id = upload_markdown(client, teacher, bank_id, "ready.md")["document_id"]
    ready_chunks = {
        row.id for row in db.query(DocumentChunk).filter_by(document_id=ready_id).all()
    }
    observations = []

    def search(document_id=None):
        response = client.post(
            f"/api/banks/{bank_id}/search", headers=teacher,
            json={"query": "导数", "mode": mode, "top_k": 50, "document_id": document_id},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        groups = ("results",) if mode in ("dense", "sparse") else (
            "dense", "sparse", "fused", "reranked",
        )
        return {name: {hit["chunk_id"] for hit in payload[name]} for name in groups}

    def fail_after_sql_commit(contents):
        # 在真实 embed 调用边界观察已提交的 SQL、FTS 与 processing 状态。
        with type(db)(bind=db.get_bind()) as observer:
            pending = observer.query(Document).filter_by(bank_id=bank_id, status="embedding").one()
            chunks = observer.query(DocumentChunk).filter_by(document_id=pending.id).all()
            assert chunks and contents
            assert observer.execute(text(
                "SELECT count(*) FROM document_chunks_fts WHERE document_id=:id"
            ), {"id": pending.id}).scalar_one() == len(chunks)
            # 模拟中断留下的向量；可见性必须依赖 SQL ready 状态而非向量存在。
            collection = vectorstore.get_collection(bank_id)
            for chunk in chunks:
                collection.add(
                    ids=[chunk.id], documents=[chunk.text],
                    embeddings=[embeddings.embed_one(chunk.text)],
                    metadatas=[{"chunk_id": chunk.id, "doc_id": pending.id,
                                "doc_name": pending.name, "chunk_index": chunk.chunk_index}],
                )
            observations.append(search(pending.id if document_scope else None))
        raise embeddings.EmbeddingError("假嵌入失败", "server")

    monkeypatch.setattr(embeddings, "embed_texts", fail_after_sql_commit)
    failed_id = upload_markdown(client, teacher, bank_id, "failed.md")["document_id"]
    db.expire_all()
    assert db.get(Document, failed_id).status == "failed"
    failed_chunks = {
        row.id for row in db.query(DocumentChunk).filter_by(document_id=failed_id).all()
    }
    assert failed_chunks, "失败切片应保留用于诊断与重建"
    assert db.execute(text(
        "SELECT count(*) FROM document_chunks_fts WHERE document_id=:id"
    ), {"id": failed_id}).scalar_one() == len(failed_chunks)
    observations.append(search(failed_id if document_scope else None))
    assert len(observations) == 2, "必须观察 embedding 期间和 failed 之后的真实路由"
    for groups in observations:
        for name, chunk_ids in groups.items():
            assert not chunk_ids & failed_chunks, f"{mode}/{name} 泄漏未发布切片"
        if document_scope:
            assert all(not ids for ids in groups.values())
        else:
            assert groups["results" if mode in ("dense", "sparse") else "fused"] & ready_chunks
    assert search(ready_id)["results" if mode in ("dense", "sparse") else "fused"] & ready_chunks


@pytest.mark.parametrize("mode", ["dense", "sparse", "hybrid", "hybrid_rerank"])
def test_search_backfills_ready_hits_past_unpublished_and_orphan_candidates(
    client, teacher, db, monkeypatch, retrieval_store, mode,
):
    """靠前的未发布切片和残留索引不能挤掉 ready 召回名额。"""
    monkeypatch.setattr(embeddings, "embed_texts", lambda contents: [[0.0, 1.0] for _ in contents])
    monkeypatch.setattr(embeddings, "embed_one", lambda content: [1.0, 0.0])
    bank_id = create_bank(client, teacher)["id"]
    ready_id = upload_markdown(client, teacher, bank_id)["document_id"]
    ready = db.get(Document, ready_id)
    ready_chunks = {row.id for row in db.query(DocumentChunk).filter_by(document_id=ready_id)}
    collection = vectorstore.get_collection(bank_id)
    hidden_ids = []
    for status in ("uploaded", "parsing", "ocr", "chunking", "embedding", "failed"):
        document_id = f"hidden_{status}"
        db.add(Document(
            id=document_id, bank_id=bank_id, name=f"{status}.md", format="MD", size_bytes=1,
            storage_path="unused-test-path", uploader_id=ready.uploader_id, status=status,
        ))
        db.flush()
        for index in range(4):
            chunk_id = f"{document_id}_{index}"
            hidden_ids.append(chunk_id)
            db.add(DocumentChunk(
                id=chunk_id, bank_id=bank_id, document_id=document_id, chunk_index=index,
                text="导数", tokens="导数", char_count=2,
            ))
            fts.insert_rows(db, [{"chunk_id": chunk_id, "bank_id": bank_id,
                                  "document_id": document_id, "tokens": "导数"}])
            collection.add(
                ids=[chunk_id], documents=["导数"], embeddings=[[1.0, 0.0]],
                metadatas=[{"chunk_id": chunk_id, "doc_id": document_id}],
            )
    for index, document_id in enumerate((ready_id, "deleted-document")):
        chunk_id = f"orphan_{index}"
        hidden_ids.append(chunk_id)
        collection.add(
            ids=[chunk_id], documents=["导数"], embeddings=[[1.0, 0.0]],
            metadatas=[{"chunk_id": chunk_id, "doc_id": document_id}],
        )
        fts.insert_rows(db, [{"chunk_id": chunk_id, "bank_id": bank_id,
                              "document_id": document_id, "tokens": "导数"}])
    db.commit()
    # 明确证明最靠前的候选都是无效索引，不能靠“碰巧先召回 ready”通过。
    assert vectorstore.search(bank_id, [1.0, 0.0], 1)[0]["chunk_id"] in hidden_ids
    response = client.post(
        f"/api/banks/{bank_id}/search", headers=teacher,
        json={"query": "导数", "mode": mode, "top_k": 1},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    groups = ("results",) if mode in ("dense", "sparse") else (
        "dense", "sparse", "fused", "reranked",
    )
    for name in groups:
        if mode == "hybrid" and name == "reranked":
            assert payload[name] == []
            continue
        assert payload[name], f"{mode}/{name} 丢失 ready 结果"
        assert {hit["chunk_id"] for hit in payload[name]} <= ready_chunks


@pytest.mark.parametrize("mode", ["dense", "sparse", "hybrid", "hybrid_rerank"])
@pytest.mark.parametrize("document_scope", [False, True], ids=["bank", "document"])
@pytest.mark.parametrize("pollute_index", [False, True], ids=["clean-index", "polluted-index"])
def test_search_keeps_ready_results_within_sql_scope(
    client, teacher, db, monkeypatch, retrieval_store,
    mode: str, document_scope: bool, pollute_index: bool,
) -> None:
    """其他 ready 文档及伪造索引归属不能越界，也不能挤掉范围内的 top_k。"""
    monkeypatch.setattr(embeddings, "embed_texts", lambda contents: [[0.0, 1.0] for _ in contents])
    monkeypatch.setattr(embeddings, "embed_one", lambda content: [1.0, 0.0])
    bank_id = create_bank(client, teacher, "目标题库")["id"]
    other_bank_id = create_bank(client, teacher, "其他题库")["id"]
    target_id = upload_markdown(client, teacher, bank_id, "target.md")["document_id"]
    sibling_id = upload_markdown(client, teacher, bank_id, "sibling.md")["document_id"]
    foreign_id = upload_markdown(client, teacher, other_bank_id, "foreign.md")["document_id"]
    chunks_by_document = {}
    for document_id, owner_bank, count, vector, tokens in (
        (target_id, bank_id, 3, [0.0, 1.0], "导数 " + "背景 " * 100),
        (sibling_id, bank_id, 24, [0.8, 0.6], "导数 " + "背景 " * 25),
        (foreign_id, other_bank_id, 24, [1.0, 0.0], "导数 " * 16),
    ):
        document = db.get(Document, document_id)
        assert document.status == "ready"
        chunks = db.query(DocumentChunk).filter_by(document_id=document_id).all()
        next_index = max(chunk.chunk_index for chunk in chunks) + 1
        extra_chunks = [
            DocumentChunk(
                id=f"{document_id}_scope_{index}", bank_id=owner_bank,
                document_id=document_id, chunk_index=next_index + index,
                text=tokens.strip(), tokens=tokens.strip(), char_count=len(tokens.strip()),
            )
            for index in range(max(0, count - len(chunks)))
        ]
        db.add_all(extra_chunks)
        fts.insert_rows(db, [
            {"chunk_id": chunk.id, "bank_id": owner_bank,
             "document_id": document_id, "tokens": chunk.tokens}
            for chunk in extra_chunks
        ])
        if extra_chunks:
            vectorstore.get_collection(owner_bank).add(
                ids=[chunk.id for chunk in extra_chunks],
                documents=[chunk.text for chunk in extra_chunks],
                embeddings=[vector for _ in extra_chunks],
                metadatas=[{"chunk_id": chunk.id, "doc_id": document_id}
                           for chunk in extra_chunks],
            )
        chunks_by_document[document_id] = chunks + extra_chunks
    db.commit()
    target_chunks = {chunk.id for chunk in chunks_by_document[target_id]}
    sibling_chunks = {chunk.id for chunk in chunks_by_document[sibling_id]}
    allowed_chunks = target_chunks if document_scope else target_chunks | sibling_chunks
    scoped_document = target_id if document_scope else None

    if pollute_index:
        # SQL 也可能留下错误的冗余 bank_id；文档与切片的两侧归属都必须校验。
        failed_id = "scope_failed_document"
        db.add(Document(
            id=failed_id, bank_id=bank_id, name="failed.md", format="MD", size_bytes=1,
            storage_path="unused-test-path", status="failed",
            uploader_id=db.get(Document, target_id).uploader_id,
        ))
        db.flush()
        invalid_chunks = [
            DocumentChunk(
                id=chunk_id, bank_id=chunk_bank, document_id=document_id,
                chunk_index=1000, text="导数 " * 16, tokens="导数 " * 16, char_count=48,
            )
            for chunk_id, chunk_bank, document_id in (
                ("scope_wrong_document_bank", bank_id, foreign_id),
                ("scope_wrong_chunk_bank", other_bank_id, target_id),
                ("scope_failed_chunk", bank_id, failed_id),
            )
        ]
        db.add_all(invalid_chunks)
        candidates = [
            *chunks_by_document[foreign_id], *chunks_by_document[sibling_id], *invalid_chunks,
        ]
        # 同库跨文档和跨库切片都伪装成目标文档，绕过 Chroma 自身的 where 过滤。
        vectorstore.get_collection(bank_id).upsert(
            ids=[chunk.id for chunk in candidates] + ["scope_orphan"],
            documents=[chunk.text for chunk in candidates] + ["导数 " * 16],
            embeddings=[
                [0.8, 0.6] if chunk.id in sibling_chunks else [1.0, 0.0]
                for chunk in candidates
            ] + [[1.0, 0.0]],
            metadatas=[
                {"chunk_id": chunk_id, "bank_id": bank_id, "doc_id": target_id}
                for chunk_id in [chunk.id for chunk in candidates] + ["scope_orphan"]
            ],
        )
        fts.insert_rows(db, [
            {"chunk_id": chunk.id, "bank_id": bank_id,
             "document_id": target_id, "tokens": chunk.tokens}
            for chunk in candidates
        ] + [{"chunk_id": "scope_orphan", "bank_id": bank_id,
              "document_id": target_id, "tokens": "导数 " * 16}])
        db.commit()
        # 20 超过本例 top_k，也覆盖 hybrid 默认候选窗口；证明补召回确实受到攻击。
        raw_dense = vectorstore.search(bank_id, [1.0, 0.0], 20, doc_id=scoped_document)
        assert len(raw_dense) == 20
        assert all(hit["chunk_id"] not in allowed_chunks for hit in raw_dense)
        raw_sparse = db.execute(text(
            "SELECT chunk_id FROM document_chunks_fts "
            "WHERE document_chunks_fts MATCH :query AND bank_id = :bank "
            "AND document_id = :document ORDER BY bm25(document_chunks_fts) LIMIT 20"
        ), {"query": '"导数"', "bank": bank_id, "document": target_id}).scalars().all()
        assert len(raw_sparse) == 20
        assert not set(raw_sparse) & allowed_chunks

    top_k = 2
    response = client.post(
        f"/api/banks/{bank_id}/search", headers=teacher,
        json={"query": "导数", "mode": mode, "top_k": top_k,
              "document_id": scoped_document},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    groups = ("results",) if mode in ("dense", "sparse") else (
        "dense", "sparse", "fused", "reranked",
    )
    for name in groups:
        hits = payload[name]
        if mode == "hybrid" and name == "reranked":
            assert hits == []
            continue
        chunk_ids = {hit["chunk_id"] for hit in hits}
        assert chunk_ids <= allowed_chunks, f"{mode}/{name} 泄漏范围外或非 ready 切片"
        assert len(chunk_ids) == len(hits), f"{mode}/{name} 重复候选挤占名额"
        assert len(hits) >= top_k, f"{mode}/{name} 越界候选挤掉有效 top_k"
        if name in ("results", "reranked"):
            assert len(hits) == top_k


@pytest.mark.parametrize("mode", ["hybrid", "hybrid_rerank", "generation"])
def test_hybrid_mode_controls_rerank_calls(
    client, teacher, monkeypatch, retrieval_store, mode,
):
    """普通 hybrid 零重排；重排路由与默认出题入口各调用一次假重排。"""
    bank_id = create_bank(client, teacher)["id"]
    upload_markdown(client, teacher, bank_id)
    calls = []
    fake_rerank = rerank.rerank

    def counted_rerank(query, documents, top_n=None):
        calls.append((query, documents, top_n))
        return fake_rerank(query, documents, top_n)

    monkeypatch.setattr(rerank, "rerank", counted_rerank)
    if mode == "generation":
        assert retrieval.retrieve_for_generation(bank_id, "导数", None, None)
        assert len(calls) == 1
        return
    response = client.post(
        f"/api/banks/{bank_id}/search", headers=teacher,
        json={"query": "导数", "mode": mode, "top_k": 1},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["fused"]
    if mode == "hybrid":
        assert calls == [], "普通 hybrid 不得调用后丢弃重排结果"
        assert result["reranked"] == []
    else:
        assert len(calls) == 1
        assert calls[0][2] == 1
        assert len(result["reranked"]) == 1


@pytest.mark.parametrize("document_scope", [False, True], ids=["bank", "document"])
def test_dense_backfill_respects_sqlite_parameter_limit(
    client, teacher, db, monkeypatch, retrieval_store, document_scope,
):
    """大量孤立向量在前时，受 SQLite 变量上限约束仍能召回后排 ready 切片。"""
    bank_id = create_bank(client, teacher)["id"]
    ready_id = upload_markdown(client, teacher, bank_id)["document_id"]
    ready_chunk = db.query(DocumentChunk).filter_by(document_id=ready_id).first()
    candidates = [{"chunk_id": f"orphan_limit_{index}"} for index in range(1200)]
    candidates.append({"chunk_id": ready_chunk.id})
    monkeypatch.setattr(
        vectorstore, "search", lambda bank_id, vector, top_k, doc_id=None: candidates[:top_k],
    )
    # 仅改变隔离测试连接；Session 关闭后保留外部连接，最后恢复原始上限。
    with db.get_bind().connect() as connection:
        driver = connection.connection.driver_connection
        previous = driver.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 999)
        monkeypatch.setattr(retrieval, "SessionLocal", sessionmaker(bind=connection))
        try:
            hits = retrieval.dense_search(
                bank_id, [1.0, 0.0], top_k=20,
                document_id=ready_id if document_scope else None,
            )
        finally:
            driver.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, previous)
    assert [hit["chunk_id"] for hit in hits] == [ready_chunk.id]
