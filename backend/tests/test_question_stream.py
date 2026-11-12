"""流式题目边界：及时交付、残损输出修复及可诊断的契约错误。"""

import json
from unittest.mock import Mock

import pytest

from app.services.rag import question_gen
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


@pytest.mark.parametrize("missing_field", ["stem", "answer", "analysis"])
def test_stream_missing_required_field_reports_question_output_error(
    monkeypatch: pytest.MonkeyPatch, missing_field: str,
) -> None:
    """完整对象缺必填字段时立即阻断，报告字段名并保留原输出以供重试。"""
    question = _question("缺字段的题目")
    del question[missing_field]
    output = json.dumps({"questions": [question]}, ensure_ascii=False)
    stream = Mock(return_value=iter([output]))
    monkeypatch.setattr(question_gen.llm, "chat_stream", stream)

    with pytest.raises(QuestionOutputError) as caught:
        _stream_questions([], budget=100, api_key=None)

    assert missing_field in caught.value.summary
    assert caught.value.raw_excerpt == output
