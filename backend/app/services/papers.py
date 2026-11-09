"""组卷业务：题目快照、发布、停止恢复、删除、统计、催交。"""
import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import func
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


def publications(db: Session, paper_id: str) -> list[tuple[PaperPublication, StudySpace]]:
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


def _latest_attempt(db: Session, paper_id: str, student_id: str, space_id: str | None = None) -> PaperAttempt | None:
    q = db.query(PaperAttempt).filter(
        PaperAttempt.paper_id == paper_id,
        PaperAttempt.student_id == student_id,
    )
    if space_id:
        q = q.filter(PaperAttempt.space_id == space_id)
    return q.order_by(PaperAttempt.started_at.desc()).first()


def paper_payload(
    db: Session,
    paper: Paper,
    viewer: User,
    include_questions: bool = True,
    space_id: str | None = None,
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
    latest = _latest_attempt(db, paper.id, viewer.id, space_id) if viewer.role == "student" else None
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
        "saved_to_records": bool(paper.saved_to_records),
        "allow_review": bool(paper.allow_review),
        "allow_retake": bool(paper.allow_retake),
        "exam_window": (
            {"start": _aware(paper.exam_start), "end": _aware(paper.exam_end)}
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
        # 他人试卷仅在交卷且允许复盘时下发答案，个人练习拥有者保留查看权限
        include_answer = viewer.id == paper.owner_id or (submitted and bool(paper.allow_review))
        data["questions"] = [paper_question_payload(r, include_answer) for r in rows]
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


def _sync_publications(db: Session, paper: Paper, user: User, space_ids: list[str]) -> None:
    desired = {s.id: s for s in validate_space_ids(db, user, space_ids)}
    existing = {pub.space_id: pub for pub, _s in publications(db, paper.id)}
    # 删除不在目标里的发布记录；有作答时禁止
    for sid, pub in existing.items():
        if sid not in desired:
            if db.query(PaperAttempt).filter(PaperAttempt.paper_id == paper.id, PaperAttempt.space_id == sid).first():
                raise AppError("FORBIDDEN", "该空间已有学生作答，不能移除发布", status_code=409)
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
            if db.query(PaperAttempt).filter(PaperAttempt.paper_id == paper.id).first():
                raise AppError("FORBIDDEN", "已有学生作答，不能取消发布", status_code=409)
            for pub, _s in publications(db, paper.id):
                db.delete(pub)
            paper.status = "draft"

    db.commit()
    db.refresh(paper)
    return paper


def publish_paper(db: Session, paper: Paper, user: User, body) -> Paper:
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
    pub.stopped = stopped
    pub.stopped_at = utcnow() if stopped else None
    db.commit()


def remove_publication(db: Session, paper: Paper, pub: PaperPublication) -> None:
    if not pub.stopped:
        raise AppError("FORBIDDEN", "请先停止作答，才能从空间删除", status_code=403)
    db.delete(pub)
    db.flush()
    if not db.query(PaperPublication).filter(PaperPublication.paper_id == paper.id).first():
        paper.status = "draft"
    db.commit()


def remove_paper_questions(db: Session, paper: Paper, paper_question_ids: list[str]) -> Paper:
    if db.query(PaperAttempt).filter(PaperAttempt.paper_id == paper.id).first():
        raise AppError("FORBIDDEN", "已有学生作答，不能删除题目", status_code=409)
    rows = (
        db.query(PaperQuestion)
        .filter(PaperQuestion.paper_id == paper.id, PaperQuestion.id.in_(paper_question_ids))
        .all()
    )
    if not rows:
        raise AppError("NOT_FOUND", "题目不在该试卷中", status_code=404)
    for r in rows:
        db.delete(r)
    db.flush()
    remaining = (
        db.query(PaperQuestion)
        .filter(PaperQuestion.paper_id == paper.id)
        .order_by(PaperQuestion.order_no)
        .all()
    )
    for i, r in enumerate(remaining, 1):
        r.order_no = i
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
) -> list[dict]:
    """组卷记录严格按账号隔离：只返回当前用户自己创建的试卷。

    学生作答老师发布的试卷通过学习空间（space_papers）与作答接口进入，
    不混入学生的组卷记录列表。
    """
    papers = {p.id: p for p in db.query(Paper).filter(Paper.owner_id == user.id).all()}

    out = []
    for p in sorted(papers.values(), key=lambda x: x.created_at, reverse=True):
        if not include_drafts and p.status != "published":
            continue
        if saved_only and not p.saved_to_records:
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
        latest = _latest_attempt(db, paper.id, viewer.id, space.id) if viewer.role == "student" else None
        out.append(
            {
                "id": paper.id,
                "name": paper.name,
                "created_at": paper.created_at,
                "question_count": paper.question_count,
                "total_score": paper.total_score,
                "status": paper.status,
                "allow_review": bool(paper.allow_review),
                "allow_retake": bool(paper.allow_retake),
                "exam_window": (
                    {"start": _aware(paper.exam_start), "end": _aware(paper.exam_end)}
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
    """催交：同一（试卷, 空间）24 小时内只允许一次。"""
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
        .filter(StudySpace.status == "active", Paper.status == "published")
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
                "exam_end": _aware(paper.exam_end),
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
        total = len(attempts)
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
