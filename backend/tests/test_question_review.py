"""出题中间件测试：查重、盲评映射与否决、双评仲裁、缺陷修补、解析覆盖。"""
import hashlib
import json
import threading
from types import SimpleNamespace

import httpx
import pytest

from app.db import SessionLocal, Base, engine
from app.schemas.question import Difficulty, GenerateParams, OptionItem, Question, QuestionType, TypeCount
from app.services.generation_cancellation import GenerationCanceled
from app.services import latex_utils, question_review
from app.services.rag import question_gen
from app.services.question_review import review_questions as real_review

_REAL_EMBED_TEXTS = question_review.embeddings.embed_texts


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
        **dict.fromkeys(question_review._JOINT_FIELDS, True),
        "verifiable": True,
        "evidence": "对多项式直接求导并代入验证。",
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
                return {"answer": "$18$", "confidence": "high",
                        "status": "solved", "evidence": "求导后代入得 18"}
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


def test_exact_tier_boundaries():
    assert question_review.in_target(1.0, Difficulty.low)
    for lower, higher, cutoff in [
        (Difficulty.low, Difficulty.mid, 2.0),
        (Difficulty.mid, Difficulty.high, 3.0),
        (Difficulty.high, Difficulty.hell, 4.0),
    ]:
        assert question_review.in_target(cutoff - 0.01, lower)
        assert not question_review.in_target(cutoff, lower)
        assert question_review.in_target(cutoff, higher)
        assert not question_review.in_target(cutoff - 0.01, higher)
    assert question_review.in_target(5.0, Difficulty.hell)


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

    def solve(messages, **kwargs):
        result = fake(messages, **kwargs)
        answer = "3" if "修补后的题干" in messages[-1]["content"] else "2"
        return {**result, "answer": answer, "evidence": f"求导后代入得 {answer}。"}

    monkeypatch.setattr(question_review.llm, "chat_json", solve)

    params = GenerateParams(
        kb_id="bank_test", doc_id="doc_test",
        types=[TypeCount(type=QuestionType.single, count=1)],
        difficulty=Difficulty.high, scope="导数",
    )
    original = _q("原题：求 $y=x^2$ 在 $x=1$ 处的导数。")
    original.answer = "B"
    original.analysis = "求导得 $2x$，代入得 2。"
    result, stats = real_review(db, "u_test", [original], params, "doc.md", "sk-test")

    assert stats.repaired == 1
    assert len(result) == 1
    assert result[0].stem.startswith("修补后的题干")
    assert result[0].difficultyScore > 3
    assert result[0].answer == "B"
    assert "代入得 3" in result[0].analysis
    assert stats.solved == 1
    assert not stats.rejections
    assert fake.solve_calls == 2 and fake.repair_calls == 1


def test_duplicate_shortfall_is_left_for_caller(db, monkeypatch):
    fake = FakeLLM(
        reviews=[_review_json(GOOD_SCORES)],
        solve_payload={"status": "solved", "answer": "3", "evidence": "在 $x=1$ 代入得 3。"},
    )
    monkeypatch.setattr(question_review.llm, "chat_text", fake)
    monkeypatch.setattr(question_review.llm, "chat_json", fake)
    monkeypatch.setattr(question_review, "load_corpus", lambda *_a, **_k: ["求 $y=x^2$ 的导数。"])

    def unexpected_regen(*args, **kwargs):
        pytest.fail("候选审核不得生成补题")

    monkeypatch.setattr(question_gen, "generate_questions", unexpected_regen)

    params = GenerateParams(
        kb_id="bank_test", doc_id="doc_test",
        types=[TypeCount(type=QuestionType.single, count=2)],
        difficulty=Difficulty.high, scope="导数",
    )
    candidate = _q("求 $y=x^3$ 在 $x=1$ 处的导数。")
    candidate.options[0].text = "3"
    candidate.analysis = "求导得 $3x^2$，代入得 3。"
    result, stats = real_review(
        db, "u_test", [_q("求 $y=x^2$ 的导数。"), candidate], params, "doc.md", "sk-test",
    )

    assert stats.duplicates == 1
    assert stats.regenerated == 0
    assert stats.rejections == {(QuestionType.single, Difficulty.high): {"重复题目": 1}}
    assert len(result) == 1


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


def test_solver_transport_failure_rejects_even_with_existing_answer(db, monkeypatch):
    question = _q("已有完整答案")
    before = question.model_dump()

    def fail(*args, **kwargs):
        raise question_review.llm.LLMError("模型调用失败，请稍后重试")

    monkeypatch.setattr(question_review.llm, "chat_json", fail)
    monkeypatch.setattr(question_review, "evaluate", lambda *a, **k: {"unknown": True})
    params = GenerateParams(
        kb_id="fake-bank", doc_id="fake-document",
        types=[TypeCount(type=QuestionType.single, count=1)], difficulty=Difficulty.high,
    )
    result, stats = real_review(db, "fake-user", [question], params, "fake.pdf", None)
    assert result == []
    assert stats.rejections == {(QuestionType.single, Difficulty.high): {"无法验证": 1}}
    assert question.answer == before["answer"]
    assert question.options == [OptionItem.model_validate(item) for item in before["options"]]
    assert question.analysis == before["analysis"]
    assert stats.solved == 0


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

    monkeypatch.setattr(question_gen.llm, "chat_stream", stream)
    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    monkeypatch.setattr(question_review, "evaluate", lambda *a, **k: {"unknown": True})
    tc = TypeCount(type=qtype, count=1)
    params = GenerateParams(kb_id="fake-bank", doc_id="fake-doc", types=[tc],
                            source_mode=source_mode)
    generated = question_gen._gen_batch(
        tc, params, "fake.pdf", None, 1, [], False, None, [{"text": "fixture context"}], "",
    )
    result, stats = real_review(db, "fake-user", generated, params, "fake.pdf", None)
    assert result == []
    assert stats.solved == 0
    assert stream_calls == [1] and solve_calls == [1, 1]
    assert generated[0].answer == generated[0].analysis == ""
    expected = []
    if qtype == QuestionType.judge:
        expected = [OptionItem(label="A", text="正确"), OptionItem(label="B", text="错误")]
    elif source_mode == "original" and qtype in (QuestionType.single, QuestionType.multiple):
        expected = [OptionItem.model_validate(option) for option in payload["options"]]
    assert generated[0].options == expected


def test_original_existing_question_is_rejected_after_failed_solve(db, monkeypatch):
    """原题需要通过独立求解，审核失败时原始内容也不能被改写。"""
    question = _q("题库直接提取的有效原题：求函数的导数。")
    before = question.model_dump()
    monkeypatch.setattr(question_review.llm, "chat_json", lambda *a, **k: {})
    monkeypatch.setattr(question_review, "evaluate", lambda *a, **k: {"unknown": True})
    params = GenerateParams(kb_id="fake-bank", doc_id="fake-doc", source_mode="original",
                            types=[TypeCount(type=QuestionType.single, count=1)],
                            difficulty=Difficulty.high)
    result, stats = real_review(db, "fake-user", [question], params, "fake.pdf", None)
    assert result == [] and stats.solved == 0
    assert stats.rejections == {(QuestionType.single, Difficulty.high): {"无法验证": 1}}
    assert question.answer == before["answer"]
    assert question.analysis == before["analysis"]
    assert [item.model_dump() for item in question.options] == before["options"]


def test_cross_round_stems_share_normalized_review_corpus(db, monkeypatch):
    stem = "求函数 $y=x^2$ 在原点的导数"
    monkeypatch.setattr(question_review, "load_corpus", lambda *a: [stem + "."])
    monkeypatch.setattr(question_review, "evaluate", lambda *a, **k: {"unknown": True})
    params = GenerateParams(
        kb_id="fake-bank", doc_id="fake-doc",
        types=[TypeCount(type=QuestionType.single, count=1)],
        difficulty=Difficulty.high,
        existing_stems=[stem + "?", "证明数列的极限等于给定常数."],
    )
    result, stats = real_review(
        db, "fake-user", [_q("证明数列的极限等于给定常数?")], params, "fake.pdf", None,
    )
    assert result == []
    assert stats.duplicates == 1
    assert stats.rejections == {(QuestionType.single, Difficulty.high): {"重复题目": 1}}


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
        return {
            "answer": "1", "analysis": "关键步骤得 1。",
            "status": "solved", "evidence": "导数恒为 1。",
        }

    def judge(messages, **kwargs):
        checks.append(not db.in_transaction())
        return _review_json({**dict.fromkeys(question_review._SCORE_KEYS, 2), "unique": 5})

    def progress(percent, stage):
        checks.append(not db.in_transaction())
        phases.append(percent)

    monkeypatch.setattr(question_review.llm, "chat_json", model)
    monkeypatch.setattr(question_review.llm, "chat_text", judge)
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


def _candidate_params(*items, source_mode="new", existing_stems=None):
    return GenerateParams(
        kb_id="fake-bank",
        doc_id="fake-doc",
        scope="导数与初等代数",
        source_mode=source_mode,
        existing_stems=existing_stems or [],
        types=[TypeCount(type=qtype, difficulty=tier, count=1) for qtype, tier in items],
    )


@pytest.mark.parametrize("outcome", ["pass", "duplicate", "bad_analysis", "changed_original"])
def test_counterexample_repair_restarts_complete_review(db, monkeypatch, outcome):
    original = outcome == "changed_original"
    question = Question(
        type=QuestionType.essay, difficulty=Difficulty.low,
        stem="证明对所有实数 $x$，都有 $x^2>x$。",
    )
    repaired = question.model_copy(update={
        "stem": "证明对所有实数 $x$，都有 $x^2\u2265 0$。",
        "answer": "成立",
        "analysis": "实数的平方非负，因此不等式恒成立。",
    })
    counterexample = "$x=0$ 时两边相等，严格不等式不成立。"
    repair_calls, solve_calls, joint_calls = [], [], []

    def solve(messages, **_):
        prompt = messages[-1]["content"]
        solve_calls.append(prompt)
        if original:
            return {"status": "solved", "answer": "不成立", "evidence": counterexample}
        if question.stem in prompt:
            return {"status": "false_proposition", "evidence": counterexample}
        assert repaired.stem in prompt
        return {"status": "solved", "answer": "成立", "evidence": "实数平方非负。"}

    def verify_or_repair(messages, **_):
        prompt = messages[-1]["content"]
        if prompt.startswith("下面这道题没有通过"):
            repair_calls.append(prompt)
            assert counterexample in prompt
            return repaired.model_dump_json()
        joint_calls.append(prompt)
        report = json.loads(_review_json({**dict.fromkeys(question_review._SCORE_KEYS, 1), "unique": 5}))
        if original:
            report.update(scopeValid=False, passed=False, evidence=counterexample)
        else:
            assert repaired.stem in prompt and repaired.analysis in prompt
            if outcome == "bad_analysis":
                report.update(analysisValid=False, passed=False, evidence="解析未覆盖小问。")
        return json.dumps(report, ensure_ascii=False)

    if original:
        question.answer = "不成立"
        question.analysis = "引用范围之外的定理判定。"
    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    monkeypatch.setattr(question_review.llm, "chat_text", verify_or_repair)
    params = _candidate_params(
        (QuestionType.essay, Difficulty.low),
        source_mode="original" if original else "new",
        existing_stems=[repaired.stem] if outcome == "duplicate" else [],
    )
    result, stats = real_review(db, "u", [question], params, "doc.md", None)

    assert len(repair_calls) == 1
    assert len(solve_calls) == (1 if original else 2)
    assert len(joint_calls) == (2 if original else 1)
    assert question.stem != repaired.stem
    if outcome == "pass":
        assert result[0].stem == repaired.stem
        assert stats.rejections == {}
    else:
        reason = {
            "duplicate": "重复题目", "bad_analysis": "解析不成立",
            "changed_original": "原题被改动",
        }[outcome]
        assert not result
        assert stats.rejections == {(question.type, question.difficulty): {reason: 1}}


@pytest.mark.parametrize("solve_status, reason", [
    ("insufficient_conditions", "题设不足"),
    ("contradictory_conditions", "条件矛盾"),
    ("unverifiable", "无法验证"),
    ("", "无法验证"),
])
def test_missing_or_invalid_multiple_choice_is_never_delivered(db, monkeypatch, solve_status, reason):
    qtype = QuestionType.multiple
    eligible = Question(type=qtype, difficulty=Difficulty.low, stem="以下正确的说法有哪些？")
    other_tier = eligible.model_copy(update={"difficulty": Difficulty.hell, "stem": "不在本组配额"})
    progress = []

    def solve(messages, **_):
        prompt = messages[-1]["content"]
        assert eligible.stem in prompt and other_tier.stem not in prompt
        progress.append("solve")
        return {"status": solve_status, "evidence": "缺少供判断的数学命题。"}

    def repair(messages, **_):
        assert "缺少供判断的数学命题" in messages[-1]["content"]
        progress.append("repair")
        return "{}"

    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    monkeypatch.setattr(question_review.llm, "chat_text", repair)
    result, stats = real_review(
        db, "u", [eligible, other_tier], _candidate_params((qtype, Difficulty.low)), "doc.md", None,
    )
    assert not result
    assert stats.rejections == {(qtype, Difficulty.low): {reason: 1}}
    assert progress == (["solve", "repair"] if reason != "无法验证" else
                        ["solve"] if solve_status else ["solve", "solve"])


@pytest.mark.parametrize("outcome", ["verified", "undefined_option", "missing_evidence", "wrong_tier"])
def test_joint_gate_checks_original_choice_options(db, monkeypatch, outcome):
    question = Question(
        type=QuestionType.multiple, difficulty=Difficulty.mid,
        stem="在实数范围内选出成立的陈述。",
        options=[
            OptionItem(label="A", text="$2^2=4$"), OptionItem(label="B", text="$3^2=9$"),
            OptionItem(label="C", text="$4^2=8$"), OptionItem(label="D", text="$5^2=10$"),
        ],
        answer="AB",
        analysis="逐项计算得 4、9、16、25，因此只有 A、B 成立。",
    )
    if outcome == "undefined_option":
        question.options[2].text = r"$\sqrt{-1}=0$"
    monkeypatch.setattr(
        question_review.llm, "chat_json",
        lambda *a, **k: {"status": "solved", "answer": ["$2^2=4$", "$3^2=9$"],
                         "evidence": "直接计算前两项等式成立。"},
    )

    def judge_or_repair(messages, **_):
        prompt = messages[-1]["content"]
        if prompt.startswith("下面这道题没有通过"):
            assert outcome == "undefined_option" and "实数域无定义" in prompt
            return "{}"
        for value in [question.stem, question.answer, question.analysis]:
            assert value in prompt
        for option in question.options:
            assert json.dumps(option.text, ensure_ascii=False) in prompt
        score = 3 if outcome == "wrong_tier" else 2
        report = json.loads(_review_json({**dict.fromkeys(question_review._SCORE_KEYS, score), "unique": 5}))
        if outcome == "undefined_option":
            report.update(optionsValid=False, passed=False, evidence="选项 C 在实数域无定义。")
        elif outcome == "missing_evidence":
            report["evidence"] = ""
        return json.dumps(report, ensure_ascii=False)

    monkeypatch.setattr(question_review.llm, "chat_text", judge_or_repair)
    result, stats = real_review(
        db, "u", [question], _candidate_params((question.type, question.difficulty),
                                              source_mode="original"), "doc.md", None,
    )
    if outcome == "verified":
        assert result[0].options == question.options
        assert stats.rejections == {}
    else:
        reason = {
            "undefined_option": "选项不合格", "missing_evidence": "无法验证",
            "wrong_tier": "难度不符",
        }[outcome]
        assert not result
        assert stats.rejections == {(question.type, question.difficulty): {reason: 1}}


def test_false_judgment_is_a_valid_solution(db, monkeypatch):
    question = Question(
        type=QuestionType.judge, difficulty=Difficulty.low,
        stem="判断命题：所有实数的平方都严格大于零。",
    )

    def solve(messages, **_):
        if messages[0]["content"].startswith(question_review.SOLVE_ANSWER_SYSTEM):
            return {"status": "solved", "answer": "错误", "evidence": "$0^2=0$。"}
        return {"analysis": "取 $x=0$，平方等于零。", "conclusion": "错误"}

    def verify(messages, **_):
        payload = messages[-1]["content"]
        assert '"answer": "B"' in payload
        assert '平方等于零' in payload
        return _review_json({**dict.fromkeys(question_review._SCORE_KEYS, 1), "unique": 5})

    monkeypatch.setattr(question_review.llm, "chat_json", solve)
    monkeypatch.setattr(question_review.llm, "chat_text", verify)
    result, stats = real_review(
        db, "u", [question], _candidate_params((question.type, question.difficulty)), "doc.md", None,
    )
    assert result[0].answer == "B"
    assert stats.solved == 1 and not stats.rejections


@pytest.mark.parametrize("qtype, solved, texts, answer, accepted", [
    (QuestionType.single, "12", ["12", "2"], "B", False),
    (QuestionType.single, r"P\leftarrow Q", [r"Q\rightarrow P", r"P\rightarrow Q"], "B", False),
    (QuestionType.single, r"P\leftarrow Q", [r"P\leftarrow Q", r"P\rightarrow Q"], "A", True),
    (QuestionType.multiple, ["2", "3"], ["2", "3", "13", "5"], "AC", False),
    (QuestionType.multiple, ["3", "$2$"], ["2", "3", "13", "5"], "BA", True),
    (QuestionType.judge, "错误", ["正确", "错误"], "A", False),
    (QuestionType.judge, "错误", ["错误", "正确"], "B", False),
])
def test_candidate_requires_exact_selected_answer_texts(
    db, monkeypatch, qtype, solved, texts, answer, accepted,
):
    question = Question(
        type=qtype, difficulty=Difficulty.low, stem="按条件选出成立的结论。",
        options=[OptionItem(label=label, text=item) for label, item in zip("ABCD", texts)],
        answer=answer, analysis="根据条件逐项判断。",
    )
    monkeypatch.setattr(question_review.llm, "chat_json", lambda *a, **k: {
        "status": "solved", "answer": solved, "evidence": "计算得到独立结果。",
    })
    repair_prompts = []
    scores = {**dict.fromkeys(question_review._SCORE_KEYS, 1), "unique": 5}

    def judge_or_repair(messages, **_):
        prompt = messages[-1]["content"]
        if prompt.startswith("下面这道题没有通过"):
            repair_prompts.append(prompt)
            return question.model_dump_json()
        return _review_json(scores)

    monkeypatch.setattr(question_review.llm, "chat_text", judge_or_repair)
    result, stats = real_review(
        db, "u", [question], _candidate_params((qtype, Difficulty.low)), "doc.md", None,
    )
    assert bool(result) is accepted
    if accepted:
        assert not repair_prompts and not stats.rejections
    else:
        assert len(repair_prompts) == 1 and "独立求解" in repair_prompts[0]
        assert stats.rejections == {(qtype, Difficulty.low): {"答案不成立": 1}}


def test_original_choice_without_source_options_is_rejected_before_solving(db, monkeypatch):
    question = Question(type=QuestionType.single, stem="求方程 $x+1=2$ 的解。")

    def unexpected(*args, **kwargs):
        pytest.fail("原题缺少选项时不应重新生成选项")

    monkeypatch.setattr(question_review.llm, "chat_json", unexpected)
    key = (question.type, question.difficulty)
    result, stats = real_review(
        db, "u", [question], _candidate_params(key, source_mode="original"), "doc.md", None,
    )
    assert not result
    assert stats.rejections == {key: {"原题选项缺失": 1}}


@pytest.mark.parametrize("has_defect", [True, False])
def test_candidate_keeps_verified_defect_when_peer_judge_is_unavailable(db, monkeypatch, has_defect):
    qtype = QuestionType.essay
    question = Question(
        type=qtype, difficulty=Difficulty.low, stem="证明实数平方非负。",
        answer="成立", analysis="依定理可知。",
    )
    repaired = question.model_copy(update={"analysis": "由实数乘法符号规则，平方非负。"})
    monkeypatch.setattr(question_review.llm, "chat_json", lambda *a, **k: {
        "status": "solved", "answer": "成立", "evidence": "同号实数相乘非负。",
    })
    lock = threading.Lock()
    completed = False
    repairs = []
    evidence = "解析未给出证明依据。"
    scores = {**dict.fromkeys(question_review._SCORE_KEYS, 1), "unique": 5}

    def judge_or_repair(messages, **_):
        nonlocal completed
        prompt = messages[-1]["content"]
        if prompt.startswith("下面这道题没有通过"):
            repairs.append(prompt)
            return repaired.model_dump_json()
        if repaired.analysis in prompt:
            return _review_json(scores)
        with lock:
            if completed:
                raise RuntimeError("fake judge unavailable")
            completed = True
        report = json.loads(_review_json(scores))
        if has_defect:
            report.update(analysisValid=False, passed=False, evidence=evidence)
        return json.dumps(report)

    monkeypatch.setattr(question_review.llm, "chat_text", judge_or_repair)
    result, stats = real_review(
        db, "u", [question], _candidate_params((qtype, Difficulty.low)), "doc.md", None,
    )
    if has_defect:
        assert len(repairs) == 1 and evidence in repairs[0]
        assert result[0].analysis == repaired.analysis and not stats.rejections
    else:
        assert not repairs and not result
        assert stats.rejections == {(qtype, Difficulty.low): {"无法验证": 1}}


def test_candidate_duplicate_check_cancels_between_embedding_sub_batches(monkeypatch):
    embeddings = question_review.embeddings
    requests = []
    config = SimpleNamespace(
        embedding_api_key="fake-key", embedding_base_url="https://embed.invalid",
        embedding_model="fake-model",
    )

    def respond(request):
        batch = json.loads(request.content)["input"]
        requests.append(batch)
        return httpx.Response(200, json={"data": [
            {"index": index, "embedding": [1.0]} for index in range(len(batch))
        ]})

    def cancel():
        if requests:
            raise GenerationCanceled("fixture canceled")

    client_class = httpx.Client
    transport = httpx.MockTransport(respond)
    monkeypatch.setattr(embeddings, "current_snapshot", lambda: SimpleNamespace(config=config))
    monkeypatch.setattr(embeddings, "embed_texts", _REAL_EMBED_TEXTS)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: client_class(
        transport=transport, **kwargs,
    ))
    corpus = [f"语料题 {index}" for index in range(65)]

    with pytest.raises(GenerationCanceled):
        question_review._drop_duplicates([_q("待判重题")], corpus, cancel_check=cancel)
    assert requests == [corpus[:32]]
