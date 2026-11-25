"""Shared delivery quotas, refill rounds and teacher-facing review summaries."""
from collections import Counter
from collections.abc import Callable, Mapping
from typing import Protocol

from app.schemas.api import GenerationReviewGroup
from app.schemas.question import (
    Difficulty, ExistingQuestion, GenerateParams, Question, QuestionType, TypeCount,
)
from app.services import phoenix_tracing as trace
from app.services.generation_cancellation import check_cancellation
from app.services.question_dedup import QuestionDeduper
from app.services.question_review import ReviewStats
from app.services.rag import llm
from app.services.rag.question_gen import (
    NO_USABLE_CANDIDATES,
    REFILL_GUIDANCE,
    FailureCB,
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
    gen_fn: Callable[[GenerateParams, list[str], Progress, FailureCB], list[Question]],
    progress_cb: Progress | None = None,
    cancel_check: Callable[[], None] | None = None,
    *,
    initial_events: Mapping[GroupKey, Counter[str]] | None = None,
    deduper: QuestionDeduper | None = None,
) -> tuple[list[Question], ReviewStats, list[GenerationReviewGroup]]:
    """Review the initial pool and at most three rounds of replacement candidates."""
    quota: Counter[GroupKey] = Counter()
    for item in params.types:
        quota[item.type, item.difficulty or params.difficulty] += item.count
    delivered: Counter[GroupKey] = Counter()
    events = {key: Counter((initial_events or {}).get(key, {})) for key in quota}
    accepted: list[Question] = []
    exclusions = list(dict.fromkeys((existing_stems or []) + params.existing_stems))
    if deduper is None:
        deduper = QuestionDeduper(
            None, "", params.kb_id, exclusions, params.existing_questions, None, cancel_check,
        )
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

    def round_params(
        types: list[TypeCount], reasons: tuple[str, ...] = (),
    ) -> GenerateParams:
        return params.model_copy(update={
            "types": types, "existing_stems": exclusions, "refill_reasons": reasons,
            "existing_questions": params.existing_questions + [
                ExistingQuestion.model_construct(type=q.type, stem=q.stem, options=q.options)
                for q in accepted[-12:]
            ],
        })

    def remaining() -> dict[GroupKey, int]:
        return {key: count - delivered[key] for key, count in quota.items()
                if count > delivered[key]}

    def record_failure(kind: QuestionType, difficulty: Difficulty, reason: str) -> None:
        events[kind, difficulty][reason] += 1

    def type_counts(key: GroupKey, count: int) -> list[TypeCount]:
        kind, difficulty = key
        return [
            TypeCount(type=kind, difficulty=difficulty, count=min(100, count - offset))
            for offset in range(0, count, 100)
        ]

    def record_selection(
        question: Question, round_number: int, outcome: str, reason: str | None = None,
    ) -> None:
        with trace.question_round(round_number):
            trace.question_decision(
                "delivery", outcome, reason, candidate_id=question.id,
                kind=question.type.value, difficulty=question.difficulty.value,
            )

    for round_no in range(MAX_REFILL_ROUNDS + 1):
        percent = 78 + round_no * 5
        report(percent, "正在审核题目" if not round_no else f"正在审核第 {round_no} 轮补题")
        deficits = remaining()
        types = [item for key, count in deficits.items() for item in type_counts(key, count)]
        previous_rejections: dict[GroupKey, Counter[str]] = {}
        if pool:
            with trace.question_round(round_no):
                pending = []
                for question in pool:
                    exact = deduper.check_exact(question)
                    if not exact.duplicate:
                        pending.append(question)
                        continue
                    trace.question_decision(
                        "corpus_dedup", "rejected", exact.code, candidate_id=question.id,
                        kind=question.type.value, difficulty=question.difficulty.value, revision=0,
                    )
                    key = (question.type, question.difficulty)
                    stats.duplicates += 1
                    stats.rejections.setdefault(key, Counter())["重复题目"] += 1
                    previous_rejections.setdefault(key, Counter())["重复题目"] += 1
                passed, current = (
                    review_fn(pending, round_params(types), list(exclusions))
                    if pending else ([], ReviewStats())
                )
            check_cancellation(cancel_check)
            stats.duplicates += current.duplicates
            stats.repaired += current.repaired
            stats.regenerated += current.regenerated
            stats.solved += current.solved
            for key, reasons in current.rejections.items():
                stats.rejections.setdefault(key, Counter()).update(reasons)
                previous_rejections.setdefault(key, Counter()).update(reasons)
            for question in passed:
                key = (question.type, question.difficulty)
                if delivered[key] >= quota[key] or len(accepted) >= requested:
                    record_selection(question, round_no, "skipped", "quota_filled")
                    continue
                with trace.question_round(round_no), trace.question_stage(
                    "finished_dedup", candidate_id=question.id, kind=question.type.value,
                    difficulty=question.difficulty.value,
                ) as observation:
                    duplicate = deduper.check(question)
                    if duplicate.duplicate:
                        observation.decision("rejected", duplicate.code)
                    else:
                        observation.decision(
                            "passed", duplicate.code if duplicate.code != "unique" else None,
                        )
                if duplicate.duplicate:
                    record_selection(question, round_no, "rejected", "duplicate")
                    stats.duplicates += 1
                    stats.solved = max(0, stats.solved - 1)
                    stats.rejections.setdefault(key, Counter())["重复题目"] += 1
                    previous_rejections.setdefault(key, Counter())["重复题目"] += 1
                    continue
                record_selection(question, round_no, "selected")
                delivered[key] += 1
                accepted.append(question)
                deduper.remember(question)
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
                with trace.question_round(round_number), trace.question_stage(
                    "refill", kind=key[0].value, difficulty=key[1].value,
                ) as observation:
                    try:
                        ranked = sorted(
                            previous_rejections.get(key, {}).items(),
                            key=lambda entry: (-entry[1], entry[0]),
                        )
                        reasons = tuple(
                            name for name, _ in ranked if name in REFILL_GUIDANCE
                        )[:2]
                        fresh = gen_fn(
                            round_params([item], reasons), list(exclusions),
                            refill_progress, record_failure,
                        )
                    except NeedConfirmError:
                        reason = "可用原题不足"
                    except llm.LLMError as exc:
                        reason = llm.friendly_error(exc)
                    except (ValueError, QuestionOutputError):
                        reason = NO_USABLE_CANDIDATES
                    else:
                        check_cancellation(cancel_check)
                        if len(fresh) < item.count:
                            reason = "生成未返回候选题"
                            events[key][reason] += 1
                            observation.decision("failed", reason)
                        else:
                            observation.decision("passed")
                        pool.extend(fresh)
                        stats.regenerated += len(fresh)
                        continue
                    events[key][reason] += 1
                    observation.decision("failed", reason)

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
