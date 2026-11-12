"""Actual HTTP/SDK business G0 against an explicitly isolated local Phoenix.

Importing this module does not import the app, read configuration, create clients,
or write files. Run in a fresh process with TEMP/TMP in the authorized D: .scratch.
Only the model HTTP transport and retrieval/embedding service boundaries are fake.
The fixture module is imported, never its pytest autouse model substitutions.
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator, Iterator, Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from contextvars import ContextVar, copy_context
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import hashlib
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import re
import socket
import sys
import threading
import time
from types import ModuleType
from typing import TYPE_CHECKING, cast
from unittest.mock import patch
from urllib.parse import urlsplit

if TYPE_CHECKING:
    import httpx
    from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
MODEL_URL = "https://models.example.test/v1"
BODY_MARKER = "G0_PRIVATE_BODY_"
CASES = (
    "sync_success", "async_success", "model_failure", "review_degraded",
    "chat_fast", "chat_creative", "chat_cancel", "reply_commit_failure",
    "concurrency", "chat_same_session", "recovery_sync",
)
_case: ContextVar[Case | None] = ContextVar("ops_g0_business_case", default=None)


class GateError(RuntimeError):
    """An intentionally content-free acceptance failure."""


def require(condition: object, code: str) -> None:
    """Fail with a fixed diagnostic code, never provider/configuration content."""
    if not condition:
        raise GateError(code)


def mapping(value: object) -> dict[str, object]:
    """Narrow public JSON at its boundary."""
    require(isinstance(value, dict) and all(isinstance(k, str) for k in value), "json_shape")
    return cast(dict[str, object], value)


def validate_base_url(value: str) -> str:
    """Allow an explicit numeric loopback HTTP origin, excluding old Phoenix 6016."""
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "::1"}
            and parsed.port is not None and parsed.port != 6016
            and not parsed.username and not parsed.password
            and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment
        )
    except ValueError:
        valid = False
    require(valid, "isolated_loopback_origin_required")
    return value.rstrip("/")


def validate_label(value: str) -> str:
    """Restrict API paths to a new, explicitly synthetic business project."""
    require(re.fullmatch(r"ops-g0-business-[A-Za-z0-9-]{1,80}", value), "business_label")
    return value


class _Discard(io.TextIOBase):
    def write(self, value: str) -> int:
        return len(value)


@contextmanager
def quiet() -> Iterator[None]:
    """Drop library output rather than retaining potentially sensitive exceptions."""
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        with redirect_stdout(_Discard()), redirect_stderr(_Discard()):
            yield
    finally:
        logging.disable(previous)


@dataclass
class NetworkGuard:
    """Count and refuse every socket destination except this one Phoenix origin."""

    port: int
    blocked: int = 0
    allowed: int = 0
    _pair: threading.local = field(default_factory=threading.local, repr=False)

    @contextmanager
    def installed(self) -> Iterator[None]:
        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_pair = socket.socketpair
        original_resolve = socket.getaddrinfo

        def allowed(address: object) -> bool:
            if getattr(self._pair, "active", False):
                return True
            valid = (
                isinstance(address, tuple) and len(address) >= 2
                and address[0] in {"127.0.0.1", "::1"} and address[1] == self.port
            )
            if valid:
                self.allowed += 1
                return True
            self.blocked += 1
            raise GateError("external_socket_blocked")

        def connect(instance: socket.socket, address: object) -> None:
            if allowed(address):
                original_connect(instance, address)

        def connect_ex(instance: socket.socket, address: object) -> int:
            allowed(address)
            return original_connect_ex(instance, address)

        def pair(*args: object, **kwargs: object) -> tuple[socket.socket, socket.socket]:
            self._pair.active = True
            try:
                return original_pair(*args, **kwargs)
            finally:
                self._pair.active = False

        def resolve(host: object, port: object, *args: object, **kwargs: object) -> object:
            allowed((host, port))
            return original_resolve(host, port, *args, **kwargs)

        with ExitStack() as stack:
            stack.enter_context(patch.object(socket.socket, "connect", connect))
            stack.enter_context(patch.object(socket.socket, "connect_ex", connect_ex))
            stack.enter_context(patch.object(socket, "socketpair", pair))
            stack.enter_context(patch.object(socket, "getaddrinfo", resolve))
            yield


class Phoenix:
    """Read private authorization once; query only this fresh project's public API."""

    def __init__(self, home: Path, base_url: str, label: str) -> None:
        import httpx

        self.label = validate_label(label)
        self.base_url = validate_base_url(base_url)
        home = home.resolve(strict=True)
        private = (home / "private.json").resolve(strict=True)
        require(private.parent == home, "private_path_outside_home")
        config = mapping(json.loads(private.read_text(encoding="utf-8")))
        admin, export = config.get("admin_secret"), config.get("export_key")
        require(isinstance(admin, str) and admin, "phoenix_admin_unavailable")
        require(isinstance(export, str) and export, "export_key_not_prepared")
        self.export_key = cast(str, export)
        self.canaries = [str(v) for v in config.values() if isinstance(v, str) and v]
        self.client = httpx.Client(
            base_url=self.base_url, timeout=4, trust_env=False,
            follow_redirects=False, headers={"Authorization": "Bearer " + cast(str, admin)},
        )

    def fresh(self) -> None:
        response = self.client.get("/v1/projects/" + self.label)
        require(response.status_code == 404, "fresh_business_project_required")

    def spans(self) -> list[dict[str, object]]:
        spans: list[dict[str, object]] = []
        cursor: str | None = None
        for _ in range(10):
            params: dict[str, str | int] = {"limit": 1000}
            if cursor:
                params["cursor"] = cursor
            response = self.client.get("/v1/projects/" + self.label + "/spans", params=params)
            if response.status_code == 404:
                return []
            require(response.status_code == 200, "phoenix_query_status")
            page = mapping(response.json())
            data = page.get("data")
            require(isinstance(data, list), "phoenix_page_shape")
            spans.extend(mapping(item) for item in cast(list[object], data))
            cursor = cast(str | None, page.get("next_cursor"))
            if not cursor:
                return spans
        raise GateError("phoenix_pagination_limit")

    def close(self) -> None:
        self.client.close()


@dataclass
class Case:
    """Only safe facts are serialized; transport bodies remain ephemeral."""

    name: str
    owner: str
    behavior: str = "success"
    account: str = "teacher"
    scope: str = "http_business"
    events: list[dict[str, object]] = field(default_factory=list)
    wire: list[dict[str, object]] = field(default_factory=list)
    checks: dict[str, bool] = field(default_factory=dict)
    http_status: int | None = None
    generated: int = 0
    commits: int = 0
    streams: int = 0
    closed_streams: int = 0
    session_id: str | None = None
    batch_id: str | None = None
    task_id: str | None = None
    question_ids: list[str] = field(default_factory=list)
    error_code: str | None = None
    entered: threading.Event = field(default_factory=threading.Event, repr=False)
    release: threading.Event = field(default_factory=threading.Event, repr=False)
    barrier: threading.Barrier | None = field(default=None, repr=False)
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def collect(self, event: object) -> None:
        with self.lock:
            self.events.append(asdict(event))

    def evidence(self) -> dict[str, object]:
        return {
            key: value for key, value in vars(self).items()
            if key not in {"entered", "release", "barrier", "lock", "behavior"}
        }


def _question(case: Case, phase: str) -> dict[str, object]:
    return {
        "type": "single", "score": 5, "difficulty": "中", "knowledgePoint": "导数",
        "stem": f"{BODY_MARKER}{case.name}_{phase}_{case.generated} 求函数导数。",
        "options": [{"label": label, "text": label} for label in "ABCD"],
        "answer": "A", "analysis": BODY_MARKER + "draft_analysis",
    }


class ModelWire:
    """A real OpenAI HTTPX transport, shared by pre-run legacy and native SDK calls."""

    def __init__(self) -> None:
        self.keys: dict[str, str] = {}
        self.clients: list[object] = []

    def respond(self, request: httpx.Request) -> httpx.Response:
        import httpx

        from app.services import generation_observation as observation
        from app.services.rag.prompts import SLOT_EXTRACT_SYSTEM, SOLVE_SYSTEM

        case = _case.get()
        require(case is not None, "model_request_outside_case")
        case = cast(Case, case)
        require(str(request.url) == MODEL_URL + "/chat/completions", "model_mock_origin")
        require(request.headers.get("authorization") == "Bearer " + self.keys[case.owner],
                "model_account_key_mismatch")
        body = mapping(json.loads(request.content))
        messages = cast(list[dict[str, object]], body.get("messages", []))
        texts = [str(m.get("content", "")) for m in messages]
        system, prompt = texts[0] if texts else "", "\n".join(texts)
        streaming = body.get("stream") is True
        kind = (
            "generation" if streaming else "slots" if system == SLOT_EXTRACT_SYSTEM
            else "solve" if system == SOLVE_SYSTEM else "repair" if "请只做最小修补" in prompt
            else "review" if "独立数学审题人" in prompt
            else "planning" if "细分考点" in prompt else "text"
        )
        run = observation.current_run()
        if run is not None:
            require(run.owner_user_id == case.owner and run.backend == "sdk", "wire_run_owner")
        with case.lock:
            case.wire.append({
                "kind": kind, "stream": streaming, "run_id": run.run_id if run else None,
                "owner_user_id": run.owner_user_id if run else case.owner,
                "session_id": run.session_id if run else case.session_id,
                "backend": run.backend if run else "pre_run_legacy",
            })
        if case.barrier is not None and kind == "generation" and not case.checks.get(
            "provider_barrier_entered"
        ):
            case.checks["provider_barrier_entered"] = True
            case.barrier.wait(timeout=10)
            case.checks["provider_overlap_confirmed"] = True
        if (case.behavior == "model_failure" and kind == "generation") or (
            case.behavior == "review_degraded" and kind == "review"
        ):
            return httpx.Response(503, json={"error": {
                "message": BODY_MARKER + "model_failure", "type": "synthetic_error",
            }})
        if kind == "generation":
            case.generated += 1
            phase = "regenerated" if case.generated > 1 else "initial"
            content = json.dumps({"questions": [_question(case, phase)]}, ensure_ascii=False)
        elif kind == "slots":
            content = json.dumps({
                "types": [{"type": "single", "count": 1}], "scope": "导数",
                "difficulty": "中", "source_mode": "variant_data", "mixed_difficulty": False,
            }, ensure_ascii=False)
        elif kind == "repair":
            content = json.dumps(_question(case, "repaired"), ensure_ascii=False)
        elif kind == "review":
            passed = case.behavior != "repair_regen" or "regenerated" in prompt
            content = json.dumps({
                "scores": {key: (5 if key == "unique" else 2) if passed else 1 for key in
                           ("knowledge", "steps", "abstraction", "computation", "trap", "unique")},
                "passed": passed, "defectCodes": [] if passed else ["A"],
                "primarySuggestion": "调整参数", "methods": ["独立求导"],
                "independentAnswer": "A",
            }, ensure_ascii=False)
        elif kind == "solve":
            content = json.dumps({"answer": "A", "analysis": BODY_MARKER + "solved_analysis",
                                  "confidence": "high"}, ensure_ascii=False)
        elif kind == "planning":
            content = json.dumps({"points": ["导数定义", "乘法法则"]}, ensure_ascii=False)
        else:
            content = BODY_MARKER + "hypothetical_derivative_document"
        if not streaming:
            return httpx.Response(200, json={
                "id": "chatcmpl-g0-fake", "object": "chat.completion", "created": 1,
                "model": "g0-fake-model", "choices": [{"index": 0, "finish_reason": "stop",
                    "message": {"role": "assistant", "content": content, "refusal": None}}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            })

        class Stream(httpx.SyncByteStream, httpx.AsyncByteStream):
            def __init__(self) -> None:
                self.closed = False
                case.streams += 1

            def __iter__(self) -> Iterator[bytes]:
                raise GateError("sse_requires_native_async_model")
                yield b""  # pragma: no cover

            async def __aiter__(self) -> AsyncIterator[bytes]:
                if case.behavior == "cancel":
                    case.entered.set()
                    ready = await asyncio.to_thread(case.release.wait, 15)
                    require(ready, "cancel_release_timeout")
                for part in [content[i:i + 32] for i in range(0, len(content), 32)]:
                    chunk = {"id": "chatcmpl-g0-fake", "created": 1,
                             "object": "chat.completion.chunk", "model": "g0-fake-model",
                             "choices": [{"index": 0, "delta": {"content": part},
                                          "finish_reason": None}]}
                    yield ("data: " + json.dumps(chunk) + "\n\n").encode()
                terminal = {"id": "chatcmpl-g0-fake", "created": 1,
                            "object": "chat.completion.chunk", "model": "g0-fake-model",
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}
                yield ("data: " + json.dumps(terminal) + "\n\n").encode()
                yield b"data: [DONE]\n\n"

            def close(self) -> None:
                if not self.closed:
                    case.closed_streams += 1
                    self.closed = True

            async def aclose(self) -> None:
                self.close()

        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Stream())

    def async_client(self, api_key: str | None, state: object = None) -> object:
        import httpx
        from openai import AsyncOpenAI

        hooks = {"response": [getattr(state, "on_response")]} if state is not None else None
        client = AsyncOpenAI(
            api_key=api_key, base_url=MODEL_URL, max_retries=0,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self.respond),
                                         trust_env=False, event_hooks=hooks),
        )
        self.clients.append(client)
        return client

    def sync_client(self, api_key: str | None = None) -> object:
        import httpx
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=MODEL_URL, max_retries=0,
                        http_client=httpx.Client(transport=httpx.MockTransport(self.respond),
                                                 trust_env=False))
        self.clients.append(client)
        return client


def isolated_fixtures() -> ModuleType:
    """Import the existing isolation before any app import; never execute autouse."""
    require("app.config" not in sys.modules, "fresh_process_required")
    spec = importlib.util.spec_from_file_location(
        "_ops_business_isolated_fixtures", ROOT / "backend/tests/conftest.py",
    )
    require(spec is not None and spec.loader is not None, "fixtures_unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(getattr(module, "_test_secrets") is sys.modules.get("app.local_secrets"),
            "fake_secrets_required")
    return module


def fake_embeddings(texts: list[str]) -> list[list[float]]:
    """Deterministic orthogonal-ish vectors: identical text matches, new text differs."""
    return [[1.0 if bit & 1 else -1.0 for bit in hashlib.sha512(text.encode()).digest()]
            for text in texts]


class BusinessHarness:
    """Drive actual auth, HTTP generation/review, cancellation and SQL transactions."""

    def __init__(self, fixtures: ModuleType, phoenix: Phoenix) -> None:
        self.fixtures, self.phoenix = fixtures, phoenix
        self.wire = ModelWire()
        self.cases: list[Case] = []
        self.headers: dict[str, dict[str, str]] = {}
        self.owners: dict[str, str] = {}
        self.bank_id = ""
        self.doc_id = ""
        self.client: TestClient

    def install(self, stack: ExitStack) -> None:
        import fakeredis
        from sqlalchemy.orm import Session

        from app.config import settings
        from app.db import engine
        from app.services import agent_sdk, cache
        from app.services.rag import embeddings, llm, rerank, retrieval

        require(Path(cast(str, engine.url.database)).resolve().is_relative_to(
            self.fixtures.TEST_ROOT.resolve()), "isolated_database_required")
        for name, value in {
            "generation_llm_backend": "sdk", "agent_trace_enabled": True,
            "agent_trace_endpoint": self.phoenix.base_url + "/v1/traces",
            "agent_trace_api_key": self.phoenix.export_key,
            "agent_trace_project": self.phoenix.label, "agent_trace_queue_capacity": 1024,
            "agent_trace_timeout_seconds": 1.0, "deepseek_base_url": MODEL_URL,
            "deepseek_model": "g0-fake-model",
        }.items():
            stack.enter_context(patch.object(settings, name, value))
        redis = fakeredis.FakeRedis(decode_responses=True)
        stack.callback(redis.close)
        stack.enter_context(patch.object(cache, "get_redis", lambda: redis))
        stack.enter_context(patch.object(agent_sdk, "_new_client", self.wire.async_client))
        stack.enter_context(patch.object(llm, "get_client", self.wire.sync_client))
        stack.enter_context(patch.object(embeddings, "embed_texts", fake_embeddings))
        stack.enter_context(patch.object(embeddings, "embed_one", lambda t: fake_embeddings([t])[0]))
        stack.enter_context(patch.object(rerank, "rerank", self.fixtures.fake_rerank))
        stack.enter_context(patch.object(retrieval, "retrieve_for_generation", lambda *a, **k: [{
            "text": BODY_MARKER + "derivative_reference", "section": "导数", "chunk_id": "g0chunk",
            "document_id": self.doc_id, "doc_name": "fake-notes.md", "chunk_type": "general",
        }]))
        original_commit = Session.commit

        def commit(session: Session) -> None:
            from app.services.generation_observation import current_run
            case = _case.get()
            if case is not None and current_run() is not None:
                case.commits += 1
                if case.behavior == "reply_commit_failure" and case.commits == 2:
                    from sqlalchemy.exc import OperationalError
                    raise OperationalError("synthetic commit failure", {}, RuntimeError("fake"))
            original_commit(session)

        stack.enter_context(patch.object(Session, "commit", commit))
        from app.services.auth_delivery import get_turnstile_verifier

        class Verifier:
            def verify(self, token: str, action: str, remote_ip: str) -> None:
                require(token == "test-turnstile-token", "fake_turnstile_token")

        stack.enter_context(patch.dict(self.fixtures.fastapi_app.dependency_overrides,
                                      {get_turnstile_verifier: lambda: Verifier()}))
        self.fixtures._reset_database()
        self.fixtures._seed_users()
        self.seed_second_teacher()

    @staticmethod
    def seed_second_teacher() -> None:
        """Add one fake teacher to the already validated disposable SQLite database."""
        from app.db import SessionLocal
        from app.models import User, UserModelSetting
        from app.models.base import new_id
        from app.services.auth import hash_password

        with SessionLocal() as db:
            teacher = User(
                id=new_id("u"), account="teacher2", password_hash=hash_password("123123"),
                role="teacher", identity="教师", display_name="G0 second teacher",
                user_no="TKG00002", email="teacher2@example.test",
                email_normalized="teacher2@example.test", email_verified=True,
                email_verified_at=datetime.now(UTC), school="G0 synthetic school", status="active",
            )
            db.add(teacher)
            db.flush()
            db.add(UserModelSetting(user_id=teacher.id))
            db.commit()

    def seed_http(self, client: TestClient) -> None:
        from app.db import SessionLocal
        from app.models import Document
        from app.models.base import new_id

        self.client = client
        for account in ("teacher", "teacher2", "student"):
            response = client.post("/api/auth/login/account", json={
                "account": account, "password": "123123",
                "turnstile_token": "test-turnstile-token",
            })
            require(response.status_code == 200, "fake_account_login")
            headers = {"Authorization": "Bearer " + response.json()["access_token"]}
            self.headers[account] = headers
            me = client.get("/api/auth/me", headers=headers)
            require(me.status_code == 200, "fake_account_identity")
            if account in {"teacher", "teacher2"}:
                require(me.json()["user"]["role"] == "teacher", "teacher_role_required")
            self.owners[account] = me.json()["user"]["id"]
            key = "g0-fake-model-key-" + account
            self.wire.keys[self.owners[account]] = key
            saved = client.put("/api/users/me/model-settings", headers=headers,
                               json={"deepseek_api_key": key})
            require(saved.status_code == 200, "fake_model_setting")
        bank = client.post("/api/banks", headers=self.headers["teacher"],
                           json={"name": "G0 synthetic bank"})
        require(bank.status_code == 201, "fake_bank_creation")
        self.bank_id = bank.json()["id"]
        member = client.post(f"/api/banks/{self.bank_id}/members",
                             headers=self.headers["teacher"],
                             json={"account": "teacher2", "role": "editor"})
        require(member.status_code == 201, "second_teacher_membership")
        self.doc_id = new_id("doc")
        with SessionLocal() as db:
            db.add(Document(
                id=self.doc_id, bank_id=self.bank_id, name="fake-notes.md", format="MD",
                size_bytes=0, storage_path=str(self.fixtures.TEST_ROOT / "fake-notes.md"),
                status="ready", uploader_id=self.owners["teacher"],
            ))
            db.commit()

    def body(self) -> dict[str, object]:
        return {"bank_id": self.bank_id, "document_id": self.doc_id,
                "types": [{"type": "single", "count": 1}], "difficulty": "中",
                "scope": "导数", "source_mode": "variant_data", "existing_stems": []}

    def session(self, case: Case) -> str:
        response = self.client.post("/api/chat/sessions", headers=self.headers[case.account],
                                    json={"bank_id": self.bank_id, "document_id": self.doc_id})
        require(response.status_code == 201, "chat_session_creation")
        case.session_id = response.json()["session_id"]
        return cast(str, case.session_id)

    def message(self, case: Case, mode: str = "generate") -> httpx.Response:
        return self.client.post(
            f"/api/chat/sessions/{case.session_id}/messages", headers=self.headers[case.account],
            json={"message": ("创新命题" if mode == "creative" else "出题") +
                  "：导数，1道单选题，中等难度，改数据。", "mode": mode},
        )

    def execute(
        self, name: str, *, account: str = "teacher",
        barrier: threading.Barrier | None = None, session_id: str | None = None,
    ) -> Case | None:
        from app.services import generation_observation as observation

        if name == "concurrency":
            self.concurrent_http()
            return None
        if name == "chat_same_session":
            self.repeat_conversation()
            return None
        behavior = {"model_failure": "model_failure", "review_degraded": "review_degraded",
                    "chat_creative": "repair_regen", "chat_cancel": "cancel",
                    "reply_commit_failure": "reply_commit_failure"}.get(name, "success")
        case = Case(name, self.owners[account], behavior, account=account,
                    barrier=barrier, session_id=session_id)
        self.cases.append(case)
        token = _case.set(case)
        try:
            with observation.event_sink(case.collect):
                if name.startswith("chat_") or name == "reply_commit_failure":
                    if case.session_id is None:
                        self.session(case)
                    if name == "chat_cancel":
                        with ThreadPoolExecutor(max_workers=1) as pool:
                            future = pool.submit(copy_context().run, self.message, case)
                            try:
                                require(case.entered.wait(10), "cancel_model_not_entered")
                                canceled = self.client.post(
                                    f"/api/chat/sessions/{case.session_id}/cancel",
                                    headers=self.headers[case.account],
                                )
                                require(canceled.status_code == 202, "cancel_http_status")
                            finally:
                                case.release.set()
                            response = future.result(timeout=20)
                    else:
                        response = self.message(case, "creative" if name == "chat_creative"
                                                else "generate")
                elif name in {"async_success", "model_failure"}:
                    started = self.client.post("/api/generate/start", json=self.body(),
                                               headers=self.headers[case.account])
                    require(started.status_code == 202, "async_start_status")
                    case.task_id = started.json()["task_id"]
                    response = self.client.get(f"/api/generate/progress/{case.task_id}",
                                               headers=self.headers[case.account])
                else:
                    response = self.client.post("/api/generate", json=self.body(),
                                                headers=self.headers[case.account])
                case.http_status = response.status_code
                if name == "reply_commit_failure":
                    require(response.status_code >= 500 and case.commits == 2,
                            "second_commit_fault_not_observed")
                else:
                    require(response.status_code == 200, "business_http_status")
                    result = response.json()
                    if name == "model_failure":
                        require(result.get("done") and result.get("error"), "async_failure_state")
                    elif name == "chat_cancel":
                        require(not result.get("questions") and not result.get("batch_id"),
                                "cancel_created_questions")
                    else:
                        questions = result if isinstance(result, list) else result.get("questions")
                        require(isinstance(questions, list) and len(questions) == 1,
                                "business_question_count")
            self.verify_case(case)
            if barrier is not None:
                require(case.checks.get("provider_overlap_confirmed"), "http_overlap_missing")
                case.checks["separate_login_http_generation_verified"] = True
        except Exception as exc:
            case.error_code = str(exc) if isinstance(exc, GateError) else type(exc).__name__
        finally:
            case.release.set()
            _case.reset(token)
        return case

    def verify_case(self, case: Case) -> None:
        from app.db import SessionLocal
        from app.models import ChatMessage, GenerationBatch, Question

        ended = [e for e in case.events if event_name(e) == "run.ended"]
        require(len(ended) == 1, "run_terminal_count")
        run_id = ended[0]["run_id"]
        expected = "failed" if case.behavior in {"model_failure", "reply_commit_failure"} else (
            "cancelled" if case.behavior == "cancel" else "completed")
        require(mapping(ended[0]["metadata"]).get("status") == expected, "run_terminal_status")
        require(all(e["run_id"] == run_id and e["owner_user_id"] == case.owner
                    and e["backend"] == "sdk" for e in case.events), "event_run_correlation")
        committed = [e for e in case.events if event_name(e) == "delivery.committed"
                     and mapping(e["metadata"]).get("kind") == "batch"]
        if case.behavior in {"model_failure", "cancel"}:
            require(not committed, "failed_or_cancelled_batch_commit")
        else:
            require(len(committed) == 1, "batch_delivery_count")
            case.batch_id = cast(str, committed[0]["batch_id"])
            with SessionLocal() as db:
                batch = db.get(GenerationBatch, case.batch_id)
                require(batch is not None and batch.user_id == case.owner, "sql_batch_owner")
                rows = db.query(Question).filter(Question.batch_id == case.batch_id).all()
                case.question_ids = sorted(row.id for row in rows)
                delivered = [mapping(e["metadata"]) for e in case.events
                             if event_name(e) == "delivery.question"]
                require(sorted(str(e["question_id"]) for e in delivered) == case.question_ids,
                        "sql_delivery_question_set")
                revisions = {mapping(e["metadata"])["question_id"]: mapping(e["metadata"])
                             for e in case.events if event_name(e) == "question.revised"}
                require(all(revision_id(e) == revision_id(revisions[e["question_id"]])
                            for e in delivered), "delivered_revision_mismatch")
                if case.behavior == "reply_commit_failure":
                    assistant = db.query(ChatMessage).filter(
                        ChatMessage.session_id == case.session_id,
                        ChatMessage.role == "assistant",
                    ).count()
                    require(assistant == 0, "failed_reply_persisted")
                    require(any(event_name(e) == "delivery.failed" and
                                mapping(e["metadata"]).get("kind") == "assistant_reply"
                                for e in case.events), "reply_failure_event")
                    case.checks["batch_survived_failed_second_commit"] = True
            case.checks["sql_delivery_and_latest_revision_match"] = True
        if case.behavior == "review_degraded":
            require(any(event_name(e) == "degradation.selected" for e in case.events),
                    "review_degradation_missing")
        if case.behavior == "repair_regen":
            stages = {mapping(e["metadata"]).get("stage") for e in case.events}
            require({"review.repair", "review.regenerate", "solve"} <= stages,
                    "repair_regeneration_solve_not_executed")
            require(any(event_name(e) == "regeneration.started" for e in case.events),
                    "regeneration_event_missing")
        require(case.streams == case.closed_streams, "model_stream_not_closed")
        require(any(w["backend"] == "sdk" for w in case.wire), "native_sdk_not_executed")
        case.checks["actual_native_sdk_and_terminal_verified"] = True

    def concurrent_http(self) -> None:
        """Overlap two authenticated teacher HTTP requests at the provider boundary."""
        barrier = threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(self.execute, "concurrency_" + account,
                                   account=account, barrier=barrier)
                       for account in ("teacher", "teacher2")]
            cases = [future.result(timeout=30) for future in futures]
        require(all(case is not None and case.error_code is None for case in cases),
                "concurrent_http_acceptance")
        require(len({cast(Case, case).owner for case in cases}) == 2,
                "concurrent_http_distinct_owners")
        require(len({cast(Case, case).batch_id for case in cases}) == 2,
                "concurrent_http_distinct_batches")
        session_case = next((case for case in self.cases if case.session_id and
                             case.scope == "http_business"), None)
        if session_case is not None:
            for account in ("teacher2", "student"):
                rejected = self.client.get(f"/api/chat/sessions/{session_case.session_id}",
                                           headers=self.headers[account])
                require(rejected.status_code == 404, "cross_account_chat_access")
            session_case.checks["cross_account_same_session_rejected"] = True

    def repeat_conversation(self) -> None:
        """Send two real messages to one HTTP-created session, each owning a new run."""
        first = self.execute("chat_same_session_first")
        require(first is not None and first.error_code is None and first.session_id,
                "first_session_message")
        first = cast(Case, first)
        second = self.execute("chat_same_session_second", session_id=first.session_id)
        require(second is not None and second.error_code is None, "second_session_message")
        second = cast(Case, second)
        require(first.session_id == second.session_id, "real_session_not_reused")
        require(first.events[0]["run_id"] != second.events[0]["run_id"],
                "same_session_run_reused")
        require(first.events[0]["sdk_trace_id"] != second.events[0]["sdk_trace_id"],
                "same_session_sdk_trace_reused")
        require(first.batch_id != second.batch_id, "same_session_batch_reused")
        response = self.client.get(f"/api/chat/sessions/{first.session_id}",
                                   headers=self.headers[first.account])
        require(response.status_code == 200, "repeated_session_read")
        assistant_batches = {m.get("batch_id") for m in response.json()["messages"]
                             if m.get("role") == "assistant" and m.get("batch_id")}
        require(assistant_batches == {first.batch_id, second.batch_id},
                "same_session_reply_batch_links")
        for case in (first, second):
            case.checks["two_real_messages_distinct_runs_and_reply_batches"] = True


def event_name(event: Mapping[str, object]) -> str:
    """Accept the new canonical event schema and its earlier safe spelling."""
    name = str(event.get("event_type", event.get("name", "")))
    return {"ended": "run.ended", "revision": "question.revised",
            "degradation": "degradation.selected", "regen.started": "regeneration.started"
            }.get(name, name)


def revision_id(facts: Mapping[str, object]) -> object:
    """Use the canonical question revision key, accepting the earlier schema."""
    return facts.get("question_revision_id", facts.get("revision_id"))


def metadata(attributes: Mapping[str, object], key: str) -> object:
    if "metadata." + key in attributes:
        return attributes["metadata." + key]
    value = attributes.get("metadata", {})
    if isinstance(value, str):
        value = json.loads(value)
    return mapping(value).get(key)


def verify_execution_metadata(
    spans: list[dict[str, object]], case: Case, parents: Mapping[object, object],
) -> None:
    """Join stage/attempt events to persisted anchors and inherited native spans."""
    def ancestors(span: Mapping[str, object]) -> list[object]:
        result: list[object] = []
        current = span["span_id"]
        while current:
            result.append(current)
            current = parents[current]
        return result

    stage_events = [mapping(e["metadata"]) for e in case.events
                    if event_name(e) == "stage.started"]
    stage_ends = [mapping(e["metadata"]) for e in case.events
                  if event_name(e) == "stage.ended"]
    stages = {e.get("stage_id"): e for e in stage_events}
    require(stages and None not in stages and len(stages) == len(stage_events),
            "stage_event_identity")
    require(len(stage_ends) == len(stages) and
            {e.get("stage_id") for e in stage_ends} == stages.keys(), "stage_event_pairing")
    require(all(e.get("stage") == stages[e["stage_id"]].get("stage") for e in stage_ends),
            "stage_event_name")
    stage_anchors: dict[object, object] = {}
    for stage_id, event in stages.items():
        anchors = [s for s in spans if s["kind"] == "CHAIN" and s["stage_id"] == stage_id
                   and s["name"] == event["stage"]]
        require(len(anchors) == 1, "phoenix_stage_anchor")
        stage_anchors[stage_id] = anchors[0]["span_id"]
    stages_by_span = {span_id: stage_id for stage_id, span_id in stage_anchors.items()}
    for span in spans:
        stage_id = span["stage_id"]
        lineage = ancestors(span)
        if stage_id is not None:
            require(stage_id in stages and stage_anchors[stage_id] in lineage,
                    "phoenix_stage_correlation")
        if span["kind"] == "LLM" or (span["kind"] == "AGENT" and span["parent_id"]):
            nearest = next((stages_by_span[s] for s in lineage if s in stages_by_span), None)
            require(stage_id is not None and stage_id == nearest, "phoenix_native_stage_metadata")
        if span["span_id"] in stages_by_span:
            stage_id = stages_by_span[span["span_id"]]
            parent_stage = next((stages_by_span[s] for s in lineage[1:]
                                 if s in stages_by_span), None)
            require(stages[stage_id].get("parent_stage_id") == parent_stage,
                    "phoenix_stage_parent_metadata")
    starts = [mapping(e["metadata"]) for e in case.events
              if event_name(e) == "regeneration.started"]
    finishes = [mapping(e["metadata"]) for e in case.events
                if event_name(e) == "regeneration.finished"]
    attempts = {e.get("attempt_id") for e in starts}
    require(None not in attempts and len(attempts) == len(starts), "attempt_event_identity")
    require(len(finishes) == len(starts) and
            {e.get("attempt_id") for e in finishes} == attempts, "attempt_event_pairing")
    attempt_anchors: dict[object, object] = {}
    for attempt_id in attempts:
        anchors = [s for s in spans if s["kind"] == "CHAIN" and
                   s["name"] == "regeneration.attempt" and s["attempt_id"] == attempt_id]
        require(len(anchors) == 1, "phoenix_attempt_anchor")
        attempt_anchors[anchors[0]["span_id"]] = attempt_id
    for span in spans:
        expected = next((attempt_anchors[s] for s in ancestors(span) if s in attempt_anchors),
                        None)
        require(span["attempt_id"] == expected, "phoenix_attempt_correlation")
    case.checks["persisted_stage_and_attempt_metadata_match"] = True


def verify_phoenix(spans: list[dict[str, object]], cases: list[Case],
                   canaries: list[str]) -> list[dict[str, object]]:
    """Independently audit persisted roots/agents/LLMs, ancestry, ownership and bodies."""
    serialized = json.dumps(spans, ensure_ascii=False)
    require(not any(marker in serialized for marker in [BODY_MARKER, *canaries]),
            "phoenix_sensitive_content")
    runs = {cast(str, e["run_id"]): case for case in cases for e in case.events}
    records: list[dict[str, object]] = []
    for span in spans:
        attrs, context = mapping(span["attributes"]), mapping(span["context"])
        run_id = metadata(attrs, "run_id")
        require(run_id in runs, "phoenix_unexpected_run")
        case = runs[cast(str, run_id)]
        require(metadata(attrs, "owner_user_id") == case.owner and
                attrs.get("user.id") == case.owner, "phoenix_account_correlation")
        require(metadata(attrs, "session_id") == case.session_id, "phoenix_session_correlation")
        require(metadata(attrs, "task_id") == case.task_id, "phoenix_task_correlation")
        expected_trace = case.events[0]["sdk_trace_id"]
        require(metadata(attrs, "sdk_trace_id") == expected_trace, "phoenix_sdk_trace_correlation")
        batch_id = metadata(attrs, "batch_id")
        require(batch_id in {None, "", case.batch_id}, "phoenix_wrong_batch")
        require(not any(k.startswith(("input.", "output.", "exception.", "llm.input",
                                      "llm.output")) for k in attrs), "phoenix_body_attributes")
        name = str(span.get("name", ""))
        records.append({
            "run_id": run_id, "owner_user_id": case.owner, "session_id": case.session_id,
            "task_id": case.task_id, "batch_id_at_span_creation": batch_id,
            "final_batch_id_from_delivery": case.batch_id,
            "stage_id": metadata(attrs, "stage_id"),
            "attempt_id": metadata(attrs, "attempt_id"),
            "question_id": metadata(attrs, "question_id"),
            "question_revision_id": metadata(attrs, "question_revision_id"),
            "trace_id": context["trace_id"], "span_id": context["span_id"],
            "parent_id": span.get("parent_id") or "",
            "name": name if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", name) else "redacted",
            "kind": span.get("span_kind", attrs.get("openinference.span.kind")),
        })
    trace_owners: dict[str, str] = {}
    for run_id, case in runs.items():
        selected = [s for s in records if s["run_id"] == run_id]
        roots = [s for s in selected if not s["parent_id"]]
        require(len(roots) == 1, "phoenix_root_count")
        root = roots[0]
        trace_id = cast(str, root["trace_id"])
        require(trace_id not in trace_owners, "phoenix_trace_reused")
        trace_owners[trace_id] = run_id
        require(all(s["trace_id"] == trace_id for s in selected), "phoenix_split_trace")
        parents = {s["span_id"]: s["parent_id"] for s in selected}
        for span in selected:
            current, visited = span["span_id"], set()
            while current != root["span_id"]:
                require(current not in visited and parents.get(current), "phoenix_parent_chain")
                visited.add(current)
                current = parents[current]
        execution_agents = {s["span_id"] for s in selected
                            if s["kind"] == "AGENT" and s["parent_id"]}
        require(execution_agents, "phoenix_execution_agent_missing")
        models = [s for s in selected if s["kind"] == "LLM"]
        require(models, "phoenix_llm_missing")
        for model in models:
            ancestor = model["parent_id"]
            while ancestor != root["span_id"] and ancestor not in execution_agents:
                ancestor = parents[ancestor]
            require(ancestor in execution_agents, "phoenix_llm_execution_parent")
        verify_execution_metadata(selected, case, parents)
        case.checks["llms_descend_from_nonroot_execution_agents"] = True
        case.checks["persisted_parent_chain_and_native_spans_match"] = True
    return records


def run(args: argparse.Namespace) -> tuple[Path, dict[str, object]]:
    """Execute in a disposable fixture environment and emit only allowlisted JSON."""
    base, label = validate_base_url(args.base_url), validate_label(args.label)
    temp = Path(os.environ.get("TEMP", "")).resolve()
    require(temp.is_dir() and ".scratch" in temp.parts and str(temp).isascii(), "scratch_temp_required")
    require(Path(os.environ.get("TMP", "")).resolve() == temp, "matching_tmp_required")
    output_dir = Path(args.output_dir).resolve() if args.output_dir else temp / "business-evidence"
    require(".scratch" in output_dir.parts, "scratch_evidence_required")
    output_dir.mkdir(parents=True, exist_ok=True)
    output = output_dir / (label + ".safe.json")
    require(not output.exists(), "evidence_already_exists")
    report: dict[str, object] = {
        "schema_version": 1, "project": label, "status": "FAILED",
        "created_at": datetime.now(UTC).isoformat(), "real_model_requests": 0,
        "scope": "actual_http_business_with_native_sdk_and_mock_model_transport",
        "limitations": ["retrieval_and_embeddings_are_fake", "document_ready_is_fixture_seeded",
                        "export_faults_and_retention_are_separate_acceptance"],
    }
    guard = NetworkGuard(cast(int, urlsplit(base).port))
    harness: BusinessHarness | None = None
    phoenix: Phoenix | None = None
    try:
        with quiet(), guard.installed(), ExitStack() as stack:
            phoenix = Phoenix(Path(args.home), base, label)
            stack.callback(phoenix.close)
            phoenix.fresh()
            fixtures = isolated_fixtures()
            harness = BusinessHarness(fixtures, phoenix)
            harness.install(stack)
            from fastapi.testclient import TestClient
            from app.services import agent_tracing

            client = stack.enter_context(TestClient(fixtures.fastapi_app,
                                                   raise_server_exceptions=False))
            require(agent_tracing.snapshot()["status"] == "enabled", "tracing_not_enabled")
            harness.seed_http(client)
            for name in args.cases or CASES:
                harness.execute(name)
            require(agent_tracing.flush(3), "export_flush_timeout")
            counters = agent_tracing.snapshot()
            report["export"] = counters
            accepted = int(counters.get("accepted", 0))
            require(accepted > 0, "no_exported_spans")
            deadline = time.monotonic() + 15
            while True:
                spans = phoenix.spans()
                if len(spans) >= accepted or time.monotonic() >= deadline:
                    break
                time.sleep(0.2)
            require(len(spans) == accepted, "phoenix_span_count")
            report["spans"] = verify_phoenix(spans, harness.cases,
                                              phoenix.canaries + list(harness.wire.keys.values()))
            require(not any(counters.get(k, 0) for k in
                            ("failed", "dropped", "boundary_errors", "rejected_responses")),
                    "export_incomplete")
            require(not guard.blocked, "unexpected_network_attempts")
            require(all(case.error_code is None for case in harness.cases), "case_acceptance_failed")
            report["status"] = "PASSED"
    except Exception as exc:
        report["error_code"] = str(exc) if isinstance(exc, GateError) else type(exc).__name__
    finally:
        if harness is not None:
            report["cases"] = [case.evidence() for case in harness.cases]
            report["mock_model_requests"] = sum(len(c.wire) for c in harness.cases)
            report["case_count"] = len(harness.cases)
        report["network"] = {"blocked_attempts": guard.blocked,
                             "allowed_local_connections": guard.allowed}
        report["real_model_requests"] = 0
        with output.open("x", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
    return output, report


def parser() -> argparse.ArgumentParser:
    """Require explicit private home/project; default only to the new loopback port."""
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--home", required=True)
    result.add_argument("--base-url", default="http://127.0.0.1:6026")
    result.add_argument("--label", required=True)
    result.add_argument("--output-dir")
    result.add_argument("--cases", nargs="+", choices=CASES)
    return result


def main() -> int:
    """Print only evidence path, counts and status, including failures."""
    try:
        output, report = run(parser().parse_args())
        print(json.dumps({"path": str(output), "status": report["status"],
                          "case_count": report.get("case_count", 0),
                          "mock_model_requests": report.get("mock_model_requests", 0),
                          "real_model_requests": report["real_model_requests"]}))
        return 0 if report["status"] == "PASSED" else 1
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "error_type": type(exc).__name__}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
