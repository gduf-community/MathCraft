"""对话需求补齐回归：信息齐备前禁止生成，跨轮保留明确要求。"""
import sys
from copy import deepcopy
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from schemas.question import Question, QuestionType, TypeCount
from services import chat_flow
from services.slots import build_followup, build_params, missing_keys


@pytest.fixture
def complete_state():
    return {
        "types": [{"type": "single", "count": 3}],
        "scope": "一元二次方程",
        "source_mode": "new",
        "difficulty": "中",
    }


@pytest.fixture
def mocked_services(monkeypatch):
    extract = AsyncMock(return_value={})
    generate = AsyncMock(return_value=[
        Question(type=QuestionType.single, stem="求方程 $x^2=1$ 的解", answer="±1", analysis="开平方")
    ])
    monkeypatch.setattr(chat_flow, "extract_slots", extract)
    monkeypatch.setattr(chat_flow, "generate_questions", generate)
    return extract, generate


async def chat(state, message="继续", history=None):
    return await chat_flow.handle_chat(
        kb_id="test-kb", doc_id="test-doc", doc_name="测试教材",
        message=message, history=history or [], slot_state=state,
        existing_stems=["已有题干"],
    )


def assert_followup(result, generate):
    assert result["done"] is False
    assert result["questions"] == []
    assert result["reply"]
    generate.assert_not_awaited()


@pytest.mark.parametrize("question_type", list(QuestionType))
@pytest.mark.asyncio
async def test_each_type_requires_an_explicit_count(question_type, complete_state, mocked_services):
    extract, generate = mocked_services
    extract.return_value = {**complete_state, "types": [{"type": question_type.value, "count": None}]}

    result = await chat({})

    assert_followup(result, generate)
    assert result["slot_state"]["types"] == [{"type": question_type.value, "count": None}]
    assert "counts" in missing_keys(result["slot_state"])
    assert "多少" in result["reply"] or "数量" in result["reply"]


@pytest.mark.asyncio
async def test_partial_counts_only_ask_for_unfilled_types(complete_state, mocked_services):
    extract, generate = mocked_services
    extract.return_value = {
        **complete_state,
        "types": [
            {"type": "single", "count": 3},
            {"type": "judge", "count": None},
            {"type": "blank", "count": None},
        ],
    }

    result = await chat({})

    assert_followup(result, generate)
    assert "判断" in result["reply"]
    assert "填空" in result["reply"]
    assert "选择" not in result["reply"]
    assert missing_keys(result["slot_state"]) == ["counts"]


@pytest.mark.asyncio
async def test_counts_are_completed_across_turns_before_generation(complete_state, mocked_services):
    extract, generate = mocked_services
    extract.side_effect = [
        {**complete_state, "types": [{"type": "single", "count": None}, {"type": "judge", "count": None}]},
        {"types": [{"type": "single", "count": 3}, {"type": "judge", "count": None}]},
        {"types": [{"type": "single", "count": None}, {"type": "judge", "count": 2}],
         "scope": None, "difficulty": None, "source_mode": None},
    ]

    first = await chat({}, "选择题和判断题")
    assert_followup(first, generate)
    second = await chat(first["slot_state"], "选择题三道")
    assert_followup(second, generate)
    assert "判断" in second["reply"]
    assert "选择" not in second["reply"]
    third = await chat(second["slot_state"], "判断题两道")

    assert third["done"] is True
    assert third["questions"][0]["stem"] == generate.return_value[0].stem
    generate.assert_awaited_once()
    params = generate.await_args.args[0]
    assert {item.type.value: item.count for item in params.types} == {"single": 3, "judge": 2}
    assert params.kb_id == "test-kb"
    assert params.doc_id == "test-doc"
    assert params.difficulty.value == "中"
    assert params.source_mode == "new"
    assert generate.await_args.kwargs["scope"] == "一元二次方程"
    assert generate.await_args.kwargs["existing_stems"] == ["已有题干"]


@pytest.mark.asyncio
async def test_existing_multiturn_flow_still_completes(mocked_services):
    extract, generate = mocked_services
    extract.side_effect = [
        {"types": [{"type": "single", "count": 4}]},
        {"scope": "函数", "source_mode": "variant_data"},
        {"difficulty": "高"},
    ]
    state = {}
    history = []
    for message in ["四道选择题", "函数，改数据", "难一点"]:
        result = await chat(state, message, history)
        extract.assert_awaited_with(message, history)
        if message != "难一点":
            assert_followup(result, generate)
        state = result["slot_state"]
        history += [{"role": "user", "text": message}, {"role": "assistant", "text": result["reply"]}]

    assert result["done"] is True
    generate.assert_awaited_once()
    assert generate.await_args.args[0].types[0].count == 4


@pytest.mark.parametrize("field,value,label", [
    ("scope", None, "知识点"),
    ("scope", "   ", "知识点"),
    ("difficulty", None, "难度"),
    ("source_mode", None, "来源"),
])
@pytest.mark.asyncio
async def test_other_missing_requirements_continue_followup(field, value, label, complete_state, mocked_services):
    extract, generate = mocked_services
    extract.return_value = {**complete_state, field: value}

    result = await chat({})

    assert_followup(result, generate)
    assert label in result["reply"]
    assert "多少" not in result["reply"]


INVALID_COUNTS = [0, -1, True, False, 1.5, float("nan"), float("inf"), -float("inf"), 21]
INVALID_IDS = ["zero", "negative", "true", "false", "fraction", "nan", "infinity", "negative-infinity", "over-limit"]


@pytest.mark.parametrize("count", INVALID_COUNTS, ids=INVALID_IDS)
@pytest.mark.asyncio
async def test_invalid_extracted_count_never_generates(count, complete_state, mocked_services):
    extract, generate = mocked_services
    extract.return_value = {**complete_state, "types": [{"type": "single", "count": count}]}

    result = await chat({})

    assert_followup(result, generate)
    assert "counts" in missing_keys(result["slot_state"])


@pytest.mark.parametrize("count", INVALID_COUNTS, ids=INVALID_IDS)
def test_build_params_rejects_invalid_persisted_count(count, complete_state):
    complete_state["types"] = [{"type": "single", "count": count}]
    with pytest.raises(ValueError):
        build_params(complete_state, "test-kb", "test-doc")


@pytest.mark.parametrize("field", ["types", "scope", "source_mode", "difficulty"])
def test_build_params_rejects_missing_requirement(field, complete_state):
    complete_state.pop(field)
    with pytest.raises(ValueError):
        build_params(complete_state, "test-kb", "test-doc")


def test_build_params_rejects_one_missing_count_among_complete_types(complete_state):
    complete_state["types"].append({"type": "judge", "count": None})
    with pytest.raises(ValueError):
        build_params(complete_state, "test-kb", "test-doc")


@pytest.mark.parametrize("count", [1, 20, 1.0, 20.0])
@pytest.mark.asyncio
async def test_valid_typecount_boundaries_reach_generator(count, complete_state, mocked_services):
    extract, generate = mocked_services
    expected = TypeCount(type=QuestionType.single, count=count)
    extract.return_value = {**complete_state, "types": [expected.model_dump(mode="json")]}

    result = await chat({})

    assert result["done"] is True
    generate.assert_awaited_once()
    assert generate.await_args.args[0].types == [expected]


@pytest.mark.asyncio
async def test_null_extraction_preserves_confirmed_count_without_mutating_input(complete_state, mocked_services):
    extract, generate = mocked_services
    complete_state.pop("difficulty")
    before = deepcopy(complete_state)
    extract.return_value = {"types": [{"type": "single", "count": None}], "difficulty": None}

    result = await chat(complete_state)

    assert_followup(result, generate)
    assert result["slot_state"]["types"] == [{"type": "single", "count": 3}]
    assert "counts" not in missing_keys(result["slot_state"])
    assert complete_state == before


def test_followup_remains_callable_without_state():
    reply = build_followup(["counts"])
    assert "多少" in reply or "数量" in reply



@pytest.mark.asyncio
async def test_new_type_stays_pending_through_two_empty_turns(complete_state, mocked_services):
    extract, generate = mocked_services
    extract.side_effect = [
        {"types": [{"type": "judge", "count": None}]},
        {},
        {},
        {"types": [{"type": "judge", "count": 2}]},
    ]
    state = complete_state
    for message in ["再加判断题", "继续", "就这样"]:
        result = await chat(state, message)
        assert_followup(result, generate)
        assert "判断" in result["reply"]
        assert "选择" not in result["reply"]
        assert result["slot_state"]["types"] == [
            {"type": "single", "count": 3},
            {"type": "judge", "count": None},
        ]
        state = result["slot_state"]

    result = await chat(state, "判断题两道")

    assert result["done"] is True
    assert extract.await_count == 4
    generate.assert_awaited_once()
    assert {item.type.value: item.count for item in generate.await_args.args[0].types} == {
        "single": 3, "judge": 2,
    }
