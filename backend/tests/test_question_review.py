"""出题中间件测试：查重、盲评映射与否决、双评仲裁、缺陷修补、解析覆盖。"""
import hashlib
import json
import threading

import pytest

from app.db import SessionLocal, Base, engine
from app.schemas.question import Difficulty, GenerateParams, OptionItem, Question, QuestionType, TypeCount
from app.services.generation_cancellation import GenerationCanceled
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
        self.explain_calls = 0
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
            # 解题分两步：先只求解，再依该答案写解析与干扰项
            if "数学解题专家" in system:
                self.solve_calls += 1
                if self.solve_payload is not None:
                    return self.solve_payload
                return {"answer": "$18$", "confidence": "high"}
            self.explain_calls += 1
            return {"analysis": "由定义可得 $y'=3x^2$。",
                    "distractors": ["$-18$", "$81$", "$8.1$"], "confidence": "high"}


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
            return {"analysis": "解析", "confidence": "high"}  # 缺 answer

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
    """选择题先由解题模型解出答案，再依该答案生成干扰项，代码随机分配选项位。"""
    calls = []

    def solve(messages, **kwargs):
        calls.append(messages)
        system = messages[0]["content"]
        if system == question_review.SOLVE_ANSWER_SYSTEM:
            assert kwargs.get("thinking") is True  # 求解显式开启思考模式
            return {"answer": "$18$", "confidence": "low"}
        assert system == question_review.SOLVE_EXPLAIN_SYSTEM
        return {"analysis": r"由 \(x=2\) 可得答案 $18$。",
                "distractors": ["$-18$", "$81$", "$8.1$"], "confidence": "low"}

    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    question = _q("独立求解 JSON 回归题目")
    result = question_review._solve_one(question, "fake-model-key")
    assert result is True
    assert len(calls) == 2  # 先求解、再讲解，两步分开
    labels = {o.label: o.text for o in question.options}
    assert set(labels) == {"A", "B", "C", "D"}
    assert len(set(labels.values())) == 4  # 四个选项互不相同
    correct = [lbl for lbl, txt in labels.items() if txt == "$18$"]
    assert len(correct) == 1  # 正确答案恰好占一个选项位
    assert question.answer == correct[0]
    # 解析经 LaTeX 机械修复：反斜杠括号已转为美元定界
    assert r"\(" not in question.analysis and "$x=2$" in question.analysis
    assert "置信度低" in question.selfCheck["note"]


def test_solver_rejects_analysis_with_draft_trace(monkeypatch):
    """解析里混入自我怀疑或重算草稿时判为不合格，不让它进题库。"""
    def solve(messages, **kwargs):
        system = messages[0]["content"]
        if system == question_review.SOLVE_ANSWER_SYSTEM:
            return {"answer": "$18$", "confidence": "high"}
        return {"analysis": "计算得到 $18$，不对，好像有误，应该是 $81$。",
                "distractors": ["$-18$", "$81$", "$8.1$"], "confidence": "high"}

    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    question = _q("草稿泄漏回归题目")
    assert question_review._solve_one(question, "fake-key") is False
    assert question.answer == "A" and question.analysis == "旧解析"


def test_solver_invalid_output_leaves_question_unsolved(monkeypatch):
    """求解缺答案、干扰项数量不符、解析缺失或 LaTeX 违规时，题目保持无答案状态。"""
    good_answer = {"answer": "$18$", "confidence": "high"}
    good_explain = {"analysis": "新的独立解析",
                    "distractors": ["$-18$", "$81$", "$8.1$"], "confidence": "high"}
    cases = [
        ({"answer": "", "confidence": "high"}, good_explain),                 # 答案为空
        ({"confidence": "high"}, good_explain),                               # 没有 answer 字段
        (good_answer, {"analysis": "新的独立解析", "distractors": ["$-18$"]}),   # 干扰项不足三个
        (good_answer, {"analysis": "", "distractors": ["$-18$", "$81$", "$8.1$"]}),  # 缺解析
        (good_answer, {"analysis": "奇数个 $ 符号未闭合",
                       "distractors": ["$-18$", "$81$", "$8.1$"]}),           # 解析 LaTeX 违规
    ]
    for answer_payload, explain_payload in cases:
        def solve(messages, _answer=answer_payload, _explain=explain_payload, **kwargs):
            system = messages[0]["content"]
            return _answer if system == question_review.SOLVE_ANSWER_SYSTEM else _explain

        monkeypatch.setattr(question_review.llm, "chat_json", solve)
        question = _q("无效解题输出回归")
        stats = question_review.ReviewStats()
        question_review._solve_all([question], "fake-key", stats)
        # 求解失败保留旧题；新题独立求解门禁由审核外层负责。
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


@pytest.mark.parametrize("qtype,payload", [
    (QuestionType.single, {"answer": "1", "distractors": ["$1$", "2", "3"]}),
    (QuestionType.single, {"answer": "1", "distractors": ["2", "2", "3"]}),
    (QuestionType.single, {"answer": {}, "distractors": ["2", "3", "4"]}),
    (QuestionType.multiple, {"answer": ["1", "1"], "distractors": ["2", "3"]}),
    (QuestionType.multiple, {"answer": ["1", "2"], "distractors": ["2", "3"]}),
    (QuestionType.blank, {"answer": ""}),
    (QuestionType.blank, {"answer": {"unexpected": "shape"}}),
    (QuestionType.blank, {"answer": "$$未闭合"}),
    (QuestionType.judge, {"answer": "无法判断"}),
])
def test_invalid_solver_output_preserves_entire_existing_question(monkeypatch, qtype, payload):
    question = _q("已有答案的保护回归", qtype)
    question.selfCheck = {"note": "旧备注"}
    before = question.model_dump()
    def solve(messages, **kwargs):
        if messages[0]["content"] == question_review.SOLVE_ANSWER_SYSTEM:
            return {"answer": payload.get("answer"), "confidence": "low"}
        return {**payload, "analysis": "关键步骤"}

    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    stats = question_review.ReviewStats()
    question_review._solve_all([question], None, stats)
    assert question.model_dump() == before
    assert stats.solved == 0


def test_solver_transport_failure_preserves_existing_question(db, monkeypatch):
    question = _q("已有完整答案")
    before = question.model_dump()

    def fail(*args, **kwargs):
        raise question_review.llm.LLMError("模型调用失败，请稍后重试")

    monkeypatch.setattr(question_review.llm, "chat_json", fail)
    monkeypatch.setattr(question_review, "evaluate", lambda *a, **k: {"unknown": True})
    params = GenerateParams(
        kb_id="fake-bank", doc_id="fake-document",
        types=[TypeCount(type=QuestionType.single, count=1)],
    )
    result, stats = real_review(db, "fake-user", [question], params, "fake.pdf", None)
    assert result == [question]
    assert question.answer == before["answer"]
    assert question.options == [OptionItem.model_validate(item) for item in before["options"]]
    assert question.analysis == before["analysis"]
    assert stats.solved == 0


@pytest.mark.parametrize("source", ["repair", "regenerate"])
def test_fast_model_answer_cannot_replace_independent_solution(db, monkeypatch, source):
    question = _q("无答案的新题：求函数在原点的导数。")
    question.answer = ""
    question.analysis = ""
    replacement = _q("快速模型修改题干后的答案尚未独立验证。")
    replacement.id = question.id
    monkeypatch.setattr(question_review, "evaluate", lambda q, *a, **k: {
        "passed": q is replacement, "total": 3.5,
    })
    monkeypatch.setattr(question_review, "_repair", lambda *a, **k: (
        replacement if source == "repair" else None
    ))
    monkeypatch.setattr(question_review, "_regen", lambda *a, **k: [replacement])
    monkeypatch.setattr(question_review, "_solve_one", lambda *a, **k: False)
    params = GenerateParams(kb_id="fake-bank", doc_id="fake-doc",
                            types=[TypeCount(type=QuestionType.single, count=1)])
    result, stats = real_review(db, "fake-user", [question], params, "fake.pdf", None)
    assert result == []
    assert stats.solved == 0
    assert stats.repaired == (1 if source == "repair" else 0)
    assert stats.regenerated == (1 if source == "regenerate" else 0)


@pytest.mark.parametrize("source_mode", ["new", "variant_data", "variant_context", "original"])
@pytest.mark.parametrize("qtype", list(QuestionType))
def test_real_gen_batch_cannot_deliver_fast_model_answer_without_solving(
    db, monkeypatch, source_mode, qtype,
):
    """真实流式解析和命题后处理必须阻断快速模型答案冒充已有有效题。"""
    payload = {
        "type": qtype.value, "stem": "命题边界回归：求函数在给定点处的导数。",
        "answer": "A", "analysis": "",
        "options": [{"label": "A", "text": "快速模型选项一"},
                    {"label": "B", "text": "快速模型选项二"}],
    }
    stream_calls, solve_calls = [], []

    def stream(*args, **kwargs):
        stream_calls.append(1)
        yield json.dumps({"questions": [payload]}, ensure_ascii=False)

    def solve(*args, **kwargs):
        solve_calls.append(1)
        return {}

    monkeypatch.setattr(question_review.question_gen.llm, "chat_stream", stream)
    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    monkeypatch.setattr(question_review, "evaluate", lambda *a, **k: {"unknown": True})
    tc = TypeCount(type=qtype, count=1)
    params = GenerateParams(kb_id="fake-bank", doc_id="fake-doc", types=[tc],
                            source_mode=source_mode)
    generated = question_review.question_gen._gen_batch(
        tc, params, "fake.pdf", None, 1, [], False, None, [{"text": "fixture context"}], "",
    )
    result, stats = real_review(db, "fake-user", generated, params, "fake.pdf", None)
    assert result == []
    assert stats.solved == 0
    assert stream_calls == [1] and solve_calls == [1, 1]
    assert generated[0].answer == generated[0].analysis == ""
    expected = [OptionItem(label="A", text="正确"), OptionItem(label="B", text="错误")]
    assert generated[0].options == (expected if qtype == QuestionType.judge else [])


def test_original_existing_question_survives_failed_independent_solve(db, monkeypatch):
    """已有有效原题直接送审，不经模型命题边界时继续保留原答案、解析与选项。"""
    question = _q("题库直接提取的有效原题：求函数的导数。")
    before = question.model_dump()
    monkeypatch.setattr(question_review.llm, "chat_json", lambda *a, **k: {})
    monkeypatch.setattr(question_review, "evaluate", lambda *a, **k: {"unknown": True})
    params = GenerateParams(kb_id="fake-bank", doc_id="fake-doc", source_mode="original",
                            types=[TypeCount(type=QuestionType.single, count=1)])
    result, stats = real_review(db, "fake-user", [question], params, "fake.pdf", None)
    assert result == [question] and stats.solved == 0
    assert question.answer == before["answer"]
    assert question.analysis == before["analysis"]
    assert [item.model_dump() for item in question.options] == before["options"]


def test_cross_round_stems_share_normalized_review_corpus(db, monkeypatch):
    stem = "求函数 $y=x^2$ 在原点的导数"
    monkeypatch.setattr(question_review, "load_corpus", lambda *a: [stem + "."])
    monkeypatch.setattr(question_review, "evaluate", lambda *a, **k: {"unknown": True})
    monkeypatch.setattr(question_review, "_regen", lambda *a, **k: [])
    monkeypatch.setattr(question_review, "_solve_one", lambda *a, **k: False)
    seen = []
    drop = question_review._drop_duplicates

    def check_corpus(questions, corpus, **kwargs):
        seen.append(list(corpus))
        return drop(questions, corpus, **kwargs)

    monkeypatch.setattr(question_review, "_drop_duplicates", check_corpus)
    params = GenerateParams(
        kb_id="fake-bank", doc_id="fake-doc",
        types=[TypeCount(type=QuestionType.single, count=1)],
        existing_stems=[stem + "?", "证明数列的极限等于给定常数."],
    )
    result, stats = real_review(
        db, "fake-user", [_q("证明数列的极限等于给定常数?")], params, "fake.pdf", None,
    )
    assert result == []
    assert stats.duplicates == 1
    assert seen[0] == [stem + ".", "证明数列的极限等于给定常数."]


def test_multiple_solver_maps_all_correct_answers_to_shuffled_labels(monkeypatch):
    question = _q("多选题回归", QuestionType.multiple)
    def solve(messages, **kwargs):
        if messages[0]["content"] == question_review.SOLVE_ANSWER_SYSTEM:
            return {"answer": ["1", "2"]}
        return {"distractors": ["3", "4"], "analysis": "逐项判断正确项为 1、2。"}

    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    assert question_review._solve_one(question, None)
    assert len(question.answer) == 2
    assert {item.text for item in question.options if item.label in question.answer} == {"1", "2"}


def test_canceled_solver_batch_does_not_apply_already_solved_candidates(monkeypatch):
    questions = [_q("第一题"), _q("第二题")]
    snapshots = [question.model_dump() for question in questions]
    calls = []

    def solve(messages, **kwargs):
        calls.append(messages)
        if len(calls) == 3:
            raise GenerationCanceled("fixture canceled")
        if messages[0]["content"] == question_review.SOLVE_ANSWER_SYSTEM:
            return {"answer": "18", "confidence": "low"}
        return {"distractors": ["-18", "81", "8.1"], "analysis": "关键步骤得 18。"}

    monkeypatch.setattr(question_review, "_THINK_WORKERS", 1)
    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    stats = question_review.ReviewStats()
    with pytest.raises(GenerationCanceled):
        question_review._solve_all(questions, None, stats)
    assert len(calls) == 3  # 第一题两步已完成，第二题取消时仍不得回写第一题。
    assert [question.model_dump() for question in questions] == snapshots
    assert stats.solved == 0


def test_review_releases_read_transaction_before_models_and_progress(db, monkeypatch):
    checks = []
    phases = []

    def model(messages, **kwargs):
        checks.append(not db.in_transaction())
        return {"answer": "1", "analysis": "关键步骤得 1。"}

    def evaluate(*args, **kwargs):
        checks.append(not db.in_transaction())
        return {"unknown": True}

    def progress(percent, stage):
        checks.append(not db.in_transaction())
        phases.append(percent)

    monkeypatch.setattr(question_review.llm, "chat_json", model)
    monkeypatch.setattr(question_review, "evaluate", evaluate)
    question = Question(type=QuestionType.blank, stem="求导")
    params = GenerateParams(
        kb_id="fake-bank", doc_id="fake-document",
        types=[TypeCount(type=QuestionType.blank, count=1)],
    )
    result, stats = real_review(db, "fake-user", [question], params, "fake.pdf", None,
                                progress=progress)
    assert result[0].answer == "1" and stats.solved == 1
    assert checks and all(checks)
    assert phases[-1] == 100
    assert not db.in_transaction()


@pytest.mark.parametrize("conclusion,answer,agrees", [
    ("", "5", True),
    ("5", "25", False),
    ("$5$", "5", True),
    ("结果为 5", "5", True),
])
def test_optional_conclusion_keeps_agent_comparison(conclusion, answer, agrees):
    assert question_review._answers_agree(conclusion, answer) is agrees


@pytest.mark.parametrize("recovers", [True, False])
def test_contradictory_explanation_restarts_solving_without_partial_updates(monkeypatch, recovers):
    calls = []
    answers = iter(["17", "5" if recovers else "17"])

    def solve(messages, **kwargs):
        system = messages[0]["content"]
        calls.append(system)
        if system == question_review.SOLVE_ANSWER_SYSTEM:
            return {"answer": next(answers)}
        assert "thinking_off" not in kwargs
        return {
            "analysis": "按题干计算得到 5。", "conclusion": "5",
            "distractors": ["1", "2", "3"],
        }

    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    question = _q("答案与解析矛盾")
    before = question.model_dump()
    stats = question_review.ReviewStats()
    solved = question_review._solve_all([question], None, stats)
    assert len(calls) == 4
    assert solved == ({id(question)} if recovers else set())
    assert stats.solved == int(recovers)
    if recovers:
        assert next(item.text for item in question.options if item.label == question.answer) == "5"
    else:
        assert question.model_dump() == before


@pytest.mark.parametrize("phase", ["answer", "explain"])
@pytest.mark.parametrize("transport_error", [False, True])
def test_two_solver_phases_retry_independently(monkeypatch, phase, transport_error):
    calls = {"answer": 0, "explain": 0}

    def solve(messages, **kwargs):
        step = "answer" if messages[0]["content"] == question_review.SOLVE_ANSWER_SYSTEM else "explain"
        calls[step] += 1
        if step == phase and calls[step] == 1:
            if transport_error:
                raise question_review.llm.LLMError("fixture unavailable")
            return {}
        if step == "answer":
            assert kwargs["thinking"] is True
            return {"answer": "18"}
        assert "thinking_off" not in kwargs
        return {"analysis": "结果为 18。", "distractors": ["1", "2", "3"]}

    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    assert question_review._solve_one(_q("分阶段重试"), None)
    assert calls == {"answer": 1 + int(phase == "answer"), "explain": 1 + int(phase == "explain")}


@pytest.mark.parametrize("phase", ["answer", "explain"])
@pytest.mark.parametrize("transport_error", [False, True])
def test_two_step_cancellation_propagates_without_retry(monkeypatch, phase, transport_error):
    canceled = threading.Event()
    calls = []

    def check():
        if canceled.is_set():
            raise GenerationCanceled("fixture canceled")

    def solve(messages, **kwargs):
        assert kwargs["cancel_check"] is check
        step = "answer" if messages[0]["content"] == question_review.SOLVE_ANSWER_SYSTEM else "explain"
        calls.append(step)
        if step == phase:
            canceled.set()
            if transport_error:
                raise question_review.llm.LLMError("fixture unavailable")
            return {}
        return {"answer": "18"}

    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    question = _q("取消保护")
    before = question.model_dump()
    with pytest.raises(GenerationCanceled):
        question_review._solve_one(question, None, cancel_check=check)
    assert calls == (["answer"] if phase == "answer" else ["answer", "explain"])
    assert question.model_dump() == before


@pytest.mark.parametrize("answer_payload,explain_payload", [
    ({"answer": ["1"]}, {}),
    ({"answer": 1}, {}),
    ({"answer": "1"}, {"analysis": {"invalid": "shape"}}),
    ({"answer": "1"}, {"distractors": [2, "3", "4"]}),
    ({"answer": "1"}, {"distractors": "234"}),
    ({"answer": "1"}, {"conclusion": ["1"]}),
    ({"answer": "1"}, {"distractors": ["2", "$2$", "4"]}),
])
def test_two_step_solver_rejects_wrong_field_types_and_normalized_duplicates(
    monkeypatch, answer_payload, explain_payload,
):
    def solve(messages, **kwargs):
        if messages[0]["content"] == question_review.SOLVE_ANSWER_SYSTEM:
            return answer_payload
        return {"analysis": "关键步骤", "distractors": ["2", "3", "4"], **explain_payload}

    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    question = _q("严格字段验证")
    before = question.model_dump()
    assert not question_review._solve_one(question, None)
    assert question.model_dump() == before
