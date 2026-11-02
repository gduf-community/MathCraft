"""Batch-one acceptance through the unified app, using controlled sources only."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from unittest.mock import AsyncMock
from types import SimpleNamespace

import pytest

from MathCraft.runtime.home import get_runtime_data_root
from MathCraft.services.rag.evidence import UNITS_FILE, Evidence, KnowledgeError, select_evidence


@pytest.fixture(autouse=True)
def fake_model_budget(monkeypatch):
    monkeypatch.setattr(
        "services.question_gen.get_llm_config",
        lambda: SimpleNamespace(model="fake-llm", context_window=131072, max_tokens=4096),
    )


def wait_ready(client, name):
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        stats = client.get(f"/api/knowledge-bases/{name}").json().get("statistics", {})
        if stats.get("rag_initialized"):
            return
        assert stats.get("status") not in {"failed", "error"}, stats
        time.sleep(0.05)
    raise AssertionError("fake-service index did not finish")


def create(client, name, documents):
    response = client.post(
        "/api/knowledge-bases",
        data={
            "name": name,
            "rel_paths": [key for key, _ in documents],
        },
        files=[
            ("files", (Path(key).name, data, "application/octet-stream")) for key, data in documents
        ],
    )
    assert response.status_code == 200, response.text
    wait_ready(client, name)
    return get_runtime_data_root() / "knowledge_bases" / name


def query(client, name, keys=None, text="函数 定义 条件"):
    body = {"query": text, "top_k": 8}
    if keys is not None:
        body["document_keys"] = keys
    response = client.post(f"/api/knowledge-bases/{name}/query", json=body)
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture(scope="module")
def books(client):
    long_text = (
        "A_ONLY 函数定义与条件。"
        + ("若参数满足指定条件，应保留全部计算条件。\n" * 350)
        + "最终条件_END"
    )
    paths = {
        "first/shared.txt": long_text.encode(),
        "second/shared.txt": b"B_ONLY function conditions.",
        "notes.md": "MD_ONLY 定义 $f(x)=x^2$，条件 $x>0$。".encode(),
    }
    kb = create(client, "evidence-books", list(paths.items()))
    other = create(client, "evidence-other", [("first/shared.txt", b"OTHER_KB_ONLY function")])
    yield kb, other, long_text
    client.delete("/api/knowledge-bases/evidence-books")
    client.delete("/api/knowledge-bases/evidence-other")


def params(doc="first/shared.txt", **updates):
    return {
        "kb_id": "evidence-books",
        "doc_id": doc,
        "types": [{"type": "compute", "count": 1}],
        "difficulty": "中",
        "source_mode": "variant_data",
        **updates,
    }


@pytest.fixture
def fake_llm(monkeypatch):
    from services import question_gen, chat_flow

    prompts = []

    async def generate(messages):
        text = messages[-1]["content"]
        prompts.append(text)
        ids = re.findall(r"证据 (E-[0-9a-f]+)", text)
        return {
            "questions": [
                {
                    "type": "compute",
                    "stem": "计算 $1+1$",
                    "answer": "2",
                    "analysis": "由加法得到。",
                    "evidence_ids": ids[:1],
                }
            ]
        }

    monkeypatch.setattr(question_gen, "chat_json", generate)
    monkeypatch.setattr(chat_flow, "extract_slots", AsyncMock(return_value={}))
    return prompts


def test_scoped_text_and_markdown_recall_and_long_evidence(client, books):
    _, _, long_text = books
    result = query(client, "evidence-books", ["first/shared.txt"])
    assert result["sources"]
    for source in result["sources"]:
        assert source["document_key"] == "first/shared.txt"
        assert source["evidence_text"] == long_text
        assert len(source["evidence_text"]) > 6000
        assert source["source_status"] == "valid"
        assert source["index_version"].startswith("version-")
        assert "B_ONLY" not in source["evidence_text"]
        assert "OTHER_KB_ONLY" not in source["evidence_text"]
    md = query(client, "evidence-books", ["notes.md"])
    assert md["sources"][0]["evidence_text"].startswith("MD_ONLY")
    assert not query(client, "evidence-books", [])["sources"]
    assert (
        query(client, "evidence-books", ["../escape.txt"])["error_type"] == "invalid_document_scope"
    )
    assert query(client, "evidence-books")["sources"]


def test_missing_unindexed_replaced_and_legacy_sources(client, books):
    kb, _, _ = books
    (kb / "raw/new.txt").write_text("Not indexed", encoding="utf-8")
    assert query(client, "evidence-books", ["new.txt"])["error_type"] == "document_not_indexed"
    source = kb / "raw/notes.md"
    original = source.read_bytes()
    try:
        source.unlink()
        assert query(client, "evidence-books", ["notes.md"])["error_type"] == "source_missing"
        source.write_text("A replaced book", encoding="utf-8")
        assert query(client, "evidence-books", ["notes.md"])["error_type"] == "source_changed"
        assert all(
            s.get("document_key") != "notes.md" for s in query(client, "evidence-books")["sources"]
        )
    finally:
        source.write_bytes(original)
    sidecar = next(kb.glob(f"version-*/{UNITS_FILE}"))
    saved = sidecar.read_bytes()
    try:
        sidecar.unlink()
        result = query(client, "evidence-books", ["notes.md"])
        assert result["error_type"] == "index_provenance_unavailable"
        legacy = query(client, "evidence-books")
        assert legacy["sources"] and legacy["warnings"]
        assert legacy["sources"][0]["completeness"] == "unknown"
    finally:
        sidecar.write_bytes(saved)
    try:
        incomplete = json.loads(saved)
        next(iter(incomplete["units"].values())).pop("parser_signature")
        sidecar.write_text(json.dumps(incomplete), encoding="utf-8")
        assert (
            query(client, "evidence-books", ["notes.md"])["error_type"]
            == "index_provenance_unavailable"
        )
    finally:
        sidecar.write_bytes(saved)


def test_unsupported_engine_is_rejected_before_retrieval(client, books, monkeypatch):
    from MathCraft.services.rag.service import RAGService
    from services import knowledge

    service = RAGService(kb_base_dir=str(books[0].parent), provider="kiwix")
    monkeypatch.setattr(
        service, "_get_pipeline", lambda _: pytest.fail("unproven engine must not run")
    )
    import asyncio

    result = asyncio.run(service.search("函数", "evidence-books", document_keys=["notes.md"]))
    assert result["error_type"] == "document_scope_unsupported"


def test_generate_chat_save_edit_and_fresh_process_read(client, books, fake_llm):
    response = client.post("/api/generate", json=params())
    assert response.status_code == 200, response.text
    question = response.json()[0]
    assert books[2] in fake_llm[0]
    assert question["sources"][0]["relation"] == "variant_reference"
    assert question["review_status"] == "unreviewed"
    question_id = question["id"]
    original_sources = question["sources"]
    assert client.get(f"/api/questions/{question_id}").json()["sources"] == original_sources
    assert any(q["id"] == question_id for q in client.get("/api/questions").json())
    forged = client.put(
        f"/api/questions/{question_id}", json={"sources": [{"evidence_id": "invented"}]}
    )
    assert forged.status_code == 422
    score = client.put(f"/api/questions/{question_id}", json={"score": 20}).json()
    assert score["review_status"] == "unreviewed"
    edited = client.put(
        f"/api/questions/{question_id}", json={"stem": "计算 $2+2$", "answer": "4"}
    ).json()
    assert edited["sources"] == original_sources
    assert edited["review_status"] == "edited_requires_review"
    # A new interpreter reconstructs the store and source access after restart.
    script = (
        "import json; from services.questions import QuestionStore; "
        f"q=QuestionStore().read({question_id!r}); "
        "print(json.dumps({'status':q.review_status,'sources':len(q.sources),'valid':q.sources[0].source_status}))"
    )
    restarted = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=60
    )
    assert restarted.returncode == 0, restarted.stderr
    assert json.loads(restarted.stdout) == {
        "status": "edited_requires_review",
        "sources": 1,
        "valid": "valid",
    }
    state = {
        "types": [{"type": "compute", "count": 1}],
        "scope": "函数",
        "source_mode": "new",
        "difficulty": "中",
    }
    chat = client.post(
        "/api/chat",
        json={
            "kb_id": "evidence-books",
            "doc_id": "notes.md",
            "message": "生成",
            "slot_state": state,
        },
    ).json()
    assert chat["done"] is True, chat
    assert chat["slot_state"] == state
    assert chat["questions"][0]["sources"][0]["relation"] == "concept_reference"
    # Missing requirements stay missing; the model stub must not be used to fill them.
    partial = {"types": [{"type": "compute", "count": 1}]}
    followup = client.post(
        "/api/chat",
        json={
            "kb_id": "evidence-books",
            "doc_id": "notes.md",
            "message": "继续",
            "slot_state": partial,
        },
    ).json()
    assert followup["done"] is False and not followup["questions"]
    assert followup["slot_state"] == partial


def test_expected_failures_keep_chat_slots_and_do_not_generate(client, books, fake_llm):
    state = {
        "types": [{"type": "compute", "count": 1}],
        "scope": "函数",
        "source_mode": "original",
        "difficulty": "中",
    }
    original = client.post("/api/generate", json=params(source_mode="original"))
    assert original.status_code == 422
    assert original.json()["detail"]["kind"] == "exercise_analysis_unavailable"
    result = client.post(
        "/api/chat",
        json={
            "kb_id": "evidence-books",
            "doc_id": "notes.md",
            "message": "继续",
            "slot_state": state,
        },
    ).json()
    assert result["error_type"] == "exercise_analysis_unavailable"
    assert result["slot_state"] == state and not result["done"] and not result["questions"]
    bad = client.post(
        "/api/chat",
        json={
            "kb_id": "evidence-books",
            "doc_id": "../bad",
            "message": "继续",
            "slot_state": state,
        },
    ).json()
    assert bad["error_type"] == "invalid_document_scope" and bad["slot_state"] == state
    assert not fake_llm


def test_http_engine_gate_and_source_failures_keep_confirmed_slots(
    client, books, fake_llm, monkeypatch
):
    state = {
        "types": [{"type": "compute", "count": 1}],
        "scope": "函数",
        "source_mode": "new",
        "difficulty": "中",
    }
    from MathCraft.services.rag.service import RAGService

    with monkeypatch.context() as gate:
        gate.setattr(RAGService, "_resolve_provider", lambda self, name: "kiwix")
        generated = client.post("/api/generate", json=params(doc="notes.md"))
        assert generated.status_code == 422
        assert generated.json()["detail"]["kind"] == "document_scope_unsupported"
        chat = client.post(
            "/api/chat",
            json={
                "kb_id": "evidence-books",
                "doc_id": "notes.md",
                "message": "继续",
                "slot_state": state,
            },
        ).json()
        assert chat["error_type"] == "document_scope_unsupported" and chat["slot_state"] == state
    path = books[0] / "raw/notes.md"
    original = path.read_bytes()
    try:
        for expected in ("source_changed", "source_missing"):
            if expected == "source_changed":
                path.write_text("Changed", encoding="utf-8")
            else:
                path.unlink()
            generated = client.post("/api/generate", json=params(doc="notes.md"))
            assert generated.json()["detail"]["kind"] == expected
            chat = client.post(
                "/api/chat",
                json={
                    "kb_id": "evidence-books",
                    "doc_id": "notes.md",
                    "message": "继续",
                    "slot_state": state,
                },
            ).json()
            assert chat["error_type"] == expected and chat["slot_state"] == state
            assert not chat["questions"] and not chat["done"]
    finally:
        path.write_bytes(original)
    assert not fake_llm


def test_model_cannot_supply_its_own_source_location(client, books, monkeypatch):
    async def forged(messages):
        evidence_id = re.findall(r"证据 (E-[0-9a-f]+)", messages[-1]["content"])[0]
        return {
            "questions": [
                {
                    "type": "compute",
                    "stem": "伪造页码",
                    "answer": "1",
                    "analysis": "test",
                    "evidence_ids": [evidence_id],
                    "sources": [{"page_indices": [999]}],
                }
            ]
        }

    monkeypatch.setattr("services.question_gen.chat_json", forged)
    response = client.post("/api/generate", json=params(doc="notes.md"))
    assert response.status_code == 422
    assert response.json()["detail"]["kind"] == "invalid_evidence_reference"


def test_frozen_internal_version_never_falls_through_to_another_version(client, books):
    import asyncio
    from MathCraft.services.rag.service import RAGService
    from MathCraft.services.rag.index_versioning import resolve_storage_dir_for_read
    from MathCraft.services.embedding.config import get_embedding_config
    from MathCraft.services.rag.embedding_signature import signature_from_config

    service = RAGService(kb_base_dir=str(books[0].parent))
    version = query(client, "evidence-books", ["notes.md"])["index_version"]
    result = asyncio.run(
        service.search("函数", "evidence-books", document_keys=["notes.md"], _index_version=version)
    )
    assert result["index_version"] == version and result["sources"]
    signature = signature_from_config(get_embedding_config())
    assert (
        resolve_storage_dir_for_read(books[0], signature, version="version-not-published") is None
    )
    rejected = asyncio.run(
        service.search(
            "函数",
            "evidence-books",
            document_keys=["notes.md"],
            _index_version="version-not-published",
        )
    )
    assert rejected["error_type"] == "document_not_indexed" and not rejected["sources"]


@pytest.mark.parametrize("ids", [["invented"], [], ["E-other-document"]])
def test_model_cannot_invent_evidence(client, books, monkeypatch, ids):
    from services import question_gen

    monkeypatch.setattr(
        question_gen,
        "chat_json",
        AsyncMock(
            return_value={
                "questions": [
                    {
                        "type": "compute",
                        "stem": "Bad citation",
                        "answer": "1",
                        "analysis": "test",
                        "evidence_ids": ids,
                    }
                ]
            }
        ),
    )
    before = len(client.get("/api/questions").json())
    response = client.post("/api/generate", json=params())
    assert response.status_code == 422
    assert response.json()["detail"]["kind"] == "invalid_evidence_reference"
    assert len(client.get("/api/questions").json()) == before


def test_missing_image_and_budget_are_explicit(client, fake_llm):
    create(
        client,
        "evidence-limits",
        [
            ("image.md", b"Condition ![figure](missing.png)"),
            ("big.txt", ("Complete condition. " * 1800).encode()),
        ],
    )
    try:
        image = query(client, "evidence-limits", ["image.md"])["sources"][0]
        assert image["completeness"] == "incomplete" and image["image_status"] == "missing"
        for doc, error in [
            ("image.md", "evidence_incomplete"),
            ("big.txt", "evidence_budget_exceeded"),
        ]:
            response = client.post("/api/generate", json=params(doc=doc, kb_id="evidence-limits"))
            assert response.status_code == 422, response.text
            assert response.json()["detail"]["kind"] == error
        assert not fake_llm
    finally:
        client.delete("/api/knowledge-bases/evidence-limits")


def test_old_question_is_readable_without_fabricated_sources(client):
    root = get_runtime_data_root() / "questions"
    root.mkdir(exist_ok=True)
    (root / "legacy-q.json").write_text(
        json.dumps(
            {
                "id": "legacy-q",
                "type": "compute",
                "stem": "旧题",
                "answer": "旧答案",
                "analysis": "旧解析",
                "docName": "仅有旧书名",
            }
        ),
        encoding="utf-8",
    )
    legacy = client.get("/api/questions/legacy-q").json()
    assert legacy["sources"] == [] and legacy["review_status"] == "legacy_unknown"


def test_bm25_and_vector_receive_the_same_allowed_corpus(client, books, monkeypatch):
    from llama_index.core.retrievers import BaseRetriever
    from llama_index.core.schema import NodeWithScore
    from MathCraft.services.rag.pipelines.llamaindex import retrievers

    captured = []

    class LexicalProbe(BaseRetriever):
        @classmethod
        def from_defaults(cls, *, nodes, similarity_top_k):
            captured.extend(nodes)
            instance = cls()
            instance.nodes = nodes
            return instance

        def _retrieve(self, query_bundle):
            return [NodeWithScore(node=node, score=1.0) for node in self.nodes]

    monkeypatch.setattr(retrievers, "_import_bm25_retriever", lambda: LexicalProbe)
    result = query(client, "evidence-books", ["notes.md"])
    assert captured and {node.metadata["document_key"] for node in captured} == {"notes.md"}
    assert {s["document_key"] for s in result["sources"]} == {"notes.md"}
    assert result["retrieval_profile"] == "hybrid"


def test_no_match_and_small_model_budget_are_business_results(client, books, monkeypatch, fake_llm):
    from services import retrieval

    original_retrieve = retrieval.retrieve
    monkeypatch.setattr(retrieval, "retrieve", AsyncMock(return_value=[]))
    response = client.post("/api/generate", json=params())
    assert response.json()["detail"]["kind"] == "no_match"
    monkeypatch.setattr(retrieval, "retrieve", original_retrieve)
    monkeypatch.setattr(
        "services.question_gen.get_llm_config",
        lambda: SimpleNamespace(model="fake-small", context_window=8192, max_tokens=4096),
    )
    response = client.post("/api/generate", json=params())
    assert (
        response.status_code == 422
        and response.json()["detail"]["kind"] == "evidence_budget_exceeded"
    )


def test_saved_source_change_is_visible(client, books, fake_llm):
    generated = client.post("/api/generate", json=params(doc="notes.md")).json()[0]
    path = books[0] / "raw/notes.md"
    original = path.read_bytes()
    try:
        path.write_text("Replaced source", encoding="utf-8")
        assert (
            client.get(f"/api/questions/{generated['id']}").json()["sources"][0]["source_status"]
            == "changed"
        )
        assert client.get(generated["sources"][0]["file_url"]).status_code == 409
        path.unlink()
        assert (
            client.get(f"/api/questions/{generated['id']}").json()["sources"][0]["source_status"]
            == "missing"
        )
    finally:
        path.write_bytes(original)


def test_each_question_uses_only_declared_evidence(client, books, monkeypatch):
    from services import question_gen, retrieval

    base = query(client, "evidence-books", ["notes.md"])["sources"][0]
    hits = [
        {**base, "evidence_id": f"E-{i}", "text": f"完整受控材料 {i}", "doc_name": "notes.md"}
        for i in (1, 2)
    ]
    monkeypatch.setattr(retrieval, "retrieve", AsyncMock(return_value=hits))
    monkeypatch.setattr(
        question_gen,
        "chat_json",
        AsyncMock(
            return_value={
                "questions": [
                    {
                        "type": "compute",
                        "stem": f"受控题目{i}",
                        "answer": str(i),
                        "analysis": "test",
                        "evidence_ids": [f"E-{i}"],
                    }
                    for i in (1, 2)
                ]
            }
        ),
    )
    response = client.post(
        "/api/generate", json=params(doc="notes.md", types=[{"type": "compute", "count": 2}])
    )
    assert response.status_code == 200, response.text
    assert [[s["evidence_id"] for s in q["sources"]] for q in response.json()] == [["E-1"], ["E-2"]]


def pdf_bytes(label):
    import pymupdf

    with pymupdf.open() as doc:
        for n in range(2):
            page = doc.new_page()
            page.insert_text((72, 72), f"Controlled {label} page {n + 1}")
        return doc.tobytes()


def test_numbered_pdf_scope_cross_page_and_exact_fallback(client, monkeypatch, fake_llm):
    from MathCraft.services.parsing import cache
    from MathCraft.services.parsing.service import ParseService
    from MathCraft.services.parsing.types import ParsedDocument
    from MathCraft.services.path_service import get_path_service

    def controlled_parse(self, source_path, **kwargs):
        path = Path(source_path)
        label = "A_PDF" if path.parent.name == "one" else "B_PDF"
        blocks = [
            {"type": "text", "text": "第二章", "text_level": 1, "page_idx": 0},
            {"type": "text", "text": "习题", "page_idx": 0},
            {"type": "text", "text": f"2-13 {label} " + "完整题干条件 " * 100, "page_idx": 0},
            {"type": "text", "text": "跨页末尾必要条件_END", "page_idx": 1},
            {"type": "text", "text": "2-14 下一题", "page_idx": 1},
        ]
        digest = cache.source_hash_from_path(path)
        workdir = cache.reserve(get_path_service().get_parse_cache_root(), digest, "controlled-v1")
        (workdir / "full_content_list.json").write_text(
            json.dumps(blocks, ensure_ascii=False), encoding="utf-8"
        )
        cache.write_manifest(workdir, {"source_hash": digest, "signature": "controlled-v1"})
        return ParsedDocument(
            markdown="\n".join(b["text"] for b in blocks),
            blocks=blocks,
            source_hash=digest,
            parser_signature="controlled-v1",
            engine="mineru",
            workdir=workdir,
        )

    monkeypatch.setattr(ParseService, "_parse", controlled_parse)
    create(
        client,
        "evidence-pdf",
        [("one/shared.pdf", pdf_bytes("A")), ("two/shared.pdf", pdf_bytes("B"))],
    )
    create(client, "evidence-pdf-other", [("one/shared.pdf", pdf_bytes("OTHER"))])
    try:
        exact = query(client, "evidence-pdf", ["one/shared.pdf"], "找习题 2-13")
        assert exact["sources"], exact
        assert exact["sources"][0]["document_key"] == "one/shared.pdf"
        text = exact["sources"][0]["evidence_text"]
        assert len(text) > 200 and "跨页末尾必要条件_END" in text and "B_PDF" not in text
        assert exact["sources"][0]["page_indices"] == [0, 1]
        assert exact["sources"][0]["completeness"] == "unknown"
        assert "source_hash=" in exact["sources"][0]["source_page_urls"][0]
        # A missing structural parse falls back inside the already frozen corpus.
        monkeypatch.setattr(
            "MathCraft.services.rag.pipelines.llamaindex.exercise_lookup._parse_for",
            lambda *a: None,
        )
        fallback = query(client, "evidence-pdf", ["one/shared.pdf"], "找习题 2-13")
        assert fallback["sources"] and all(
            s["document_key"] == "one/shared.pdf" for s in fallback["sources"]
        )
        assert "跨页末尾必要条件_END" in fallback["sources"][0]["evidence_text"]
        generated = client.post(
            "/api/generate", json=params(doc="one/shared.pdf", kb_id="evidence-pdf")
        )
        assert generated.status_code == 200, generated.text
        assert "跨页末尾必要条件_END" in fake_llm[-1]
        page_url = generated.json()[0]["sources"][0]["source_page_urls"][1]
        assert client.get(page_url).status_code == 200
    finally:
        client.delete("/api/knowledge-bases/evidence-pdf")
        client.delete("/api/knowledge-bases/evidence-pdf-other")


def test_failed_candidate_keeps_published_version_but_not_changed_source(
    client, books, monkeypatch
):
    from MathCraft.services.rag.pipelines.llamaindex import storage

    kb = books[0]
    before = query(client, "evidence-books", ["notes.md"])["index_version"]

    def reject(_):
        raise ValueError("controlled publication probe failure")

    monkeypatch.setattr(storage, "verify_persisted_index", reject)
    from MathCraft.services.rag.embedding_binding import default_selection

    accepted = client.post(
        "/api/knowledge-bases/evidence-books/reindex",
        data={"embedding_model": json.dumps(default_selection())},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json().get("task_id"), accepted.text
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        run = client.get("/api/knowledge-bases/evidence-books/indexing-run").json().get("run") or {}
        if run.get("state") in {"failed", "partial", "cancelled"} or run.get("status") in {
            "failed",
            "error",
        }:
            break
        # The publication probe writes no meta.json; its building marker remains.
        candidates = [
            p for p in kb.glob("version-*") if p.name != before and (p / UNITS_FILE).exists()
        ]
        if (
            candidates
            and client.get("/api/knowledge-bases/evidence-books/progress").json().get("stage")
            == "error"
        ):
            break
        time.sleep(0.05)
    else:
        raise AssertionError(f"failed reindex did not terminate: {run}")
    after = query(client, "evidence-books", ["notes.md"])
    assert after["index_version"] == before and after["sources"]
    assert all(
        not json.loads(p.read_text()).get("state") == "published"
        for p in kb.glob("version-*/meta.json")
        if p.parent.name != before
    )
    source = kb / "raw/notes.md"
    original = source.read_bytes()
    try:
        source.write_text("Changed after failed candidate", encoding="utf-8")
        assert query(client, "evidence-books", ["notes.md"])["error_type"] == "source_changed"
    finally:
        source.write_bytes(original)


def test_runtime_home_rename_reads_same_legacy_settings_and_index(tmp_path, monkeypatch):
    from MathCraft.runtime.home import get_runtime_data_root
    from services.questions import QuestionStore

    legacy = tmp_path / "existing-home"
    settings = legacy / "data/user/settings/model_catalog.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"version":1,"services":{}}', encoding="utf-8")
    index = legacy / "data/knowledge_bases/old/version-1"
    index.mkdir(parents=True)
    (index / "docstore.json").write_text('{"docstore/data":{}}', encoding="utf-8")
    (index / "meta.json").write_text(
        '{"provider":"llamaindex","state":"published"}', encoding="utf-8"
    )
    before = {str(p): p.read_bytes() for p in legacy.rglob("*.json")}
    monkeypatch.setenv("MATHCRAFT_HOME", str(legacy))
    monkeypatch.setenv("MATH_Q_HOME", str(tmp_path / "ignored-old-variable"))
    root = get_runtime_data_root()
    assert json.loads((root / "user/settings/model_catalog.json").read_text())["version"] == 1
    from MathCraft.services.rag.index_versioning import resolve_storage_dir_for_read

    assert resolve_storage_dir_for_read(root / "knowledge_bases/old", None) == index
    assert QuestionStore().root == root / "questions"
    assert before == {str(p): p.read_bytes() for p in legacy.rglob("*.json")}
