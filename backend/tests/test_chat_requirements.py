"""快速出题需求回归：严格数量、逐轮补齐及参数构造的完整性检查。"""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from app.schemas.question import Difficulty, Question, QuestionType, TypeCount
from app.services.rag import chat_flow, slots


@pytest.fixture
def complete_state():
    return {"types": [{"type": "single", "count": 3}], "scope": "导数",
            "source_mode": "new", "difficulty": "中"}


@pytest.fixture
def mocked_services(monkeypatch):
    extract = Mock(return_value={})
    generate = Mock(return_value=[Question(
        type=QuestionType.compute, score=5, difficulty=Difficulty.mid,
        stem="求函数 $f(x)=x^2$ 的导数", answer="2x", analysis="幂函数求导",
    )])
    monkeypatch.setattr(chat_flow, "extract_slots", extract)
    monkeypatch.setattr(chat_flow, "generate_questions", generate)
    return extract, generate


def _chat(state):
    return chat_flow.handle_chat("bank-test", "doc-test", "导数教材", "继续", [], state)


def _assert_followup(result, generate):
    assert result["done"] is False
    assert result["questions"] == []
    assert result["reply"]
    generate.assert_not_called()


@pytest.mark.parametrize("question_type", list(QuestionType))
def test_each_type_requires_explicit_count(question_type, complete_state, mocked_services):
    extract, generate = mocked_services
    extract.return_value = {**complete_state,
                            "types": [{"type": question_type.value, "count": None}]}
    result = _chat({})
    _assert_followup(result, generate)
    assert "count" in slots.missing_keys(result["slot_state"])


def test_counts_complete_across_turns_preserving_confirmed_values(complete_state, mocked_services):
    extract, generate = mocked_services
    extract.side_effect = [
        {**complete_state, "types": [{"type": "single", "count": 3},
                                     {"type": "judge", "count": None}]},
        {}, {},
        {"types": [{"type": "single", "count": None}, {"type": "judge", "count": 2}]},
    ]
    state = {}
    for _ in range(3):
        result = _chat(state)
        _assert_followup(result, generate)
        assert "判断" in result["reply"]
        assert "选择" not in result["reply"]
        state = result["slot_state"]
    result = _chat(state)
    assert result["done"] is True
    generate.assert_called_once()
    assert {item.type.value: item.count for item in generate.call_args.args[0].types} == {
        "single": 3, "judge": 2,
    }


INVALID_COUNTS = [0, -1, True, False, 1.5, float("nan"), float("inf"), -float("inf"), 21]


@pytest.mark.parametrize("count", INVALID_COUNTS)
def test_invalid_extracted_count_never_generates(count, complete_state, mocked_services):
    extract, generate = mocked_services
    extract.return_value = {**complete_state, "types": [{"type": "single", "count": count}]}
    _assert_followup(_chat({}), generate)


@pytest.mark.parametrize("count", INVALID_COUNTS)
def test_invalid_total_count_never_generates(count, complete_state, mocked_services):
    extract, generate = mocked_services
    extract.return_value = {**complete_state, "types": [{"type": "single", "count": None}],
                            "count": count}
    _assert_followup(_chat({}), generate)


@pytest.mark.parametrize("count", INVALID_COUNTS)
def test_build_params_rejects_invalid_persisted_count(count, complete_state):
    complete_state["types"][0]["count"] = count
    with pytest.raises(ValueError):
        slots.build_params(complete_state, "bank-test", "doc-test")


@pytest.mark.parametrize("field", ["types", "scope", "difficulty"])
def test_build_params_rejects_missing_requirement(field, complete_state):
    complete_state.pop(field)
    with pytest.raises(ValueError):
        slots.build_params(complete_state, "bank-test", "doc-test")


@pytest.mark.parametrize("field,value", [("scope", "  "), ("difficulty", "无效"),
                                        ("types", [{"type": "unknown", "count": 1}])])
def test_persisted_invalid_requirements_do_not_generate(field, value, complete_state,
                                                       mocked_services):
    _, generate = mocked_services
    complete_state[field] = value
    _assert_followup(_chat(complete_state), generate)


def test_build_params_rejects_one_missing_count(complete_state):
    complete_state["types"].append({"type": "judge", "count": None})
    with pytest.raises(ValueError):
        slots.build_params(complete_state, "bank-test", "doc-test")


@pytest.mark.parametrize("count", [1, 20, 1.0, 20.0])
def test_valid_boundaries_reach_generator(count, complete_state, mocked_services):
    extract, generate = mocked_services
    extract.return_value = {**complete_state, "types": [{"type": "single", "count": count}]}
    assert _chat({})["done"] is True
    assert generate.call_args.args[0].types == [TypeCount(type=QuestionType.single, count=count)]


def test_null_extraction_preserves_count_without_mutating_input(complete_state, mocked_services):
    extract, generate = mocked_services
    complete_state.pop("difficulty")
    before = deepcopy(complete_state)
    extract.return_value = {"types": [{"type": "single", "count": None}]}
    result = _chat(complete_state)
    _assert_followup(result, generate)
    assert result["slot_state"]["types"][0]["count"] == 3
    assert complete_state == before


def test_total_count_applies_only_to_single_type(complete_state):
    state = slots.merge_slots({}, {"count": 4})
    assert slots.missing_keys(state) == ["types", "difficulty", "scope"]
    merged = slots.merge_slots(state, {**complete_state,
                                     "types": [{"type": "single", "count": None}]})
    assert merged["types"][0]["count"] == 4
    assert slots.missing_keys(merged) == []
    assert state == {"total_count": 4}
    multiple = slots.merge_slots({}, {**complete_state, "count": 4,
                                      "types": [{"type": "single", "count": None},
                                                {"type": "judge", "count": None}]})
    assert slots.missing_keys(multiple) == ["count"]


def test_source_mode_defaults_without_becoming_required(complete_state, mocked_services):
    extract, generate = mocked_services
    complete_state.pop("source_mode")
    extract.return_value = complete_state
    assert _chat({})["done"] is True
    assert generate.call_args.args[0].source_mode == "variant_data"


def test_followup_remains_callable_without_state():
    assert "多少" in slots.build_followup(["count"])
