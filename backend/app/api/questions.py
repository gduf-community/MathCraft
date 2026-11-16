"""题目接口：列表（分页）、编辑、删除、批量删除（v2 5.7）。"""
import json

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import AppError
from app.models import Bank, Document, Favorite, Question, User
from app.schemas.api import BatchDeleteBody, QuestionUpdateBody
from app.services.generation import question_to_api
from app.services.rag_settings import assert_mutations_allowed

router = APIRouter(prefix="/api/questions", tags=["questions"])


def _get_owned_question(question_id: str, user: User, db: Session) -> Question:
    q = db.get(Question, question_id, populate_existing=True)
    if q is None:
        raise AppError("QUESTION_NOT_FOUND", "题目不存在或已被删除", status_code=404)
    if q.created_by != user.id:
        raise AppError("FORBIDDEN", "只能操作自己生成的题目", status_code=403)
    _assert_question_material_available(db, q)
    return q


def _assert_question_material_available(db: Session, question: Question) -> None:
    """调用方持有资料变更门禁，避免对删除中的资源确认题目写入。"""
    bank = db.get(Bank, question.bank_id, populate_existing=True)
    document = db.get(Document, question.document_id, populate_existing=True)
    if (bank is None or bank.status != "active" or document is None
            or document.bank_id != question.bank_id or document.status == "deleting"):
        raise AppError("QUESTION_RESOURCE_UNAVAILABLE", "题目所属资料正在删除或已不可用", 409)


@router.get("")
def list_questions(
    batch_id: str = "",
    bank_id: str = "",
    document_id: str = "",
    type: str = "",
    difficulty: str = "",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """本人题目分页及收藏状态；过滤删除中、已删除或归属不符的源资料。"""
    q = (
        db.query(Question)
        .join(Bank, Bank.id == Question.bank_id)
        .join(Document, (Document.id == Question.document_id) & (Document.bank_id == Bank.id))
        .filter(
            Question.created_by == user.id,
            Bank.status == "active",
            Document.status != "deleting",
        )
    )
    if batch_id:
        q = q.filter(Question.batch_id == batch_id)
    if bank_id:
        q = q.filter(Question.bank_id == bank_id)
    if document_id:
        q = q.filter(Question.document_id == document_id)
    if type:
        q = q.filter(Question.type == type)
    if difficulty:
        q = q.filter(Question.difficulty == difficulty)
    total = q.count()
    rows = q.order_by(Question.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()

    favs = {
        f.question_id: f
        for f in db.query(Favorite).filter(
            Favorite.user_id == user.id, Favorite.question_id.in_([r.id for r in rows])
        ).all()
    }
    doc_ids = {r.document_id for r in rows}
    doc_names = (
        dict(db.query(Document.id, Document.name).filter(Document.id.in_(doc_ids)).all())
        if doc_ids
        else {}
    )
    return {
        "items": [
            question_to_api(
                r,
                starred=r.id in favs,
                favorite_group_id=favs[r.id].group_id if r.id in favs else None,
                doc_name=doc_names.get(r.document_id, ""),
            )
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.put("/{question_id}")
def update_question(
    question_id: str,
    body: QuestionUpdateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_mutations_allowed(db)
    q = _get_owned_question(question_id, user, db)
    if body.type is not None:
        q.type = body.type
    if body.score is not None:
        q.score = body.score
    if body.difficulty is not None:
        q.difficulty = body.difficulty
    if body.stem is not None:
        q.stem = body.stem
    if body.options is not None:
        q.options_json = json.dumps(body.options, ensure_ascii=False) if body.options else None
    if body.answer is not None:
        q.answer = body.answer
    if body.analysis is not None:
        q.analysis = body.analysis
    if body.knowledge_point is not None:
        q.knowledge_point = body.knowledge_point
    db.commit()
    db.refresh(q)
    fav = db.query(Favorite).filter(Favorite.user_id == user.id, Favorite.question_id == q.id).first()
    return question_to_api(q, starred=fav is not None, favorite_group_id=fav.group_id if fav else None)


@router.delete("/{question_id}", status_code=204)
def delete_question(
    question_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_mutations_allowed(db)
    q = _get_owned_question(question_id, user, db)
    db.query(Favorite).filter(Favorite.question_id == q.id).delete(synchronize_session=False)
    db.delete(q)
    db.commit()
    return None


@router.post("/batch-delete", status_code=204)
def batch_delete(
    body: BatchDeleteBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assert_mutations_allowed(db)
    rows = db.query(Question).filter(
        Question.id.in_(body.question_ids), Question.created_by == user.id,
    ).populate_existing().all()
    for row in rows:
        _assert_question_material_available(db, row)
    if rows:
        db.query(Favorite).filter(Favorite.question_id.in_([r.id for r in rows])).delete(synchronize_session=False)
        for r in rows:
            db.delete(r)
        db.commit()
    return None
