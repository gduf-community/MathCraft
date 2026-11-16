"""组卷业务：题目快照、发布、停止恢复、删除、统计、催交。"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from app.errors import AppError
from app.models import (
    AttemptAnswer,
    Paper,
    PaperAttempt,
    PaperPublication,
    PaperQuestion,
    PaperUrge,
    Question,
    SpaceMember,
    StudySpace,
    UrgeReadState,
    User,
)
from app.models.base import new_id, utcnow
from app.services.paper_state import lock_paper

TYPE_ORDER = ["single", "multiple", "judge", "blank", "compute", "essay"]

URGE_COOLDOWN = timedelta(hours=24)


def _aware(dt: datetime) -> datetime:
    """SQLite 读回的 datetime 为 naive（实际是 UTC），统一补成 aware 便于比较。"""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def validate_exam_window(start: datetime | None, end: datetime | None) -> None:
    if start is not None and end is None:
        raise AppError("BAD_REQUEST", "请同时设置开始与结束时间，或都不设置", status_code=400)
    if end is not None and start is None:
        raise AppError("BAD_REQUEST", "请同时设置开始与结束时间，或都不设置", status_code=400)
    if start and end and end <= start:
        raise AppError("BAD_REQUEST", "结束时间必须晚于开始时间", status_code=400)


def compute_modules(questions: list[Question]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for q in questions:
        m = grouped.setdefault(q.type, {"type": q.type, "count": 0, "total_score": 0})
        m["count"] += 1
        m["total_score"] += q.score
    return [grouped[t] for t in TYPE_ORDER if t in grouped]


def _snapshot_rows(paper_id: str, questions: list[Question]) -> list[PaperQuestion]:
    rows = []
    for i, q in enumerate(questions, 1):
        rows.append(
            PaperQuestion(
                id=new_id("pq"),
                paper_id=paper_id,
                source_question_id=q.id,
                order_no=i,
                module_type=q.type,
                type=q.type,
                score=q.score,
                difficulty=q.difficulty,
                difficulty_score=q.difficulty_score,
                stem=q.stem,
                options_json=q.options_json,
                answer=q.answer,
                analysis=q.analysis,
                knowledge_point=q.knowledge_point,
            )
        )
    return rows


def get_questions_for_owner(db: Session, owner_id: str, question_ids: list[str]) -> list[Question]:
    rows = db.query(Question).filter(Question.id.in_(question_ids), Question.created_by == owner_id).all()
    by_id = {q.id: q for q in rows}
    missing = [qid for qid in question_ids if qid not in by_id]
    if missing:
        raise AppError("QUESTION_NOT_FOUND", f"有 {len(missing)} 道题目不存在或不属于当前用户", status_code=404)
    # 保留请求顺序
    return [by_id[qid] for qid in question_ids]


def paper_question_payload(pq: PaperQuestion, include_answer: bool = True) -> dict:
    payload = {
        "id": pq.id,
        "paper_question_id": pq.id,
        "source_question_id": pq.source_question_id,
        "no": pq.order_no,
        "type": pq.type,
        "score": pq.score,
        "difficulty": pq.difficulty,
        "stem": pq.stem,
        "options": json.loads(pq.options_json) if pq.options_json else [],
        "knowledge_point": pq.knowledge_point or "",
    }
    if include_answer:
        payload["answer"] = pq.answer
        payload["analysis"] = pq.analysis
    return payload


def publications(db: Session, paper_id: str) -> list[Row[PaperPublication, StudySpace]]:
    return (
        db.query(PaperPublication, StudySpace)
        .join(StudySpace, StudySpace.id == PaperPublication.space_id)
        .filter(PaperPublication.paper_id == paper_id)
        .all()
    )


def _submitted_count(db: Session, paper_id: str, space_id: str | None = None) -> int:
    q = db.query(PaperAttempt.student_id).filter(
        PaperAttempt.paper_id == paper_id,
        PaperAttempt.status == "submitted",
    )
    if space_id:
        q = q.filter(PaperAttempt.space_id == space_id)
    return q.distinct().count()


def _student_count_for_paper(db: Session, paper_id: str) -> int:
    total = 0
    for _pub, space in publications(db, paper_id):
        if space.status == "active":
            total += (
                db.query(func.count(SpaceMember.id))
                .filter(
                    SpaceMember.space_id == space.id,
                    SpaceMember.status == "active",
                    SpaceMember.role == "member",
                )
                .scalar()
                or 0
            )
    return total


def _latest_attempt(
    db: Session, paper_id: str, student_id: str, space_id: str | None = None,
    *, submitted_only: bool = False,
) -> PaperAttempt | None:
    q = db.query(PaperAttempt).filter(
        PaperAttempt.paper_id == paper_id,
        PaperAttempt.student_id == student_id,
    )
    if space_id:
        q = q.filter(PaperAttempt.space_id == space_id)
    paper = db.get(Paper, paper_id)
    if submitted_only or (paper is not None and (paper.closed or paper.deleted)):
        q = q.filter(PaperAttempt.status == "submitted")
    return q.order_by(PaperAttempt.started_at.desc()).first()


def paper_payload(
    db: Session,
    paper: Paper,
    viewer: User,
    include_questions: bool = True,
    space_id: str | None = None,
    include_history: bool = False,
) -> dict:
    pubs = publications(db, paper.id)
    spaces = [
        {
            "space_id": space.id,
            "name": space.name,
            "stopped": bool(pub.stopped),
            "published_at": pub.published_at,
        }
        for pub, space in pubs
    ]
    latest = _latest_attempt(
        db, paper.id, viewer.id, space_id,
        submitted_only=any(pub.space_id == space_id and pub.stopped for pub, _space in pubs),
    ) if viewer.role == "student" else None
    submitted = bool(latest and latest.status == "submitted")

    data = {
        "id": paper.id,
        "name": paper.name,
        "owner_id": paper.owner_id,
        "created_at": paper.created_at,
        "updated_at": paper.updated_at,
        "question_count": paper.question_count,
        "total_score": paper.total_score,
        "status": paper.status,
        "closed": bool(paper.closed),
        "deleted": bool(paper.deleted),
        "saved_to_records": bool(paper.saved_to_records),
        "allow_review": bool(paper.allow_review),
        "allow_retake": bool(paper.allow_retake),
        "exam_window": (
            {
                "start": _aware(paper.exam_start) if paper.exam_start is not None else None,
                "end": _aware(paper.exam_end) if paper.exam_end is not None else None,
            }
            if paper.exam_start or paper.exam_end
            else None
        ),
        "spaces": spaces,
        "submitted_count": _submitted_count(db, paper.id, space_id),
        "student_count": _student_count_for_paper(db, paper.id),
        "answered": submitted,
        "modules_order": json.loads(paper.modules_order_json) if paper.modules_order_json else [],
    }
    if include_questions:
        rows = (
            db.query(PaperQuestion)
            .filter(PaperQuestion.paper_id == paper.id)
            .order_by(PaperQuestion.order_no)
            .all()
        )
        if include_history:
            historical_ids = {
                question_id
                for attempt in db.query(PaperAttempt).filter_by(paper_id=paper.id).all()
                for question_id in json.loads(attempt.question_ids_json or "[]")
            }
            rows = [row for row in rows if not row.removed or row.id in historical_ids]
        else:
            rows = [row for row in rows if not row.removed]
        # 他人试卷仅在交卷且允许复盘时下发答案，个人练习拥有者保留查看权限
        include_answer = viewer.id == paper.owner_id or (submitted and bool(paper.allow_review))
        data["questions"] = [
            {**paper_question_payload(row, include_answer),
             "no": row.order_no if include_history else index}
            for index, row in enumerate(rows, 1)
        ]
    return data


def validate_space_ids(db: Session, user: User, space_ids: list[str]) -> list[StudySpace]:
    if not space_ids:
        return []
    if user.role != "teacher":
        raise AppError("FORBIDDEN", "只有教师可以发布到学习空间", status_code=403)
    spaces = db.query(StudySpace).filter(StudySpace.id.in_(space_ids), StudySpace.status == "active").all()
    by_id = {s.id: s for s in spaces}
    for sid in space_ids:
        s = by_id.get(sid)
        if s is None:
            raise AppError("SPACE_NOT_FOUND", "学习空间不存在或已解散", status_code=404)
        if s.creator_id != user.id:
            raise AppError("FORBIDDEN", "只能发布到自己创建的学习空间", status_code=403)
    return [by_id[sid] for sid in space_ids]


def create_paper(db: Session, user: User, body) -> Paper:
    questions = get_questions_for_owner(db, user.id, body.questions)
    validate_exam_window(body.exam_start, body.exam_end)

    is_published = bool(body.is_published) and user.role == "teacher"
    space_ids = body.space_ids if is_published else []
    if user.role == "student":
        # 学生只能保存个人练习卷，不发布、不设置做题时间
        is_published = False
        space_ids = []
        body.exam_start = None
        body.exam_end = None
    if is_published and not space_ids:
        raise AppError("BAD_REQUEST", "发布时必须至少选择一个学习空间", status_code=400)
    spaces = validate_space_ids(db, user, space_ids)

    modules = (
        [m.model_dump() for m in body.modules_order]
        if body.modules_order
        else compute_modules(questions)
    )
    paper = Paper(
        id=new_id("paper"),
        name=body.name.strip(),
        owner_id=user.id,
        status="published" if is_published else "draft",
        saved_to_records=bool(body.save_to_records) if user.role == "teacher" else True,
        allow_review=bool(body.allow_review),
        allow_retake=bool(body.allow_retake),
        modules_order_json=json.dumps(modules, ensure_ascii=False),
        question_count=len(questions),
        total_score=sum(q.score for q in questions),
        exam_start=body.exam_start,
        exam_end=body.exam_end,
        published_at=utcnow() if is_published else None,
    )
    db.add(paper)
    db.flush()
    db.add_all(_snapshot_rows(paper.id, questions))
    for space in spaces:
        db.add(
            PaperPublication(
                id=new_id("pub"),
                paper_id=paper.id,
                space_id=space.id,
                published_at=utcnow(),
            )
        )
    db.commit()
    db.refresh(paper)
    return paper


def _check_publication_removal(db: Session, paper: Paper, pub: PaperPublication) -> None:
    """在试卷写门禁内确认指定空间的发布可移除。"""
    if db.query(PaperAttempt.id).filter_by(
        paper_id=paper.id, space_id=pub.space_id,
    ).first():
        raise AppError(
            "PAPER_HAS_ATTEMPTS",
            "该空间已有作答，不能移除发布；请停止作答或整卷删除以保留历史",
            status_code=409,
        )
    if not pub.stopped:
        raise AppError("PAPER_PUBLICATION_OPEN", "请先停止作答，才能移除发布", status_code=409)


def _sync_publications(db: Session, paper: Paper, user: User, space_ids: list[str]) -> None:
    desired = {s.id: s for s in validate_space_ids(db, user, space_ids)}
    existing = {pub.space_id: pub for pub, _s in publications(db, paper.id)}
    # 删除不在目标里的发布记录；有作答时禁止
    for sid, pub in existing.items():
        if sid not in desired:
            db.refresh(pub)
            _check_publication_removal(db, paper, pub)
            db.delete(pub)
    # 新增
    for sid in desired:
        if sid not in existing:
            db.add(
                PaperPublication(
                    id=new_id("pub"),
                    paper_id=paper.id,
                    space_id=sid,
                    published_at=utcnow(),
                )
            )


def update_paper(db: Session, paper: Paper, user: User, body) -> Paper:
    paper = lock_paper(db, paper.id)
    if body.name is not None:
        paper.name = body.name.strip()

    if body.questions is not None:
        if db.query(PaperAttempt).filter(PaperAttempt.paper_id == paper.id).first():
            raise AppError("FORBIDDEN", "已有学生作答，不能整体替换题目", status_code=409)
        questions = get_questions_for_owner(db, user.id, body.questions)
        db.query(PaperQuestion).filter(PaperQuestion.paper_id == paper.id).delete(synchronize_session=False)
        db.add_all(_snapshot_rows(paper.id, questions))
        paper.question_count = len(questions)
        paper.total_score = sum(q.score for q in questions)
        if body.modules_order is None:
            paper.modules_order_json = json.dumps(compute_modules(questions), ensure_ascii=False)

    if body.modules_order is not None:
        paper.modules_order_json = json.dumps([m.model_dump() for m in body.modules_order], ensure_ascii=False)

    fields = body.model_fields_set
    if body.allow_review is not None:
        paper.allow_review = body.allow_review
    if body.allow_retake is not None:
        paper.allow_retake = body.allow_retake
    if user.role == "student":
        paper.exam_start = None
        paper.exam_end = None
    elif "exam_start" in fields or "exam_end" in fields:
        validate_exam_window(body.exam_start, body.exam_end)
        paper.exam_start = body.exam_start
        paper.exam_end = body.exam_end

    if body.space_ids is not None:
        if user.role != "teacher":
            raise AppError("FORBIDDEN", "学生不能发布到学习空间", status_code=403)
        _sync_publications(db, paper, user, body.space_ids)
        paper.status = "published" if body.space_ids else "draft"
        if paper.status == "published":
            paper.published_at = paper.published_at or utcnow()

    if body.is_published is not None:
        if user.role != "teacher":
            raise AppError("FORBIDDEN", "学生不能发布试卷", status_code=403)
        if body.is_published:
            current = [pub.space_id for pub, _s in publications(db, paper.id)]
            if not current:
                raise AppError("BAD_REQUEST", "发布时必须至少选择一个学习空间", status_code=400)
            paper.status = "published"
            paper.published_at = paper.published_at or utcnow()
        else:
            _sync_publications(db, paper, user, [])
            paper.status = "draft"

    db.commit()
    db.refresh(paper)
    return paper


def publish_paper(db: Session, paper: Paper, user: User, body) -> Paper:
    paper = lock_paper(db, paper.id)
    if user.role != "teacher":
        raise AppError("FORBIDDEN", "只有教师可以发布试卷", status_code=403)
    validate_exam_window(body.exam_start, body.exam_end)
    spaces = validate_space_ids(db, user, body.space_ids)
    existing = {pub.space_id for pub, _s in publications(db, paper.id)}
    dup = [s.id for s in spaces if s.id in existing]
    if dup:
        raise AppError("ALREADY_PUBLISHED", "该试卷已发布到所选空间", status_code=409)
    for space in spaces:
        db.add(PaperPublication(id=new_id("pub"), paper_id=paper.id, space_id=space.id, published_at=utcnow()))
    if body.exam_start is not None:
        paper.exam_start = body.exam_start
        paper.exam_end = body.exam_end
    paper.status = "published"
    paper.published_at = paper.published_at or utcnow()
    db.commit()
    db.refresh(paper)
    return paper


def get_publication(db: Session, paper_id: str, space_id: str) -> PaperPublication:
    pub = (
        db.query(PaperPublication)
        .filter(PaperPublication.paper_id == paper_id, PaperPublication.space_id == space_id)
        .one_or_none()
    )
    if pub is None:
        raise AppError("PAPER_NOT_PUBLISHED", "试卷未发布到该空间", status_code=404)
    return pub


def set_publication_stopped(db: Session, pub: PaperPublication, stopped: bool) -> None:
    lock_paper(db, pub.paper_id)
    db.refresh(pub)
    pub.stopped = stopped
    pub.stopped_at = utcnow() if stopped else None
    db.commit()


def set_closed(db: Session, paper: Paper, closed: bool) -> Paper:
    """关闭只阻止新作答及交卷；历史复盘继续可用。"""
    paper = lock_paper(db, paper.id)
    paper.closed = closed
    db.commit()
    return paper


def delete_paper(
    db: Session, paper: Paper, mode: str = "record", *, commit: bool = True,
) -> None:
    """移除记录或关闭后的试卷，保留发布、题目、答案及历史统计。"""
    paper = lock_paper(db, paper.id)
    has_pub = db.query(PaperPublication.id).filter_by(paper_id=paper.id).first()
    if mode == "record" and paper.status == "published" and has_pub:
        paper.saved_to_records = False
    else:
        if not paper.closed:
            raise AppError("PAPER_NOT_CLOSED", "请先关闭试卷，才能删除", 409)
        if db.query(PaperPublication.id).filter_by(paper_id=paper.id, stopped=False).first():
            raise AppError("PAPER_PUBLICATION_OPEN", "请先停止所有学习空间中的作答", 409)
        if db.query(PaperAttempt.id).filter_by(paper_id=paper.id, status="grading").first():
            raise AppError("GRADING_BUSY", "试卷正在批卷，请稍后删除", 409)
        paper.deleted = True
        paper.saved_to_records = False
    if commit:
        db.commit()


def remove_publication(db: Session, paper: Paper, pub: PaperPublication) -> None:
    """停止且被移除空间没有该试卷作答时允许移除发布，否则保留该空间历史入口。"""
    paper = lock_paper(db, paper.id)
    db.refresh(pub)
    _check_publication_removal(db, paper, pub)
    db.delete(pub)
    db.flush()
    if not db.query(PaperPublication).filter(PaperPublication.paper_id == paper.id).first():
        paper.status = "draft"
    db.commit()


def remove_paper_questions(db: Session, paper: Paper, paper_question_ids: list[str]) -> Paper:
    paper = lock_paper(db, paper.id)
    if not paper.closed:
        raise AppError("PAPER_NOT_CLOSED", "请先关闭试卷，才能删除题目", 409)
    if db.query(PaperAttempt).filter_by(paper_id=paper.id, status="grading").first():
        raise AppError("GRADING_BUSY", "试卷正在批卷，请稍后删除", 409)
    rows = (
        db.query(PaperQuestion)
        .filter(PaperQuestion.paper_id == paper.id, PaperQuestion.id.in_(paper_question_ids), PaperQuestion.removed.is_(False))
        .all()
    )
    if not rows:
        raise AppError("NOT_FOUND", "题目不在该试卷中", status_code=404)
    for r in rows:
        r.removed = True
    db.flush()
    remaining = (
        db.query(PaperQuestion)
        .filter(PaperQuestion.paper_id == paper.id, PaperQuestion.removed.is_(False))
        .order_by(PaperQuestion.order_no)
        .all()
    )
    paper.question_count = len(remaining)
    paper.total_score = sum(r.score for r in remaining)
    paper.modules_order_json = json.dumps(
        [
            {
                "type": t,
                "count": sum(1 for r in remaining if r.type == t),
                "total_score": sum(r.score for r in remaining if r.type == t),
            }
            for t in TYPE_ORDER
            if any(r.type == t for r in remaining)
        ],
        ensure_ascii=False,
    )
    db.commit()
    db.refresh(paper)
    return paper


def list_papers(
    db: Session,
    user: User,
    include_drafts: bool = True,
    saved_only: bool = False,
    space_id: str | None = None,
    include_history: bool = False,
) -> list[dict]:
    """组卷记录严格按账号隔离：只返回当前用户自己创建的试卷。

    学生作答老师发布的试卷通过学习空间（space_papers）与作答接口进入，
    不混入学生的组卷记录列表。
    """
    query = db.query(Paper).filter(Paper.owner_id == user.id)
    if not include_history:
        query = query.filter(Paper.deleted.is_(False))
    papers = {p.id: p for p in query.all()}

    out = []
    for p in sorted(papers.values(), key=lambda x: x.created_at, reverse=True):
        if p.deleted and not db.query(PaperAttempt.id).filter_by(
            paper_id=p.id, status="submitted",
        ).first():
            continue
        if not include_drafts and p.status != "published":
            continue
        if saved_only and not p.saved_to_records and not (include_history and p.deleted):
            continue
        if space_id:
            exists = (
                db.query(PaperPublication.id)
                .filter(PaperPublication.paper_id == p.id, PaperPublication.space_id == space_id)
                .first()
            )
            if not exists:
                continue
        out.append(paper_payload(db, p, user, include_questions=False, space_id=space_id))
    return out


def space_papers(db: Session, space: StudySpace, viewer: User) -> list[dict]:
    rows = (
        db.query(PaperPublication, Paper)
        .join(Paper, Paper.id == PaperPublication.paper_id)
        .filter(PaperPublication.space_id == space.id, Paper.status == "published")
        .order_by(PaperPublication.published_at.desc())
        .all()
    )
    # 每份试卷在该空间的最近一次催交时间（前端用于 24 小时冷却置灰）
    urge_map: dict[str, datetime] = {}
    if rows:
        for pid, last in (
            db.query(PaperUrge.paper_id, func.max(PaperUrge.created_at))
            .filter(
                PaperUrge.space_id == space.id,
                PaperUrge.paper_id.in_([p.id for _pub, p in rows]),
            )
            .group_by(PaperUrge.paper_id)
            .all()
        ):
            urge_map[pid] = last
    out = []
    for pub, paper in rows:
        if paper.deleted:
            history = db.query(PaperAttempt.id).filter_by(
                paper_id=paper.id, space_id=space.id, status="submitted",
            )
            if viewer.role == "student":
                history = history.filter(PaperAttempt.student_id == viewer.id)
            if history.first() is None:
                continue
        latest = _latest_attempt(
            db, paper.id, viewer.id, space.id, submitted_only=pub.stopped,
        ) if viewer.role == "student" else None
        out.append(
            {
                "id": paper.id,
                "name": paper.name,
                "created_at": paper.created_at,
                "question_count": paper.question_count,
                "total_score": paper.total_score,
                "status": paper.status,
                "closed": bool(paper.closed),
                "deleted": bool(paper.deleted),
                "allow_review": bool(paper.allow_review),
                "allow_retake": bool(paper.allow_retake),
                "exam_window": (
                    {
                        "start": _aware(paper.exam_start) if paper.exam_start is not None else None,
                        "end": _aware(paper.exam_end) if paper.exam_end is not None else None,
                    }
                    if paper.exam_start or paper.exam_end
                    else None
                ),
                "stopped": bool(pub.stopped),
                "submitted_count": _submitted_count(db, paper.id, space.id),
                "student_count": (
                    db.query(func.count(SpaceMember.id))
                    .filter(
                        SpaceMember.space_id == space.id,
                        SpaceMember.status == "active",
                        SpaceMember.role == "member",
                    )
                    .scalar()
                    or 0
                ),
                "answered": bool(latest and latest.status == "submitted"),
                "last_urge_at": urge_map.get(paper.id),
            }
        )
    return out


def urge_paper(db: Session, paper: Paper, space: StudySpace, teacher: User) -> dict:
    """统一写门禁内检查可作答状态及同一发布的 24 小时催交冷却。"""
    paper = lock_paper(db, paper.id)
    pub = get_publication(db, paper.id, space.id)
    db.refresh(pub)
    if paper.closed:
        raise AppError("PAPER_CLOSED", "该试卷已关闭，不能催交", status_code=403)
    if pub.stopped:
        raise AppError("PAPER_STOPPED", "本空间已停止作答，不能催交", status_code=403)
    last = (
        db.query(PaperUrge)
        .filter(PaperUrge.paper_id == paper.id, PaperUrge.space_id == space.id)
        .order_by(PaperUrge.created_at.desc())
        .first()
    )
    now = utcnow()
    if last is not None and now - _aware(last.created_at) < URGE_COOLDOWN:
        remaining = URGE_COOLDOWN - (now - _aware(last.created_at))
        hours = int(remaining.total_seconds() // 3600) + 1
        raise AppError(
            "URGE_COOLDOWN",
            f"已催交过，请等待约 {hours} 小时后再次催交",
            status_code=409,
        )
    db.add(PaperUrge(id=new_id("urge"), paper_id=paper.id, space_id=space.id, teacher_id=teacher.id))
    db.commit()
    return {"ok": True}


def urge_feed(db: Session, student: User) -> dict:
    """学生的催交通知列表（最早在前）与未读角标数。"""
    rows = (
        db.query(PaperUrge, Paper, StudySpace, User)
        .join(Paper, Paper.id == PaperUrge.paper_id)
        .join(StudySpace, StudySpace.id == PaperUrge.space_id)
        .join(User, User.id == PaperUrge.teacher_id)
        .join(
            SpaceMember,
            (SpaceMember.space_id == PaperUrge.space_id)
            & (SpaceMember.user_id == student.id)
            & (SpaceMember.status == "active"),
        )
        .filter(StudySpace.status == "active", Paper.status == "published", Paper.deleted.is_(False))
        .order_by(PaperUrge.created_at.asc())
        .all()
    )
    state = db.get(UrgeReadState, student.id)
    cleared = _aware(state.cleared_at) if state and state.cleared_at else None
    read_ids = _read_ids(state)
    items = []
    unread = 0
    for urge, paper, space, teacher in rows:
        created = _aware(urge.created_at)
        if (cleared is None or created > cleared) and urge.id not in read_ids:
            unread += 1
        items.append(
            {
                "id": urge.id,
                "paper_id": paper.id,
                "paper_name": paper.name,
                "space_id": space.id,
                "space_name": space.name,
                "teacher_name": teacher.display_name,
                "created_at": created,
                "exam_end": _aware(paper.exam_end) if paper.exam_end is not None else None,
            }
        )
    return {"unread_count": unread, "items": items}


def _read_ids(state: UrgeReadState | None) -> set[str]:
    if state is None or not state.read_ids:
        return set()
    try:
        return set(json.loads(state.read_ids))
    except (ValueError, TypeError):
        return set()


def mark_urge_read(db: Session, student: User, urge_id: str) -> None:
    """单条催交标记已读：从角标中消除该条。"""
    state = db.get(UrgeReadState, student.id)
    if state is None:
        # cleared_at 用纪元起点，保证不把历史催交整体判为已读，仅 read_ids 生效
        state = UrgeReadState(user_id=student.id, cleared_at=datetime(1970, 1, 1, tzinfo=timezone.utc))
        db.add(state)
    ids = _read_ids(state)
    ids.add(urge_id)
    state.read_ids = json.dumps(sorted(ids))
    db.commit()


def remove_urge(db: Session, user: User, urge_id: str) -> None:
    """删除单条催交记录：创建教师或该空间在读学生可删。"""
    urge = db.get(PaperUrge, urge_id)
    if urge is None:
        raise AppError("NOT_FOUND", "通知不存在或已被删除", status_code=404)
    allowed = urge.teacher_id == user.id
    if not allowed and user.role == "student":
        allowed = (
            db.query(SpaceMember.id)
            .filter(
                SpaceMember.space_id == urge.space_id,
                SpaceMember.user_id == user.id,
                SpaceMember.status == "active",
            )
            .first()
            is not None
        )
    if not allowed:
        raise AppError("FORBIDDEN", "无权删除该通知", status_code=403)
    db.delete(urge)
    db.commit()


def clear_urge_badge(db: Session, student: User) -> None:
    """清除催交红点：之后的催交才计入角标。"""
    state = db.get(UrgeReadState, student.id)
    if state is None:
        state = UrgeReadState(user_id=student.id)
        db.add(state)
    state.cleared_at = utcnow()
    state.read_ids = None
    db.commit()


def statistics(db: Session, paper: Paper, space_id: str) -> dict:
    space = db.get(StudySpace, space_id)
    if space is None or space.status != "active":
        raise AppError("SPACE_NOT_FOUND", "学习空间不存在或已解散", status_code=404)
    get_publication(db, paper.id, space_id)

    attempts = (
        db.query(PaperAttempt)
        .filter(
            PaperAttempt.paper_id == paper.id,
            PaperAttempt.space_id == space_id,
            PaperAttempt.status == "submitted",
        )
        .all()
    )
    submitted_students = {a.student_id for a in attempts}
    student_count = (
        db.query(func.count(SpaceMember.id))
        .filter(
            SpaceMember.space_id == space_id,
            SpaceMember.status == "active",
            SpaceMember.role == "member",
        )
        .scalar()
        or 0
    )

    questions = (
        db.query(PaperQuestion)
        .filter(PaperQuestion.paper_id == paper.id)
        .order_by(PaperQuestion.order_no)
        .all()
    )
    attempt_ids = [a.id for a in attempts]
    answer_rows = (
        db.query(AttemptAnswer)
        .filter(AttemptAnswer.attempt_id.in_(attempt_ids))
        .all()
        if attempt_ids
        else []
    )
    answers_by_pq: dict[str, list[AttemptAnswer]] = {}
    for a in answer_rows:
        answers_by_pq.setdefault(a.paper_question_id, []).append(a)

    result_questions = []
    for pq in questions:
        rows = answers_by_pq.get(pq.id, [])
        total = sum(
            1 for attempt in attempts
            if not attempt.question_ids_json or pq.id in json.loads(attempt.question_ids_json)
        )
        if pq.removed and total == 0:
            continue
        average = round(sum(r.score for r in rows) / total, 2) if total else 0.0
        correct = sum(1 for r in rows if r.is_correct)
        item = {
            "paper_question_id": pq.id,
            "no": pq.order_no,
            "type": pq.type,
            "average_score": average,
            "correct_rate": round(correct / total, 2) if total else 0.0,
        }
        if pq.type in ("single", "multiple", "judge"):
            labels = [o["label"] for o in (json.loads(pq.options_json) if pq.options_json else [])]
            counts = {label: 0 for label in labels}
            for r in rows:
                picked = json.loads(r.choices_json) if r.choices_json else []
                for label in picked:
                    if label in counts:
                        counts[label] += 1
            item["option_counts"] = [{"label": label, "count": counts[label]} for label in labels]
        result_questions.append(item)

    return {
        "paper_id": paper.id,
        "space_id": space_id,
        "student_count": student_count,
        "submitted_count": len(submitted_students),
        "questions": result_questions,
    }
