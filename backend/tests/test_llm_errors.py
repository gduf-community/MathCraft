"""真实 OpenAI SDK 经假传输验证模型异常的公开安全边界。"""
import json
import traceback
from collections.abc import Callable, Iterator

import httpx
import pytest
from fastapi.testclient import TestClient
from openai import OpenAI
from sqlalchemy.orm import Session

from app.models import Document, DocumentChunk
from app.models.base import new_id
from app.config import settings
from app.services.rag import fts, llm, vectorstore
from conftest import create_bank


FAKE_KEY = "fake-llm-key-for-error-regression-only"
PRIVATE_MARKER = "FAKE_PRIVATE_UPSTREAM_DIAGNOSTIC"
PRIVATE_URL = "https://private.example.test/fake?secret=fake-private-marker"
PRIVATE_ERROR = f"{PRIVATE_MARKER} Bearer {FAKE_KEY} {PRIVATE_URL}"
GENERIC_ERROR = "模型调用失败，请稍后重试"
MISSING_KEY_ERROR = "DeepSeek API Key 未配置：请到设置 → 模型与服务中填写"
INVALID_JSON_ERROR = "模型返回的 JSON 无法解析，请重试"
AUTH_ERROR = "DeepSeek API Key 无效，请到设置 → 模型与服务检查密钥"
BALANCE_ERROR = "DeepSeek 账户余额不足，请到设置 → 模型与服务更换密钥或充值后重试"
RATE_ERROR = "模型接口请求过于频繁，请等一两分钟再试"
TIMEOUT_ERROR = "模型响应超时，请稍后重试"
FAILURES = [
    pytest.param(400, GENERIC_ERROR, id="unknown-400"),
    pytest.param(401, AUTH_ERROR, id="authentication"),
    pytest.param(402, BALANCE_ERROR, id="balance"),
    pytest.param(429, RATE_ERROR, id="rate-limit"),
    pytest.param(503, GENERIC_ERROR, id="unknown-503"),
    pytest.param("timeout", TIMEOUT_ERROR, id="timeout"),
    pytest.param("connect", GENERIC_ERROR, id="connection"),
]
MESSAGES = [{"role": "user", "content": "fake test prompt"}]
REAL_CHAT_TEXT = llm.chat_text
REAL_CHAT_JSON = llm.chat_json
REAL_CHAT_STREAM = llm.chat_stream
TransportHandler = Callable[[httpx.Request], httpx.Response]
SdkTransport = Callable[[TransportHandler], None]


@pytest.fixture
def sdk_transport(
    fake_models: None, monkeypatch: pytest.MonkeyPatch,
) -> Iterator[SdkTransport]:
    """恢复待测入口，仅将 SDK 的 HTTP 传输替换为 MockTransport。"""
    monkeypatch.setattr(llm, "chat_text", REAL_CHAT_TEXT)
    monkeypatch.setattr(llm, "chat_json", REAL_CHAT_JSON)
    monkeypatch.setattr(llm, "chat_stream", REAL_CHAT_STREAM)
    clients: dict[str, OpenAI] = {}
    monkeypatch.setattr(llm, "_clients", clients)

    def install(handler: TransportHandler) -> None:
        clients[FAKE_KEY] = OpenAI(
            api_key=FAKE_KEY, base_url="https://model.example.test/v1", max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        )

    yield install
    for sdk in clients.values():
        sdk.close()


def _reject(request: httpx.Request, failure: int | str) -> httpx.Response:
    if failure == "timeout":
        raise httpx.ReadTimeout(PRIVATE_ERROR, request=request)
    if failure == "connect":
        raise httpx.ConnectError(PRIVATE_ERROR, request=request)
    assert isinstance(failure, int)
    return httpx.Response(failure, json={"error": {"message": PRIVATE_ERROR}})


@pytest.mark.parametrize("failure,expected", FAILURES)
def test_deepseek_sdk_error_is_redacted(
    client: TestClient, teacher: dict[str, str], sdk_transport: SdkTransport,
    caplog: pytest.LogCaptureFixture, failure: int | str, expected: str,
) -> None:
    """连接测试不得将 SDK 的响应诊断和凭据返回调用方或写入日志。"""
    requests: list[httpx.Request] = []

    def reject(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _reject(request, failure)

    sdk_transport(reject)
    saved = client.put(
        "/api/users/me/model-settings", headers=teacher, json={"deepseek_api_key": FAKE_KEY},
    )
    assert saved.status_code == 200

    response = client.post("/api/users/me/model-settings/test-deepseek", headers=teacher)

    assert len(requests) == 1
    assert response.status_code == 400
    assert response.json()["detail"] == {"code": "LLM_ERROR", "message": expected}
    for private in (PRIVATE_MARKER, FAKE_KEY, PRIVATE_URL, "Bearer"):
        assert private not in response.text + caplog.text


@pytest.mark.parametrize("mode", ["text", "json", "stream"])
@pytest.mark.parametrize("failure,expected", FAILURES)
def test_llm_creation_error_is_safely_wrapped(
    sdk_transport: SdkTransport, caplog: pytest.LogCaptureFixture, mode: str,
    failure: int | str, expected: str,
) -> None:
    """所有调用入口统一抛安全 LLMError，格式化异常栈也不得带原始诊断。"""
    requests: list[httpx.Request] = []

    def reject(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return _reject(request, failure)

    sdk_transport(reject)

    with pytest.raises(llm.LLMError) as caught:
        if mode == "text":
            llm.chat_text(MESSAGES, api_key=FAKE_KEY)
        elif mode == "json":
            llm.chat_json(MESSAGES, api_key=FAKE_KEY)
        else:
            list(llm.chat_stream(MESSAGES, api_key=FAKE_KEY))

    assert len(requests) == 1, "传输与鉴权错误不能触发 JSON 修复重试"
    assert str(caught.value) == expected
    exposed = "".join(traceback.format_exception(caught.value)) + caplog.text
    for private in (PRIVATE_MARKER, FAKE_KEY, PRIVATE_URL, "Bearer"):
        assert private not in exposed


@pytest.mark.parametrize("status,expected", [
    (401, AUTH_ERROR), (402, BALANCE_ERROR), (429, RATE_ERROR),
])
def test_llm_http_status_precedes_untrusted_diagnostic_numbers(
    sdk_transport: SdkTransport, status: int, expected: str,
) -> None:
    """SDK 结构化状态优先于上游诊断中的数字，避免将鉴权错误误报为余额不足。"""
    sdk_transport(lambda request: httpx.Response(status, json={
        "error": {"message": f"{PRIVATE_ERROR} fake_diagnostic_codes=401,402,429"},
    }))
    with pytest.raises(llm.LLMError) as caught:
        llm.chat_text(MESSAGES, api_key=FAKE_KEY)
    assert str(caught.value) == expected


def _chunk(content: str) -> bytes:
    payload = {"choices": [{"index": 0, "delta": {"content": content}, "finish_reason": None}]}
    return f"data: {json.dumps(payload)}\n\n".encode()


class ResponseStream(httpx.SyncByteStream):
    """跟踪流关闭，提供真实 SSE 字节及可选故障。"""

    def __init__(self, failure: str | None = None) -> None:
        self.failure = failure
        self.closed = False

    def __iter__(self) -> Iterator[bytes]:
        yield b'data: {"choices": []}\n\n'
        yield _chunk("")
        yield _chunk("safe partial output")
        if self.failure == "transport":
            raise httpx.ReadError(PRIVATE_ERROR)
        if self.failure == "timeout":
            raise httpx.ReadTimeout(PRIVATE_ERROR)
        if self.failure == "sse":
            yield f'data: {json.dumps({"error": {"message": PRIVATE_ERROR}})}\n\n'.encode()
        if self.failure == "malformed":
            yield b"data: {fake malformed upstream JSON\n\n"
        yield _chunk("safe final output")
        yield b"data: [DONE]\n\n"

    def close(self) -> None:
        self.closed = True
        if self.failure == "close":
            raise RuntimeError(PRIVATE_ERROR)


@pytest.mark.parametrize("failure", ["transport", "sse", "timeout", "malformed", "close"])
def test_llm_stream_iteration_error_is_redacted_and_closed(
    sdk_transport: SdkTransport, caplog: pytest.LogCaptureFixture, failure: str,
) -> None:
    """已交付增量保留，随后发生的异常安全转换，底层流必须关闭。"""
    stream = ResponseStream(failure)
    sdk_transport(lambda request: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=stream,
    ))
    chunks = llm.chat_stream(MESSAGES, api_key=FAKE_KEY)
    assert next(chunks) == "safe partial output"

    with pytest.raises(llm.LLMError) as caught:
        list(chunks)

    assert str(caught.value) == (TIMEOUT_ERROR if failure == "timeout" else GENERIC_ERROR)
    assert stream.closed
    exposed = "".join(traceback.format_exception(caught.value)) + caplog.text
    for private in (PRIVATE_MARKER, FAKE_KEY, PRIVATE_URL, "Bearer"):
        assert private not in exposed


@pytest.mark.parametrize("failure,expected", FAILURES + [
    pytest.param("stream", GENERIC_ERROR, id="stream-iteration"),
])
def test_generation_sdk_error_is_redacted_in_progress(
    client: TestClient, teacher: dict[str, str], db: Session,
    sdk_transport: SdkTransport, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture, failure: int | str, expected: str,
) -> None:
    """真实出题编排遇到 SDK 错误后，公开 progress 只含固定提示且释放生成锁。"""
    bank = create_bank(client, teacher)
    user_id = client.get("/api/auth/me", headers=teacher).json()["user"]["id"]
    document_id = new_id("doc")
    chunk_id = new_id("chunk")
    db.add(Document(
        id=document_id, bank_id=bank["id"], name="导数.md", format="MD", size_bytes=1,
        storage_path="fake-unused-document.md", status="ready", uploader_id=user_id,
    ))
    db.flush()
    db.add(DocumentChunk(
        id=chunk_id, bank_id=bank["id"], document_id=document_id, chunk_index=0,
        text="导数与求导法则", tokens="导数 求导 法则", char_count=8,
    ))
    fts.insert_rows(db, [{
        "chunk_id": chunk_id, "bank_id": bank["id"], "document_id": document_id,
        "tokens": "导数 求导 法则",
    }])
    db.commit()
    # 向量存储为外部边界；实际 SQL/FTS 检索与出题编排均执行。
    monkeypatch.setattr(vectorstore, "search", lambda *args, **kwargs: [])
    assert client.put(
        "/api/users/me/model-settings", headers=teacher, json={"deepseek_api_key": FAKE_KEY},
    ).status_code == 200
    requests: list[httpx.Request] = []

    def reject(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if failure == "stream":
            # HyDE 使用非流接口，直接失败并降级；出题的流在交付增量后失败。
            if json.loads(request.content).get("stream"):
                return httpx.Response(
                    200, headers={"content-type": "text/event-stream"},
                    stream=ResponseStream("sse"),
                )
            return _reject(request, 400)
        return _reject(request, failure)

    sdk_transport(reject)
    body = {
        "bank_id": bank["id"], "document_id": document_id,
        "types": [{"type": "single", "count": 1}], "difficulty": "中", "scope": "导数",
    }
    started = client.post("/api/generate/start", headers=teacher, json=body)
    assert started.status_code == 202, started.text
    task_id = started.json()["task_id"]

    response = client.get(f"/api/generate/progress/{task_id}", headers=teacher)

    assert requests, "必须到达真实 SDK 的假传输边界"
    assert response.status_code == 200
    progress = response.json()
    assert progress["done"] is True
    assert progress["error"] == {"message": expected}
    assert progress["questions"] == []
    assert progress["batch_id"] is None
    for private in (PRIVATE_MARKER, FAKE_KEY, PRIVATE_URL, "Bearer"):
        assert private not in response.text + caplog.text
    # 同一用户再次请求可受理，说明失败任务没有遗留生成锁。
    assert client.post("/api/generate/start", headers=teacher, json=body).status_code == 202


@pytest.mark.parametrize("mode", ["text", "json", "stream"])
def test_missing_key_keeps_fixed_configuration_hint(
    sdk_transport: SdkTransport, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    """缺配置在三种入口一致，不因重复包装丢失可操作说明。"""
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    with pytest.raises(llm.LLMError, match="^" + MISSING_KEY_ERROR + "$"):
        if mode == "text":
            llm.chat_text(MESSAGES)
        elif mode == "json":
            llm.chat_json(MESSAGES)
        else:
            list(llm.chat_stream(MESSAGES))


@pytest.mark.parametrize("safe", [
    GENERIC_ERROR, MISSING_KEY_ERROR, INVALID_JSON_ERROR, AUTH_ERROR,
    BALANCE_ERROR, RATE_ERROR, TIMEOUT_ERROR,
])
def test_friendly_error_only_preserves_exact_safe_llm_messages(safe: str) -> None:
    """自己生成的固定提示可重入，附带私有诊断的同类异常必须重新过滤。"""
    assert llm.friendly_error(llm.LLMError(safe)) == safe
    assert llm.friendly_error(llm.LLMError(f"{safe} {PRIVATE_ERROR}")) == GENERIC_ERROR


@pytest.mark.parametrize("early_close", [False, True], ids=["completed", "cancelled"])
def test_stream_preserves_output_and_closes(
    sdk_transport: SdkTransport, early_close: bool,
) -> None:
    """正常流按原样交付非空增量，耗尽或消费者提前关闭均释放底层流。"""
    stream = ResponseStream()
    sdk_transport(lambda request: httpx.Response(
        200, headers={"content-type": "text/event-stream"}, stream=stream,
    ))
    chunks = llm.chat_stream(MESSAGES, api_key=FAKE_KEY)
    assert next(chunks) == "safe partial output"
    if early_close:
        chunks.close()
    else:
        assert list(chunks) == ["safe final output"]
    assert stream.closed


def _completion(content: str | None) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{
        "index": 0, "message": {"role": "assistant", "content": content},
        "finish_reason": "stop",
    }]})


def test_json_repairs_output_after_budget_escalation(sdk_transport: SdkTransport) -> None:
    """截断输出先扩预算，仍非法时回喂修复提示，最终返回实际解析的 JSON。"""
    requests: list[dict[str, object]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) < 4:
            return _completion('{"answer":')
        return _completion('{"answer": "safe result", "count": 2}')

    sdk_transport(respond)

    result = llm.chat_json(MESSAGES, api_key=FAKE_KEY, max_tokens=10, retries=1)

    assert result == {"answer": "safe result", "count": 2}
    assert [request["max_tokens"] for request in requests] == [10, 16, 25, 25]
    assert requests[0]["messages"] == MESSAGES
    assert requests[-1]["messages"][1]["content"] == '{"answer":'
    assert "请严格只输出合法 JSON" in requests[-1]["messages"][-1]["content"]
    assert MESSAGES == [{"role": "user", "content": "fake test prompt"}]


def test_json_exhaustion_keeps_fixed_parse_hint(
    sdk_transport: SdkTransport, caplog: pytest.LogCaptureFixture,
) -> None:
    """非法 JSON 重试耗尽后保留解析类别，异常栈与日志不输出模型内容。"""
    sdk_transport(lambda request: _completion(PRIVATE_ERROR))

    with pytest.raises(llm.LLMError) as caught:
        llm.chat_json(MESSAGES, api_key=FAKE_KEY, retries=0)

    assert str(caught.value) == INVALID_JSON_ERROR
    assert llm.friendly_error(caught.value) == INVALID_JSON_ERROR
    exposed = "".join(traceback.format_exception(caught.value)) + caplog.text
    for private in (PRIVATE_MARKER, FAKE_KEY, PRIVATE_URL, "Bearer"):
        assert private not in exposed


@pytest.mark.parametrize("content", [None, "safe full output"])
def test_text_preserves_successful_output(
    sdk_transport: SdkTransport, content: str | None,
) -> None:
    """成功文本保持原样，空内容沿用空字符串语义。"""
    sdk_transport(lambda request: _completion(content))
    assert llm.chat_text(MESSAGES, api_key=FAKE_KEY) == (content or "")


@pytest.mark.parametrize("mode", ["text", "json", "stream"])
def test_thinking_compatibility_retry_keeps_success_semantics(
    sdk_transport: SdkTransport, mode: str,
) -> None:
    """仅不支持 thinking 参数时兼容重发，正常文本、JSON 与流均继续可用。"""
    requests: list[dict[str, object]] = []
    stream = ResponseStream()

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        if len(requests) == 1:
            return httpx.Response(400, json={"error": {"message": "unsupported thinking field"}})
        if mode == "stream":
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=stream,
            )
        return _completion('{"answer": "safe result"}' if mode == "json" else "safe result")

    sdk_transport(respond)
    if mode == "text":
        assert llm.chat_text(MESSAGES, api_key=FAKE_KEY, thinking_off=True) == "safe result"
    elif mode == "json":
        assert llm.chat_json(MESSAGES, api_key=FAKE_KEY, thinking_off=True) == {
            "answer": "safe result",
        }
    else:
        assert list(llm.chat_stream(MESSAGES, api_key=FAKE_KEY, thinking_off=True)) == [
            "safe partial output", "safe final output",
        ]
        assert stream.closed
    assert len(requests) == 2
    assert requests[0]["thinking"] == {"type": "disabled"}
    assert "thinking" not in requests[1]
