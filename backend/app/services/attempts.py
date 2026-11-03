"""学生作答、交卷与复盘业务。"""
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    AttemptAnswer,
    Paper,
    PaperAttempt,
    PaperPublication,
    PaperQuestion,
    SpaceMember,
    StudySpace,
    User,
)
from app.models.base import new_id, utcnow
from app.services import grading
from app.services.model_settings import get_effective_deepseek_key


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def check_window(paper: Paper, publication: PaperPublication | None, check_time: bool = True) -> None:
    """停止作答始终校验；时间窗校验可通过 check_time=False 跳过（复盘已交卷时）。"""
    if publication and publication.stopped:
        raise AppError("PAPER_STOPPED", "该试卷已停止作答", status_code=403)
    if not check_time:
        return
    now = utcnow()
    start, end = _aware(paper.exam_start), _aware(paper.exam_end)
    if start and now < start:
        raise AppError("EXAM_NOT_STARTED", "作答尚未开始", status_code=403)
    if end and now > end:
        raise AppError("EXAM_ENDED", "已过作答时间", status_code=403)


def attempt_access(
    db: Session,
    user: User,
    paper_id: str,
    space_id: str | None,
    require_open_window: bool = True,
) -> tuple[Paper, PaperPublication | None, StudySpace | None]:
    """校验作答入口；require_open_window=False 时不校验时间窗（复盘已交卷时使用）。"""
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise AppError("PAPER_NOT_FOUND", "试卷不存在或已被删除", status_code=404)

    if space_id:
        space = db.get(StudySpace, space_id)
        if space is None or space.status != "active":
            raise AppError("SPACE_NOT_FOUND", "学习空间不存在或已解散", status_code=404)
        member = (
            db.query(SpaceMember)
            .filter(
                SpaceMember.space_id == space_id,
                SpaceMember.user_id == user.id,
                SpaceMember.status == "active",
            )
            .one_or_none()
        )
        if member is None:
            raise AppError("NOT_SPACE_MEMBER", "你不是该学习空间成员", status_code=403)
        pub = (
            db.query(PaperPublication)
            .filter(PaperPublication.paper_id == paper.id, PaperPublication.space_id == space_id)
            .one_or_none()
        )
        if pub is None or paper.status != "published":
            raise AppError("PAPER_NOT_PUBLISHED", "试卷未发布到该空间", status_code=403)
        # 停止作答始终拦截；时间窗仅在 require_open_window 时校验（复盘已交卷可越过时间）
        check_window(paper, pub, check_time=require_open_window)
        return paper, pub, space

    # 个人练习卷：只有创建者本人可以作答
    if paper.owner_id != user.id:
        raise AppError("PAPER_NOT_PUBLISHED", "试卷未发布到你的学习空间", status_code=403)
    check_window(paper, None, check_time=require_open_window)
    return paper, None, None


def latest_attempt(
    db: Session, paper_id: str, student_id: str, space_id: str | None
) -> PaperAttempt | None:
    q = db.query(PaperAttempt).filter(
        PaperAttempt.paper_id == paper_id,
        PaperAttempt.student_id == student_id,
    )
    if space_id:
        q = q.filter(PaperAttempt.space_id == space_id)
    else:
        q = q.filter(PaperAttempt.space_id.is_(None))
    return q.order_by(PaperAttempt.started_at.desc()).first()


def create_attempt(db: Session, paper: Paper, student: User, space_id: str | None) -> PaperAttempt:
    existing = latest_attempt(db, paper.id, student.id, space_id)
    if existing and existing.status == "answering":
        return existing
    if existing and existing.status == "submitted" and not paper.allow_retake:
        raise AppError("RETAKE_NOT_ALLOWED", "该试卷不允许修改答案重新提交", status_code=403)
    attempt = PaperAttempt(
        id=new_id("att"),
        paper_id=paper.id,
        space_id=space_id,
        student_id=student.id,
        status="answering",
        total_score=paper.total_score,
        started_at=utcnow(),
    )
    db.add(attempt)
    db.flush()
    if existing and existing.status == "submitted":
        # 修改答案重做：携带上一次提交的答案，学生可在此基础上修改后重新交卷
        prev_answers = db.query(AttemptAnswer).filter(AttemptAnswer.attempt_id == existing.id).all()
        for a in prev_answers:
            db.add(
                AttemptAnswer(
                    id=new_id("ans"),
                    attempt_id=attempt.id,
                    paper_question_id=a.paper_question_id,
                    choices_json=a.choices_json,
                    text_answer=a.text_answer,
                    score=0,
                    is_correct=False,
                    graded_by=a.graded_by,
                )
            )
    db.commit()
    db.refresh(attempt)
    return attempt


def _question_rows(db: Session, paper_id: str) -> list[PaperQuestion]:
    return (
        db.query(PaperQuestion)
        .filter(PaperQuestion.paper_id == paper_id)
        .order_by(PaperQuestion.order_no)
        .all()
    )


def preview_payload(db: Session, paper: Paper, space: StudySpace | None) -> dict:
    rows = _question_rows(db, paper.id)
    return {
        "paper": {
            "id": paper.id,
            "name": paper.name,
            "total_score": paper.total_score,
            "allow_review": bool(paper.allow_review),
            "allow_retake": bool(paper.allow_retake),
            "exam_window": (
                {"start": _aware(paper.exam_start), "end": _aware(paper.exam_end)}
                if paper.exam_start or paper.exam_end
                else None
            ),
            "stopped": False,
        },
        "space": {"id": space.id, "name": space.name} if space else None,
        "questions": [
            {
                "paper_question_id": pq.id,
                "no": pq.order_no,
                "type": pq.type,
                "score": pq.score,
                "difficulty": pq.difficulty,
                "stem": pq.stem,
                "options": json.loads(pq.options_json) if pq.options_json else [],
                "knowledge_point": pq.knowledge_point or "",
            }
            for pq in rows
        ],
        "attempt": None,
        "answers": [],
    }


def attempt_payload(
    db: Session,
    attempt: PaperAttempt,
    paper: Paper,
    space: StudySpace | None,
) -> dict:
    rows = _question_rows(db, paper.id)
    submitted = attempt.status == "submitted"
    answers = {
        a.paper_question_id: a
        for a in db.query(AttemptAnswer).filter(AttemptAnswer.attempt_id == attempt.id).all()
    }
    questions = []
    for pq in rows:
        item = {
            "paper_question_id": pq.id,
            "no": pq.order_no,
            "type": pq.type,
            "score": pq.score,
            "difficulty": pq.difficulty,
            "stem": pq.stem,
            "options": json.loads(pq.options_json) if pq.options_json else [],
            "knowledge_point": pq.knowledge_point or "",
        }
        if submitted and paper.allow_review:
            # 未勾选「交卷后查看答案和解析」时不下发答案
            item["answer"] = pq.answer
            item["analysis"] = pq.analysis
        questions.append(item)

    return {
        "paper": {
            "id": paper.id,
            "name": paper.name,
            "total_score": paper.total_score,
            "allow_review": bool(paper.allow_review),
            "allow_retake": bool(paper.allow_retake),
            "exam_window": (
                {"start": _aware(paper.exam_start), "end": _aware(paper.exam_end)}
                if paper.exam_start or paper.exam_end
                else None
            ),
            "stopped": False,
        },
        "space": {"id": space.id, "name": space.name} if space else None,
        "questions": questions,
        "attempt": {
            "id": attempt.id,
            "status": attempt.status,
            "score": attempt.score,
            "total_score": attempt.total_score,
            "started_at": attempt.started_at,
            "submitted_at": attempt.submitted_at,
        },
        "answers": [
            {
                "paper_question_id": qid,
                "choices": json.loads(a.choices_json) if a.choices_json else [],
                "text": a.text_answer or "",
                "score": a.score,
                "is_correct": bool(a.is_correct),
                "grading_note": a.grading_note,
            }
            for qid, a in answers.items()
        ],
    }


def submit_attempt(
    db: Session,
    attempt: PaperAttempt,
    student: User,
    answers: list,
) -> dict:
    if attempt.student_id != student.id:
        raise AppError("FORBIDDEN", "不能提交他人的作答", status_code=403)
    if attempt.status != "answering":
        raise AppError("ALREADY_SUBMITTED", "当前作答已交卷", status_code=409)

    paper, pub, _space = attempt_access(db, student, attempt.paper_id, attempt.space_id)
    rows = _question_rows(db, paper.id)
    by_id = {r.id: r for r in rows}
    submitted = {a.paper_question_id: a for a in answers if a.paper_question_id in by_id}

    # 主观题且填写了答案时，必须配置 DeepSeek 密钥
    api_key = get_effective_deepseek_key(db, student.id)
    needs_llm = any(
        grading.answer_needs_llm(pq, submitted[pq.id].text if pq.id in submitted else "")
        for pq in rows
    )
    if needs_llm and not api_key:
        raise AppError(
            "DEEPSEEK_KEY_MISSING",
            "主观题批卷需要 DeepSeek API Key，请到个人中心 → 模型配置中填写",
            status_code=400,
        )

    db.query(AttemptAnswer).filter(AttemptAnswer.attempt_id == attempt.id).delete(synchronize_session=False)
    total = 0
    detail = []
    for pq in rows:
        item = submitted.get(pq.id)
        choices = item.choices if item else []
        text = item.text if item else ""
        if pq.type in grading.CHOICE_TYPES:
            score, is_correct = grading.grade_objective(pq, choices)
            note = None
            graded_by = "rule"
        else:
            score, is_correct, note = grading.grade_subjective(pq, text, api_key)
            graded_by = "llm" if text.strip() else "rule"
        total += score
        db.add(
            AttemptAnswer(
                id=new_id("ans"),
                attempt_id=attempt.id,
                paper_question_id=pq.id,
                choices_json=grading.serialize_choices(choices),
                text_answer=text or None,
                score=score,
                is_correct=is_correct,
                graded_by=graded_by,
                grading_note=note,
            )
        )
        detail.append(
            {
                "paper_question_id": pq.id,
                "score": score,
                "is_correct": bool(is_correct),
                **({"answer": pq.answer, "analysis": pq.analysis} if paper.allow_review else {}),
            }
        )

    attempt.status = "submitted"
    attempt.score = total
    attempt.total_score = paper.total_score
    attempt.submitted_at = utcnow()
    db.commit()
    return {
        "attempt_id": attempt.id,
        "score": total,
        "total_score": paper.total_score,
        "detail": detail,
    }


def get_attempt_for_student(db: Session, attempt_id: str, student: User) -> tuple[PaperAttempt, Paper, StudySpace | None]:
    attempt = db.get(PaperAttempt, attempt_id)
    if attempt is None or attempt.student_id != student.id:
        raise AppError("ATTEMPT_NOT_FOUND", "作答记录不存在", status_code=404)
    paper = db.get(Paper, attempt.paper_id)
    if paper is None:
        raise AppError("PAPER_NOT_FOUND", "试卷不存在或已被删除", status_code=404)
    space = db.get(StudySpace, attempt.space_id) if attempt.space_id else None
    return attempt, paper, space
