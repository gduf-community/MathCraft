"""数据管理：自然语言 → 结构化查询 DSL → 参数化 ORM 查询。

读操作直接执行；删除/修改先生成影响预览存 Redis，前端确认后才执行。
不做裸 SQL，全部走字段白名单映射，杜绝注入面。
"""
import json
import re

from sqlalchemy.orm import Session

import app.services.cache as cache
from app.errors import AppError
from app.models import (
    Favorite,
    FavoriteGroup,
    Paper,
    PaperAttempt,
    Question,
    SpaceMember,
    StudySpace,
    User,
)
from app.models.base import new_id
from app.services.rag.llm import chat_json
from app.services.rag.prompts import DATA_SYSTEM

CONFIRM_TTL_SECONDS = 300
ENTITY_LABELS = {"favorites": "题目收藏", "questions": "我出的题", "papers": "我的试卷",
                 "spaces": "学习空间", "attempts": "学生做题记录"}
TYPE_LABELS = {"single": "单选", "multiple": "多选", "judge": "判断",
               "blank": "填空", "compute": "计算", "essay": "简答"}


def _confirm_key(confirm_id: str) -> str:
    return f"chat:confirm:{confirm_id}"


def _stem_summary(stem: str, limit: int = 40) -> str:
    """题干摘要：完整公式替换为占位符，避免截断撕裂 LaTeX 定界符导致渲染错乱。"""
    text = re.sub(r"\$\$[\s\S]+?\$\$", "〔公式〕", stem)
    text = re.sub(r"\$[^$\n]+?\$", "〔公式〕", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _match(value, op: str, expected) -> bool:
    """内存过滤：个人账号数据量小，取行后过滤，天然防注入。"""
    if value is None:
        return False
    if op == "eq":
        return str(value).lower() == str(expected).lower()
    if op == "like":
        return str(expected).lower() in str(value).lower()
    try:
        a, b = float(value), float(expected)
    except (TypeError, ValueError):
        return False
    return {"gt": a > b, "lt": a < b, "ge": a >= b, "le": a <= b}.get(op, False)


def _collect_rows(db: Session, user: User, entity: str, dsl: dict) -> list[dict]:
    """按实体取行（owner 过滤），行结构 {sort, raw, cells}；raw 供 DSL 过滤，cells 供展示。"""
    filters = dsl.get("filters") if isinstance(dsl.get("filters"), list) else []
    limit = min(max(int(dsl.get("limit") or 50), 1), 200)
    rows: list[dict] = []
    field_map: dict[str, str] = {}

    if entity == "favorites":
        q = (db.query(Favorite, Question, FavoriteGroup)
             .join(Question, Favorite.question_id == Question.id)
             .join(FavoriteGroup, Favorite.group_id == FavoriteGroup.id)
             .filter(Favorite.user_id == user.id)
             .order_by(Favorite.created_at.desc()).limit(400))
        for fav, question, group in q:
            rows.append({
                "sort": question.difficulty_score,
                "raw": {"type": question.type, "difficulty": question.difficulty,
                        "knowledge_point": question.knowledge_point or "", "group": group.name},
                "cells": {"题目": _stem_summary(question.stem), "题型": TYPE_LABELS.get(question.type, question.type),
                          "难度": question.difficulty, "知识点": question.knowledge_point or "—",
                          "分组": group.name},
            })
        field_map = {"type": "type", "difficulty": "difficulty",
                     "knowledge_point": "knowledge_point", "group": "group"}
    elif entity == "questions":
        q = (db.query(Question).filter(Question.created_by == user.id)
             .order_by(Question.created_at.desc()).limit(400))
        for question in q:
            rows.append({
                "sort": question.difficulty_score,
                "raw": {"type": question.type, "difficulty": question.difficulty,
                        "knowledge_point": question.knowledge_point or ""},
                "cells": {"题目": _stem_summary(question.stem), "题型": TYPE_LABELS.get(question.type, question.type),
                          "难度": question.difficulty, "难度分": round(question.difficulty_score, 2),
                          "知识点": question.knowledge_point or "—"},
            })
        field_map = {"type": "type", "difficulty": "difficulty", "knowledge_point": "knowledge_point"}
    elif entity == "papers":
        q = (db.query(Paper).filter(Paper.owner_id == user.id)
             .order_by(Paper.created_at.desc()).limit(200))
        for paper in q:
            rows.append({
                "sort": paper.created_at,
                "raw": {"name": paper.name, "status": paper.status},
                "cells": {"试卷": paper.name, "状态": "已发布" if paper.status == "published" else "草稿",
                          "题数": paper.question_count, "总分": paper.total_score},
            })
        field_map = {"name": "name", "status": "status"}
    elif entity == "spaces":
        if user.role == "teacher":
            spaces = db.query(StudySpace).filter(StudySpace.creator_id == user.id).limit(100).all()
        else:
            ids = [m.space_id for m in db.query(SpaceMember)
                   .filter(SpaceMember.user_id == user.id).limit(100).all()]
            spaces = db.query(StudySpace).filter(StudySpace.id.in_(ids or ["-"])).limit(100).all()
        for space in spaces:
            rows.append({
                "sort": space.created_at,
                "raw": {"name": space.name},
                "cells": {"空间": space.name, "容量": space.capacity,
                          "状态": "正常" if space.status == "active" else space.status},
            })
        field_map = {"name": "name"}
    elif entity == "attempts":
        if user.role != "teacher":
            raise AppError("DATA_PERMISSION", "学生做题情况只有教师账号可以查看", status_code=403)
        q = (db.query(PaperAttempt, Paper, User)
             .join(Paper, PaperAttempt.paper_id == Paper.id)
             .join(User, PaperAttempt.student_id == User.id)
             .join(StudySpace, PaperAttempt.space_id == StudySpace.id)
             .filter(StudySpace.creator_id == user.id)
             .order_by(PaperAttempt.started_at.desc()).limit(400))
        for attempt, paper, student in q:
            rows.append({
                "sort": attempt.score if attempt.score is not None else -1,
                "raw": {"paper": paper.name, "student": student.display_name,
                        "status": attempt.status, "score": attempt.score},
                "cells": {"学生": student.display_name, "试卷": paper.name,
                          "状态": "已交卷" if attempt.status == "submitted" else "作答中",
                          "得分": attempt.score if attempt.score is not None else "—",
                          "总分": attempt.total_score},
            })
        field_map = {"paper": "paper", "student": "student", "status": "status", "score": "score"}
    else:
        raise AppError("DATA_ENTITY", "暂不支持查询这类数据", status_code=400)

    for f in filters:
        raw_key = field_map.get(str(f.get("field")))
        if not raw_key:
            continue
        op = str(f.get("op") or "eq")
        rows = [r for r in rows if _match(r["raw"].get(raw_key), op, f.get("value"))]

    order_by = str(dsl.get("order_by") or "none")
    if order_by.startswith("-"):
        key = order_by[1:]
        rows.sort(key=lambda r: _num_or_str(r["raw"].get(field_map.get(key, ""))), reverse=True)
    elif order_by != "none":
        key = field_map.get(order_by, "")
        rows.sort(key=lambda r: _num_or_str(r["raw"].get(key)))
    return rows[:limit]


def _num_or_str(value):
    return value if isinstance(value, (int, float)) else str(value or "")


def _aggregate(rows: list[dict], aggregate: str) -> str:
    if aggregate == "count":
        return f"共 {len(rows)} 条记录。"
    if aggregate.startswith(("avg:", "max:", "min:")):
        field = aggregate.split(":", 1)[1]
        meta = {"score": "得分", "difficulty_score": "难度分"}.get(field, field)
        numbers = [float(r["sort"]) for r in rows
                   if isinstance(r["sort"], (int, float)) and r["sort"] >= 0]
        if not numbers:
            return f"没有可用于{meta}聚合的数值。"
        if aggregate.startswith("avg:"):
            return f"共 {len(numbers)} 条，{meta}平均 {sum(numbers) / len(numbers):.2f}。"
        extreme = max(numbers) if aggregate.startswith("max:") else min(numbers)
        best = next((r for r in rows if isinstance(r["sort"], (int, float))
                     and abs(float(r["sort"]) - extreme) < 1e-9), None)
        detail = "；".join(f"{k}：{v}" for k, v in best["cells"].items()) if best else ""
        return f"{meta}最{'高' if aggregate.startswith('max:') else '低'}为 {extreme}。明细：{detail}"
    return ""


def _preview(db: Session, user: User, entity: str, dsl: dict) -> tuple[int, list[str]]:
    rows = _collect_rows(db, user, entity, {**dsl, "action": "select", "aggregate": "none"})
    return len(rows), ["；".join(f"{k}：{v}" for k, v in r["cells"].items()) for r in rows[:5]]


def run_data_request(db: Session, user: User, message: str, api_key: str | None) -> dict:
    """数据管理入口：LLM 转 DSL 后执行或生成确认预览。返回 chat 响应片段。"""
    try:
        dsl = chat_json(
            [
                {"role": "system", "content": DATA_SYSTEM},
                {"role": "user", "content": message},
            ],
            api_key=api_key,
            thinking_off=True,
        )
    except Exception as exc:  # noqa: BLE001
        from app.services.rag.llm import LLMError, friendly_error

        return {"reply": friendly_error(exc) if isinstance(exc, LLMError) else "数据查询服务暂时不可用，请稍后再试。",
                "questions": [], "done": True}
    if not isinstance(dsl, dict):
        return {"reply": "我没理解你要查哪类数据。目前支持：题目收藏、我出的题、我的试卷、学习空间、空间内学生做题情况（教师）。",
                "questions": [], "done": True}

    # 一次询问多类数据：逐实体执行，合并回复
    multi = dsl.get("entities") if isinstance(dsl.get("entities"), list) else None
    if multi:
        parts = []
        for sub in multi[:3]:
            if not isinstance(sub, dict) or sub.get("entity") in (None, "", "unknown"):
                continue
            sub_entity = str(sub["entity"])
            label = ENTITY_LABELS.get(sub_entity, sub_entity)
            try:
                rows = _collect_rows(db, user, sub_entity, {**sub, "action": "select", "aggregate": "none"})
            except AppError as exc:
                parts.append(f"{label}：{exc.message}")
                continue
            agg = _aggregate(rows, str(sub.get("aggregate") or "count"))
            parts.append(f"{label}：{agg or f'共 {len(rows)} 条记录。'}")
        if not parts:
            return {"reply": "这几类数据我暂时没能对应上，请换个说法再问一次。", "questions": [], "done": True}
        return {"reply": "一次回答你问的几项数据：\n" + "\n".join(parts), "questions": [], "done": True}

    if dsl.get("entity") in (None, "", "unknown"):
        return {"reply": "我没理解你要查哪类数据。目前支持：题目收藏、我出的题、我的试卷、学习空间、空间内学生做题情况（教师）。",
                "questions": [], "done": True}

    entity = str(dsl.get("entity"))
    action = str(dsl.get("action") or "select")
    explanation = str(dsl.get("explanation") or "")

    if action == "select":
        rows = _collect_rows(db, user, entity, dsl)
        head = _aggregate(rows, str(dsl.get("aggregate") or "none"))
        detail = "\n".join(f"{i}. " + "；".join(f"{k}：{v}" for k, v in r["cells"].items())
                           for i, r in enumerate(rows[:10], 1))
        more = f"\n…还有 {len(rows) - 10} 条未展示。" if len(rows) > 10 else ""
        parts = [head or f"共 {len(rows)} 条记录。"]
        if rows:
            parts.append(detail + more)
        if explanation:
            parts.append(f"（{explanation}）")
        return {"reply": "\n".join(parts), "questions": [], "done": True}

    if action == "delete" and entity not in ("favorites", "papers"):
        return {"reply": "目前只支持删除收藏和试卷，其他数据不提供删除。", "questions": [], "done": True}
    if action == "update" and entity != "papers":
        return {"reply": "目前只支持修改试卷名称，其他数据不提供修改。", "questions": [], "done": True}
    if action == "update" and not dsl.get("set_name"):
        return {"reply": "请告诉我试卷要改成什么名字。", "questions": [], "done": True}

    affected, samples = _preview(db, user, entity, dsl)
    if affected == 0:
        return {"reply": "没有找到符合条件的数据，无需执行该操作。", "questions": [], "done": True}

    confirm_id = new_id("cfm")
    payload = {"confirm_id": confirm_id, "action": action, "entity": entity,
               "dsl": dsl, "user_id": user.id}
    cache.get_redis().set(_confirm_key(confirm_id),
                          json.dumps(payload, ensure_ascii=False), ex=CONFIRM_TTL_SECONDS)
    verb = "删除" if action == "delete" else "改名"
    preview_text = (f"该操作将{verb} {affected} 条{ENTITY_LABELS.get(entity, entity)}记录，影响范围如下：\n"
                    + "\n".join(f"{i}. {s}" for i, s in enumerate(samples, 1))
                    + (f"\n（{explanation}）" if explanation else ""))
    return {"reply": preview_text, "questions": [], "done": False,
            "confirm": {"id": confirm_id, "action": action, "entity": entity,
                        "entity_label": ENTITY_LABELS.get(entity, entity), "affected": affected,
                        "samples": samples, "explanation": explanation}}


def execute_confirmed(db: Session, user: User, confirm_id: str, accepted: bool) -> str:
    """执行或取消已预览的高危操作；payload 二次校验属主。"""
    r = cache.get_redis()
    raw = r.get(_confirm_key(confirm_id))
    if not raw:
        raise AppError("CONFIRM_EXPIRED", "确认已过期，请重新发起该操作", status_code=400)
    payload = json.loads(raw)
    r.delete(_confirm_key(confirm_id))
    if payload.get("user_id") != user.id:
        raise AppError("CONFIRM_FORBIDDEN", "该确认不属于当前账号", status_code=403)
    if not accepted:
        return "已取消该操作，数据未做任何改动。"

    entity = payload["entity"]
    action = payload["action"]
    dsl = payload.get("dsl") or {}
    if action == "delete":
        if entity == "favorites":
            ids = [fid for (fid,) in _favorite_scope(db, user, dsl).with_entities(Favorite.id).all()]
            if ids:
                db.query(Favorite).filter(Favorite.id.in_(ids)).delete(synchronize_session=False)
                db.commit()
            return f"已删除 {len(ids)} 条收藏记录。"
        q = _paper_scope(db, user, dsl)
        n = q.count()
        q.delete(synchronize_session=False)
        db.commit()
        return f"已删除 {n} 份试卷及其关联记录。"
    if action == "update":
        new_name = str(dsl.get("set_name") or "").strip()
        q = _paper_scope(db, user, dsl)
        n = q.count()
        q.update({"name": new_name}, synchronize_session=False)
        db.commit()
        return f"已把 {n} 份试卷改名为「{new_name}」。"
    raise AppError("CONFIRM_ACTION", "不支持的操作类型", status_code=400)


def _favorite_scope(db: Session, user: User, dsl: dict):
    filters = dsl.get("filters") if isinstance(dsl.get("filters"), list) else []
    fmap = {str(f.get("field")): f for f in filters if isinstance(f, dict)}
    q = (db.query(Favorite)
         .join(Question, Favorite.question_id == Question.id)
         .join(FavoriteGroup, Favorite.group_id == FavoriteGroup.id)
         .filter(Favorite.user_id == user.id))
    if "type" in fmap:
        q = q.filter(Question.type == str(fmap["type"].get("value")))
    if "difficulty" in fmap:
        q = q.filter(Question.difficulty == str(fmap["difficulty"].get("value")))
    if "knowledge_point" in fmap:
        q = q.filter(Question.knowledge_point.like(f"%{fmap['knowledge_point'].get('value')}%"))
    if "group" in fmap:
        q = q.filter(FavoriteGroup.name == str(fmap["group"].get("value")))
    return q


def _paper_scope(db: Session, user: User, dsl: dict):
    filters = dsl.get("filters") if isinstance(dsl.get("filters"), list) else []
    fmap = {str(f.get("field")): f for f in filters if isinstance(f, dict)}
    q = db.query(Paper).filter(Paper.owner_id == user.id)
    if "name" in fmap:
        q = q.filter(Paper.name.like(f"%{fmap['name'].get('value')}%"))
    if "status" in fmap:
        q = q.filter(Paper.status == str(fmap["status"].get("value")))
    return q
