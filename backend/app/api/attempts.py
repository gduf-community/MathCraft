"""学生作答、交卷与复盘接口（v2 5.11）。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import require_student
from app.errors import AppError
from app.models import PaperAttempt, User
from app.schemas.paper import AttemptCreateBody, AttemptSubmitBody
from app.services import attempts

router = APIRouter(prefix="/api", tags=["attempts"])


@router.get("/papers/{paper_id}/attempt")
def get_attempt(
    paper_id: str,
    space_id: str | None = None,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    # 已交卷的作答允许在时间窗结束后打开复盘；未交卷时必须处于作答时间内
    paper, pub, space = attempts.attempt_access(db, student, paper_id, space_id, require_open_window=False)
    latest = attempts.latest_attempt(db, paper.id, student.id, space_id)
    if latest is None or latest.status == "answering":
        attempts.check_window(paper, pub)
    if latest is None:
        return attempts.preview_payload(db, paper, space)
    return attempts.attempt_payload(db, latest, paper, space)


@router.post("/papers/{paper_id}/attempts", status_code=201)
def start_attempt(
    paper_id: str,
    body: AttemptCreateBody,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    paper, _pub, space = attempts.attempt_access(db, student, paper_id, body.space_id)
    attempt = attempts.create_attempt(db, paper, student, body.space_id)
    return attempts.attempt_payload(db, attempt, paper, space)


@router.post("/attempts/{attempt_id}/submit")
def submit_attempt(
    attempt_id: str,
    body: AttemptSubmitBody,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    attempt = db.get(PaperAttempt, attempt_id)
    if attempt is None:
        raise AppError("ATTEMPT_NOT_FOUND", "作答记录不存在", status_code=404)
    return attempts.submit_attempt(db, attempt, student, body.answers)


@router.get("/attempts/{attempt_id}/review")
def review_attempt(
    attempt_id: str,
    student: User = Depends(require_student),
    db: Session = Depends(get_db),
):
    attempt, paper, space = attempts.get_attempt_for_student(db, attempt_id, student)
    if attempt.status != "submitted":
        raise AppError("NOT_SUBMITTED", "尚未交卷，不能查看解析", status_code=409)
    if not paper.allow_review:
        raise AppError("REVIEW_NOT_ALLOWED", "该试卷不允许交卷后查看答案与解析", status_code=403)
    return attempts.attempt_payload(db, attempt, paper, space)
