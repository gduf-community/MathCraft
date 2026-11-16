"""出题中间件测试：查重、盲评映射与否决、双评仲裁、缺陷修补、解析覆盖。"""
import hashlib
import json
import threading

import pytest

from app.db import SessionLocal, Base, engine
from app.schemas.question import Difficulty, GenerateParams, OptionItem, Question, QuestionType, TypeCount
from app.services import latex_utils, question_review
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
    """按 prompt 类型分派：盲评、修补与独立解题均返回对应的 JSON 契约。"""

    def __init__(self, reviews: list[str], repair_items: list[dict] | None = None,
                 solve_payload: dict | None = None):
        self.reviews = reviews
        self.repair_items = repair_items or []
        self.solve_payload = solve_payload
        self.eval_calls = 0
        self.solve_calls = 0
        self.repair_calls = 0
        self._lock = threading.Lock()

    def __call__(self, messages, api_key=None, temperature=0.7, max_tokens=None,
                 thinking_off=False, thinking=None, response_format=None):
        prompt = messages[-1]["content"]
        system = messages[0]["content"]
        with self._lock:
            if "独立数学审题人" in system:
                idx = min(self.eval_calls, len(self.reviews) - 1)
                self.eval_calls += 1
                return self.reviews[idx]
            if prompt.startswith("下面这道题没有通过"):
                self.repair_calls += 1
                item = self.repair_items[min(self.repair_calls - 1, len(self.repair_items) - 1)]
                return json.dumps(item, ensure_ascii=False)
            self.solve_calls += 1
            if self.solve_payload is not None:
                return self.solve_payload
            return {"answer_text": "$18$", "distractors": ["$-18$", "$81$", "$8.1$"],
                    "analysis": "由定义可得 $y'=3x^2$。", "confidence": "high"}


@pytest.fixture
def db():
    # 本文件不经过 client fixture：单文件运行时显式建表（幂等），避免依赖其他测试先建库
    Base.metadata.create_all(bind=engine)
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
    monkeypatch.setattr(question_review.llm, "chat_json", fake)

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
    # 解题模型负责答案与选项：正确答案文本随机分配到某个选项位，answer 为对应字母
    assert result[0].answer in {"A", "B", "C", "D"}
    assert len(result[0].options) == 4
    correct_texts = [o.text for o in result[0].options if o.label == result[0].answer]
    assert correct_texts == ["$18$"]
    assert "y'=3x^2" in result[0].analysis
    assert stats.solved == 1
    assert fake.solve_calls == 1


def test_duplicate_shortfall_is_refilled(db, monkeypatch):
    """查重丢掉一题后，按缺口重出，最终数量与请求一致。"""
    fake = FakeLLM(reviews=[_review_json(GOOD_SCORES)])
    monkeypatch.setattr(question_review.llm, "chat_text", fake)
    monkeypatch.setattr(question_review.llm, "chat_json", fake)
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


def test_solver_failure_drops_question(db, monkeypatch):
    """解题输出无效时题目无答案，审核链路将其剔除（宁可少给不出半成品）。"""
    class NoSolveChatJson:
        def __call__(self, messages, api_key=None, **kwargs):
            system = messages[0]["content"]
            if "独立数学审题人" in system:
                return json.loads(_review_json(GOOD_SCORES))
            return {"analysis": "解析", "confidence": "high"}  # 缺 answer_text

    monkeypatch.setattr(question_review.llm, "chat_json", NoSolveChatJson())

    params = GenerateParams(
        kb_id="bank_test", doc_id="doc_test",
        types=[TypeCount(type=QuestionType.single, count=1)],
        difficulty=Difficulty.high, scope="导数",
    )
    # 新流程下出题模型不产答案，题目的 answer/analysis 为空
    bare = Question(id="b1", type=QuestionType.single, score=5, difficulty=Difficulty.high,
                    stem="求 $y=x^2$ 的导数。", options=[], answer="", analysis="")
    result, stats = real_review(db, "u_test", [bare], params, "doc.md", "sk-test")

    assert result == []
    assert stats.solved == 0


def test_math_delimiters_are_normalized():
    text = question_review._normalize_math(r"由 \(f(0)=0\) 可得 \[M=\max|f|\]")
    assert r"\(" not in text and r"\[" not in text
    assert "$f(0)=0$" in text


def test_latex_issue_and_repair():
    # \( \) 定界在净化阶段统一转为 $，校验只报无法机械修复的问题
    repaired = latex_utils.fix_delimiters(r"由 \(x=2\) 可得 $$y$$ 与 $z$")
    assert repaired == "由 $x=2$ 可得 $$y$$ 与 $z$"
    assert question_review._latex_issue(repaired) is None
    assert question_review._latex_issue("奇数个 $ 符号") == "$ 定界不配对"
    assert question_review._latex_issue(r"裸的 \frac{1}{2} 命令") == "存在未用 $ 包裹的数学命令"


def test_independent_solver_assigns_random_options(monkeypatch):
    """选择题由解题模型解出答案文本并生成干扰项，代码随机分配选项位。"""
    calls = []

    def solve(messages, **kwargs):
        calls.append(messages)
        assert kwargs.get("thinking") is True  # 解题显式开启思考模式
        return {"answer_text": "$18$", "distractors": ["$-18$", "$81$", "$8.1$"],
                "analysis": r"由 \(x=2\) 可得答案 $18$。", "confidence": "low"}

    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    question = _q("独立求解 JSON 回归题目")
    result = question_review._solve_one(question, "fake-model-key")
    assert result is True
    assert len(calls) == 1
    assert calls[0][0]["content"] == question_review.SOLVE_SYSTEM
    labels = {o.label: o.text for o in question.options}
    assert set(labels) == {"A", "B", "C", "D"}
    assert len(set(labels.values())) == 4  # 四个选项互不相同
    correct = [lbl for lbl, txt in labels.items() if txt == "$18$"]
    assert len(correct) == 1  # 正确答案恰好占一个选项位
    assert question.answer == correct[0]
    # 解析经 LaTeX 机械修复：反斜杠括号已转为美元定界
    assert r"\(" not in question.analysis and "$x=2$" in question.analysis
    assert "置信度低" in question.selfCheck["note"]


def test_solver_invalid_output_leaves_question_unsolved(monkeypatch):
    """解题输出字段缺失、干扰项数量不符或解析违规时，题目保持无答案状态。"""
    base = {"answer_text": "$18$", "distractors": ["$-18$", "$81$", "$8.1$"],
            "analysis": "新的独立解析", "confidence": "high"}
    cases = [
        {**base, "answer_text": None},                 # 缺正确答案
        {**base, "distractors": ["$-18$"]},            # 干扰项数量不符
        {**base, "analysis": None},                    # 缺解析
        {**base, "analysis": "奇数个 $ 符号未闭合"},      # 解析 LaTeX 违规且不可机械修复
    ]
    for payload in cases:
        monkeypatch.setattr(question_review.llm, "chat_json", lambda *a, **kw: payload)
        question = _q("无效解题输出回归")
        stats = question_review.ReviewStats()
        question_review._solve_all([question], "fake-key", stats)
        # 解题失败不覆盖题目任何字段；新流程下出题模型本就不产答案
        assert question.answer == "A" and question.analysis == "旧解析"
        assert stats.solved == 0

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
