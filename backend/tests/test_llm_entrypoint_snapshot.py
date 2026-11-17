"""个人连接测试和扫描简化沿用平台运行快照，不混用部署模型。"""

import json

import httpx
import pytest

from app.config import settings
from app.services import knowledge_simplify
from app.services.rag import llm
from test_llm_merge_runtime import runtime_sdk as runtime_sdk

PLATFORM = ("fake-platform-entry-key", "https://entry.example.test/v1", "entry-model")


def _response() -> httpx.Response:
    return httpx.Response(200, json={"choices": [{
        "index": 0, "message": {"role": "assistant", "content": "ok"},
        "finish_reason": "stop",
    }]})


def test_personal_connection_test_accepts_platform_without_personal_or_deployment_key(
    client, teacher, runtime_sdk, monkeypatch,
):
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    monkeypatch.setattr(llm, "get_platform_llm", lambda: PLATFORM)
    calls = []

    def respond(request):
        calls.append(json.loads(request.content))
        assert request.url.host == "entry.example.test"
        assert request.headers["authorization"] == "Bearer fake-platform-entry-key"
        return _response()

    runtime_sdk(PLATFORM, respond)
    response = client.post("/api/users/me/model-settings/test-deepseek", headers=teacher)
    assert response.status_code == 200, response.text
    assert response.json()["reply"] == "ok"
    assert [call["model"] for call in calls] == ["entry-model"]


@pytest.mark.parametrize("retry_effort", [False, True])
def test_simplify_uses_snapshot_model_for_initial_request_and_parameter_retry(
    runtime_sdk, monkeypatch, retry_effort,
):
    current = [PLATFORM]
    monkeypatch.setattr(llm, "get_platform_llm", lambda: current[0])
    key = llm.ResolvedApiKey(llm.resolve_llm_runtime())
    current[0] = ("fake-replacement-key", "https://replacement.example.test/v1", "other-model")
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        assert request.url.host == "entry.example.test"
        assert request.headers["authorization"] == "Bearer fake-platform-entry-key"
        if retry_effort and len(calls) == 1:
            return httpx.Response(400, json={"error": {"message": "effort unsupported"}})
        return _response()

    runtime_sdk(PLATFORM, respond)
    content, _usage = knowledge_simplify._chat_text(
        [{"role": "user", "content": "fixture"}], api_key=key,
    )
    assert content == "ok"
    assert len(calls) == (2 if retry_effort else 1)
    assert all(call["model"] == "entry-model" for call in calls)
