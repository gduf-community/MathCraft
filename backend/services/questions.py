"""Minimal single-tenant question snapshots, with immutable source provenance."""

from __future__ import annotations

from pathlib import Path
import re
import threading

from MathCraft.runtime.home import get_runtime_data_root
from MathCraft.services.file_io import atomic_write_json
from MathCraft.services.rag.evidence import KnowledgeError, source_status
from schemas.question import Question, QuestionUpdate
from services.knowledge import resolve_for_rag

_LOCK = threading.RLock()
_MATH_FIELDS = {"type", "stem", "options", "answer", "analysis", "knowledgePoint"}


class QuestionStore:
    def __init__(self, root: Path | None = None):
        self.root = root or get_runtime_data_root() / "questions"

    def _path(self, question_id: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", question_id):
            raise KnowledgeError("invalid_question_id", "题目编号非法。")
        return self.root / f"{question_id}.json"

    @staticmethod
    def _refresh(question: Question) -> Question:
        for source in question.sources:
            try:
                resource = resolve_for_rag(source.kb_id)
                state = source_status(resource.base_dir / resource.name, source.model_dump())
            except Exception:
                state = "missing"
            source.source_status = state
        return question

    def save_generated(self, questions: list[Question]) -> None:
        with _LOCK:
            for question in questions:
                refreshed = self._refresh(question.model_copy(deep=True))
                if any(s.source_status != "valid" for s in refreshed.sources):
                    raise KnowledgeError(
                        "source_changed", "生成期间来源已失效，题目未保存，请重新检查资料。"
                    )
            for question in questions:
                atomic_write_json(self._path(question.id), question.model_dump(mode="json"))

    def read(self, question_id: str) -> Question:
        with _LOCK:
            path = self._path(question_id)
            if not path.exists():
                raise FileNotFoundError(question_id)
            return self._refresh(Question.model_validate_json(path.read_text(encoding="utf-8")))

    def list(self) -> list[Question]:
        return [self.read(p.stem) for p in sorted(self.root.glob("*.json"))]

    def edit(self, question_id: str, update: QuestionUpdate) -> Question:
        with _LOCK:
            question = self.read(question_id)
            patch = update.model_dump(exclude_unset=True, mode="json")
            if any(v is None for v in patch.values()):
                raise KnowledgeError("invalid_question_edit", "题目字段不能设为空值。")
            changed = any(
                k in _MATH_FIELDS and question.model_dump(mode="json")[k] != v
                for k, v in patch.items()
            )
            question = Question.model_validate({**question.model_dump(), **patch})
            if changed:
                question.review_status = "edited_requires_review"
                for source in question.sources:
                    if source.relation == "original":
                        source.relation = "variant_reference"
            atomic_write_json(self._path(question_id), question.model_dump(mode="json"))
            return question
