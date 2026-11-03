"""收藏接口：分组 CRUD + 收藏增删换组（v2 5.8）。default 分组固定不可删改。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import get_current_user
from app.errors import AppError
from app.models import Document, Favorite, FavoriteGroup, Question, User
from app.models.base import new_id
from app.schemas.api import FavoriteAddBody, FavoriteGroupBody, FavoriteMoveBody
from app.services.generation import question_to_api

router = APIRouter(prefix="/api", tags=["favorites"])


def _my_group(db: Session, user_id: str, group_id: str) -> FavoriteGroup:
    g = db.query(FavoriteGroup).filter(
        FavoriteGroup.id == group_id, FavoriteGroup.user_id == user_id
    ).one_or_none()
    if g is None:
        # "default" 为固定默认分组的别名，实际 id 按用户唯一
        if group_id == "default":
            return ensure_default_group(db, user_id)
        raise AppError("GROUP_NOT_FOUND", "收藏分组不存在", status_code=404)
    return g


def ensure_default_group(db: Session, user_id: str) -> FavoriteGroup:
    g = db.query(FavoriteGroup).filter(FavoriteGroup.user_id == user_id, FavoriteGroup.is_default.is_(True)).first()
    if g is None:
        g = FavoriteGroup(id=f"default_{user_id}", user_id=user_id, name="默认", is_default=True)
        db.add(g)
        db.commit()
        db.refresh(g)
    return g


@router.get("/favorite-groups")
def list_groups(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from sqlalchemy import func

    ensure_default_group(db, user.id)
    groups = (
        db.query(FavoriteGroup)
        .filter(FavoriteGroup.user_id == user.id)
        .order_by(FavoriteGroup.created_at)
        .all()
    )
    count_rows = (
        db.query(Favorite.group_id, func.count(Favorite.id))
        .filter(Favorite.user_id == user.id)
        .group_by(Favorite.group_id)
        .all()
    )
    count_map = dict(count_rows)
    return [
        {"id": g.id, "name": g.name, "is_default": bool(g.is_default), "count": count_map.get(g.id, 0)}
        for g in groups
    ]


@router.post("/favorite-groups", status_code=201)
def create_group(
    body: FavoriteGroupBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    exists = db.query(FavoriteGroup).filter(
        FavoriteGroup.user_id == user.id, FavoriteGroup.name == body.name.strip()
    ).first()
    if exists:
        raise AppError("GROUP_EXISTS", "已存在同名收藏分组", status_code=409)
    g = FavoriteGroup(id=new_id("fg"), user_id=user.id, name=body.name.strip())
    db.add(g)
    db.commit()
    db.refresh(g)
    return {"id": g.id, "name": g.name, "is_default": False, "count": 0}


@router.put("/favorite-groups/{group_id}")
def rename_group(
    group_id: str,
    body: FavoriteGroupBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    g = _my_group(db, user.id, group_id)
    if g.is_default:
        raise AppError("FORBIDDEN", "默认分组不可重命名", status_code=403)
    name = body.name.strip()
    dup = db.query(FavoriteGroup).filter(
        FavoriteGroup.user_id == user.id, FavoriteGroup.name == name, FavoriteGroup.id != g.id
    ).first()
    if dup:
        raise AppError("GROUP_EXISTS", "已存在同名收藏分组", status_code=409)
    g.name = name
    db.commit()
    return {"id": g.id, "name": g.name, "is_default": False}


@router.delete("/favorite-groups/{group_id}", status_code=204)
def delete_group(
    group_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    g = _my_group(db, user.id, group_id)
    if g.is_default:
        raise AppError("FORBIDDEN", "默认分组不可删除", status_code=403)
    default = ensure_default_group(db, user.id)
    # 组内收藏移入 default
    db.query(Favorite).filter(Favorite.group_id == g.id).update({"group_id": default.id})
    db.delete(g)
    db.commit()
    return None


@router.get("/favorites")
def list_favorites(
    group_id: str = "",
    type: str = "",
    difficulty: str = "",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = (
        db.query(Favorite, Question)
        .join(Question, Question.id == Favorite.question_id)
        .filter(Favorite.user_id == user.id)
    )
    if group_id:
        q = q.filter(Favorite.group_id == group_id)
    if type:
        q = q.filter(Question.type == type)
    if difficulty:
        q = q.filter(Question.difficulty == difficulty)
    rows = q.order_by(Favorite.created_at.desc()).all()
    doc_ids = {row.document_id for _fav, row in rows}
    doc_names = (
        dict(db.query(Document.id, Document.name).filter(Document.id.in_(doc_ids)).all())
        if doc_ids
        else {}
    )
    return [
        question_to_api(
            row,
            starred=True,
            favorite_group_id=fav.group_id,
            doc_name=doc_names.get(row.document_id, ""),
        )
        for fav, row in rows
    ]


@router.post("/favorites", status_code=201)
def add_favorite(
    body: FavoriteAddBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.get(Question, body.question_id)
    if q is None:
        raise AppError("QUESTION_NOT_FOUND", "题目不存在或已被删除", status_code=404)
    if q.created_by != user.id:
        raise AppError("FORBIDDEN", "只能收藏自己生成的题目", status_code=403)
    group = _my_group(db, user.id, body.group_id)
    exists = db.query(Favorite).filter(
        Favorite.user_id == user.id, Favorite.question_id == body.question_id
    ).first()
    if exists:
        exists.group_id = group.id
        db.commit()
        return {"favorite_id": exists.id, "moved": True}
    fav = Favorite(id=new_id("fav"), user_id=user.id, question_id=body.question_id, group_id=group.id)
    db.add(fav)
    db.commit()
    return {"favorite_id": fav.id, "moved": False}


@router.put("/favorites/{question_id}", status_code=204)
def move_favorite(
    question_id: str,
    body: FavoriteMoveBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fav = db.query(Favorite).filter(
        Favorite.user_id == user.id, Favorite.question_id == question_id
    ).one_or_none()
    if fav is None:
        raise AppError("FAVORITE_NOT_FOUND", "尚未收藏该题目", status_code=404)
    group = _my_group(db, user.id, body.group_id)
    fav.group_id = group.id
    db.commit()
    return None


@router.delete("/favorites/{question_id}", status_code=204)
def remove_favorite(
    question_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    fav = db.query(Favorite).filter(
        Favorite.user_id == user.id, Favorite.question_id == question_id
    ).one_or_none()
    if fav is None:
        raise AppError("FAVORITE_NOT_FOUND", "尚未收藏该题目", status_code=404)
    db.delete(fav)
    db.commit()
    return None
