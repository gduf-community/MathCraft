"""Saved questions; provenance is written only by the generation workflow."""

from fastapi import APIRouter, HTTPException

from MathCraft.services.rag.evidence import KnowledgeError
from schemas.question import Question, QuestionUpdate
from services.questions import QuestionStore

router = APIRouter(prefix="/api/questions", tags=["questions"])


@router.get("", response_model=list[Question])
async def list_questions():
    return QuestionStore().list()


@router.get("/{question_id}", response_model=Question)
async def read_question(question_id: str):
    try:
        return QuestionStore().read(question_id)
    except FileNotFoundError as exc:
        raise HTTPException(404, "题目不存在") from exc
    except KnowledgeError as exc:
        raise HTTPException(422, exc.detail()) from exc


@router.put("/{question_id}", response_model=Question)
async def edit_question(question_id: str, body: QuestionUpdate):
    try:
        return QuestionStore().edit(question_id, body)
    except FileNotFoundError as exc:
        raise HTTPException(404, "题目不存在") from exc
    except KnowledgeError as exc:
        raise HTTPException(422, exc.detail()) from exc
