"""Opt-in acceptance against the local Phoenix container at port 6017."""
import json
import os
import socket
from itertools import count
from time import monotonic, sleep
from uuid import uuid4

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import select

from app.api import chat
from app.config import settings
from app.db import SessionLocal
from app.models import Document, OpsRun
from app.models.base import new_id
from app.services import phoenix_tracing, question_review
from app.services.rag import llm, retrieval, slots
from app.services.rag.prompts import HYDE_SYSTEM
from conftest import create_bank

pytestmark = pytest.mark.skipif(
    os.getenv("MATHCRAFT_PHOENIX_ACCEPTANCE") != "1",
    reason="requires the local Phoenix service on 127.0.0.1:6017",
)
PHOENIX = "http://127.0.0.1:6017"
PROJECT = f"mathcraft-gates-acceptance-{uuid4().hex[:12]}"
PRIVATE = "acceptance-private-marker"
FAKE_KEY = "fake-acceptance-key"
_SOCKET_CONNECT = socket.socket.connect
_CREATE_CONNECTION = socket.create_connection
_REAL_REVIEW = question_review.review_questions
_REAL_LLM = {name: getattr(llm, name) for name in ("chat_json", "chat_text", "chat_stream")}


@pytest.fixture
def phoenix(client, monkeypatch, prohibit_network):
    blocked_connect = socket.socket.connect

    def loopback_only(sock, address):
        if address == ("127.0.0.1", 6017):
            return _SOCKET_CONNECT(sock, address)
        return blocked_connect(sock, address)

    blocked_create = socket.create_connection

    def create_loopback(address, *args, **kwargs):
        if address == ("127.0.0.1", 6017):
            return _CREATE_CONNECTION(address, *args, **kwargs)
        return blocked_create(address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", loopback_only)
    monkeypatch.setattr(socket, "create_connection", create_loopback)
    with httpx.Client(base_url=PHOENIX, trust_env=False, timeout=3) as reader:
        assert reader.get("/healthz").status_code == 200
        assert phoenix_tracing.configure(settings.model_copy(update={
            "phoenix_enabled": True,
            "phoenix_endpoint": f"{PHOENIX}/v1/traces",
            "phoenix_project": PROJECT,
            "phoenix_api_key": SecretStr(""),
            "phoenix_timeout_seconds": 2.0,
            "phoenix_queue_size": 512,
        }))
        try:
            yield reader
        finally:
            phoenix_tracing.shutdown()


def _candidate(stem):
    return {
        "type": "essay", "score": 10, "difficulty": "地狱", "stem": stem,
        "options": [], "answer": "结论成立",
        "analysis": f"由导数定义直接验证结论。{PRIVATE}",
        "knowledgePoint": "导数",
    }


def _install_model(monkeypatch, scenario):
    nominations = count(1)
    false_stems = iter(("偶函数的导数恒正", "可导函数必严格递增", "驻点必为极大值"))
    fixed_stem = f"用导数定义证明常值函数导数为零。{PRIVATE}"

    def reply(request):
        assert request.headers["authorization"] == f"Bearer {FAKE_KEY}"
        data = json.loads(request.content)
        prompt = data["messages"][-1]["content"]
        if data.get("stream"):
            number = next(nominations)
            if scenario == "shortfall" and number >= 4:
                raise httpx.ReadTimeout(PRIVATE, request=request)
            stem = fixed_stem if scenario == "normal" else (
                f"证明{next(false_stems)}。{PRIVATE}"
            )
            content = json.dumps({"questions": [_candidate(stem)]}, ensure_ascii=False)
            chunk = {"object": "chat.completion.chunk", "choices": [
                {"index": 0, "delta": {"content": content}, "finish_reason": "stop"},
            ]}
            return httpx.Response(
                200, text=f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n",
                headers={"Content-Type": "text/event-stream"},
            )

        if data["messages"][0]["content"] == HYDE_SYSTEM:
            return _completion(f"导数定义教材片段。{PRIVATE}")
        if prompt.startswith("下面这道题没有通过"):
            assert f"反例 {PRIVATE}" in prompt
            result = _candidate(fixed_stem if scenario == "repair" else (
                f"证明可导函数的导数处处为正。{PRIVATE}"
            ))
        elif "【待核验的候选答案】" in prompt:
            result = {"analysis": _candidate(fixed_stem)["analysis"], "conclusion": "结论成立"}
        elif "【题干】" in prompt:
            result = (
                {"status": "solved", "answer": "结论成立", "evidence": PRIVATE}
                if fixed_stem in prompt else
                {"status": "false_proposition", "answer": "", "evidence": f"反例 {PRIVATE}"}
            )
        elif "stemValid" in prompt:
            result = {
                "scores": dict.fromkeys(("knowledge", "steps", "abstraction",
                                         "computation", "trap", "unique"), 5),
                "methods": ["定义", "验证"], "passed": True, "verifiable": True,
                "evidence": PRIVATE, "stemValid": True, "scopeValid": True,
                "optionsValid": True, "answerValid": True, "analysisValid": True,
            }
        else:
            pytest.fail("unexpected model request")

        return _completion(json.dumps(result, ensure_ascii=False))

    def _completion(content):
        return httpx.Response(200, json={"choices": [{
            "index": 0, "message": {"role": "assistant",
                                    "content": content},
            "finish_reason": "stop",
        }]})

    for name, original in _REAL_LLM.items():
        monkeypatch.setattr(llm, name, original)
    monkeypatch.setattr(llm, "_clients", {})
    monkeypatch.setattr(llm, "MetadataClient", lambda model: phoenix_tracing.MetadataClient(
        model, transport=httpx.MockTransport(reply),
    ))
    monkeypatch.setattr(question_review, "review_questions", _REAL_REVIEW)
    monkeypatch.setattr(retrieval, "retrieve_for_generation", lambda *a, **k: [
        {"text": f"导数定义、可导函数与驻点。{PRIVATE}"},
    ])


def _read_trace(reader, run_id):
    deadline = monotonic() + 12
    while monotonic() < deadline:
        response = reader.get(f"/v1/projects/{PROJECT}/spans", params={"limit": 1000})
        if response.status_code != 404:
            response.raise_for_status()
            spans = [span for span in response.json()["data"]
                     if _attr(span, "mathcraft.run_id") == run_id]
            if any(span["parent_id"] is None for span in spans):
                return spans
        sleep(0.1)
    pytest.fail(f"Phoenix did not return root span for {PROJECT=} {run_id=}")


def _attr(span, name):
    attrs = span["attributes"]
    if name in attrs:
        return attrs[name]
    for part in name.split("."):
        if not isinstance(attrs, dict):
            return None
        attrs = attrs.get(part)
    return attrs


@pytest.mark.parametrize("scenario", ["normal", "repair", "shortfall"])
def test_teacher_question_trace(client, teacher, phoenix, monkeypatch, scenario):
    _install_model(monkeypatch, scenario)
    bank = create_bank(client, teacher)
    owner = client.get("/api/auth/me", headers=teacher).json()["user"]["id"]
    doc_id = new_id("doc")
    with SessionLocal.begin() as db:
        db.add(Document(id=doc_id, bank_id=bank["id"], name="synthetic.md", format="MD",
                        size_bytes=1, storage_path="synthetic.md", status="ready",
                        uploader_id=owner))
    model_settings = client.put("/api/users/me/model-settings", headers=teacher,
                                json={"deepseek_api_key": FAKE_KEY})
    assert model_settings.status_code == 200
    params = {"types": [{"type": "essay", "count": 1}], "difficulty": "地狱",
              "source_mode": "variant_data", "scope": "导数"}
    resources = {"bank_id": bank["id"], "document_id": doc_id}
    if scenario == "shortfall":
        monkeypatch.setattr(chat, "detect_intent", lambda *a, **k: {
            "intent": "generate", "confidence": "high",
        })
        monkeypatch.setattr(slots, "chat_json", lambda *a, **k: params)
        session = client.post("/api/chat/sessions", headers=teacher, json=resources)
        session_id = session.json()["session_id"]
        response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                               json={"message": "出一道地狱档导数简答题，改数据"})
        assert response.status_code == 200, response.text
        result = response.json()
        assert "请求 1 道，交付 0 道，缺额 1 道" in result["reply"], result
        assert "命题为假 3 道" in result["reply"], result
        assert "模型响应超时，请稍后重试 1 次" in result["reply"], result
    elif scenario == "repair":
        start = client.post("/api/generate/start", headers=teacher, json=params | resources)
        assert start.status_code == 202, start.text
        task_id = start.json()["task_id"]
        response = client.get(f"/api/generate/progress/{task_id}", headers=teacher)
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["status"] == "done", result
    else:
        response = client.post("/api/generate?include_review=true", headers=teacher,
                               json=params | resources)
        assert response.status_code == 200, response.text
        result = response.json()

    delivered = int(scenario != "shortfall")
    assert len(result["questions"]) == delivered, result
    if delivered:
        group, = result["review"]["groups"]
        assert (group["requested"], group["delivered"], group["missing"]) == (1, 1, 0)
        assert result["questions"][0]["difficulty"] == "地狱"
    with SessionLocal() as db:
        run, = db.scalars(select(OpsRun)).all()
    assert run.requested_count == 1 and run.delivered_count == delivered
    spans = _read_trace(phoenix, run.run_id)
    root, = [span for span in spans if span["parent_id"] is None]
    trace_id = root["context"]["trace_id"]
    print(f"{PROJECT} {scenario} run_id={run.run_id} trace_id={trace_id} spans={len(spans)}")
    assert all(span["context"]["trace_id"] == trace_id for span in spans)
    assert PRIVATE not in json.dumps(spans)
    assert FAKE_KEY not in json.dumps(spans)

    by_id = {span["context"]["span_id"]: span for span in spans}
    assert all(span["parent_id"] in by_id for span in spans if span is not root)

    def stage(name):
        return [span for span in spans if _attr(span, "mathcraft.stage") == name]

    def models(parent):
        return [span for span in spans if span["name"] == "openai.chat.completions"
                and span["parent_id"] == parent["context"]["span_id"]]

    summary, = stage("summary")
    assert [_attr(summary, f"mathcraft.{key}") for key in
            ("question_type", "target_difficulty", "decision", "requested", "delivered",
             "missing")] == ["essay", "地狱", "committed", 1, delivered, 1 - delivered]

    rejected = [span for span in stage("independent_solve")
                if _attr(span, "mathcraft.reason_code") == "false_proposition"]
    assert len(rejected) == {"normal": 0, "repair": 1, "shortfall": 6}[scenario]
    for span in rejected:
        assert _attr(span, "mathcraft.decision") == "rejected"
        model, = models(span)
        assert model["status_code"] == "OK"
        assert _attr(model, "http.response.status_code") == 200

    if scenario != "normal":
        for repair in stage("repair"):
            candidate = _attr(repair, "mathcraft.candidate_id")
            same = [span for span in stage("independent_solve")
                    if _attr(span, "mathcraft.candidate_id") == candidate]
            assert {_attr(span, "mathcraft.revision") for span in same} == {0, 1}
            assert _attr(repair, "mathcraft.reason_code") == "false_proposition"
            assert _attr(repair, "mathcraft.decision") == "passed"
            assert all(_attr(span, "http.response.status_code") == 200 for span in models(repair))
        assert stage("re_review")
    if delivered:
        final, = stage("final_acceptance")
        assert _attr(final, "mathcraft.decision") == "passed"
        assert models(final)
    else:
        assert {_attr(span, "mathcraft.refill_round") for span in stage("refill")} == {1, 2, 3}
        assert {_attr(span, "mathcraft.refill_round") for span in rejected} == {0, 1, 2}
        assert _attr(summary, "mathcraft.rejections.false_proposition") == 3
        assert _attr(summary, "mathcraft.generation_events.model_timeout") == 1
        timeouts = [span for span in spans if _attr(span, "error.type") == "TIMEOUT"]
        assert timeouts
        for span in timeouts:
            parent = by_id[span["parent_id"]]
            assert _attr(parent, "mathcraft.stage") == "nomination"
            assert _attr(parent, "mathcraft.refill_round") == 3
            assert span["status_code"] == "ERROR"
            assert _attr(span, "http.response.status_code") is None
