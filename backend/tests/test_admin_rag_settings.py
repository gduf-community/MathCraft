"""管理员 RAG 配置的 HTTP 契约：权限、版本、生效边界及凭据隔离。"""

import importlib.util
import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import TypedDict

import httpx
import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal
from app.models import Bank, BankMember, Document, DocumentChunk, RagSetting, User
from app.models.base import new_id
from app.schemas.rag_settings import RagSettingsBody
from app.services import documents as document_service
from app.services import rag_settings
from app.services.rag import embeddings, rerank, vectorstore
from app.services.rag.chunking import Chunk
from app.services.rag_runtime import RuntimeConfig, RuntimeSnapshot, current_snapshot, use_snapshot
from conftest import create_bank
from test_admin import admin_headers


RAG_URL = "/api/admin/rag-settings"
EMBEDDING_KEY = "fake-admin-embedding-key-for-tests-1234"
RERANK_KEY = "fake-admin-rerank-key-for-tests-5678"
# 在 autouse fake_models 生效前捕获真实适配器，专用回归仍通过假 HTTP 返回值隔离网络。
_ORIGINAL_RERANK = rerank.rerank


class EmbeddingSnapshot(TypedDict):
    """对外可见的嵌入配置，不包含密钥原文。"""

    embedding_model: str
    embedding_base_url: str
    embedding_key_configured: bool
    embedding_key_masked: str | None


class ActiveSnapshot(EmbeddingSnapshot):
    """当前已经生效的模型配置。"""

    rerank_model: str
    rerank_base_url: str
    rerank_key_configured: bool
    rerank_key_masked: str | None


class RagSnapshot(TypedDict):
    """管理员接口公开的配置与任务快照。"""

    active: ActiveSnapshot
    pending: EmbeddingSnapshot | None
    vector_store: dict[str, object]
    rebuild: dict[str, object]
    revision: int


@pytest.fixture(autouse=True)
def fake_vector_client(monkeypatch: pytest.MonkeyPatch) -> None:
    """在客户端创建边界打桩，避免进入本机 Chroma 原生库。"""
    client = SimpleNamespace(heartbeat=lambda: 1, list_collections=lambda: [])
    monkeypatch.setattr(vectorstore, "get_client", lambda: client)
    monkeypatch.setattr(vectorstore, "add_chunks", lambda *args, **kwargs: None)


@pytest.fixture()
def administrator(client: TestClient, db: Session) -> dict[str, str]:
    """通过已有管理员登录辅助函数取得真实鉴权头。"""
    return admin_headers(client, db)


@pytest.fixture()
def model_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, RuntimeSnapshot]]:
    """假模型记录运行时快照，验证临时配置确实传至服务边界。"""
    calls: list[tuple[str, RuntimeSnapshot]] = []

    def embed(texts: list[str]) -> list[list[float]]:
        calls.append(("embedding", current_snapshot()))
        return [[0.5] * 1024 for _ in texts]

    def rank(query: str, documents: list[str], top_n: int | None = None) -> list[dict]:
        calls.append(("rerank", current_snapshot()))
        return [{"index": 0, "score": 0.9}]

    monkeypatch.setattr(embeddings, "embed_texts", embed)
    monkeypatch.setattr(rerank, "rerank", rank)
    return calls


@pytest.fixture()
def ready_documents(
    client: TestClient, teacher: dict[str, str], db: Session, tmp_path: Path,
) -> tuple[str, list[str]]:
    """创建真实归属的题库和已有 SQL 切片，重建无需解析或 Chroma。"""
    bank = create_bank(client, teacher)
    owner = db.query(User).filter(User.account == "teacher").one()
    document_ids: list[str] = []
    for index in range(2):
        document_id = new_id("doc")
        content = f"第 {index + 1} 份资料：导数的定义。"
        source = tmp_path / f"notes-{index}.md"
        source.write_text(content, encoding="utf-8")
        db.add(Document(
            id=document_id, bank_id=bank["id"], uploader_id=owner.id,
            name=source.name, format="MD", storage_path=str(source),
            size_bytes=len(content.encode()), status="ready", progress=100, chunk_count=1,
        ))
        db.flush()
        db.add(DocumentChunk(
            id=new_id("chunk"), bank_id=bank["id"], document_id=document_id,
            chunk_index=0, chunk_type="general", section="导数", text=content,
            tokens="导数 定义", char_count=len(content),
        ))
        document_ids.append(document_id)
    db.commit()
    return bank["id"], document_ids


def _snapshot(client: TestClient, headers: dict[str, str]) -> RagSnapshot:
    """通过新的 HTTP 请求读取持久化配置。"""
    response = client.get(RAG_URL, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def _update_body(snapshot: RagSnapshot) -> dict[str, object]:
    """从最新可编辑配置生成完整保存请求，密钥默认省略。"""
    embedding = snapshot["pending"] or snapshot["active"]
    return {
        "embedding_model": embedding["embedding_model"],
        "embedding_base_url": embedding["embedding_base_url"],
        "rerank_model": snapshot["active"]["rerank_model"],
        "rerank_base_url": snapshot["active"]["rerank_base_url"],
        "revision": snapshot["revision"],
    }


def _save(
    client: TestClient, headers: dict[str, str], body: dict[str, object],
) -> RagSnapshot:
    """保存配置并确认 PUT 返回可直接使用的完整快照。"""
    response = client.put(RAG_URL, json=body, headers=headers)
    assert response.status_code == 200, response.text
    snapshot = response.json()
    assert set(snapshot) == {"active", "pending", "vector_store", "rebuild", "revision"}
    assert snapshot == _snapshot(client, headers)
    return snapshot


@pytest.mark.parametrize("role", ["anonymous", "teacher", "student"])
@pytest.mark.parametrize("operation", ["read", "save", "test", "rebuild"])
def test_non_admin_cannot_manage_rag_settings(
    client: TestClient, request: pytest.FixtureRequest, role: str, operation: str,
) -> None:
    """每个管理入口都必须鉴权，已有教师/学生账号也不能越权。"""
    headers = {} if role == "anonymous" else request.getfixturevalue(role)
    if operation == "read":
        response = client.get(RAG_URL, headers=headers)
    elif operation == "save":
        response = client.put(RAG_URL, headers=headers, json={
            "embedding_model": "fake-embedding-model",
            "embedding_base_url": "https://embedding.example.test/v1",
            "rerank_model": "fake-rerank-model",
            "rerank_base_url": "https://rerank.example.test/v1",
            "revision": 0,
        })
    elif operation == "test":
        response = client.post(f"{RAG_URL}/test", headers=headers, json={
            "service": "embedding", "model": "fake-embedding-model",
            "base_url": "https://probe.example.test/v1", "api_key": EMBEDDING_KEY,
        })
    else:
        response = client.post(f"{RAG_URL}/rebuild", headers=headers, json={"revision": 0})

    assert response.status_code == (401 if role == "anonymous" else 403), response.text
    if role != "anonymous":
        assert response.json()["detail"]["code"] == "FORBIDDEN"
    assert EMBEDDING_KEY not in response.text


def test_default_snapshot(client: TestClient, administrator: dict[str, str]) -> None:
    """首次读取保持既有默认模型，并完整说明存储与重建状态。"""
    data = _snapshot(client, administrator)

    assert set(data) == {"active", "pending", "vector_store", "rebuild", "revision"}
    assert data["active"] == {
        "embedding_model": "BAAI/bge-m3",
        "embedding_base_url": settings.siliconflow_base_url,
        "embedding_key_configured": False,
        "embedding_key_masked": None,
        "rerank_model": "BAAI/bge-reranker-v2-m3",
        "rerank_base_url": settings.siliconflow_base_url,
        "rerank_key_configured": False,
        "rerank_key_masked": None,
    }
    assert data["pending"] is None
    assert type(data["revision"]) is int
    assert data["revision"] >= 0
    assert data["vector_store"]["backend"] == "chroma"
    assert data["vector_store"]["available"] is True
    assert isinstance(data["vector_store"]["message"], str)
    assert Path(str(data["vector_store"]["path"])).resolve() == settings.chroma_path().resolve()
    assert set(data["rebuild"]) == {"status", "progress", "stage", "error"}
    assert data["rebuild"]["status"] == "idle"
    assert data["rebuild"]["progress"] == 0
    assert isinstance(data["rebuild"]["stage"], str)
    assert data["rebuild"]["error"] is None
    assert _snapshot(client, administrator) == data


def test_key_only_update_is_immediate_and_never_returns_plaintext(
    client: TestClient, administrator: dict[str, str],
) -> None:
    """只换密钥不要求重建，PUT 与 GET 都只公开配置状态和掩码。"""
    before = _snapshot(client, administrator)
    body = _update_body(before)
    body.update(embedding_api_key=EMBEDDING_KEY, rerank_api_key=RERANK_KEY)

    saved = _save(client, administrator, body)

    assert saved["pending"] is None
    assert saved["revision"] > before["revision"]
    for service, secret in (("embedding", EMBEDDING_KEY), ("rerank", RERANK_KEY)):
        assert saved["active"][f"{service}_key_configured"] is True
        masked = saved["active"][f"{service}_key_masked"]
        assert isinstance(masked, str) and masked and masked != secret
        assert f"{service}_api_key" not in saved["active"]
        assert secret not in json.dumps(saved)


@pytest.mark.parametrize("key_input", [None, ""], ids=["omitted", "empty-string"])
def test_omitted_or_empty_keys_preserve_saved_secrets(
    client: TestClient, administrator: dict[str, str], key_input: str | None,
) -> None:
    """完整表单保存时省略或留空密钥，不能意外清除已有凭据。"""
    body = _update_body(_snapshot(client, administrator))
    body.update(embedding_api_key=EMBEDDING_KEY, rerank_api_key=RERANK_KEY)
    configured = _save(client, administrator, body)
    body = _update_body(configured)
    body["rerank_model"] = "fake-rerank-next"
    if key_input is not None:
        body.update(embedding_api_key=key_input, rerank_api_key=key_input)

    saved = _save(client, administrator, body)

    assert saved["active"]["rerank_model"] == "fake-rerank-next"
    assert saved["pending"] is None
    for service in ("embedding", "rerank"):
        assert saved["active"][f"{service}_key_configured"] is True
        assert (saved["active"][f"{service}_key_masked"]
                == configured["active"][f"{service}_key_masked"])


@pytest.mark.parametrize("field,value", [
    ("embedding_model", "fake-new-embedding-space"),
    ("embedding_base_url", "https://new-embedding.example.test/v1"),
])
def test_embedding_changes_are_pending_while_rerank_changes_apply_immediately(
    client: TestClient, administrator: dict[str, str], field: str, value: str,
) -> None:
    """嵌入模型或地址变更不得提前切换旧索引正在使用的配置。"""
    before = _snapshot(client, administrator)
    body = _update_body(before)
    body[field] = value
    body.update(
        embedding_api_key=EMBEDDING_KEY,
        rerank_model="fake-rerank-next",
        rerank_base_url="https://new-rerank.example.test/v1",
        rerank_api_key=RERANK_KEY,
    )

    saved = _save(client, administrator, body)

    pending = saved["pending"]
    assert pending is not None
    assert set(pending) == {
        "embedding_model", "embedding_base_url",
        "embedding_key_configured", "embedding_key_masked",
    }
    for name in ("embedding_model", "embedding_base_url"):
        assert saved["active"][name] == before["active"][name]
        assert pending[name] == body[name]
    for name in ("embedding_key_configured", "embedding_key_masked"):
        assert saved["active"][name] == before["active"][name]
    assert pending["embedding_key_configured"] is True
    assert pending["embedding_key_masked"]
    assert saved["active"]["rerank_model"] == body["rerank_model"]
    assert saved["active"]["rerank_base_url"] == body["rerank_base_url"]
    assert saved["active"]["rerank_key_configured"] is True
    assert saved["rebuild"]["status"] == "idle"
    assert saved["revision"] > before["revision"]
    assert EMBEDDING_KEY not in json.dumps(saved)
    assert RERANK_KEY not in json.dumps(saved)


@pytest.mark.parametrize("operation", ["save", "rebuild"])
def test_stale_revision_returns_conflict_without_changing_configuration(
    client: TestClient, administrator: dict[str, str], operation: str,
) -> None:
    """旧页面的保存或重建请求不能覆盖管理员已经确认的新版本。"""
    before = _snapshot(client, administrator)
    body = _update_body(before)
    body["embedding_model"] = "fake-pending-embedding"
    current = _save(client, administrator, body)

    if operation == "save":
        stale = _update_body(before)
        stale.update(rerank_model="fake-stale-rerank", embedding_api_key=EMBEDDING_KEY)
        response = client.put(RAG_URL, json=stale, headers=administrator)
    else:
        response = client.post(f"{RAG_URL}/rebuild", headers=administrator,
                               json={"revision": before["revision"]})

    assert response.status_code == 409, response.text
    assert _snapshot(client, administrator) == current
    assert EMBEDDING_KEY not in response.text


INVALID_FIELDS = [
    ("model", ""),
    ("model", " \t "),
    ("base_url", ""),
    ("base_url", " \t "),
    ("base_url", "ftp://models.example.test/v1"),
    ("base_url", "file:///tmp/fake-model"),
    ("base_url", "https://fake-user:fake-password@models.example.test/v1"),
    ("base_url", "https://fake-user@models.example.test/v1"),
    ("base_url", "https://example.test:bad/v1"),
    ("base_url", "https://example.test:70000/v1"),
    ("base_url", "https://example.test/v1?"),
    ("base_url", "https://example.test/v1#"),
]


@pytest.mark.parametrize("service", ["embedding", "rerank"])
@pytest.mark.parametrize("field,value", INVALID_FIELDS)
def test_invalid_settings_are_rejected_without_partial_write(
    client: TestClient, administrator: dict[str, str], service: str, field: str, value: str,
) -> None:
    """任意模型字段非法时，整个保存失败，其他字段也不能部分生效。"""
    before = _snapshot(client, administrator)
    body = _update_body(before)
    body.update(embedding_api_key=EMBEDDING_KEY, rerank_api_key=RERANK_KEY)
    body[f"{service}_{field}"] = value

    response = client.put(RAG_URL, json=body, headers=administrator)

    assert response.status_code == 422, response.text
    assert _snapshot(client, administrator) == before
    assert EMBEDDING_KEY not in response.text
    assert RERANK_KEY not in response.text
    assert "fake-password" not in response.text


@pytest.mark.parametrize("service", ["embedding", "rerank"])
@pytest.mark.parametrize("field,value", INVALID_FIELDS)
def test_invalid_probe_configuration_is_rejected_before_network(
    client: TestClient, administrator: dict[str, str],
    model_calls: list[tuple[str, RuntimeSnapshot]], service: str, field: str, value: str,
) -> None:
    """连接测试与持久化接口遵守相同字段边界，非法输入不能发请求。"""
    before = _snapshot(client, administrator)
    body = {"service": service, "model": "fake-probe-model",
            "base_url": "https://probe.example.test/v1", "api_key": EMBEDDING_KEY}
    body[field] = value

    response = client.post(f"{RAG_URL}/test", json=body, headers=administrator)

    assert response.status_code == 422, response.text
    assert model_calls == []
    assert _snapshot(client, administrator) == before
    assert EMBEDDING_KEY not in response.text
    assert "fake-password" not in response.text


@pytest.mark.parametrize("service", ["embedding", "rerank"])
def test_probe_uses_one_off_credentials_without_persisting_them(
    client: TestClient, administrator: dict[str, str],
    model_calls: list[tuple[str, RuntimeSnapshot]], service: str,
) -> None:
    """测试请求必须实际使用临时表单配置，且不修改 active、pending 或版本。"""
    body = _update_body(_snapshot(client, administrator))
    body.update(embedding_api_key=EMBEDDING_KEY, rerank_api_key=RERANK_KEY)
    configured = _save(client, administrator, body)
    body = _update_body(configured)
    body["embedding_model"] = "fake-pending-embedding"
    before = _save(client, administrator, body)
    temporary_key = "fake-one-off-probe-key-never-persist-9999"

    response = client.post(f"{RAG_URL}/test", headers=administrator, json={
        "service": service,
        "model": "fake-one-off-probe-model",
        "base_url": "https://one-off.example.test/v1",
        "api_key": temporary_key,
    })

    assert response.status_code == 200, response.text
    assert response.json()["ok"] is True
    assert isinstance(response.json()["message"], str) and response.json()["message"]
    assert len(model_calls) == 1
    called_service, snapshot = model_calls[0]
    assert called_service == service
    assert getattr(snapshot.config, f"{service}_base_url") == "https://one-off.example.test/v1"
    assert getattr(snapshot.config, f"{service}_api_key") == temporary_key
    assert getattr(snapshot.config, f"{service}_model") == "fake-one-off-probe-model"
    assert temporary_key not in response.text
    assert _snapshot(client, administrator) == before


def test_failed_rebuild_preserves_active_index_and_can_retry(
    client: TestClient, administrator: dict[str, str], db: Session,
    ready_documents: tuple[str, list[str]], monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """新索引写入一部分后失败，旧指针和草稿保留，重试成功才一次切换。"""
    bank_id, document_ids = ready_documents
    body = _update_body(_snapshot(client, administrator))
    body.update(embedding_model="fake-candidate-embedding", embedding_api_key=EMBEDDING_KEY)
    pending = _save(client, administrator, body)
    row = db.get(RagSetting, 1)
    assert row is not None
    row.generation = "fake-old-generation"
    db.commit()
    before_runtime = current_snapshot()
    before_storage = (row.active_json, row.pending_json, row.generation)
    writes: list[tuple[RuntimeSnapshot, str]] = []

    def write_index(
        target_bank_id: str, document_id: str, document_name: str,
        chunks: list[Chunk], vectors: list[list[float]],
        chunk_ids: list[str] | None = None,
    ) -> None:
        assert target_bank_id == bank_id
        assert document_id in document_ids
        assert chunks and len(chunks) == len(vectors)
        assert chunk_ids and len(chunk_ids) == len(chunks)
        writes.append((current_snapshot(), document_id))
        if len(writes) == 2:
            raise RuntimeError(f"fake-index-write-failed {EMBEDDING_KEY}")

    monkeypatch.setattr(vectorstore, "add_chunks", write_index)

    response = client.post(f"{RAG_URL}/rebuild", headers=administrator,
                           json={"revision": pending["revision"]})

    assert response.status_code == 202, response.text
    assert response.json()["rebuild"]["status"] == "queued"
    failed = _snapshot(client, administrator)
    assert failed["rebuild"]["status"] == "failed"
    assert failed["rebuild"]["error"]
    assert failed["active"] == pending["active"]
    assert failed["pending"] == pending["pending"]
    assert failed["revision"] > pending["revision"]
    db.expire_all()
    row = db.get(RagSetting, 1)
    assert row is not None
    assert (row.active_json, row.pending_json, row.generation) == before_storage
    assert current_snapshot() == before_runtime
    assert len(writes) == 2
    failed_generation = writes[0][0].generation
    assert failed_generation and failed_generation != before_runtime.generation
    assert all(snapshot.generation == failed_generation for snapshot, _ in writes)
    assert all(snapshot.config.embedding_model == body["embedding_model"]
               for snapshot, _ in writes)
    assert EMBEDDING_KEY not in json.dumps(failed)
    assert EMBEDDING_KEY not in caplog.text

    # 第二次后台任务使用同一份 SQL 切片，写入全部成功后发布新版本。
    retry = client.post(f"{RAG_URL}/rebuild", headers=administrator,
                        json={"revision": failed["revision"]})

    assert retry.status_code == 202, retry.text
    succeeded = _snapshot(client, administrator)
    assert succeeded["rebuild"]["status"] == "succeeded"
    assert succeeded["rebuild"]["progress"] == 100
    assert succeeded["rebuild"]["error"] is None
    assert succeeded["pending"] is None
    assert succeeded["active"]["embedding_model"] == body["embedding_model"]
    assert succeeded["active"]["embedding_key_configured"] is True
    assert succeeded["revision"] > failed["revision"]
    assert len(writes) == 4
    published = current_snapshot()
    assert published.generation not in {before_runtime.generation, failed_generation}
    assert published.config.embedding_model == body["embedding_model"]
    assert all(snapshot == published for snapshot, _ in writes[2:])
    assert {document_id for _, document_id in writes[2:]} == set(document_ids)
    assert db.query(DocumentChunk).count() == 2
    assert db.query(Document).filter(Document.status == "ready").count() == 2


@pytest.fixture()
def queued_rebuild(
    client: TestClient, administrator: dict[str, str], db: Session,
    ready_documents: tuple[str, list[str]],
) -> tuple[str, list[str]]:
    """只排队不启动后台任务，为门禁测试提供稳定的重建窗口。"""
    body = _update_body(_snapshot(client, administrator))
    body["embedding_model"] = "fake-queued-embedding"
    pending = _save(client, administrator, body)
    rag_settings.queue_rebuild(db, pending["revision"])
    assert _snapshot(client, administrator)["rebuild"]["status"] == "queued"
    return ready_documents


@pytest.mark.parametrize("status", ["queued", "running"])
@pytest.mark.parametrize("operation", ["upload", "reprocess", "delete_document", "delete_bank"])
def test_rebuild_blocks_document_mutations_without_changing_existing_materials(
    client: TestClient, administrator: dict[str, str], teacher: dict[str, str],
    db: Session, queued_rebuild: tuple[str, list[str]], status: str, operation: str,
) -> None:
    """有资料管理权限的用户在重建期间仍不能改变索引输入。"""
    bank_id, document_ids = queued_rebuild
    row = db.get(RagSetting, 1)
    assert row is not None
    row.rebuild_status = status
    db.commit()
    before = _snapshot(client, administrator)
    document_url = f"/api/banks/{bank_id}/documents/{document_ids[0]}"
    original_document = client.get(document_url, headers=teacher).json()

    if operation == "upload":
        response = client.post(f"/api/banks/{bank_id}/documents", headers=teacher,
                               files={"file": ("blocked.md", b"# fake material", "text/markdown")})
    elif operation == "reprocess":
        response = client.post(f"{document_url}/reprocess", headers=teacher)
    elif operation == "delete_document":
        response = client.delete(document_url, headers=teacher)
    else:
        response = client.delete(f"/api/banks/{bank_id}", headers=teacher)

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "RAG_REBUILD_BUSY"
    assert _snapshot(client, administrator) == before
    assert client.get(document_url, headers=teacher).json() == original_document
    assert client.get(f"/api/banks/{bank_id}", headers=teacher).status_code == 200
    db.expire_all()
    assert db.query(Document).count() == 2
    assert db.query(DocumentChunk).count() == 2
    for document_id in document_ids:
        document = db.get(Document, document_id)
        assert document is not None and document.status == "ready"
        assert Path(document.storage_path).exists()


@pytest.mark.parametrize("operation", ["save", "rebuild"])
def test_queued_rebuild_blocks_setting_changes_and_duplicate_jobs(
    client: TestClient, administrator: dict[str, str],
    queued_rebuild: tuple[str, list[str]], operation: str,
) -> None:
    """即使用最新 revision，也不能在重建期间保存配置或重复提交任务。"""
    before = _snapshot(client, administrator)
    if operation == "save":
        body = _update_body(before)
        body["rerank_model"] = "fake-concurrent-rerank"
        response = client.put(RAG_URL, headers=administrator, json=body)
    else:
        response = client.post(f"{RAG_URL}/rebuild", headers=administrator,
                               json={"revision": before["revision"]})

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "RAG_REBUILD_BUSY"
    assert _snapshot(client, administrator) == before


def test_rebuild_blocks_combined_bank_upload_without_leaving_an_empty_bank(
    client: TestClient, administrator: dict[str, str], teacher: dict[str, str],
    queued_rebuild: tuple[str, list[str]],
) -> None:
    """建库并上传的组合入口被门禁拒绝时，不能留下已提交的空题库。"""
    before = _snapshot(client, administrator)
    existing_banks = client.get("/api/banks", headers=teacher).json()

    response = client.post("/api/banks/with-document", headers=teacher,
                           data={"name": "重建期间禁止创建的资料题库"},
                           files={"file": ("blocked.md", b"# fake material", "text/markdown")})

    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "RAG_REBUILD_BUSY"
    assert client.get("/api/banks", headers=teacher).json() == existing_banks
    assert _snapshot(client, administrator) == before


def test_in_flight_snapshot_keeps_old_model_and_collection_after_successful_rebuild(
    client: TestClient, administrator: dict[str, str], db: Session,
    queued_rebuild: tuple[str, list[str]],
    model_calls: list[tuple[str, RuntimeSnapshot]],
) -> None:
    """在途请求继续用旧模型与集合，退出上下文后的请求才使用已发布版本。"""
    bank_id, _ = queued_rebuild
    row = db.get(RagSetting, 1)
    assert row is not None and row.rebuild_id is not None
    row.generation = "fake-pinned-old-index"
    db.commit()
    job_id = row.rebuild_id
    before = current_snapshot()
    old_collection = vectorstore.safe_collection(bank_id)

    with use_snapshot() as pinned:
        assert pinned == before
        rag_settings.run_rebuild(job_id)
        published = _snapshot(client, administrator)
        assert published["rebuild"]["status"] == "succeeded"
        assert published["pending"] is None
        assert published["active"]["embedding_model"] != before.config.embedding_model
        assert current_snapshot() == before
        assert vectorstore.safe_collection(bank_id) == old_collection
        with use_snapshot():
            embeddings.embed_texts(["在途请求继续使用旧向量空间"])
            assert model_calls[-1] == ("embedding", before)
            assert vectorstore.safe_collection(bank_id) == old_collection
        assert current_snapshot() == before

    latest = current_snapshot()
    assert latest.generation == job_id
    assert latest.config.embedding_model == published["active"]["embedding_model"]
    assert latest.config != before.config
    assert vectorstore.safe_collection(bank_id) != old_collection
    embeddings.embed_texts(["后续请求使用新向量空间"])
    assert model_calls[-1] == ("embedding", latest)


@pytest.mark.parametrize("status", ["queued", "running"])
def test_recovery_marks_interrupted_job_failed_without_switching_index(
    client: TestClient, administrator: dict[str, str], db: Session,
    queued_rebuild: tuple[str, list[str]], status: str,
) -> None:
    """重启不能发布未完成索引；恢复幂等，旧任务不能复活，管理员可重新排队。"""
    row = db.get(RagSetting, 1)
    assert row is not None and row.rebuild_id is not None
    row.rebuild_status = status
    row.rebuild_progress = 40 if status == "running" else 0
    row.generation = "fake-recovery-old-index"
    db.commit()
    interrupted_job = row.rebuild_id
    before = _snapshot(client, administrator)
    before_storage = (row.active_json, row.pending_json, row.generation)
    before_runtime = current_snapshot()

    rag_settings.recover_interrupted_rebuild()

    recovered = _snapshot(client, administrator)
    assert recovered["rebuild"]["status"] == "failed"
    assert recovered["rebuild"]["error"]
    assert recovered["rebuild"]["stage"]
    assert recovered["active"] == before["active"]
    assert recovered["pending"] == before["pending"]
    assert recovered["revision"] > before["revision"]
    db.refresh(row)
    assert (row.active_json, row.pending_json, row.generation) == before_storage
    assert current_snapshot() == before_runtime

    rag_settings.run_rebuild(interrupted_job)
    rag_settings.recover_interrupted_rebuild()
    assert _snapshot(client, administrator) == recovered
    retry_job = rag_settings.queue_rebuild(db, recovered["revision"])
    assert retry_job != interrupted_job
    assert _snapshot(client, administrator)["rebuild"]["status"] == "queued"
    assert current_snapshot() == before_runtime


def test_sqlite_migration_matches_orm_and_supports_settings_round_trip(tmp_path: Path) -> None:
    """直接执行真实迁移，在新 SQLite 文件中验证 ORM 契约与配置读写。"""
    migration_path = Path(__file__).resolve().parents[1] / (
        "alembic/versions/i4d5e6f7a890_platform_rag_settings.py"
    )
    spec = importlib.util.spec_from_file_location("test_platform_rag_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    isolated_engine = create_engine(f"sqlite:///{(tmp_path / 'rag-migration.db').as_posix()}")
    expected_schema = MetaData()
    RagSetting.__table__.to_metadata(expected_schema)
    try:
        with isolated_engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            assert compare_metadata(
                MigrationContext.configure(connection, opts={"compare_type": True}), expected_schema,
            ) == []

        with Session(isolated_engine) as session:
            row = session.get(RagSetting, 1)
            assert row is not None and row.generation == ""
            initial = rag_settings.read_settings(session)
            assert initial.pending is None
            assert initial.rebuild.status == "idle"
            body = RagSettingsBody.model_validate({
                "embedding_model": "fake-migrated-embedding",
                "embedding_base_url": "https://migrated.example.test/v1",
                "embedding_api_key": EMBEDDING_KEY,
                "rerank_model": initial.active.rerank_model,
                "rerank_base_url": initial.active.rerank_base_url,
                "revision": initial.revision,
            })
            saved = rag_settings.save_settings(session, body)
            assert saved.active == initial.active
            assert saved.pending is not None
            assert saved.pending.embedding_model == body.embedding_model
            assert saved.pending.embedding_key_configured is True
            assert saved.revision > initial.revision
            assert EMBEDDING_KEY not in saved.model_dump_json()

        with Session(isolated_engine) as session:
            assert rag_settings.read_settings(session) == saved
            row = session.get(RagSetting, 1)
            assert row is not None and row.generation == ""
    finally:
        isolated_engine.dispose()


@pytest.mark.parametrize("filename,content,code", [
    ("invalid.exe", b"fake unsupported content", "UNSUPPORTED_FORMAT"),
    ("empty.md", b"", "EMPTY_FILE"),
])
def test_invalid_combined_upload_rolls_back_bank_creation(
    client: TestClient, teacher: dict[str, str], db: Session,
    filename: str, content: bytes, code: str,
) -> None:
    """上传校验失败时，已 flush 的题库和成员也必须随请求回滚。"""
    existing_banks = client.get("/api/banks", headers=teacher).json()
    existing_counts = (db.query(Bank).count(), db.query(BankMember).count(),
                       db.query(Document).count())
    response = client.post("/api/banks/with-document", headers=teacher,
                           data={"name": "非法上传不能留下的题库"},
                           files={"file": (filename, content, "application/octet-stream")})

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == code
    assert client.get("/api/banks", headers=teacher).json() == existing_banks
    assert (db.query(Bank).count(), db.query(BankMember).count(),
            db.query(Document).count()) == existing_counts


def test_combined_upload_publishes_bank_and_document_atomically(
    client: TestClient, teacher: dict[str, str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """独立数据库会话观察每次提交，永远不能看到已提交题库却没有首个资料。"""
    bank_name = "事务边界验证题库"
    observed_publications: list[tuple[int, int]] = []

    def observe_committed_materials(_session: Session) -> None:
        with SessionLocal() as observer:
            banks = observer.query(Bank).filter(Bank.name == bank_name).all()
            bank_ids = [bank.id for bank in banks]
            documents = observer.query(Document).filter(Document.bank_id.in_(bank_ids)).count()
            observed_publications.append((len(banks), documents))

    monkeypatch.setattr(document_service, "run_ingestion", lambda *args, **kwargs: None)
    event.listen(Session, "after_commit", observe_committed_materials)
    try:
        response = client.post("/api/banks/with-document", headers=teacher,
                               data={"name": bank_name},
                               files={"file": ("notes.md", b"# fake material", "text/markdown")})
    finally:
        event.remove(Session, "after_commit", observe_committed_materials)

    assert response.status_code == 201, response.text
    assert observed_publications
    assert all(publication == (1, 1) for publication in observed_publications)
    created = response.json()
    assert created["bank"]["name"] == bank_name
    assert created["document"]["document_id"]


def test_rebuild_preserves_chunk_indices_across_embedding_batches(
    client: TestClient, administrator: dict[str, str], db: Session,
    ready_documents: tuple[str, list[str]], monkeypatch: pytest.MonkeyPatch,
) -> None:
    """资料跨越嵌入批次后，写入向量库的切片顺序不能从零重新开始。"""
    bank_id, document_ids = ready_documents
    document_id = document_ids[0]
    document = db.get(Document, document_id)
    assert document is not None
    db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).delete()
    expected_ids: list[str] = []
    for index in range(33):
        chunk_id = new_id("chunk")
        content = f"第 {index} 个片段：导数。"
        db.add(DocumentChunk(
            id=chunk_id, bank_id=bank_id, document_id=document_id, chunk_index=index,
            chunk_type="general", section="导数", text=content,
            tokens="导数", char_count=len(content),
        ))
        expected_ids.append(chunk_id)
    document.chunk_count = len(expected_ids)
    db.commit()
    written: list[tuple[str, int]] = []

    def capture_chunks(
        target_bank_id: str, target_document_id: str, document_name: str,
        chunks: list[Chunk], vectors: list[list[float]],
        chunk_ids: list[str] | None = None,
    ) -> None:
        if target_document_id == document_id:
            assert target_bank_id == bank_id
            assert chunk_ids is not None
            assert len(chunks) == len(vectors) == len(chunk_ids)
            written.extend((chunk_id, chunk.meta.get("chunk_index", -1))
                           for chunk_id, chunk in zip(chunk_ids, chunks, strict=True))

    monkeypatch.setattr(vectorstore, "add_chunks", capture_chunks)
    body = _update_body(_snapshot(client, administrator))
    body["embedding_model"] = "fake-batched-embedding"
    pending = _save(client, administrator, body)

    response = client.post(f"{RAG_URL}/rebuild", headers=administrator,
                           json={"revision": pending["revision"]})

    assert response.status_code == 202, response.text
    assert _snapshot(client, administrator)["rebuild"]["status"] == "succeeded"
    assert written == list(zip(expected_ids, range(33), strict=True))


def test_first_rebuild_commit_failure_marks_failed_and_preserves_old_index(
    client: TestClient, administrator: dict[str, str], db: Session,
    queued_rebuild: tuple[str, list[str]], monkeypatch: pytest.MonkeyPatch,
    model_calls: list[tuple[str, RuntimeSnapshot]],
) -> None:
    """开始重建时的瞬态数据库错误也必须收敛到可重试失败，不能永久占用门禁。"""
    row = db.get(RagSetting, 1)
    assert row is not None and row.rebuild_id is not None
    row.generation = "fake-first-commit-old"
    db.commit()
    job_id = row.rebuild_id
    before = _snapshot(client, administrator)
    before_storage = (row.active_json, row.pending_json, row.generation)
    before_runtime = current_snapshot()
    injected = False

    @contextmanager
    def session_with_transient_failure() -> Iterator[Session]:
        with SessionLocal() as session:
            real_commit = session.commit

            def fail_first_commit() -> None:
                nonlocal injected
                if not injected:
                    injected = True
                    raise OperationalError("fake rebuild commit", {},
                                           RuntimeError("fake transient database failure"))
                real_commit()

            monkeypatch.setattr(session, "commit", fail_first_commit)
            yield session

    monkeypatch.setattr(rag_settings, "SessionLocal", session_with_transient_failure)

    rag_settings.run_rebuild(job_id)

    failed = _snapshot(client, administrator)
    assert injected
    assert failed["rebuild"]["status"] == "failed"
    assert failed["rebuild"]["error"]
    assert failed["active"] == before["active"]
    assert failed["pending"] == before["pending"]
    assert failed["revision"] > before["revision"]
    assert model_calls == []
    db.refresh(row)
    assert (row.active_json, row.pending_json, row.generation) == before_storage
    assert current_snapshot() == before_runtime

    retry_job = rag_settings.queue_rebuild(db, failed["revision"])
    rag_settings.run_rebuild(retry_job)
    succeeded = _snapshot(client, administrator)
    assert succeeded["rebuild"]["status"] == "succeeded"
    assert succeeded["pending"] is None
    assert current_snapshot().generation == retry_job


def _stub_rerank_http(
    monkeypatch: pytest.MonkeyPatch, results: list[dict[str, object]],
) -> list[httpx.Request]:
    """在真实 HTTP 传输边界返回合成响应，兼容用于坏响应回归的 NaN/Infinity。"""
    requests: list[httpx.Request] = []

    def handle(_transport: httpx.HTTPTransport, request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, content=json.dumps({"results": results}, allow_nan=True).encode(),
            headers={"Content-Type": "application/json"}, request=request,
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)
    return requests


INVALID_RERANK_RESULTS = [
    pytest.param([{"index": 2, "relevance_score": 0.9}], id="out-of-range"),
    pytest.param([{"index": -1, "relevance_score": 0.9}], id="negative-index"),
    pytest.param([{"index": True, "relevance_score": 0.9}], id="boolean-index"),
    pytest.param([{"index": 1.0, "relevance_score": 0.9}], id="float-index"),
    pytest.param([{"index": 0, "relevance_score": float("nan")}], id="nan-score"),
    pytest.param([{"index": 0, "relevance_score": float("inf")}], id="infinite-score"),
    pytest.param([{"index": 0, "relevance_score": 0.9},
                  {"index": 0, "relevance_score": 0.8}], id="duplicate-index"),
]


@pytest.mark.parametrize("results", INVALID_RERANK_RESULTS)
def test_real_rerank_adapter_rejects_invalid_provider_results(
    monkeypatch: pytest.MonkeyPatch, results: list[dict[str, object]],
) -> None:
    """真实适配器必须拒绝无法安全映射回输入资料的索引和非有限分数。"""
    requests = _stub_rerank_http(monkeypatch, results)
    config = RuntimeConfig(rerank_model="fake-adapter-rerank",
                           rerank_base_url="https://rerank.example.test/v1",
                           rerank_api_key=RERANK_KEY)

    with use_snapshot(RuntimeSnapshot(config)):
        with pytest.raises(rerank.RerankError):
            _ORIGINAL_RERANK("导数", ["导数资料甲", "导数资料乙"], top_n=2)

    assert len(requests) == 1
    assert requests[0].url.path == "/v1/rerank"
    assert requests[0].headers["Authorization"] == f"Bearer {RERANK_KEY}"
    assert json.loads(requests[0].content)["model"] == config.rerank_model


def test_real_rerank_adapter_accepts_valid_indices_and_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    """合法提供方响应仍可保留排名次序并映射到原资料，防止校验一概拒绝。"""
    requests = _stub_rerank_http(monkeypatch, [
        {"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.2},
    ])
    config = RuntimeConfig(rerank_api_key=RERANK_KEY,
                           rerank_base_url="https://rerank.example.test/v1")

    with use_snapshot(RuntimeSnapshot(config)):
        ranked = _ORIGINAL_RERANK("导数", ["导数资料甲", "导数资料乙"], top_n=2)

    assert ranked == [{"index": 1, "score": 0.9}, {"index": 0, "score": 0.2}]
    assert len(requests) == 1


@pytest.mark.parametrize("results", [
    pytest.param([{"index": 1, "relevance_score": 0.9}], id="out-of-range"),
    pytest.param([{"index": 0, "relevance_score": float("nan")}], id="nan-score"),
    pytest.param([{"index": 0, "relevance_score": 0.9},
                  {"index": 0, "relevance_score": 0.8}], id="duplicate-index"),
])
def test_rerank_probe_returns_failure_for_invalid_real_adapter_response(
    client: TestClient, administrator: dict[str, str], monkeypatch: pytest.MonkeyPatch,
    results: list[dict[str, object]],
) -> None:
    """连接测试须将实际重排响应校验失败报告为错误，且不保存临时凭据。"""
    before = _snapshot(client, administrator)
    requests = _stub_rerank_http(monkeypatch, results)
    monkeypatch.setattr(rerank, "rerank", _ORIGINAL_RERANK)
    temporary_key = "fake-invalid-rerank-probe-key-9999"

    response = client.post(f"{RAG_URL}/test", headers=administrator, json={
        "service": "rerank", "model": "fake-draft-rerank",
        "base_url": "https://rerank.example.test/v1", "api_key": temporary_key,
    })

    assert response.status_code == 400, response.text
    assert response.json()["detail"]["code"] == "RAG_SERVICE_UNAVAILABLE"
    assert response.json()["detail"]["message"]
    assert response.json().get("ok") is not True
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == f"Bearer {temporary_key}"
    assert temporary_key not in response.text
    assert _snapshot(client, administrator) == before
