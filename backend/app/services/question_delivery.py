"""Shared delivery quotas, refill rounds and teacher-facing review summaries."""
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Protocol

from app.schemas.api import GenerationReviewGroup
from app.schemas.question import Difficulty, GenerateParams, Question, QuestionType, TypeCount
from app.services.generation_cancellation import check_cancellation
from app.services.question_review import ReviewStats, _norm
from app.services.rag import llm
from app.services.rag.question_gen import (
    NO_USABLE_CANDIDATES,
    NeedConfirmError,
    QuestionOutputError,
)

MAX_REFILL_ROUNDS = 3
Progress = Callable[[int, str], None]
GroupKey = tuple[QuestionType, Difficulty]


class Reviewer(Protocol):
    """Review a candidate pool against the remaining quotas."""

    def __call__(
        self, pool: list[Question], params: GenerateParams, stems: list[str], /
    ) -> tuple[list[Question], ReviewStats]: ...


def review_with_refill(
    first_pool: list[Question],
    params: GenerateParams,
    requested: int,
    existing_stems: list[str] | None,
    review_fn: Reviewer,
    gen_fn: Callable[[GenerateParams, list[str], Progress], list[Question]],
    progress_cb: Progress | None = None,
    cancel_check: Callable[[], None] | None = None,
    *,
    initial_events: Mapping[GroupKey, Counter[str]] | None = None,
) -> tuple[list[Question], ReviewStats, list[GenerationReviewGroup]]:
    """Review the initial pool and at most three rounds of replacement candidates."""
    quota: Counter[GroupKey] = Counter()
    for item in params.types:
        quota[item.type, item.difficulty or params.difficulty] += item.count
    delivered: Counter[GroupKey] = Counter()
    events = {key: Counter((initial_events or {}).get(key, {})) for key in quota}
    accepted: list[Question] = []
    avoid = list(dict.fromkeys((existing_stems or []) + params.existing_stems))
    seen = {_norm(stem) for stem in avoid}
    stats = ReviewStats()
    pool = first_pool
    initial_counts = Counter((question.type, question.difficulty) for question in first_pool)
    for key, count in quota.items():
        if initial_counts[key] < count:
            events[key]["首轮候选产出不足"] += 1

    def report(percent: int, stage: str) -> None:
        check_cancellation(cancel_check)
        if progress_cb:
            progress_cb(percent, stage)
        check_cancellation(cancel_check)

    def remember(questions: list[Question]) -> None:
        for question in questions:
            stem = _norm(question.stem)
            if stem not in seen:
                seen.add(stem)
                avoid.append(question.stem)

    def round_params(types: list[TypeCount]) -> GenerateParams:
        return params.model_copy(update={"types": types, "existing_stems": list(avoid)})

    def remaining() -> dict[GroupKey, int]:
        return {key: count - delivered[key] for key, count in quota.items()
                if count > delivered[key]}

    def type_counts(key: GroupKey, count: int) -> list[TypeCount]:
        kind, difficulty = key
        return [
            TypeCount(type=kind, difficulty=difficulty, count=min(100, count - offset))
            for offset in range(0, count, 100)
        ]

    for round_no in range(MAX_REFILL_ROUNDS + 1):
        percent = 78 + round_no * 5
        report(percent, "正在审核题目" if not round_no else f"正在审核第 {round_no} 轮补题")
        deficits = remaining()
        types = [item for key, count in deficits.items() for item in type_counts(key, count)]
        if pool:
            passed, current = review_fn(pool, round_params(types), list(avoid))
            check_cancellation(cancel_check)
            stats.duplicates += current.duplicates
            stats.repaired += current.repaired
            stats.regenerated += current.regenerated
            stats.solved += current.solved
            for key, reasons in current.rejections.items():
                stats.rejections.setdefault(key, Counter()).update(reasons)
            for question in passed:
                key = (question.type, question.difficulty)
                if delivered[key] >= quota[key] or len(accepted) >= requested:
                    continue
                if _norm(question.stem) in seen:
                    stats.duplicates += 1
                    stats.rejections.setdefault(key, Counter())["重复题目"] += 1
                    continue
                delivered[key] += 1
                accepted.append(question)
                remember([question])
        remember(pool)
        deficits = remaining()
        if not deficits or len(accepted) >= requested or round_no == MAX_REFILL_ROUNDS:
            break

        pool = []
        for key, count in deficits.items():
            round_number = round_no + 1

            def refill_progress(_percent: int, stage: str) -> None:
                report(percent + 2, f"第 {round_number} 轮补题 · {stage}")

            for item in type_counts(key, count):
                check_cancellation(cancel_check)
                try:
                    fresh = gen_fn(round_params([item]), list(avoid), refill_progress)
                except NeedConfirmError:
                    events[key]["可用原题不足"] += 1
                    continue
                except llm.LLMError as exc:
                    events[key][llm.friendly_error(exc)] += 1
                    continue
                except (ValueError, QuestionOutputError):
                    events[key][NO_USABLE_CANDIDATES] += 1
                    continue
                check_cancellation(cancel_check)
                if len(fresh) < item.count:
                    events[key]["生成未返回候选题"] += 1
                pool.extend(fresh)
                stats.regenerated += len(fresh)

    report(98, "题目审核结束")
    groups = [
        GenerationReviewGroup(
            type=kind, difficulty=difficulty, requested=count,
            delivered=delivered[kind, difficulty], missing=count - delivered[kind, difficulty],
            rejections=dict(stats.rejections.get((kind, difficulty), {})),
            generation_events=dict(events[kind, difficulty]),
        )
        for (kind, difficulty), count in quota.items()
    ]
    return accepted, stats, groups
