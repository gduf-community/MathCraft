"""Regression coverage for scoped, request-local question deduplication."""

import json

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db import Base
from app.models.favorite import Favorite
from app.models.paper import Paper, PaperQuestion
from app.models.question import Question as QuestionRow
from app.schemas.question import ExistingQuestion, OptionItem, Question, QuestionType
from app.services.generation_cancellation import GenerationCanceled
from app.services.question_dedup import QuestionDeduper, normalize_stem, question_key


def _question(stem: str, kind: QuestionType = QuestionType.compute) -> Question:
    return Question(type=kind, stem=stem)


def _choice(stem: str, option: str) -> ExistingQuestion:
    return ExistingQuestion(
        type=QuestionType.single,
        stem=stem,
        options=[OptionItem(label="A", text=option), OptionItem(label="B", text="$0$")],
    )


def test_exact_identity_and_legacy_exclusion() -> None:
    present = _choice("请选择 $f(x)$？", "$1.2$")
    deduper = QuestionDeduper(
        None, "owner", "bank", ["旧题明确排除。"], [present],
    )
    assert deduper.check_exact(_choice("请选择 $f(x)$?", "$1.2$")).reason == "exact_duplicate"
    assert not deduper.check_exact(_choice("请选择 $f(x)$", "$12$")).duplicate
    assert not deduper.check_exact(_question(present.stem)).duplicate
    assert question_key(present.model_copy(update={"options": []})) is None
    legacy = _question("旧题明确排除?", QuestionType.single)
    assert deduper.check_exact(legacy).reason == "legacy_stem"
    assert normalize_stem(r"$f(x) = 1?$") == r"$f(x) = 1?$"
    assert normalize_stem(r"\(f(x)?") == r"\(f(x)?"
    assert normalize_stem(r"求 \(f(x)?\)？") == r"求 \(f(x)?\)"
    assert question_key(_question("计算 $f(x, y)$。")) != question_key(
        _question("计算 $f(xy)$。"),
    )


def test_sql_corpus_is_scoped_loaded_once_and_releases_transaction() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        for question_id, owner, bank, kind in (
            ("history", "owner", "bank", "compute"),
            ("other_bank", "owner", "outside", "compute"),
            ("other_owner", "other", "bank", "compute"),
            ("own_favorite", "other", "outside", "compute"),
            ("other_favorite", "other", "outside", "compute"),
            ("missing_options", "owner", "bank", "single"),
        ):
            db.add(QuestionRow(
                id=question_id, batch_id="batch", document_id="document", bank_id=bank,
                type=kind, difficulty="中", stem=question_id, answer="", analysis="",
                created_by=owner,
            ))
        db.add_all([
            Favorite(id="favorite_1", user_id="owner", question_id="own_favorite", group_id="group"),
            Favorite(id="favorite_2", user_id="other", question_id="other_favorite",
                     group_id="group"),
            Paper(id="own_paper", name="Own paper", owner_id="owner"),
            Paper(id="other_paper", name="Other paper", owner_id="other"),
            Paper(id="deleted_paper", name="Deleted paper", owner_id="owner", deleted=True),
        ])
        for paper, stem, removed, order_no in (
            ("own_paper", "own_snapshot", False, 1),
            ("own_paper", "removed_snapshot", True, 2),
            ("other_paper", "other_snapshot", False, 1),
            ("deleted_paper", "deleted_snapshot", False, 1),
        ):
            db.add(PaperQuestion(
                id=stem, paper_id=paper, type="compute", module_type="compute", order_no=order_no,
                difficulty="中", score=5, stem=stem, answer="", analysis="", removed=removed,
            ))
        db.commit()
        selects = []

        @event.listens_for(engine, "before_cursor_execute")
        def detect_query(_conn, _cursor, statement, _parameters, _context, _executemany):
            selects.append(statement)

        def embed(texts: list[str]) -> list[list[float]]:
            assert not db.in_transaction()
            return [[1.0] for _ in texts]

        def distinct(_messages: list[dict[str, str]]) -> object:
            assert not db.in_transaction()
            return {"verdict": "distinct"}

        deduper = QuestionDeduper(
            db, "owner", "bank", existing_stems=["blocked"], embedding=embed, llm_verdict=distinct,
        )
        assert deduper.check_exact(_question("blocked")).duplicate
        assert not selects
        for stem in ("history", "own_favorite", "own_snapshot"):
            assert deduper.check_exact(_question(stem)).matched_source == "corpus"
        for stem in (
            "other_bank", "other_owner", "other_favorite", "other_snapshot", "removed_snapshot",
            "deleted_snapshot",
        ):
            assert not deduper.check_exact(_question(stem)).duplicate
        assert not deduper.check_exact(_question("missing_options", QuestionType.single)).duplicate
        assert not deduper.check_exact(_choice("missing_options", "$1$")).duplicate
        assert deduper.check(_question("another question")).code == "unique"
        assert not db.in_transaction()
        assert len(selects) == 1
    engine.dispose()


def test_recall_reserves_top_five_for_same_type_and_reuses_vectors() -> None:
    same_stem = "Which value is correct?"
    prior = [_choice(f"Another prompt {index}", str(index)) for index in range(7)]
    typed_refs = [*prior, _question("Different type"), _choice(same_stem, "$-1$")]
    embedding_calls = []
    verdict_calls = []

    def embed(texts: list[str]) -> list[list[float]]:
        stems = [json.loads(text)["stem"] for text in texts]
        embedding_calls.append(stems)
        return [[0.0, 1.0] if stem == prior[-1].stem else [1.0, 0.0] for stem in stems]

    def verdict(messages: list[dict[str, str]]) -> object:
        verdict_calls.append(json.loads(messages[-1]["content"])["candidates"])
        return {"verdict": "duplicate", "duplicate_index": 0}

    deduper = QuestionDeduper(
        None, "owner", "bank", existing_questions=typed_refs, embedding=embed, llm_verdict=verdict,
    )
    result = deduper.check(_choice(same_stem, "$1$"))
    assert result.reason == "semantic_duplicate"
    assert result.recalled_count == 5
    compared = verdict_calls[0]
    assert compared[0]["stem"] == same_stem
    assert all(candidate["type"] == "single" for candidate in compared)
    assert prior[-1].stem not in {candidate["stem"] for candidate in compared}
    assert "Different type" not in embedding_calls[0]
    next_question = _choice("A new selected question", "$3$")
    deduper.check(next_question)
    assert embedding_calls[1] == [same_stem, next_question.stem]
    deduper.remember(next_question)
    assert deduper.check(next_question).matched_source == "selected"
    assert len(embedding_calls) == 2


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ({"verdict": "distinct"}, "unique"),
        ({"verdict": "uncertain"}, "verdict_uncertain"),
        ({"verdict": "duplicate", "duplicate_index": True}, "verdict_unavailable"),
        ({"verdict": "duplicate", "duplicate_index": 5}, "verdict_unavailable"),
        ({}, "verdict_unavailable"),
    ],
)
def test_structured_verdict_fails_open(response: object, expected: str) -> None:
    deduper = QuestionDeduper(
        None, "owner", "bank", existing_questions=[_question("Stored")],
        embedding=lambda texts: [[1.0] for _ in texts],
        llm_verdict=lambda _messages: response,
    )
    result = deduper.check(_question("Candidate"))
    assert result.code == expected
    assert not result.duplicate and result.reason is None


def test_unavailable_embeddings_fail_open_and_verdict_cancellation_propagates() -> None:
    def fail(_texts: list[str]) -> list[list[float]]:
        raise ConnectionError

    canceled = False

    def cancel_check() -> None:
        if canceled:
            raise GenerationCanceled

    def canceled_verdict(_messages: list[dict[str, str]]) -> object:
        nonlocal canceled
        canceled = True
        raise ConnectionError

    deduper = QuestionDeduper(
        None, "owner", "bank", existing_questions=[_question("Stored")], embedding=fail,
        llm_verdict=canceled_verdict, cancel_check=cancel_check,
    )
    assert deduper.check(_question("Candidate")).code == "embedding_unavailable"
    same_stem = "Same stem with different options"
    deduper.remember(_choice(same_stem, "$1$"))
    with pytest.raises(GenerationCanceled):
        deduper.check(_choice(same_stem, "$2$"))
