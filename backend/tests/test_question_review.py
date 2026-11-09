"""出题中间件测试：查重、盲评映射与否决、双评仲裁、缺陷修补、解析覆盖。"""
import hashlib
import json
import threading

import pytest

from app.db import SessionLocal
from app.schemas.question import Difficulty, GenerateParams, OptionItem, Question, QuestionType, TypeCount
from app.services import question_review
from app.services.question_review import review_questions as real_review


def _vec(text: str) -> list[float]:
    """按文本哈希生成确定性单位向量：相同文本完全一致，不同文本正交。"""
    vec = [0.0] * 256
    digest = hashlib.md5(text.encode("utf-8")).digest()
    vec[int.from_bytes(digest[:2], "big") % 256] = 1.0
    return vec


def _q(stem: str, qtype: QuestionType = QuestionType.single) -> Question:
    options = []
    if qtype in (QuestionType.single, QuestionType.multiple):
        options = [OptionItem(label="A", text="1"), OptionItem(label="B", text="2")]
    return Question(
        id=stem[:6], type=qtype, score=5, difficulty=Difficulty.high,
        stem=stem, options=options, answer="A", analysis="旧解析",
    )


def _review_json(scores: dict, passed: bool = True, defects=None, suggestion="") -> str:
    return json.dumps({
        "independentAnswer": "B",
        "scores": scores,
        "total": 0,
        "tier": "中",
        "defectCodes": defects or [],
        "primarySuggestion": suggestion,
        "methods": ["解法一", "解法二"],
        "passed": passed,
    }, ensure_ascii=False)


GOOD_SCORES = {"knowledge": 4, "steps": 4, "abstraction": 4, "computation": 3, "trap": 3, "unique": 5}
LOW_SCORES = {"knowledge": 3, "steps": 2, "abstraction": 2, "computation": 2, "trap": 1, "unique": 5}


class FakeLLM:
    """按 prompt 类型分派：盲评返回 JSON，修补返回题目，解题返回 ANSWER/ANALYSIS。"""

    def __init__(self, reviews: list[str], repair_items: list[dict] | None = None):
        self.reviews = reviews
        self.repair_items = repair_items or []
        self.eval_calls = 0
        self.solve_calls = 0
        self.repair_calls = 0
        self._lock = threading.Lock()

    def __call__(self, messages, api_key=None, temperature=0.7, max_tokens=None, thinking_off=False, response_format=None):
        prompt = messages[-1]["content"]
        with self._lock:
            if prompt.startswith("你是独立数学审题人"):
                idx = min(self.eval_calls, len(self.reviews) - 1)
                self.eval_calls += 1
                return self.reviews[idx]
            if prompt.startswith("下面这道题没有通过"):
                self.repair_calls += 1
                item = self.repair_items[min(self.repair_calls - 1, len(self.repair_items) - 1)]
                return json.dumps(item, ensure_ascii=False)
            self.solve_calls += 1
            return "ANSWER: B\nANALYSIS: 由定义可得 $y'=3x^2$。"


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _stub_embeddings(monkeypatch):
    monkeypatch.setattr(question_review.embeddings, "embed_texts", lambda texts: [_vec(t) for t in texts])
    monkeypatch.setattr(question_review, "load_corpus", lambda *_a, **_k: [])


def test_tier_mapping_and_tolerance():
    assert question_review.tier_of(1.4) == Difficulty.low
    assert question_review.tier_of(2.6) == Difficulty.mid
    assert question_review.tier_of(3.4) == Difficulty.high
    assert question_review.tier_of(4.2) == Difficulty.hell
    # 高难度区间 3—4，允许 ±0.5
    assert question_review.in_target(2.6, Difficulty.high)
    assert question_review.in_target(4.4, Difficulty.high)
    assert not question_review.in_target(2.4, Difficulty.high)


def test_parse_review_veto_on_unsolvable():
    data = {
        "scores": {**GOOD_SCORES, "unique": 1},
        "passed": True,
        "defectCodes": ["A"],
        "primarySuggestion": "答案不唯一",
    }
    review = question_review.parse_review(data, Difficulty.high)
    assert review["veto"] is True
    assert review["passed"] is False


def test_parse_review_recomputes_total():
    data = {"scores": GOOD_SCORES, "total": 5.0, "passed": True}
    review = question_review.parse_review(data, Difficulty.high)
    expected = round(0.2 * 4 + 0.2 * 4 + 0.2 * 4 + 0.15 * 3 + 0.15 * 3 + 0.10 * 5, 2)
    assert review["total"] == expected
    assert review["passed"] is True


def test_duplicate_stem_is_dropped(db):
    questions = [_q("求函数 $y=x^2$ 的导数。"), _q("计算定积分 $\\int_0^1 x^2\\,\\mathrm{d}x$。")]
    kept, dropped = question_review._drop_duplicates(questions, ["求函数 $y=x^2$ 的导数。"])

    assert len(kept) == 1
    assert dropped[0].stem == "求函数 $y=x^2$ 的导数。"
    assert "定积分" in kept[0].stem


def test_arbitration_when_judges_disagree(db, monkeypatch):
    low = question_review.parse_review({"scores": LOW_SCORES, "passed": True}, Difficulty.high)
    good = question_review.parse_review({"scores": GOOD_SCORES, "passed": True}, Difficulty.high)
    sequence = [low, good, good]
    calls = {"n": 0}

    def fake_judge(question, target, scope, api_key):
        item = sequence[min(calls["n"], len(sequence) - 1)]
        calls["n"] += 1
        return dict(item)

    monkeypatch.setattr(question_review, "_judge_once", fake_judge)
    review = question_review.evaluate(_q("题目"), Difficulty.high, "导数", "sk-test")

    assert calls["n"] == 3
    assert review["arbitrated"] is True
    assert review["passed"] is True


def test_repair_then_accept(db, monkeypatch):
    """首轮评审不通过 → 按缺陷修补 → 复审通过。"""
    fake = FakeLLM(
        reviews=[_review_json(LOW_SCORES, defects=["S"], suggestion="步骤从 2 增到 4"),
                 _review_json(LOW_SCORES, defects=["S"], suggestion="步骤从 2 增到 4"),
                 _review_json(GOOD_SCORES),
                 _review_json(GOOD_SCORES)],
        repair_items=[{
            "type": "single", "score": 5, "difficulty": "高", "knowledgePoint": "导数",
            "stem": "修补后的题干：求 $y=x^3$ 在 $x=1$ 处的导数。",
            "options": [{"label": "A", "text": "1"}, {"label": "B", "text": "3"}],
            "answer": "B", "analysis": "求导得 $3x^2$，代入得 3。",
            "blueprint": {"steps": 3}, "scoringPoints": ["求导"], "selfCheck": {"passed": True},
        }],
    )
    monkeypatch.setattr(question_review.llm, "chat_text", fake)

    params = GenerateParams(
        kb_id="bank_test", doc_id="doc_test",
        types=[TypeCount(type=QuestionType.single, count=1)],
        difficulty=Difficulty.high, scope="导数",
    )
    result, stats = real_review(db, "u_test", [_q("原题：求 $y=x^2$ 的导数。")], params, "doc.md", "sk-test")

    assert stats.repaired == 1
    assert len(result) == 1
    assert result[0].stem.startswith("修补后的题干")
    assert result[0].difficultyScore > 3
    assert result[0].answer == "B"  # 解析环节覆盖答案
    assert "3x^2" in result[0].analysis


def test_duplicate_shortfall_is_refilled(db, monkeypatch):
    """查重丢掉一题后，按缺口重出，最终数量与请求一致。"""
    fake = FakeLLM(reviews=[_review_json(GOOD_SCORES)])
    monkeypatch.setattr(question_review.llm, "chat_text", fake)
    monkeypatch.setattr(question_review, "load_corpus", lambda *_a, **_k: ["求 $y=x^2$ 的导数。"])

    fresh = _q("重出的新题：求 $y=x^3$ 在 $x=2$ 处的导数。")
    monkeypatch.setattr(question_review.question_gen, "generate_questions", lambda *_a, **_k: [fresh])

    params = GenerateParams(
        kb_id="bank_test", doc_id="doc_test",
        types=[TypeCount(type=QuestionType.single, count=2)],
        difficulty=Difficulty.high, scope="导数",
    )
    result, stats = real_review(
        db, "u_test", [_q("求 $y=x^2$ 的导数。"), _q("求 $y=x^3$ 的导数。")], params, "doc.md", "sk-test",
    )

    assert stats.duplicates == 1
    assert stats.regenerated == 1
    assert len(result) == 2


def test_solver_failure_keeps_original_answer(db, monkeypatch):
    class NoSolveLLM(FakeLLM):
        def __call__(self, messages, api_key=None, temperature=0.7, max_tokens=None, thinking_off=False, response_format=None):
            prompt = messages[-1]["content"]
            if prompt.startswith("你是独立数学审题人"):
                return _review_json(GOOD_SCORES)
            return "这里没有按格式输出"

    monkeypatch.setattr(question_review.llm, "chat_text", NoSolveLLM(reviews=[]))

    params = GenerateParams(
        kb_id="bank_test", doc_id="doc_test",
        types=[TypeCount(type=QuestionType.single, count=1)],
        difficulty=Difficulty.high, scope="导数",
    )
    result, stats = real_review(db, "u_test", [_q("求 $y=x^2$ 的导数。")], params, "doc.md", "sk-test")

    assert len(result) == 1
    assert result[0].answer == "A"
    assert result[0].analysis == "旧解析"
    assert stats.solved == 0


def test_math_delimiters_are_normalized():
    text = question_review._normalize_math(r"由 \(f(0)=0\) 可得 \[M=\max|f|\]")
    assert r"\(" not in text and r"\[" not in text
    assert "$f(0)=0$" in text


def test_answer_normalization():
    single = _q("题干", QuestionType.single)
    assert question_review._normalize_answer(single, "答案是 B") == "B"
    assert question_review._normalize_answer(single, "C") == "A"  # 无此选项，回退原答案

    judge = Question(
        id="j1", type=QuestionType.judge, score=3, difficulty=Difficulty.mid,
        stem="判断", options=[OptionItem(label="A", text="正确"), OptionItem(label="B", text="错误")],
        answer="A", analysis="",
    )
    assert question_review._normalize_answer(judge, "错误") == "错误"
    assert question_review._normalize_answer(judge, "正确") == "正确"
