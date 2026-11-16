"""闲聊意图分流回归：问候语不再被塞进出题槽位追问或模式切换建议。"""
from app.services.rag import chat_flow, intent


def test_detect_intent_maps_smalltalk(monkeypatch):
    monkeypatch.setattr(intent, "chat_json", lambda *a, **kw: {
        "intent": "smalltalk", "confidence": "high", "slots": {},
        "need_confirm": False, "suggested_template": "none", "reason": "问候语",
    })
    detected = intent.detect_intent("你好", "generate")
    assert detected["intent"] == "smalltalk"
    assert detected["confidence"] == "high"


def test_detect_intent_keeps_unknown_for_low_confidence(monkeypatch):
    monkeypatch.setattr(intent, "chat_json", lambda *a, **kw: {
        "intent": "unknown", "confidence": "low", "slots": {},
        "need_confirm": True, "suggested_template": "none", "reason": "拿不准",
    })
    detected = intent.detect_intent("随便说点什么", "generate")
    assert detected["intent"] == "unknown"
    assert detected["confidence"] == "low"


def test_unknown_fallback_still_current_mode(monkeypatch):
    """LLM 挂掉时保守放行当前模式（不误入对话分支阻断出题）。"""
    def broken(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(intent, "chat_json", broken)
    detected = intent.detect_intent("帮我出 5 道题", "generate")
    assert detected["intent"] == "generate"


def test_review_with_refill_trims_to_requested_quota():
    """补齐轮次用尽后按题型配额截断：总量与分布都不超过请求。"""
    from app.schemas.question import Difficulty, GenerateParams, Question, QuestionType, TypeCount

    params = GenerateParams(
        kb_id="kb", doc_id="doc",
        types=[TypeCount(type=QuestionType.single, count=35),
               TypeCount(type=QuestionType.blank, count=10),
               TypeCount(type=QuestionType.compute, count=15)],
        difficulty=Difficulty.low, scope="行列式",
    )

    def q(stem, qtype):
        return Question(id=stem[:6], type=qtype, stem=stem, answer="A", analysis="解析")

    # 模拟三轮审核累计 61+19+28 = 108（超出请求 60）
    first_pool = ([q(f"单选{i}", QuestionType.single) for i in range(61)]
                  + [q(f"填空{i}", QuestionType.blank) for i in range(19)]
                  + [q(f"计算{i}", QuestionType.compute) for i in range(28)])
    calls = []

    def review_fn(candidates, refill_params, stems):
        calls.append(list(candidates))
        return list(candidates), object()

    accepted, stats, canceled = chat_flow.review_with_refill(
        first_pool, params, 60, [], review_fn, lambda *a, **kw: [],
    )
    assert canceled is False
    assert len(accepted) == 60
    dist = {}
    for item in accepted:
        dist[item.type.value] = dist.get(item.type.value, 0) + 1
    assert dist == {"single": 35, "blank": 10, "compute": 15}
    assert len(calls) == 1  # 首轮已达配额上界，不再触发补齐


def test_smalltalk_never_triggers_mode_mismatch(client, teacher, monkeypatch):
    """问候语即使高置信度也绝不进模式守卫，直接走自由对话。"""
    from app.api import chat as chat_api
    from conftest import create_bank, upload_markdown

    bank = create_bank(client, teacher)
    doc = upload_markdown(client, teacher, bank["id"])
    client.put("/api/users/me/model-settings",
               json={"deepseek_api_key": "sk-test-deepseek"}, headers=teacher)
    session = client.post(
        "/api/chat/sessions",
        json={"bank_id": bank["id"], "document_id": doc["document_id"]},
        headers=teacher,
    ).json()
    url = f"/api/chat/sessions/{session['session_id']}/messages"

    captured: dict = {}
    monkeypatch.setattr(chat_api, "answer_casually",
                        lambda mode, doc_name, history, message, api_key=None, **kwargs:
                        captured.setdefault("message", message)
                        or "你好呀，我是智能出题助手。")
    monkeypatch.setattr(chat_api, "detect_intent", lambda *a, **kw: {
        "intent": "smalltalk", "confidence": "high", "slots": {},
        "need_confirm": False, "suggested_template": "none", "reason": "问候语",
    })
    resp = client.post(url, json={"message": "你好", "images": []}, headers=teacher)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    # 不出现模式切换建议文案，且走到了自由对话
    assert "分段控制器" not in data["reply"]
    assert captured["message"] == "你好"
    # confirm/batch_id 必须显式存在：缺失（undefined）会锁死前端的发送与历史切换
    assert data["confirm"] is None
    assert "batch_id" in data
