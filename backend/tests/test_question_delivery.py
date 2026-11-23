"""Regression coverage for shared question delivery quotas and refill results."""

from collections import Counter

from app.schemas.api import GenerationReviewGroup
from app.schemas.question import Difficulty, GenerateParams, Question, QuestionType, TypeCount
from app.services.question_delivery import review_with_refill
from app.services.question_review import ReviewStats
from app.services.rag.question_gen import NeedConfirmError


def _candidate(stem: str, kind: QuestionType, difficulty: Difficulty) -> Question:
    return Question(type=kind, difficulty=difficulty, stem=stem, answer="A", analysis="合成解析")


def test_three_refill_rounds_report_zero_delivery_and_all_candidate_rejections():
    kind, difficulty = QuestionType.single, Difficulty.hell
    params = GenerateParams(
        kb_id="fake-bank", doc_id="fake-doc", difficulty=difficulty,
        types=[TypeCount(type=kind, count=2)],
    )
    refill_requests = []

    def generate(refill_params, stems, progress):
        group, = refill_params.types
        refill_requests.append((group.type, group.difficulty, group.count))
        return [_candidate(f"补题 {len(refill_requests)}", kind, difficulty)]

    def reject(pool, review_params, stems):
        return [], ReviewStats(rejections={
            (kind, difficulty): Counter({"题设不足": len(pool)}),
        })

    accepted, _, groups = review_with_refill(
        [_candidate("首轮候选题", kind, difficulty)], params, 2, [], reject, generate,
    )

    assert accepted == []
    assert refill_requests == [(kind, difficulty, 2)] * 3
    assert groups == [GenerationReviewGroup(
        type=kind, difficulty=difficulty, requested=2, delivered=0, missing=2,
        rejections={"题设不足": 4},
        generation_events={"首轮候选产出不足": 1, "生成未返回候选题": 3},
    )]


def test_same_type_difficulty_tiers_have_independent_quotas():
    kind = QuestionType.single
    params = GenerateParams(
        kb_id="fake-bank", doc_id="fake-doc", difficulty=Difficulty.high,
        types=[
            TypeCount(type=kind, count=1, difficulty=Difficulty.low),
            TypeCount(type=kind, count=1),
        ],
    )
    low = _candidate("低档题", kind, Difficulty.low)
    surplus_low = _candidate("多余低档题", kind, Difficulty.low)
    high = _candidate("高档补题", kind, Difficulty.high)
    refill_requests = []

    def generate(refill_params, stems, progress):
        group, = refill_params.types
        refill_requests.append((group.type, group.difficulty, group.count))
        return [high]

    accepted, _, groups = review_with_refill(
        [low, surplus_low], params, 2, [], _accept, generate,
    )

    assert accepted == [low, high]
    assert refill_requests == [(kind, Difficulty.high, 1)]
    assert {(group.difficulty, group.requested, group.delivered, group.missing)
            for group in groups} == {(Difficulty.low, 1, 1, 0), (Difficulty.high, 1, 1, 0)}


def test_original_shortage_during_refill_preserves_other_group_delivery():
    difficulty = Difficulty.mid
    params = GenerateParams(
        kb_id="fake-bank", doc_id="fake-doc", difficulty=difficulty, source_mode="original",
        types=[
            TypeCount(type=QuestionType.single, count=2),
            TypeCount(type=QuestionType.blank, count=1),
        ],
    )
    initial = _candidate("首轮单选题", QuestionType.single, difficulty)
    blank = _candidate("材料填空题", QuestionType.blank, difficulty)
    refill_requests = []

    def generate(refill_params, stems, progress):
        group, = refill_params.types
        refill_requests.append(group.type)
        if group.type == QuestionType.single:
            raise NeedConfirmError("单选题", 0, group.count)
        return [blank]

    accepted, _, groups = review_with_refill([initial], params, 3, [], _accept, generate)

    assert accepted == [initial, blank]
    assert refill_requests == [
        QuestionType.single, QuestionType.blank, QuestionType.single, QuestionType.single,
    ]
    assert {group.type: group for group in groups} == {
        QuestionType.single: GenerationReviewGroup(
            type=QuestionType.single, difficulty=difficulty, requested=2, delivered=1, missing=1,
            rejections={}, generation_events={"首轮候选产出不足": 1, "可用原题不足": 3},
        ),
        QuestionType.blank: GenerationReviewGroup(
            type=QuestionType.blank, difficulty=difficulty, requested=1, delivered=1, missing=0,
            rejections={}, generation_events={"首轮候选产出不足": 1},
        ),
    }


def _accept(
    pool: list[Question], params: GenerateParams, stems: list[str],
) -> tuple[list[Question], ReviewStats]:
    return pool, ReviewStats()


def test_empty_first_round_enters_refill_and_retains_initial_events():
    single = (QuestionType.single, Difficulty.low)
    blank = (QuestionType.blank, Difficulty.mid)
    failure = "生成未返回可用候选题"
    initial_events = {single: Counter({failure: 1}), blank: Counter({failure: 1})}
    params = GenerateParams(
        kb_id="fake-bank", doc_id="fake-doc",
        types=[TypeCount(type=kind, difficulty=tier, count=1) for kind, tier in initial_events],
    )
    candidate = _candidate("补回的单选题", *single)
    refill_requests = []

    def generate(refill_params, stems, progress):
        group, = refill_params.types
        key = (group.type, group.difficulty)
        refill_requests.append(key)
        if key == single:
            return [candidate]
        raise ValueError("synthetic refill output failure")

    accepted, _, groups = review_with_refill(
        [], params, 2, [], _accept, generate, initial_events=initial_events,
    )

    assert accepted == [candidate]
    assert refill_requests == [single, blank, blank, blank]
    assert [(group.delivered, group.missing, group.generation_events) for group in groups] == [
        (1, 0, {"首轮候选产出不足": 1, failure: 1}),
        (0, 1, {"首轮候选产出不足": 1, failure: 4}),
    ]
    assert initial_events == {single: Counter({failure: 1}), blank: Counter({failure: 1})}
