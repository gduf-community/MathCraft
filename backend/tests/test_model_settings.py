"""模型配置接口测试：读取、保存、掩码、清除、测试连接。"""
from collections.abc import Callable

import httpx
import pytest
from fastapi.testclient import TestClient

from app.services import mineru
from app.services.rag import llm


FAKE_MINERU_TOKEN = "fake-mineru-token-for-regression-tests-only"
FAKE_MINERU_BASE_URL = "https://mineru.example.test/api/v4"
MineruResponseStub = Callable[[httpx.Response], list[httpx.Request]]


@pytest.fixture
def mineru_response(monkeypatch: pytest.MonkeyPatch) -> MineruResponseStub:
    """仅替换 HTTP 边界，实际执行 ping_token，所有请求留在假传输层。"""
    monkeypatch.setattr(mineru, "BASE_URL", FAKE_MINERU_BASE_URL)

    def install(response: httpx.Response) -> list[httpx.Request]:
        requests: list[httpx.Request] = []

        def handle(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return response

        def fake_get(
            url: str, *, headers: dict[str, str], timeout: float,
        ) -> httpx.Response:
            with httpx.Client(transport=httpx.MockTransport(handle)) as http_client:
                return http_client.get(url, headers=headers, timeout=timeout)

        monkeypatch.setattr(httpx, "get", fake_get)
        return requests

    return install


@pytest.mark.parametrize(
    "status_code,body",
    [
        pytest.param(401, {"code": 0, "data": {}}, id="http-401"),
        pytest.param(403, {"code": 0, "data": {}}, id="http-403"),
        pytest.param(429, {"code": 0, "data": {}}, id="http-429"),
        pytest.param(503, {"code": 0, "data": {}}, id="http-503"),
        pytest.param(302, {"code": 0, "data": {}}, id="http-redirect"),
        pytest.param(404, {"code": -60012}, id="notfound-code-http-404"),
        pytest.param(201, {"code": -60012}, id="notfound-code-http-201"),
        pytest.param(200, {"code": "A0202"}, id="invalid-token"),
        pytest.param(200, {"code": "A0211"}, id="expired-token"),
        pytest.param(200, {"code": -60013}, id="task-forbidden-int"),
        pytest.param(200, {"code": "-60013"}, id="task-forbidden-string"),
        pytest.param(200, {"code": 123456}, id="unknown-int-code"),
        pytest.param(200, {"code": "FAKE_UNKNOWN_CODE"}, id="unknown-string-code"),
        pytest.param(200, {"data": {}}, id="missing-code"),
        pytest.param(200, {"code": False, "data": {}}, id="boolean-false-code"),
        pytest.param(200, {"code": True, "data": {}}, id="boolean-true-code"),
        pytest.param(200, {"code": "0", "data": {}}, id="string-zero-code"),
        pytest.param(200, {"code": 0.0, "data": {}}, id="float-zero-code"),
        pytest.param(200, {"code": None, "data": {}}, id="null-code"),
        pytest.param(200, {"code": 0}, id="missing-data"),
        pytest.param(200, {"code": 0, "data": None}, id="null-data"),
        pytest.param(200, {"code": 0, "data": []}, id="array-data"),
        pytest.param(200, {"code": 0, "data": "fake-data"}, id="string-data"),
        pytest.param(200, {"code": 0, "data": False}, id="boolean-data"),
        pytest.param(200, {"code": 0, "data": 0}, id="number-data"),
        pytest.param(200, [], id="array-body"),
        pytest.param(200, "fake-body", id="string-body"),
    ],
)
def test_mineru_ping_rejects_unconfirmed_responses(
    mineru_response: MineruResponseStub, status_code: int, body: object,
) -> None:
    """HTTP 或业务响应不满足明确成功条件时，不得误报连接成功。"""
    requests = mineru_response(httpx.Response(status_code, json=body))

    ok, detail = mineru.ping_token(FAKE_MINERU_TOKEN)

    assert requests, "测试必须通过实际 ping_token 到达 HTTP 边界"
    assert ok is False, detail
    assert detail.strip()


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"<html>fake upstream error</html>", id="non-json"),
        pytest.param(b"", id="empty-body"),
        pytest.param(b"null", id="null-body"),
    ],
)
def test_mineru_ping_rejects_invalid_response_body(
    mineru_response: MineruResponseStub, content: bytes,
) -> None:
    """非 JSON、空响应和 JSON null 不能作为鉴权成功证据。"""
    requests = mineru_response(httpx.Response(200, content=content))

    ok, detail = mineru.ping_token(FAKE_MINERU_TOKEN)

    assert requests
    assert ok is False, detail
    assert detail.strip()


@pytest.mark.parametrize("status_code", [200, 201, 206])
@pytest.mark.parametrize("data", [{}, {"extract_result": []}], ids=["empty-object", "object"])
def test_mineru_ping_accepts_integer_zero_with_data_object(
    mineru_response: MineruResponseStub, status_code: int, data: dict[str, object],
) -> None:
    """2xx 的整数零业务码及 data 对象明确表示探测成功。"""
    requests = mineru_response(httpx.Response(status_code, json={"code": 0, "data": data}))

    ok, detail = mineru.ping_token(FAKE_MINERU_TOKEN)

    assert requests
    assert ok is True, detail


@pytest.mark.parametrize("code", [-60012, "-60012"], ids=["int-code", "string-code"])
def test_mineru_ping_accepts_explicit_task_not_found(
    mineru_response: MineruResponseStub, code: int | str,
) -> None:
    """HTTP 200 明确任务不存在码可证明探测请求已通过鉴权。"""
    requests = mineru_response(httpx.Response(200, json={"code": code, "msg": "找不到任务"}))

    ok, detail = mineru.ping_token(FAKE_MINERU_TOKEN)

    assert requests
    assert ok is True, detail


@pytest.mark.parametrize("code", [0, -60012, "-60012"])
def test_mineru_ping_success_describes_authentication_only(
    mineru_response: MineruResponseStub, code: int | str,
) -> None:
    """鉴权通过不能宣称实际文件解析能力已经验证。"""
    mineru_response(httpx.Response(200, json={"code": code, "data": {}}))

    ok, detail = mineru.ping_token(FAKE_MINERU_TOKEN)

    assert ok is True, detail
    assert "鉴权" in detail, detail
    assert "未验证" in detail and "解析" in detail, detail


def test_mineru_ping_probes_zero_uuid(mineru_response: MineruResponseStub) -> None:
    """不存在批次探测使用格式合法的全零 UUID，并传递假 Token。"""
    requests = mineru_response(httpx.Response(200, json={"code": -60012}))

    mineru.ping_token(FAKE_MINERU_TOKEN)

    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET"
    assert str(request.url) == (
        f"{FAKE_MINERU_BASE_URL}/extract-results/batch/00000000-0000-0000-0000-000000000000"
    )
    assert request.headers["Authorization"] == f"Bearer {FAKE_MINERU_TOKEN}"


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("fake-中文-token", id="unicode-token"),
        pytest.param("fake-token\ninjected", id="newline-token"),
        pytest.param("fake token", id="space-token"),
    ],
)
def test_mineru_ping_rejects_malformed_token_without_http(
    mineru_response: MineruResponseStub, token: str,
) -> None:
    """凭据在请求前校验，不能因请求头编码异常泄漏或误判成功。"""
    requests = mineru_response(httpx.Response(200, json={"code": 0, "data": {}}))

    ok, detail = mineru.ping_token(token)

    assert ok is False, detail
    assert requests == []
    assert detail.strip()
    assert token not in detail


@pytest.mark.parametrize(
    "error_type,expected_detail",
    [(httpx.ReadTimeout, "超时"), (httpx.ConnectError, "连接")],
    ids=["read-timeout", "connect-error"],
)
def test_mineru_ping_redacts_transport_errors(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
    error_type: type[httpx.RequestError], expected_detail: str,
) -> None:
    """网络异常可携带假密钥和私有 URL，公开结果只保留安全分类。"""
    private_url = "https://private.example.test/fake-probe?secret=fake-probe-secret"
    attempted: list[str] = []

    def fail_get(url: str, *, headers: dict[str, str], timeout: float) -> httpx.Response:
        attempted.append(url)
        raise error_type(
            f"Bearer {FAKE_MINERU_TOKEN} {private_url}",
            request=httpx.Request("GET", private_url),
        )

    monkeypatch.setattr(mineru, "BASE_URL", FAKE_MINERU_BASE_URL)
    monkeypatch.setattr(httpx, "get", fail_get)

    ok, detail = mineru.ping_token(FAKE_MINERU_TOKEN)

    assert len(attempted) == 1
    assert ok is False, detail
    assert expected_detail in detail
    for private in (FAKE_MINERU_TOKEN, private_url, "fake-probe-secret", "Bearer"):
        assert private not in detail + caplog.text


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("fake-中文-token", id="unicode-token"),
        pytest.param("fake-token\ninjected", id="newline-token"),
        pytest.param("fake token", id="space-token"),
    ],
)
def test_test_mineru_malformed_token_returns_400_without_http(
    client: TestClient, teacher: dict[str, str], mineru_response: MineruResponseStub,
    token: str,
) -> None:
    """保存格式错误的假凭据后，连接测试应返回业务 400，不能触发 500。"""
    requests = mineru_response(httpx.Response(200, json={"code": 0, "data": {}}))
    saved = client.put(
        "/api/users/me/model-settings", headers=teacher, json={"mineru_token": token},
    )
    assert saved.status_code == 200

    response = client.post("/api/users/me/model-settings/test-mineru", headers=teacher)

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "LLM_ERROR"
    assert response.json()["detail"]["message"].startswith("MinerU 连接测试失败：")
    assert token not in response.text
    assert requests == []


def test_default_model_settings(client, teacher):
    resp = client.get("/api/users/me/model-settings", headers=teacher)
    assert resp.status_code == 200
    data = resp.json()
    assert data["deepseek_model_id"] == "deepseek-flash"
    assert data["deepseek_key_configured"] is False
    assert data["mineru_using_default"] is True
    assert data["embedding_configurable"] is False
    assert data["rerank_configurable"] is False
    assert data["mineru_limits"] == {"max_file_mb": 200, "max_pages": 200}


def test_save_and_mask_keys(client, teacher):
    resp = client.put(
        "/api/users/me/model-settings",
        json={"deepseek_api_key": "sk-test-deepseek-1234", "mineru_token": "sk-test-mineru-5678"},
        headers=teacher,
    )
    assert resp.status_code == 200

    data = client.get("/api/users/me/model-settings", headers=teacher).json()
    assert data["deepseek_key_configured"] is True
    assert data["mineru_token_configured"] is True
    assert data["deepseek_key_masked"].startswith("sk-")
    assert data["deepseek_key_masked"].endswith("1234")
    # 完整密钥不回传
    assert "sk-test-deepseek-1234" not in str(data)


def test_clear_keys(client, teacher):
    client.put(
        "/api/users/me/model-settings",
        json={"deepseek_api_key": "sk-test-deepseek-1234", "mineru_token": "sk-test-mineru-5678"},
        headers=teacher,
    )
    client.put(
        "/api/users/me/model-settings",
        json={"deepseek_api_key": "", "mineru_token": ""},
        headers=teacher,
    )
    data = client.get("/api/users/me/model-settings", headers=teacher).json()
    assert data["deepseek_key_configured"] is False
    assert data["mineru_token_configured"] is False
    assert data["mineru_using_default"] is True


def test_test_deepseek_without_key(client, teacher):
    resp = client.post("/api/users/me/model-settings/test-deepseek", headers=teacher)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "DEEPSEEK_KEY_MISSING"


def test_test_deepseek_with_key(client, teacher):
    client.put(
        "/api/users/me/model-settings",
        json={"deepseek_api_key": "sk-test-deepseek-1234"},
        headers=teacher,
    )
    resp = client.post("/api/users/me/model-settings/test-deepseek", headers=teacher)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


@pytest.mark.parametrize("error_type", [RuntimeError, llm.LLMError])
def test_deepseek_rejects_untrusted_exception_messages(
    client: TestClient, teacher: dict[str, str], monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture, error_type: type[Exception],
) -> None:
    """即使下层直接抛普通 LLMError，公开边界也不能信任它的文本。"""
    marker = "FAKE_PRIVATE_DEEPSEEK_EXCEPTION"

    def fail(*args, **kwargs) -> str:
        raise error_type(marker)

    monkeypatch.setattr(llm, "chat_text", fail)
    assert client.put(
        "/api/users/me/model-settings", headers=teacher,
        json={"deepseek_api_key": "fake-api-key-for-exception-test-only"},
    ).status_code == 200

    response = client.post("/api/users/me/model-settings/test-deepseek", headers=teacher)

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "LLM_ERROR", "message": "模型调用失败，请稍后重试",
    }
    assert marker not in response.text + caplog.text


@pytest.mark.parametrize("code", [0, -60012, "-60012"])
def test_test_mineru(
    client: TestClient, teacher: dict[str, str], mineru_response: MineruResponseStub,
    code: int | str,
) -> None:
    """连接测试接口通过真实探测逻辑接受明确成功响应。"""
    requests = mineru_response(httpx.Response(200, json={"code": code, "data": {}}))
    resp = client.post("/api/users/me/model-settings/test-mineru", headers=teacher)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["limits"] == {"max_file_mb": 200, "max_pages": 200}
    assert requests


@pytest.mark.parametrize(
    "status_code,code",
    [
        pytest.param(401, 0, id="http-401"),
        pytest.param(403, 0, id="http-403"),
        pytest.param(429, 0, id="http-429"),
        pytest.param(503, 0, id="http-503"),
        pytest.param(200, "A0202", id="invalid-token"),
        pytest.param(200, "A0211", id="expired-token"),
        pytest.param(200, -60013, id="task-forbidden-int"),
        pytest.param(200, "-60013", id="task-forbidden-string"),
        pytest.param(200, "FAKE_UNKNOWN_CODE", id="unknown-code"),
    ],
)
def test_test_mineru_invalid(
    client: TestClient, teacher: dict[str, str], mineru_response: MineruResponseStub,
    status_code: int, code: int | str,
) -> None:
    """连接失败使用中性文案，限流、服务故障或无权限不能统称 Token 无效。"""
    requests = mineru_response(httpx.Response(status_code, json={"code": code, "data": {}}))
    resp = client.post("/api/users/me/model-settings/test-mineru", headers=teacher)
    assert resp.status_code == 400
    detail = resp.json()["detail"]
    assert detail["code"] == "LLM_ERROR"
    assert detail["message"].startswith("MinerU 连接测试失败：")
    assert detail["message"].removeprefix("MinerU 连接测试失败：").strip()
    assert requests
