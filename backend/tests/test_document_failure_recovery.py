"""隔离验证资料失败恢复、模型错误边界和原生向量持久化。"""

from types import SimpleNamespace
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event

import chromadb
import httpx
import pymupdf
import pytest
from chromadb.config import Settings
from chromadb.errors import InternalError, NotFoundError
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from app.db import Base, FTS_CREATE_SQL
from app.deps import resolve_bank_access
from app.errors import AppError
from app.main import app as fastapi_app
from app.models import Bank, BankMember, Document, DocumentChunk, RagSetting, User
from app.services import banks, cache, documents, knowledge_simplify, mineru, rag_settings
from app.services.rag import embeddings, vectorstore
from app.services.rag.chunking import Chunk
from app.services.rag_runtime import RuntimeConfig, RuntimeSnapshot, use_snapshot
from app.services import rag_runtime
from conftest import create_bank, upload_markdown

_REAL_EMBED_TEXTS = embeddings.embed_texts
_HTTP_CLIENT = httpx.Client
_FAKE_PRIVATE = "https://fake-private.example.test/v1"
_FAKE_SECRET = "fake-embedding-key-do-not-log"


@pytest.fixture()
def snapshot():
    """固定假模型配置，向量单元回归无需访问数据库。"""
    with use_snapshot(RuntimeSnapshot(RuntimeConfig(
        embedding_base_url=_FAKE_PRIVATE, embedding_api_key=_FAKE_SECRET,
    ))):
        yield


def _mock_embedding_http(monkeypatch, handler):
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: _HTTP_CLIENT(
        transport=transport, **kwargs,
    ))
    monkeypatch.setattr(embeddings, "embed_texts", _REAL_EMBED_TEXTS)


def test_vector_access_failure_is_not_an_empty_search(monkeypatch, caplog):
    """存储故障必须阻止检索，且诊断不得包含底层路径或凭据。"""
    def fail(**kwargs):
        raise InternalError("database (code: 14) /private/fake-store fake-key-do-not-log")

    monkeypatch.setattr(vectorstore, "_client", SimpleNamespace(get_collection=fail))
    with use_snapshot(RuntimeSnapshot(RuntimeConfig())):
        with pytest.raises(RuntimeError) as error:
            vectorstore.search("bank_failure", [1.0, 0.0], 1)
    assert type(error.value).__name__ == "VectorStoreError"
    assert error.value.operation == "access"
    assert error.value.native_code == 14
    assert str(error.value).startswith("向量集合访问失败")
    assert "无法打开向量数据库，请联系管理员检查存储路径与临时目录权限（code 14）" in str(error.value)
    assert "14" in caplog.text
    assert "fake-key-do-not-log" not in str(error.value) + caplog.text
    assert "/private/fake-store" not in str(error.value) + caplog.text


@pytest.mark.parametrize("create", [False, True])
def test_vector_initialization_failure_is_classified(monkeypatch, snapshot, create):
    def fail(**kwargs):
        raise InternalError("database (code: 14) fake-private-path")

    monkeypatch.setattr(vectorstore, "_client", None)
    monkeypatch.setattr(chromadb, "PersistentClient", fail)
    with pytest.raises(vectorstore.VectorStoreError) as error:
        vectorstore.get_collection("bank_failure", create=create)
    assert error.value.operation == "init"
    assert error.value.native_code == 14
    assert str(error.value).startswith("向量存储初始化失败")
    assert "存储路径与临时目录权限（code 14）" in str(error.value)


def test_only_native_not_found_is_idempotent(monkeypatch, snapshot):
    def missing(**kwargs):
        raise NotFoundError("collection missing")

    monkeypatch.setattr(vectorstore, "_client", SimpleNamespace(
        get_collection=missing, get_or_create_collection=missing, delete_collection=missing,
    ))
    assert vectorstore.search("bank_missing", [1.0, 0.0], 1) == []
    assert vectorstore.count_question_chunks("bank_missing", "doc") == []
    vectorstore.delete_document_chunks("bank_missing", "doc")
    vectorstore.delete_bank_collection("bank_missing")
    with pytest.raises(vectorstore.VectorStoreError):
        vectorstore.get_collection("bank_missing")


@pytest.mark.parametrize("operation", ["query", "write", "read", "delete", "bank_delete"])
def test_vector_operations_propagate_failures(monkeypatch, snapshot, operation):
    def fail(**kwargs):
        raise InternalError("fake storage failure")

    collection = SimpleNamespace(query=fail, add=fail, get=fail, delete=fail)
    monkeypatch.setattr(vectorstore, "_client", SimpleNamespace(
        get_collection=lambda **kwargs: collection,
        get_or_create_collection=lambda **kwargs: collection, delete_collection=fail,
    ))
    with pytest.raises(vectorstore.VectorStoreError) as error:
        if operation == "query":
            vectorstore.search("bank_failure", [1.0, 0.0], 1)
        elif operation == "write":
            vectorstore.add_chunks("bank_failure", "doc", "name", [Chunk("text", {})], [[1.0]])
        elif operation == "read":
            vectorstore.count_question_chunks("bank_failure", "doc")
        elif operation == "delete":
            vectorstore.delete_document_chunks("bank_failure", "doc")
        else:
            vectorstore.delete_bank_collection("bank_failure")
    assert error.value.operation == ("delete" if operation == "bank_delete" else operation)


def test_native_chroma_persists_queries_and_deletes_fake_vectors(monkeypatch, tmp_path, snapshot):
    """真实原生客户端只读写临时目录；不打桩、不跳过原生故障。"""
    store_path = tmp_path / "native-chroma"
    store_path.mkdir()
    native = chromadb.PersistentClient(path=str(store_path),
                                      settings=Settings(anonymized_telemetry=False))
    monkeypatch.setattr(vectorstore, "_client", native)
    vectorstore.add_chunks("bank_native", "doc_native", "fake.md", [
        Chunk("第一题 导数的定义", {"chunk_type": "question", "section": "导数"}),
        Chunk("另一份文档", {}),
    ], [[1.0, 0.0], [0.0, 1.0]], chunk_ids=["chunk_one", "chunk_two"])
    reopened = chromadb.PersistentClient(
        path=str(tmp_path / "native-chroma"), settings=Settings(anonymized_telemetry=False),
    )
    monkeypatch.setattr(vectorstore, "_client", reopened)
    assert vectorstore.search("bank_native", [1.0, 0.0], 1)[0]["chunk_id"] == "chunk_one"
    assert vectorstore.count_question_chunks("bank_native", "doc_native") == [
        {"section": "导数", "text": "第一题 导数的定义"},
    ]
    vectorstore.delete_document_chunks("bank_native", "doc_native")
    assert vectorstore.search("bank_native", [1.0, 0.0], 1) == []
    vectorstore.delete_bank_collection("bank_native")
    assert vectorstore.get_collection("bank_native", create=False) is None


@pytest.mark.parametrize(("failure", "category", "message"), [
    (401, "authentication", "鉴权"), (403, "authentication", "鉴权"),
    (429, "rate_limit", "限流"), (503, "server", "服务端"),
    (404, "request", "请求"), ("timeout", "timeout", "超时"),
    ("connection", "connection", "连接"),
])
def test_embedding_errors_are_classified_and_redacted(
    monkeypatch, snapshot, caplog, failure, category, message,
):
    def respond(request):
        if failure == "timeout":
            raise httpx.ReadTimeout(f"{_FAKE_PRIVATE} {_FAKE_SECRET}", request=request)
        if failure == "connection":
            raise httpx.ConnectError(f"{_FAKE_PRIVATE} {_FAKE_SECRET}", request=request)
        return httpx.Response(failure, json={"error": f"{_FAKE_PRIVATE} {_FAKE_SECRET}"})

    _mock_embedding_http(monkeypatch, respond)
    with pytest.raises(embeddings.EmbeddingError) as error:
        embeddings.embed_texts(["假文档正文不可输出"])
    assert error.value.category == category
    assert message in str(error.value)
    diagnostic = str(error.value) + caplog.text
    assert category in caplog.text
    for private in (_FAKE_PRIVATE, _FAKE_SECRET, "假文档正文不可输出"):
        assert private not in diagnostic


@pytest.mark.parametrize("payload", [
    None, {"data": {}}, {"data": [None]},
    {"data": [{"index": True, "embedding": [1.0]}]},
    {"data": [{"index": 0, "embedding": [True]}]},
    {"data": [{"index": 0, "embedding": ["1.0"]}]},
    {"data": [{"index": 0, "embedding": []}]},
    {"data": [{"index": 0, "embedding": [float("inf")]}]},
    {"data": [{"index": 1, "embedding": [1.0]}]},
])
def test_invalid_embedding_response_is_classified(monkeypatch, snapshot, payload):
    _mock_embedding_http(monkeypatch, lambda request: httpx.Response(
        200, content=json.dumps(payload).encode(),
    ))
    with pytest.raises(embeddings.EmbeddingError) as error:
        embeddings.embed_texts(["假输入"])
    assert error.value.category == "invalid_response"


@pytest.mark.parametrize("change_dimension", [False, True])
def test_embedding_batches_validate_order_and_dimension(monkeypatch, snapshot, change_dimension):
    def respond(request):
        batch = json.loads(request.content)["input"]
        return httpx.Response(200, json={"data": [
            {"index": index, "embedding": [float(text), 1.0] + (
                [0.0] if change_dimension and len(batch) == 1 else []
            )} for index, text in reversed(list(enumerate(batch)))
        ]})

    _mock_embedding_http(monkeypatch, respond)
    if change_dimension:
        with pytest.raises(embeddings.EmbeddingError) as error:
            embeddings.embed_texts([str(i) for i in range(33)])
        assert error.value.category == "invalid_response"
    else:
        assert embeddings.embed_texts([str(i) for i in range(33)]) == [
            [float(i), 1.0] for i in range(33)
        ]


def test_missing_embedding_credentials_do_not_request_provider(monkeypatch, snapshot):
    def unexpected(request):
        pytest.fail("缺少假凭据时不应发送请求")

    _mock_embedding_http(monkeypatch, unexpected)
    with use_snapshot(RuntimeSnapshot(RuntimeConfig())):
        with pytest.raises(embeddings.EmbeddingError) as error:
            embeddings.embed_texts(["假输入"])
    assert error.value.category == "authentication"


@pytest.fixture()
def document_store(monkeypatch):
    """仅为状态机用例替换外部存储边界，原生用例不使用此夹具。"""
    collection = SimpleNamespace(delete=lambda **kwargs: None, add=lambda **kwargs: None)
    client = SimpleNamespace(
        get_collection=lambda **kwargs: collection,
        get_or_create_collection=lambda **kwargs: collection, heartbeat=lambda: 1,
    )
    monkeypatch.setattr(vectorstore, "_client", client)
    return collection


def _upload_scan(client, teacher, bank_id):
    with pymupdf.open() as pdf:
        pdf.new_page()
        content = pdf.tobytes()
    response = client.post(
        f"/api/banks/{bank_id}/documents", headers=teacher,
        files={"file": ("fake-scan.pdf", content, "application/pdf")},
    )
    assert response.status_code == 202
    return f"/api/banks/{bank_id}/documents/{response.json()['document_id']}"


def _successful_ocr(monkeypatch):
    def extract(token, file_path, result_dir, on_progress=None):
        result_dir.mkdir(parents=True, exist_ok=True)
        (result_dir / "full.md").write_text("# 假 OCR\n\n导数的定义。", encoding="utf-8")
        return "# 假 OCR\n\n导数的定义。", result_dir

    monkeypatch.setattr(mineru, "extract_pdf", extract)
    monkeypatch.setattr(knowledge_simplify, "build_simplified_markdown", lambda *a, **k: (
        "# 《假教材》知识点简化版\n\n## 导数\n\n导数是差商的极限。", {},
    ))


@pytest.mark.parametrize("error_type", [mineru.MinerUError, RuntimeError])
def test_ocr_failure_updates_both_statuses_and_can_recover(
    client, teacher, db, monkeypatch, document_store, error_type,
):
    def fail(*args):
        raise error_type("fake OCR failure")

    monkeypatch.setattr(mineru, "extract_pdf", fail)
    bank = create_bank(client, teacher)
    url = _upload_scan(client, teacher, bank["id"])
    failed = client.get(url, headers=teacher).json()
    assert failed["status"] == "failed"
    assert failed["ocr_status"] == "failed"
    doc = db.get(Document, failed["id"])
    assert doc.ocr_error
    _successful_ocr(monkeypatch)
    assert client.post(f"{url}/reprocess", headers=teacher).status_code == 202
    recovered = client.get(url, headers=teacher).json()
    assert recovered["status"] == "ready"
    assert recovered["ocr_status"] == "done"
    db.refresh(doc)
    assert doc.ocr_error is None


@pytest.mark.parametrize(("failure", "expected"), [
    ("generic", "Token"), ("unexpected", "Token"),
    ("authentication", "权限"), ("timeout", "超时"),
    ("connection", "连接"), ("response", "返回异常"),
])
def test_ocr_failure_redacts_status_cache_logs_and_notifications(
    client, teacher, db, monkeypatch, document_store, isolated_redis, caplog,
    failure, expected,
):
    """外部异常可携带整份 OCR 响应；所有展示和持久化出口只保留分类文案。"""
    private = f"Bearer {_FAKE_SECRET} {_FAKE_PRIVATE}?token=fake-token&signature=fake-signature"

    def fail(*args):
        if failure in ("authentication", "response"):
            response = httpx.Response(
                403 if failure == "authentication" else 502,
                request=httpx.Request("POST", _FAKE_PRIVATE), text=private,
            )
            cause = httpx.HTTPStatusError(private, request=response.request, response=response)
            raise mineru.MinerUError(private) from cause
        if failure == "timeout":
            raise httpx.ReadTimeout(private)
        if failure == "connection":
            raise httpx.ConnectError(private)
        if failure == "unexpected":
            raise RuntimeError(private)
        raise mineru.MinerUError(private)

    monkeypatch.setattr(mineru, "extract_pdf", fail)
    url = _upload_scan(client, teacher, create_bank(client, teacher)["id"])
    response = client.get(url, headers=teacher)
    failed = response.json()
    assert failed["status"] == "failed"
    assert failed["ocr_status"] == "failed"
    doc = db.get(Document, failed["id"])
    notices = client.get("/api/notifications", headers=teacher)
    assert notices.status_code == 200
    assert notices.json()["items"]
    cached = isolated_redis.hgetall(cache.PREFIX_INGEST_TASK.format(document_id=doc.id))
    exposed = response.text + doc.ocr_error + notices.text + json.dumps(cached) + caplog.text
    for secret in (_FAKE_SECRET, _FAKE_PRIVATE, "Bearer", "fake-token", "fake-signature"):
        assert secret not in exposed
    assert expected in failed["error_message"]
    assert expected in doc.ocr_error
    assert "code=OCR_" in caplog.text


def test_embedding_failure_keeps_completed_ocr(client, teacher, monkeypatch, document_store):
    _successful_ocr(monkeypatch)
    _mock_embedding_http(monkeypatch, lambda request: httpx.Response(429, json={"error": "fake"}))
    bank = create_bank(client, teacher)
    with use_snapshot(RuntimeSnapshot(RuntimeConfig(embedding_api_key=_FAKE_SECRET))):
        url = _upload_scan(client, teacher, bank["id"])
    failed = client.get(url, headers=teacher).json()
    assert failed["status"] == "failed"
    assert failed["ocr_status"] == "done"
    assert "限流" in failed["error_message"]


@pytest.mark.parametrize("failure", ["service", "content", "parser"])
def test_post_ocr_failure_redacts_details_and_keeps_completed_ocr(
    client, teacher, db, monkeypatch, document_store, isolated_redis, caplog, failure,
):
    """简化服务失败、内容回退及后续解析兜底不转存上游异常正文。"""
    _successful_ocr(monkeypatch)
    private = f"Bearer {_FAKE_SECRET} {_FAKE_PRIVATE}?token=fake-token&signature=fake-signature"

    def fail(*args, **kwargs):
        if failure == "service":
            raise knowledge_simplify.SimplifyServiceError(private)
        raise ValueError(private)

    if failure == "parser":
        monkeypatch.setattr(documents, "get_parser", lambda *args: SimpleNamespace(parse=fail))
    else:
        monkeypatch.setattr(knowledge_simplify, "build_simplified_markdown", fail)
    url = _upload_scan(client, teacher, create_bank(client, teacher)["id"])
    response = client.get(url, headers=teacher)
    result = response.json()
    assert result["status"] == ("ready" if failure == "content" else "failed")
    assert result["ocr_status"] == "done"
    doc = db.get(Document, result["id"])
    assert doc.ocr_error is None
    notices = client.get("/api/notifications", headers=teacher)
    assert notices.status_code == 200
    assert notices.json()["items"]
    cached = isolated_redis.hgetall(cache.PREFIX_INGEST_TASK.format(document_id=doc.id))
    exposed = response.text + notices.text + json.dumps(cached) + caplog.text
    for secret in (_FAKE_SECRET, _FAKE_PRIVATE, "Bearer", "fake-token", "fake-signature"):
        assert secret not in exposed
    if failure == "service":
        assert "简化" in result["error_message"]
        assert "重新解析" in result["error_message"]
    elif failure == "parser":
        assert "文件格式" in result["error_message"]
    else:
        assert result["error_message"] is None


def test_reprocess_clears_stale_database_and_cache_state(
    client, teacher, db, monkeypatch, document_store, isolated_redis,
):
    bank = create_bank(client, teacher)
    uploaded = upload_markdown(client, teacher, bank["id"])
    doc = db.get(Document, uploaded["document_id"])
    doc.status = "failed"
    doc.progress = 100
    doc.chunk_count = 23
    doc.ocr_status = "failed"
    doc.ocr_error = "last OCR error"
    doc.error_message = "last error"
    doc.ocr_task_id = "last-task"
    doc.ocr_result_path = "last-path"
    doc.text_source = "ocr"
    doc.is_scanned = True
    doc.page_count = 5
    db.commit()
    monkeypatch.setattr(BackgroundTasks, "add_task", lambda *args, **kwargs: None)
    url = f"/api/banks/{bank['id']}/documents/{doc.id}"
    response = client.post(f"{url}/reprocess", headers=teacher)
    assert response.status_code == 202
    queued = client.get(url, headers=teacher).json()
    assert queued["progress"] == 0
    assert queued["chunk_count"] == 0
    assert queued["ocr_status"] is None
    assert queued["error_message"] is None
    db.refresh(doc)
    assert doc.ocr_error is None
    assert doc.ocr_task_id is None
    assert doc.ocr_result_path is None
    assert doc.text_source is None
    assert doc.page_count is None
    assert doc.is_scanned is False
    cached = isolated_redis.hgetall(cache.PREFIX_INGEST_TASK.format(document_id=doc.id))
    assert cached["status"] == "uploaded"
    assert cached["progress"] == "0"


@pytest.mark.parametrize("method", ["hset", "expire"])
@pytest.mark.parametrize("initial_status", ["ready", "failed"])
def test_reprocess_cache_outage_still_schedules_ingestion_and_allows_retry(
    client, teacher, db, monkeypatch, document_store, isolated_redis, caplog,
    method, initial_status,
):
    """Redis 断连不能在 SQL 已排队后阻止调度，整个请求期间不重启 lifespan。"""
    bank_id = create_bank(client, teacher)["id"]
    doc_id = upload_markdown(client, teacher, bank_id)["document_id"]
    url = f"/api/banks/{bank_id}/documents/{doc_id}"
    doc = db.get(Document, doc_id)
    doc.status = initial_status
    db.commit()
    original = getattr(isolated_redis, method)

    def fail_progress_cache(key, *args, **kwargs):
        if key == cache.PREFIX_INGEST_TASK.format(document_id=doc_id):
            raise RedisConnectionError(f"{_FAKE_PRIVATE} Bearer {_FAKE_SECRET}")
        return original(key, *args, **kwargs)

    monkeypatch.setattr(isolated_redis, method, fail_progress_cache)
    # 不进入新的 lifespan，避免启动恢复逻辑掩盖未调度的 uploaded。
    http = TestClient(fastapi_app, raise_server_exceptions=False)
    try:
        first = http.post(f"{url}/reprocess", headers=teacher)
        after_first = http.get(url, headers=teacher).json()
        assert first.status_code == 202, (first.text, after_first)
        assert after_first["status"] == "ready"
        assert after_first["progress"] == 100
        assert after_first["error_message"] is None
        assert http.post(f"{url}/reprocess", headers=teacher).status_code == 202
        assert http.get(url, headers=teacher).json()["status"] == "ready"
    finally:
        http.close()
    assert "PROGRESS_CACHE_UNAVAILABLE" in caplog.text
    assert "type=ConnectionError" in caplog.text
    assert _FAKE_PRIVATE not in caplog.text
    assert _FAKE_SECRET not in caplog.text


def test_reprocess_vector_cleanup_failure_preserves_existing_sql_chunks(
    client, teacher, db, monkeypatch, document_store,
):
    bank = create_bank(client, teacher)
    uploaded = upload_markdown(client, teacher, bank["id"])
    doc_id = uploaded["document_id"]
    previous = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).count()
    assert previous > 0

    def fail(**kwargs):
        raise InternalError("database (code: 14) fake-private-path")

    monkeypatch.setattr(document_store, "delete", fail)
    url = f"/api/banks/{bank['id']}/documents/{doc_id}"
    assert client.post(f"{url}/reprocess", headers=teacher).status_code == 202
    failed = client.get(url, headers=teacher).json()
    assert failed["status"] == "failed"
    assert "向量" in failed["error_message"]
    assert "fake-private-path" not in failed["error_message"]
    assert "存储路径与临时目录权限（code 14）" in failed["error_message"]
    assert db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_id).count() == previous


@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize(("format_name", "media_type"), [
    ("PDF", "application/pdf"), ("MD", "text/plain"), ("TXT", "text/plain"),
    ("DOCX", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("XLSX", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
])
def test_download_uses_current_storage_and_explicit_media_type(
    client, teacher, db, tmp_path, document_store, inline, format_name, media_type,
):
    bank = create_bank(client, teacher)
    uploaded = upload_markdown(client, teacher, bank["id"])
    doc = db.get(Document, uploaded["document_id"])
    # 当前产物与初始上传文件不同，后缀不提供 MIME 推断依据。
    current = tmp_path / "current-artifact.bin"
    current.write_bytes(b"fake current artifact")
    doc.storage_path = str(current)
    doc.format = format_name
    doc.name = "display-name.bin"
    db.commit()
    response = client.get(
        f"/api/banks/{bank['id']}/documents/{doc.id}/download", headers=teacher,
        params={"inline": str(inline).lower()},
    )
    assert response.status_code == 200
    assert response.content == b"fake current artifact"
    assert response.headers["content-type"].split(";")[0] == media_type
    assert response.headers["content-disposition"].startswith("inline" if inline else "attachment")


@pytest.mark.parametrize("mode", ["dense", "hybrid", "hybrid_rerank"])
def test_search_storage_failure_returns_safe_service_error(
    client, teacher, monkeypatch, document_store, mode,
):
    bank = create_bank(client, teacher)

    def fail(**kwargs):
        raise InternalError("database (code: 14) fake-private-path")

    monkeypatch.setattr(vectorstore._client, "get_collection", fail)
    response = client.post(f"/api/banks/{bank['id']}/search", headers=teacher, json={
        "query": "导数", "mode": mode, "top_k": 1,
    })
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "VECTOR_STORE_UNAVAILABLE"
    assert "fake-private-path" not in response.text


def test_document_delete_storage_failure_returns_safe_error(
    client, teacher, monkeypatch, document_store,
):
    bank = create_bank(client, teacher)
    uploaded = upload_markdown(client, teacher, bank["id"])

    def fail(**kwargs):
        raise InternalError("fake-private-path")

    monkeypatch.setattr(document_store, "delete", fail)
    response = client.delete(
        f"/api/banks/{bank['id']}/documents/{uploaded['document_id']}", headers=teacher,
    )
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "VECTOR_STORE_UNAVAILABLE"
    assert "fake-private-path" not in response.text


def test_vector_health_failure_retains_safe_classification(
    client, db, monkeypatch, document_store, caplog,
):
    def fail():
        raise InternalError("database (code: 14) fake-private-path")

    monkeypatch.setattr(vectorstore._client, "heartbeat", fail)
    status = rag_settings.read_settings(db).vector_store
    assert status.available is False
    assert "健康检查" in status.message
    assert "operation=health" in caplog.text
    assert "fake-private-path" not in status.message + caplog.text


@pytest.mark.parametrize("scope", ["document", "bank"])
def test_delete_vector_failure_rolls_back_sql_preserves_file_and_allows_retry(
    client, teacher, db, monkeypatch, document_store, scope,
):
    """真实删除服务在向量故障时保留 SQL、FTS 与文件，同一会话可直接重试。"""
    from pathlib import Path

    from app.config import BASE_DIR
    from app.services.rag import fts

    bank_id = create_bank(client, teacher)["id"]
    doc_id = upload_markdown(client, teacher, bank_id)["document_id"]
    doc = db.get(Document, doc_id)
    path = Path(doc.storage_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    original = path.read_bytes()
    chunks = db.query(DocumentChunk).filter_by(document_id=doc_id).count()
    epoch = db.get(RagSetting, 1).mutation_epoch

    def fail(**kwargs):
        assert path.read_bytes() == original
        raise InternalError("database (code: 14) fake-private-path fake-key-do-not-log")

    target = document_store if scope == "document" else vectorstore._client
    method = "delete" if scope == "document" else "delete_collection"
    monkeypatch.setattr(target, method, fail, raising=False)
    with pytest.raises(vectorstore.VectorStoreError):
        if scope == "document":
            banks.purge_document(db, doc)
        else:
            banks.purge_bank(db, db.get(Bank, bank_id))
    db.expire_all()
    assert db.get(Document, doc_id) is not None
    assert db.get(Bank, bank_id).status == "active"
    assert db.query(BankMember).filter_by(bank_id=bank_id).count() == 1
    assert db.query(DocumentChunk).filter_by(document_id=doc_id).count() == chunks
    assert db.get(RagSetting, 1).mutation_epoch == epoch
    assert fts.search(bank_id, "导数", 3, document_id=doc_id, db=db)
    assert path.read_bytes() == original
    monkeypatch.setattr(target, method, lambda **kwargs: None)
    if scope == "document":
        banks.purge_document(db, db.get(Document, doc_id))
        assert db.get(Bank, bank_id).status == "active"
    else:
        banks.purge_bank(db, db.get(Bank, bank_id))
        assert db.get(Bank, bank_id).status == "deleted"
        assert db.query(BankMember).filter_by(bank_id=bank_id).count() == 0
    # 批量删除使用 synchronize_session=False，重新读取实际 SQL 而非会话身份缓存。
    db.expire_all()
    assert db.get(Document, doc_id) is None
    assert db.query(DocumentChunk).filter_by(document_id=doc_id).count() == 0
    assert fts.search(bank_id, "导数", 3, document_id=doc_id, db=db) == []
    assert not path.exists()


@pytest.mark.parametrize("native_code", [None, 14])
def test_bank_delete_global_handler_returns_safe_503_and_can_retry(
    client, teacher, monkeypatch, document_store, caplog, native_code,
):
    bank_id = create_bank(client, teacher)["id"]
    doc_id = upload_markdown(client, teacher, bank_id)["document_id"]

    def fail(**kwargs):
        raise InternalError(f"(code: {native_code}) {_FAKE_PRIVATE} {_FAKE_SECRET} fake-private-body")

    monkeypatch.setattr(vectorstore._client, "delete_collection", fail, raising=False)
    with TestClient(fastapi_app, raise_server_exceptions=False) as http:
        response = http.delete(f"/api/banks/{bank_id}", headers=teacher)
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "VECTOR_STORE_UNAVAILABLE"
    assert response.json()["detail"]["message"]
    if native_code == 14:
        assert response.json()["detail"]["message"].startswith("向量删除失败")
        assert "存储路径与临时目录权限（code 14）" in response.json()["detail"]["message"]
    for private in (_FAKE_PRIVATE, _FAKE_SECRET, "fake-private-body"):
        assert private not in response.text + caplog.text
    assert client.get(f"/api/banks/{bank_id}/documents/{doc_id}", headers=teacher).status_code == 200
    monkeypatch.setattr(vectorstore._client, "delete_collection", lambda **kwargs: None)
    assert client.delete(f"/api/banks/{bank_id}", headers=teacher).status_code == 204


@pytest.mark.parametrize("scope", ["document", "bank"])
def test_delete_sql_commit_failure_preserves_file_and_can_retry(
    client, teacher, db, monkeypatch, document_store, scope,
):
    """向量先完成但 SQL 提交失败时，保留文档及原件并允许再次删除。"""
    from pathlib import Path

    from sqlalchemy import event
    from sqlalchemy.exc import SQLAlchemyError

    from app.config import BASE_DIR

    bank_id = create_bank(client, teacher)["id"]
    doc_id = upload_markdown(client, teacher, bank_id)["document_id"]
    path = Path(db.get(Document, doc_id).storage_path)
    if not path.is_absolute():
        path = BASE_DIR / path
    original = path.read_bytes()
    deleted = []

    def delete_vector(**kwargs):
        assert path.read_bytes() == original
        deleted.append(scope)

    def fail_commit(session):
        assert deleted == [scope]
        assert path.read_bytes() == original
        raise SQLAlchemyError("fake SQL commit failure")

    target = document_store if scope == "document" else vectorstore._client
    method = "delete" if scope == "document" else "delete_collection"
    monkeypatch.setattr(target, method, delete_vector, raising=False)
    event.listen(db, "before_commit", fail_commit, once=True)
    try:
        with pytest.raises(SQLAlchemyError):
            if scope == "document":
                banks.purge_document(db, db.get(Document, doc_id))
            else:
                banks.purge_bank(db, db.get(Bank, bank_id))
    finally:
        event.remove(db, "before_commit", fail_commit)
    db.expire_all()
    assert db.get(Document, doc_id) is not None
    assert db.get(Bank, bank_id).status == "active"
    assert path.read_bytes() == original
    if scope == "document":
        banks.purge_document(db, db.get(Document, doc_id))
    else:
        banks.purge_bank(db, db.get(Bank, bank_id))
    db.expire_all()
    assert db.get(Document, doc_id) is None
    assert deleted == [scope, scope]
    assert not path.exists()


@pytest.mark.parametrize("failure", ["vector", "embedding"])
def test_sync_generation_uses_global_safe_service_handler(
    client, teacher, monkeypatch, document_store, failure,
):
    """同步出题未捕获的服务异常由应用统一返回安全 503。"""
    from app.services.rag import question_gen

    bank_id = create_bank(client, teacher)["id"]
    doc_id = upload_markdown(client, teacher, bank_id)["document_id"]
    assert client.put("/api/users/me/model-settings", headers=teacher, json={
        "deepseek_api_key": "fake-deepseek-only-for-isolated-tests",
    }).status_code == 200

    def fail_storage(**kwargs):
        raise InternalError(f"{_FAKE_PRIVATE} {_FAKE_SECRET} fake-private-body")

    def fail_service(*args, **kwargs):
        raise embeddings.EmbeddingError(
            f"{_FAKE_PRIVATE} {_FAKE_SECRET} fake-private-body", "server",
        )

    if failure == "vector":
        # 原题数量统计驱动真实 Chroma 适配器，异常贯穿同步出题调用链。
        monkeypatch.setattr(document_store, "get", fail_storage, raising=False)
    else:
        # 合成已有服务异常验证 ASGI 全局边界，避免受混合检索降级策略干扰。
        monkeypatch.setattr(question_gen, "generate_questions", fail_service)
    with TestClient(fastapi_app, raise_server_exceptions=False) as http:
        response = http.post("/api/generate", headers=teacher, json={
            "bank_id": bank_id, "document_id": doc_id, "source_mode": "original",
            "types": [{"type": "single", "count": 1}],
        })
    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    expected = "VECTOR_STORE_UNAVAILABLE" if failure == "vector" else "EMBEDDING_UNAVAILABLE"
    assert response.json()["detail"]["code"] == expected
    assert response.json()["detail"]["message"]
    for private in (_FAKE_PRIVATE, _FAKE_SECRET, "fake-private-body"):
        assert private not in response.text


def test_download_contract_declares_binary_media_and_safe_errors():
    """从实时应用生成 schema 核对声明，不修改生成的契约文件。"""
    fastapi_app.openapi_schema = None
    schema = fastapi_app.openapi()
    response = schema["paths"]["/api/banks/{bank_id}/documents/{document_id}/download"]["get"][
        "responses"
    ]
    expected_media = {
        "application/pdf", "text/plain",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/octet-stream",
    }
    assert set(response["200"]["content"]) == expected_media
    for content in response["200"]["content"].values():
        assert content["schema"] == {"type": "string", "format": "binary"}
    assert response["200"]["headers"]["Content-Disposition"]["schema"]["type"] == "string"
    for status in ("401", "404", "503"):
        assert response[status]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/ErrorResponse",
        }


@pytest.fixture()
def wal_delete_store(tmp_path, monkeypatch, document_store):
    """独立真实 WAL，显式读事务复现快照升级竞争；向量边界保持离线。"""
    engine = create_engine(f"sqlite:///{(tmp_path / 'delete.db').as_posix()}",
                           connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def configure(connection, record):
        connection.isolation_level = None
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10")

    @event.listens_for(engine, "begin")
    def begin(connection):
        connection.exec_driver_sql("BEGIN")

    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    Base.metadata.create_all(engine)
    path = tmp_path / "failed.md"
    path.write_bytes(b"fake document with stale chunks")
    with sessions() as db:
        db.add(User(id="wal_user", account="wal_teacher", password_hash="fake-hash",
                    role="teacher", identity="教师", display_name="假教师"))
        db.flush()
        db.add(Bank(id="wal_bank", name="假题库", code="TK_WAL", creator_id="wal_user"))
        db.flush()
        db.add(BankMember(id="wal_member", bank_id="wal_bank", user_id="wal_user",
                          role="creator"))
        db.add(Document(id="wal_doc", bank_id="wal_bank", name="failed.md", format="MD",
                        size_bytes=path.stat().st_size, storage_path=str(path),
                        uploader_id="wal_user", status="failed", chunk_count=0))
        db.flush()
        db.add(DocumentChunk(id="wal_chunk", bank_id="wal_bank", document_id="wal_doc",
                             chunk_index=0, text="导数", tokens="导数", char_count=2))
        db.add(RagSetting(id=1, generation="before_warmup"))
        db.execute(text(FTS_CREATE_SQL))
        db.execute(text("INSERT INTO document_chunks_fts VALUES "
                        "('wal_chunk', 'wal_bank', 'wal_doc', '导数')"))
        db.commit()
    monkeypatch.setattr(rag_runtime, "SessionLocal", sessions)
    monkeypatch.setattr(vectorstore._client, "delete_collection", lambda **kwargs: None,
                        raising=False)
    try:
        yield sessions, path
    finally:
        engine.dispose()


def _wal_purge(sessions, scope):
    with sessions() as db:
        if scope == "document":
            banks.purge_document(db, db.get(Document, "wal_doc"))
        else:
            banks.purge_bank(db, db.get(Bank, "wal_bank"))


def _assert_wal_materials(sessions, path, *, deleted):
    with sessions() as db:
        assert (db.get(Document, "wal_doc") is None) is deleted
        assert db.query(DocumentChunk).count() == (0 if deleted else 1)
        assert db.execute(text("SELECT count(*) FROM document_chunks_fts")).scalar_one() == (
            0 if deleted else 1
        )
    assert path.exists() is not deleted


@pytest.mark.parametrize("scope", ["document", "bank"])
def test_wal_delete_slow_initialization_allows_other_writer(
    wal_delete_store, monkeypatch, scope,
):
    sessions, path = wal_delete_store
    initializing, release = Event(), Event()
    names = []
    original_get = vectorstore.get_client
    native = original_get()

    def initialize(**kwargs):
        initializing.set()
        assert release.wait(5), "测试未释放慢初始化"
        return native

    def unexpected_session():
        pytest.fail("删除必须使用写锁内配置快照，禁止新 SQLSession")

    def record_collection(**kwargs):
        names.append(kwargs["name"])
        return SimpleNamespace(delete=lambda **kwargs: None)

    monkeypatch.setattr(vectorstore, "_client", None)
    monkeypatch.setattr(chromadb, "PersistentClient", initialize)
    monkeypatch.setattr(native, "get_collection", record_collection)
    monkeypatch.setattr(native, "delete_collection", record_collection)
    monkeypatch.setattr(rag_runtime, "SessionLocal", unexpected_session)
    with ThreadPoolExecutor(max_workers=1) as executor:
        deletion = executor.submit(_wal_purge, sessions, scope)
        try:
            assert initializing.wait(5)
            with sessions() as writer:
                assert writer.execute(text("PRAGMA journal_mode")).scalar_one() == "wal"
                writer.execute(text("UPDATE rag_settings SET generation='after_warmup'"))
                writer.commit()
        finally:
            release.set()
        deletion.result(timeout=5)
    assert names == ["kb_wal_bank_after_warmup"]
    _assert_wal_materials(sessions, path, deleted=True)


@pytest.mark.parametrize("scope", ["document", "bank"])
def test_wal_delete_retries_whole_transaction_after_short_write_lock(
    wal_delete_store, scope,
):
    sessions, path = wal_delete_store
    contended = Event()
    engine = sessions.kw["bind"]

    def locked(context):
        if getattr(context.original_exception, "sqlite_errorcode", None) == sqlite3.SQLITE_BUSY:
            contended.set()

    event.listen(engine, "handle_error", locked)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with sessions() as writer:
                writer.execute(text("UPDATE rag_settings SET generation='after_lock'"))
                deletion = executor.submit(_wal_purge, sessions, scope)
                assert contended.wait(5), "未触发真实 SQLite 写锁竞争"
                # 改掉旧读事务已读过的文件路径，重试必须重新加载对象。
                replacement = path.with_name("replacement.md")
                replacement.write_bytes(b"new current artifact")
                writer.execute(text("UPDATE documents SET storage_path=:path"),
                               {"path": str(replacement)})
                writer.commit()
            deletion.result(timeout=5)
        assert path.exists()
        _assert_wal_materials(sessions, replacement, deleted=True)
    finally:
        event.remove(engine, "handle_error", locked)


@pytest.mark.parametrize("scope", ["document", "bank"])
def test_wal_delete_busy_exhaustion_is_retryable_and_logs_safe_code(
    wal_delete_store, caplog, scope,
):
    sessions, path = wal_delete_store
    with sessions() as writer:
        writer.execute(text("UPDATE rag_settings SET generation=:value"),
                       {"value": "fake-private-sql-parameter"})
        with pytest.raises(AppError) as error:
            _wal_purge(sessions, scope)
    assert error.value.code == "DATABASE_BUSY"
    assert error.value.status_code == 503
    assert "重试" in error.value.message
    assert "stage=gate" in caplog.text
    assert "type=OperationalError" in caplog.text
    assert "code=5" in caplog.text
    assert "INSERT INTO" not in caplog.text
    assert "fake-private-sql-parameter" not in caplog.text
    _assert_wal_materials(sessions, path, deleted=False)


@pytest.mark.parametrize("scope", ["document", "bank"])
def test_wal_delete_vector_failure_never_retries_sqlite_like_errors(
    wal_delete_store, monkeypatch, scope,
):
    sessions, path = wal_delete_store
    calls = []

    def fail(**kwargs):
        calls.append(scope)
        raise InternalError("database (code: 5) fake-private-vector-error")

    native = vectorstore.get_client()
    target = native.get_collection() if scope == "document" else native
    monkeypatch.setattr(target, "delete" if scope == "document" else "delete_collection", fail)
    with pytest.raises(vectorstore.VectorStoreError):
        _wal_purge(sessions, scope)
    assert calls == [scope]
    _assert_wal_materials(sessions, path, deleted=False)
    with sessions() as db:
        assert db.get(RagSetting, 1).mutation_epoch == 0


@pytest.mark.parametrize("scope", ["document", "bank"])
def test_wal_delete_failed_document_with_zero_count_cleans_real_chunks(
    wal_delete_store, scope,
):
    sessions, path = wal_delete_store
    _wal_purge(sessions, scope)
    _assert_wal_materials(sessions, path, deleted=True)


@pytest.mark.parametrize("scope", ["document", "bank"])
@pytest.mark.parametrize("native_code", [sqlite3.SQLITE_IOERR, None])
def test_wal_delete_nonbusy_commit_failure_does_not_retry(
    wal_delete_store, monkeypatch, scope, native_code,
):
    sessions, path = wal_delete_store
    calls = []
    native = vectorstore.get_client()
    target = native.get_collection() if scope == "document" else native
    monkeypatch.setattr(target, "delete" if scope == "document" else "delete_collection",
                        lambda **kwargs: calls.append(scope))
    with sessions() as db:
        def fail(session):
            original = sqlite3.OperationalError("database is locked fake-private-sql")
            if native_code is not None:
                original.sqlite_errorcode = native_code
            raise OperationalError("fake SQL", {"private": "fake-parameter"}, original)

        event.listen(db, "before_commit", fail)
        with pytest.raises(OperationalError):
            if scope == "document":
                banks.purge_document(db, db.get(Document, "wal_doc"))
            else:
                banks.purge_bank(db, db.get(Bank, "wal_bank"))
    assert calls == [scope]
    _assert_wal_materials(sessions, path, deleted=False)


@pytest.mark.parametrize("scope", ["document", "bank"])
def test_wal_delete_rebuild_busy_takes_priority_over_unavailable_chroma(
    wal_delete_store, monkeypatch, scope,
):
    sessions, path = wal_delete_store
    with sessions() as db:
        db.get(RagSetting, 1).rebuild_status = "running"
        db.commit()

    def fail():
        raise vectorstore.VectorStoreError("init", "InternalError", 14)

    monkeypatch.setattr(vectorstore, "get_client", fail)
    with pytest.raises(AppError) as error:
        _wal_purge(sessions, scope)
    assert error.value.code == "RAG_REBUILD_BUSY"
    assert error.value.status_code == 409
    _assert_wal_materials(sessions, path, deleted=False)


@pytest.mark.parametrize(("scope", "revocation", "status", "code"), [
    ("document", "removed", 404, "BANK_NOT_FOUND"),
    ("document", "readonly", 403, "FORBIDDEN"),
    ("bank", "transfer", 403, "FORBIDDEN"),
    ("document", "auth_version", 401, "SESSION_REVOKED"),
    ("bank", "auth_version", 401, "SESSION_REVOKED"),
    ("document", "disabled", 401, "SESSION_REVOKED"),
    ("bank", "disabled", 401, "SESSION_REVOKED"),
])
def test_wal_delete_rechecks_actor_after_write_lock_revocation(
    wal_delete_store, monkeypatch, scope, revocation, status, code,
):
    """HTTP 已缓存的账号、题库和成员权限不能跨整事务重试沿用。"""
    sessions, path = wal_delete_store
    engine = sessions.kw["bind"]
    contended = Event()
    deleted = []
    native = vectorstore.get_client()
    monkeypatch.setattr(native.get_collection(), "delete", lambda **kwargs: deleted.append(scope))
    monkeypatch.setattr(native, "delete_collection", lambda **kwargs: deleted.append(scope))

    def locked(context):
        if getattr(context.original_exception, "sqlite_errorcode", None) == sqlite3.SQLITE_BUSY:
            contended.set()

    def delete_with_stale_access():
        with sessions() as db:
            actor = db.get(User, "wal_user")
            access = resolve_bank_access(db, actor, "wal_bank")
            if scope == "document":
                banks.purge_document(db, db.get(Document, "wal_doc"), actor=actor)
            else:
                banks.purge_bank(db, access.bank, actor=actor)

    event.listen(engine, "handle_error", locked)
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            with sessions() as writer:
                writer.execute(text("UPDATE rag_settings SET mutation_epoch=mutation_epoch"))
                deletion = executor.submit(delete_with_stale_access)
                assert contended.wait(5), "未触发真实 SQLite 写锁竞争"
                if revocation == "removed":
                    writer.execute(text("DELETE FROM bank_members WHERE id='wal_member'"))
                elif revocation == "readonly":
                    writer.execute(text("UPDATE bank_members SET role='readonly'"))
                elif revocation == "transfer":
                    writer.add(User(id="wal_new_owner", account="wal_new_teacher",
                                    password_hash="fake-hash", role="teacher", identity="教师",
                                    display_name="新创建者"))
                    writer.flush()
                    writer.execute(text("UPDATE banks SET creator_id='wal_new_owner'"))
                    writer.execute(text("UPDATE bank_members SET role='editor'"))
                elif revocation == "auth_version":
                    writer.execute(text("UPDATE users SET auth_version=auth_version+1"))
                else:
                    writer.execute(text("UPDATE users SET status='disabled'"))
                writer.commit()
            with pytest.raises(AppError) as error:
                deletion.result(timeout=5)
        assert error.value.status_code == status
        assert error.value.code == code
        assert deleted == []
        _assert_wal_materials(sessions, path, deleted=False)
    finally:
        event.remove(engine, "handle_error", locked)
