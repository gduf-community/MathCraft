"""题目流边界：残损输出修复、资源释放及可诊断的契约错误。"""

import json
from unittest.mock import Mock

import pytest

from app.services.rag import question_gen
from app.services.generation_cancellation import GenerationCanceled
from app.schemas.question import GenerateParams, Question, QuestionType, TypeCount
from app.services.rag.question_gen import (
    QuestionOutputError,
    _RollingParser,
    _schema_validate,
    _stream_questions,
)


def _question(stem: str) -> dict[str, str]:
    return {
        "type": "compute", "stem": stem,
        "answer": "$2x$", "analysis": "使用幂函数求导法则",
    }


def test_rolling_parser_emits_complete_questions_before_stream_ends() -> None:
    """分片可切在 JSON 字符串与对象边界；已交付题目不能在收尾重复。"""
    first = _question('求导，保留字符串中的括号 } ] 与引号 "')
    second = _question("第二题：求函数 $x^2$ 的导数")
    encoded_first = json.dumps(first, ensure_ascii=False)
    encoded_second = json.dumps(second, ensure_ascii=False)
    parser = _RollingParser()
    parser.feed('<questions>\n{"ques')
    assert parser.extract(_schema_validate) == []
    parser.feed('tions": [' + encoded_first[:-1])
    assert parser.extract(_schema_validate) == []

    parser.feed(encoded_first[-1:] + ",")
    emitted_first = parser.extract(_schema_validate)
    assert [question.stem for question in emitted_first] == [first["stem"]]
    assert parser.extract(_schema_validate) == []

    emitted_second = []
    for character in encoded_second:
        parser.feed(character)
        emitted_second.extend(parser.extract(_schema_validate))
    assert [question.stem for question in emitted_second] == [second["stem"]]
    parser.feed("]}\n</questions>")
    assert parser.extract(_schema_validate) == []
    assert parser.finish(_schema_validate) == []


def test_stream_repairs_damaged_tail_without_duplicate_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """末题有多余逗号且缺数组闭合字符时，修复仍应保留两题且不重复首题。"""
    first = _question("第一题")
    second = _question("第二题")
    chunks = [
        '{"questions": [' + json.dumps(first, ensure_ascii=False) + ",",
        json.dumps(second, ensure_ascii=False)[:-1] + ",}",
    ]
    monkeypatch.setattr(question_gen.llm, "chat_stream", Mock(return_value=iter(chunks)))

    questions = _stream_questions([], budget=100, api_key=None)

    assert [question.stem for question in questions] == ["第一题", "第二题"]
    assert all(question.answer == "$2x$" for question in questions)


@pytest.mark.parametrize("output", [
    "42", '{"questions": 42}', '{"questions": {"unexpected": true}}',
    '{"questions": [broken }',
])
def test_stream_rejects_scalars_and_damaged_output_as_question_errors(
    monkeypatch: pytest.MonkeyPatch, output: str,
) -> None:
    """真实 JSON Repair 遇到非题目输出时应返回业务错误，不能泄漏 TypeError。"""
    monkeypatch.setattr(question_gen.llm, "chat_stream", Mock(return_value=iter([output])))

    with pytest.raises(QuestionOutputError) as caught:
        _stream_questions([], budget=100, api_key=None)

    assert caught.value.summary
    assert caught.value.raw_excerpt == output


def test_schema_failure_closes_active_model_stream(monkeypatch):
    closed = []

    def stream(*args, **kwargs):
        try:
            yield '{"questions": [{"type": "single"}]}'
        finally:
            closed.append(True)

    monkeypatch.setattr(question_gen.llm, "chat_stream", stream)
    with pytest.raises(QuestionOutputError):
        _stream_questions([], budget=100, api_key=None)
    assert closed == [True]


def test_stream_preserves_split_bare_latex_commands(monkeypatch):
    """先收齐再修复，JSON 控制转义与跨分片命令均不能损坏公式。"""
    output = r'{"questions":[{"type":"compute","stem":"求 $\frac{1}{2} + \neq$"}]}'
    boundary = output.index("frac") + 2
    monkeypatch.setattr(
        question_gen.llm, "chat_stream", lambda *a, **k: iter([
            output[:boundary], output[boundary:],
        ]),
    )
    question, = _stream_questions([], budget=100, api_key=None)
    assert question.stem == r"求 $\frac{1}{2} + \neq$"


@pytest.mark.parametrize("failure", ["transport", "canceled"])
def test_stream_closes_before_propagating_failure(monkeypatch, failure):
    """收流异常或解析前取消时都关闭流，取消后不进入 JSON 解析。"""
    closed = []
    consumed = []

    def stream(*args, **kwargs):
        try:
            yield json.dumps({"questions": [_question("完整题目")]}, ensure_ascii=False)
            consumed.append(True)
            if failure == "transport":
                raise RuntimeError("synthetic stream failure")
        finally:
            closed.append(True)

    def check_canceled():
        if consumed and failure == "canceled":
            raise GenerationCanceled("synthetic cancellation")

    parser = Mock(side_effect=AssertionError("failed stream must not be parsed"))
    monkeypatch.setattr(question_gen.llm, "chat_stream", stream)
    monkeypatch.setattr(question_gen, "_RollingParser", parser)
    error = RuntimeError if failure == "transport" else GenerationCanceled
    with pytest.raises(error):
        _stream_questions([], budget=100, api_key=None, cancel_check=check_canceled)
    assert closed == [True]
    parser.assert_not_called()


@pytest.mark.parametrize("qtype", [QuestionType.single, QuestionType.judge])
def test_gen_batch_discards_fast_model_solution_and_options(monkeypatch, qtype):
    """模型违背命题协议返回完整解答时，命题边界也必须丢弃该解答。"""
    payload = {
        "type": qtype.value, "stem": "函数的导数在原点是否等于零？",
        "answer": "B", "analysis": "快速模型给出的未经独立验证的解析。",
        "options": [{"label": "A", "text": "错误的判断选项一"},
                    {"label": "B", "text": "错误的判断选项二"}],
    }
    monkeypatch.setattr(question_gen.llm, "chat_stream", lambda *a, **k: iter([
        json.dumps({"questions": [payload]}, ensure_ascii=False),
    ]))
    tc = TypeCount(type=qtype, count=1)
    params = GenerateParams(kb_id="fake-bank", doc_id="fake-doc", types=[tc])
    question, = question_gen._gen_batch(
        tc, params, "fake.pdf", None, 1, [], False, None, [{"text": "fixture context"}], "",
    )
    assert question.answer == question.analysis == ""
    assert [item.model_dump() for item in question.options] == ([
        {"label": "A", "text": "正确"}, {"label": "B", "text": "错误"},
    ] if qtype == QuestionType.judge else [])


def test_generation_refills_through_fifth_round_and_reports_zero_to_hundred(monkeypatch):
    attempts = []
    progress = []
    params = GenerateParams(
        kb_id="fake-bank", doc_id="fake-document",
        types=[TypeCount(type=QuestionType.blank, count=1)],
    )

    def generate(*args, **kwargs):
        attempts.append(1)
        if len(attempts) < 5:
            raise ValueError("fixture batch failed")
        return [Question(type=QuestionType.blank, stem="第五轮完成的题目")]

    monkeypatch.setattr(question_gen, "_gen_batch", generate)
    result = question_gen.generate_questions(
        params, "fake.pdf", retrieve_fn=lambda query: [{"text": "fixture context"}],
        progress_cb=lambda percent, stage: progress.append(percent),
    )
    assert len(result) == 1 and len(attempts) == 5
    assert progress[0] == 0 and progress[-1] == 100
    assert progress == sorted(progress)


def test_high_pressure_planning_budget_and_scoped_fallback(monkeypatch):
    requests = []

    def plan(messages, **kwargs):
        requests.append(kwargs)
        return {"points": ["分部积分", "分部积分"]}

    monkeypatch.setattr(question_gen.llm, "chat_json", plan)
    points = question_gen._plan_points("定积分", "填空题", "高", 25, [], None)
    assert requests[0]["max_tokens"] == question_gen.HIGH_PRESSURE_PLAN_TOKENS
    assert len(points) == 25 and len(set(points)) == 25
    assert all("定积分" in point for point in points[1:])


@pytest.mark.parametrize("repaired", [42, {"unexpected": "dictionary"}, None])
def test_stream_handles_non_list_repair_result(
    monkeypatch: pytest.MonkeyPatch, repaired: object,
) -> None:
    """数组内残损内容被修成标量或字典时，收尾不能直接切片该结果。"""
    output = '{"questions": [broken }'
    repair = Mock(return_value=repaired)
    monkeypatch.setattr(question_gen.json_repair, "loads", repair)
    monkeypatch.setattr(question_gen.llm, "chat_stream", Mock(return_value=iter([output])))

    with pytest.raises(QuestionOutputError, match="未解析出任何题目对象"):
        _stream_questions([], budget=100, api_key=None)

    repair.assert_called_once()


@pytest.mark.parametrize("missing_field", ["stem"])
def test_stream_missing_required_field_reports_question_output_error(
    monkeypatch: pytest.MonkeyPatch, missing_field: str,
) -> None:
    """完整对象缺必填字段时立即阻断，报告字段名并保留原输出以供重试。

    answer/analysis 已改为可选（出题模型只命制题干，答案与解析由解题模型填充），
    缺失它们不再触发 QuestionOutputError。
    """
    question = _question("缺字段的题目")
    del question[missing_field]
    output = json.dumps({"questions": [question]}, ensure_ascii=False)
    stream = Mock(return_value=iter([output]))
    monkeypatch.setattr(question_gen.llm, "chat_stream", stream)

    with pytest.raises(QuestionOutputError) as caught:
        _stream_questions([], budget=100, api_key=None)

    assert missing_field in caught.value.summary
    assert caught.value.raw_excerpt == output
