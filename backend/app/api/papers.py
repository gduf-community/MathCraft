"""组卷、发布、停止恢复、删除、统计接口（v2 5.10 / 5.12）。"""
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user, require_paper_owner
from app.errors import AppError
from app.models import Paper, PaperPublication, SpaceMember, StudySpace, User
from app.schemas.auth import ErrorResponse
from app.schemas.paper import (
    PaperBatchDeleteBody,
    PaperCreateBody,
    PaperPublishBody,
    PaperRead,
    PaperQuestionRemoveBody,
    PaperUpdateBody,
)
from app.services import papers

router = APIRouter(prefix="/api/papers", tags=["papers"])


def _paper_visible(db: Session, user: User, paper: Paper) -> bool:
    if paper.owner_id == user.id:
        return True
    if user.role != "student" or paper.status != "published":
        return False
    exists = (
        db.query(PaperPublication.id)
        .join(StudySpace, StudySpace.id == PaperPublication.space_id)
        .join(
            SpaceMember,
            (SpaceMember.space_id == PaperPublication.space_id)
            & (SpaceMember.user_id == user.id)
            & (SpaceMember.status == "active"),
        )
        .filter(
            PaperPublication.paper_id == paper.id,
            StudySpace.status == "active",
        )
        .first()
    )
    return exists is not None


@router.get("", response_model=list[PaperRead], response_model_exclude_unset=True)
def list_papers(
    include_drafts: bool = True,
    saved: bool = False,
    space_id: str = "",
    include_history: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return papers.list_papers(
        db,
        user,
        include_drafts=include_drafts,
        saved_only=saved,
        space_id=space_id or None,
        include_history=include_history,
    )


@router.post("", status_code=201, response_model=PaperRead, response_model_exclude_unset=True)
def create_paper(
    body: PaperCreateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    paper = papers.create_paper(db, user, body)
    return papers.paper_payload(db, paper, user)


@router.post("/batch-delete", status_code=204)
def batch_delete(
    body: PaperBatchDeleteBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.query(Paper).filter(Paper.id.in_(body.paper_ids), Paper.owner_id == user.id).all()
    for p in sorted(rows, key=lambda row: row.id):
        papers.delete_paper(db, p, commit=False)
        db.flush()
    db.commit()
    return None


@router.get("/{paper_id}", response_model=PaperRead, response_model_exclude_unset=True)
def get_paper(
    paper_id: str,
    history: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    paper = db.get(Paper, paper_id)
    if paper is None or (paper.deleted and not history):
        raise AppError("PAPER_NOT_FOUND", "试卷不存在或已被删除", status_code=404)
    if history and paper.owner_id != user.id:
        raise AppError("FORBIDDEN", "只有试卷创建者可以读取整卷历史快照", 403)
    if not _paper_visible(db, user, paper):
        raise AppError("PAPER_NOT_FOUND", "试卷不存在或你无权查看", status_code=404)
    return papers.paper_payload(db, paper, user, include_history=history)


@router.put("/{paper_id}", response_model=PaperRead, response_model_exclude_unset=True, responses={
    409: {"model": ErrorResponse, "description": "PAPER_HAS_ATTEMPTS / PAPER_PUBLICATION_OPEN；目标空间有作答时保留发布历史，无作答也须先停止才能移除发布"},
})
def update_paper(
    body: PaperUpdateBody,
    paper: Paper = Depends(require_paper_owner),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updated = papers.update_paper(db, paper, user, body)
    return papers.paper_payload(db, updated, user)


@router.delete("/{paper_id}", status_code=204, responses={
    409: {"model": ErrorResponse, "description": "PAPER_NOT_CLOSED / PAPER_PUBLICATION_OPEN / GRADING_BUSY；未满足删除条件"},
})
def delete_paper(
    mode: Literal["record", "paper"] = "record",
    paper: Paper = Depends(require_paper_owner),
    db: Session = Depends(get_db),
):
    """移除记录；整卷删除要求 closed 且所有空间 stopped，保留历史作答。"""
    papers.delete_paper(db, paper, mode)
    return None


@router.post("/{paper_id}/close", response_model=PaperRead, response_model_exclude_unset=True)
def close_paper(
    paper: Paper = Depends(require_paper_owner),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """关闭整卷，禁止开始作答与交卷；不更改各空间的停止状态。"""
    return papers.paper_payload(db, papers.set_closed(db, paper, True), user)


@router.post("/{paper_id}/reopen", response_model=PaperRead, response_model_exclude_unset=True)
def reopen_paper(
    paper: Paper = Depends(require_paper_owner),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """恢复未删除试卷；各空间仍遵循自身 stopped 与时间窗。"""
    return papers.paper_payload(db, papers.set_closed(db, paper, False), user)


@router.post("/{paper_id}/questions/remove", response_model=PaperRead, response_model_exclude_unset=True)
def remove_questions(
    body: PaperQuestionRemoveBody,
    paper: Paper = Depends(require_paper_owner),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updated = papers.remove_paper_questions(db, paper, body.paper_question_ids)
    return papers.paper_payload(db, updated, user)


@router.post("/{paper_id}/publish", response_model=PaperRead, response_model_exclude_unset=True)
def publish_paper(
    body: PaperPublishBody,
    paper: Paper = Depends(require_paper_owner),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    updated = papers.publish_paper(db, paper, user, body)
    return papers.paper_payload(db, updated, user)


def _publication_for_creator(
    db: Session,
    user: User,
    paper_id: str,
    space_id: str,
) -> tuple[PaperPublication, StudySpace]:
    space = db.get(StudySpace, space_id)
    if space is None or space.status != "active":
        raise AppError("SPACE_NOT_FOUND", "学习空间不存在或已解散", status_code=404)
    if space.creator_id != user.id:
        raise AppError("FORBIDDEN", "只有空间创建者可以操作", status_code=403)
    pub = papers.get_publication(db, paper_id, space_id)
    return pub, space


@router.post("/{paper_id}/publications/{space_id}/stop", status_code=204)
def stop_publication(
    paper_id: str,
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pub, _space = _publication_for_creator(db, user, paper_id, space_id)
    papers.set_publication_stopped(db, pub, True)
    return None


@router.post("/{paper_id}/publications/{space_id}/resume", status_code=204)
def resume_publication(
    paper_id: str,
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    pub, _space = _publication_for_creator(db, user, paper_id, space_id)
    papers.set_publication_stopped(db, pub, False)
    return None


@router.delete("/{paper_id}/publications/{space_id}", status_code=204, responses={
    409: {"model": ErrorResponse, "description": "PAPER_HAS_ATTEMPTS / PAPER_PUBLICATION_OPEN；目标空间有作答时保留发布历史，无作答也须先停止才能移除发布"},
})
def remove_publication(
    paper_id: str,
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """该空间无该试卷的作答且已停止时才移除发布，其他空间作答不阻止移除。"""
    pub, _space = _publication_for_creator(db, user, paper_id, space_id)
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise AppError("PAPER_NOT_FOUND", "试卷不存在或已被删除", status_code=404)
    papers.remove_publication(db, paper, pub)
    return None


@router.post("/{paper_id}/publications/{space_id}/urge", status_code=201, responses={
    403: {"model": ErrorResponse, "description": "PAPER_CLOSED / PAPER_STOPPED / FORBIDDEN；关闭或停止后不可催交"},
    404: {"model": ErrorResponse, "description": "PAPER_NOT_FOUND / PAPER_NOT_PUBLISHED / SPACE_NOT_FOUND"},
    409: {"model": ErrorResponse, "description": "URGE_COOLDOWN；同一发布 24 小时内只能催交一次"},
})
def urge_paper(
    paper_id: str,
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """催交：仅空间创建者可催；删除、关闭或该空间停止后禁止，24 小时内一次。"""
    _pub, space = _publication_for_creator(db, user, paper_id, space_id)
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise AppError("PAPER_NOT_FOUND", "试卷不存在或已被删除", status_code=404)
    return papers.urge_paper(db, paper, space, user)


@router.get("/{paper_id}/statistics")
def get_statistics(
    paper_id: str,
    space_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    paper = db.get(Paper, paper_id)
    if paper is None:
        raise AppError("PAPER_NOT_FOUND", "试卷不存在或已被删除", status_code=404)
    space = db.get(StudySpace, space_id)
    if space is None or space.status != "active":
        raise AppError("SPACE_NOT_FOUND", "学习空间不存在或已解散", status_code=404)
    if user.role != "teacher" or (paper.owner_id != user.id and space.creator_id != user.id):
        raise AppError("FORBIDDEN", "只有试卷创建者或空间创建者可以查看统计", status_code=403)
    return papers.statistics(db, paper, space_id)
