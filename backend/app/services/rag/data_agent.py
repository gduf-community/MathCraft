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
_CONSUME_CONFIRM = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    return redis.call('DEL', KEYS[1])
end
return 0
"""
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


def _row_limit(dsl: dict) -> int:
    return min(max(int(dsl.get("limit") or 50), 1), 200)


def _collect_rows(
    db: Session, user: User, entity: str, dsl: dict, *, apply_limit: bool = True,
) -> list[dict]:
    """取完整所属集合后过滤、排序；聚合保留全集，明细与写预览才限量。"""
    raw_filters = dsl.get("filters")
    filters = raw_filters if isinstance(raw_filters, list) else []
    rows: list[dict] = []
    field_map: dict[str, str] = {}

    if entity == "favorites":
        q = (db.query(Favorite, Question, FavoriteGroup)
             .join(Question, Favorite.question_id == Question.id)
             .join(FavoriteGroup, Favorite.group_id == FavoriteGroup.id)
             .filter(Favorite.user_id == user.id)
             .order_by(Favorite.created_at.desc()))
        for fav, question, group in q:
            rows.append({
                "id": fav.id,
                "sort": question.difficulty_score,
                "raw": {"type": question.type, "difficulty": question.difficulty,
                        "knowledge_point": question.knowledge_point or "", "group": group.name,
                        "difficulty_score": question.difficulty_score},
                "cells": {"题目": _stem_summary(question.stem), "题型": TYPE_LABELS.get(question.type, question.type),
                          "难度": question.difficulty, "知识点": question.knowledge_point or "—",
                          "分组": group.name},
            })
        field_map = {"type": "type", "difficulty": "difficulty",
                     "knowledge_point": "knowledge_point", "group": "group",
                     "difficulty_score": "difficulty_score"}
    elif entity == "questions":
        q = (db.query(Question).filter(Question.created_by == user.id)
             .order_by(Question.created_at.desc()))
        for question in q:
            rows.append({
                "sort": question.difficulty_score,
                "raw": {"type": question.type, "difficulty": question.difficulty,
                        "knowledge_point": question.knowledge_point or "",
                        "difficulty_score": question.difficulty_score},
                "cells": {"题目": _stem_summary(question.stem), "题型": TYPE_LABELS.get(question.type, question.type),
                          "难度": question.difficulty, "难度分": round(question.difficulty_score, 2),
                          "知识点": question.knowledge_point or "—"},
            })
        field_map = {"type": "type", "difficulty": "difficulty", "knowledge_point": "knowledge_point",
                     "difficulty_score": "difficulty_score"}
    elif entity == "papers":
        q = (db.query(Paper).filter(Paper.owner_id == user.id)
             .order_by(Paper.created_at.desc()))
        for paper in q:
            rows.append({
                "id": paper.id,
                "sort": paper.created_at,
                "raw": {"name": paper.name, "status": paper.status},
                "cells": {"试卷": paper.name, "状态": "已发布" if paper.status == "published" else "草稿",
                          "题数": paper.question_count, "总分": paper.total_score},
            })
        field_map = {"name": "name", "status": "status"}
    elif entity == "spaces":
        if user.role == "teacher":
            spaces = db.query(StudySpace).filter(StudySpace.creator_id == user.id).all()
        else:
            ids = [m.space_id for m in db.query(SpaceMember)
                   .filter(SpaceMember.user_id == user.id).all()]
            spaces = db.query(StudySpace).filter(StudySpace.id.in_(ids or ["-"])).all()
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
             .order_by(PaperAttempt.started_at.desc()))
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
        if not isinstance(f, dict):
            continue
        raw_key = field_map.get(str(f.get("field")))
        if not raw_key:
            continue
        op = str(f.get("op") or "eq")
        rows = [r for r in rows if _match(r["raw"].get(raw_key), op, f.get("value"))]

    order_by = str(dsl.get("order_by") or "none")
    if order_by != "none":
        descending = order_by.startswith("-")
        field = order_by[1:] if descending else order_by
        key = field_map.get(field)
        if key is None:
            raise AppError("DATA_ORDER", "该类数据不支持指定的排序字段", status_code=400)
        rows.sort(key=lambda row: _num_or_str(row["raw"].get(key)), reverse=descending)
    return rows[:_row_limit(dsl)] if apply_limit else rows


def _num_or_str(value: object) -> tuple[bool, int | float | str]:
    return value is not None, value if isinstance(value, (int, float)) else str(value or "")


def _aggregate(rows: list[dict], aggregate: str) -> str:
    if aggregate == "count":
        return f"共 {len(rows)} 条记录。"
    if aggregate.startswith(("avg:", "max:", "min:")):
        field = aggregate.split(":", 1)[1]
        if field not in ("score", "difficulty_score") or any(
            field not in row["raw"] for row in rows
        ):
            raise AppError("DATA_AGGREGATE", "该类数据不支持指定的数值统计字段", status_code=400)
        meta = {"score": "得分", "difficulty_score": "难度分"}.get(field, field)
        numbers = [float(row["raw"][field]) for row in rows
                   if isinstance(row["raw"].get(field), (int, float))
                   and row["raw"][field] >= 0]
        if not numbers:
            return f"没有可用于{meta}聚合的数值。"
        if aggregate.startswith("avg:"):
            return f"共 {len(numbers)} 条，{meta}平均 {sum(numbers) / len(numbers):.2f}。"
        extreme = max(numbers) if aggregate.startswith("max:") else min(numbers)
        best = next((row for row in rows if isinstance(row["raw"].get(field), (int, float))
                     and abs(float(row["raw"][field]) - extreme) < 1e-9), None)
        detail = "；".join(f"{k}：{v}" for k, v in best["cells"].items()) if best else ""
        return f"{meta}最{'高' if aggregate.startswith('max:') else '低'}为 {extreme}。明细：{detail}"
    return ""


def _preview(db: Session, user: User, entity: str, dsl: dict) -> tuple[list[str], list[str]]:
    rows = _collect_rows(db, user, entity, {**dsl, "action": "select", "aggregate": "none"})
    return [row["id"] for row in rows], [
        "；".join(f"{k}：{v}" for k, v in row["cells"].items()) for row in rows[:5]
    ]


def run_data_request(
    db: Session, user: User, message: str, api_key: str | None,
    *, session_id: str | None = None,
) -> dict:
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
            aggregate = str(sub.get("aggregate") or "count")
            try:
                rows = _collect_rows(db, user, sub_entity, sub, apply_limit=aggregate == "none")
                agg = _aggregate(rows, aggregate)
            except AppError as exc:
                parts.append(f"{label}：{exc.message}")
                continue
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
        aggregate = str(dsl.get("aggregate") or "none")
        rows = _collect_rows(db, user, entity, dsl, apply_limit=aggregate == "none")
        head = _aggregate(rows, aggregate)
        shown = rows[:min(_row_limit(dsl), 10)]
        detail = "\n".join(f"{i}. " + "；".join(f"{k}：{v}" for k, v in r["cells"].items())
                           for i, r in enumerate(shown, 1))
        more = f"\n…还有 {len(rows) - len(shown)} 条未展示。" if len(rows) > len(shown) else ""
        parts = [head or f"共 {len(rows)} 条记录。"]
        if rows:
            parts.append(detail + more)
        if explanation:
            parts.append(f"（{explanation}）")
        return {"reply": "\n".join(parts), "questions": [], "done": True}

    if action not in ("delete", "update"):
        return {"reply": "暂不支持这类操作。", "questions": [], "done": True}
    if action == "delete" and entity not in ("favorites", "papers"):
        return {"reply": "目前只支持删除收藏和试卷，其他数据不提供删除。", "questions": [], "done": True}
    if action == "update" and entity != "papers":
        return {"reply": "目前只支持修改试卷名称，其他数据不提供修改。", "questions": [], "done": True}
    new_name = str(dsl.get("set_name") or "").strip()
    if action == "update" and not new_name:
        return {"reply": "请告诉我试卷要改成什么名字。", "questions": [], "done": True}
    if action == "update" and len(new_name) > 128:
        return {"reply": "试卷名称不能超过 128 个字符。", "questions": [], "done": True}

    target_ids, samples = _preview(db, user, entity, dsl)
    affected = len(target_ids)
    if affected == 0:
        return {"reply": "没有找到符合条件的数据，无需执行该操作。", "questions": [], "done": True}

    confirm_id = new_id("cfm")
    payload = {"confirm_id": confirm_id, "action": action, "entity": entity,
               "target_ids": target_ids, "set_name": new_name,
               "user_id": user.id, "session_id": session_id}
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


def execute_confirmed(
    db: Session, user: User, confirm_id: str, accepted: bool,
    *, session_id: str | None = None,
) -> str:
    """校验账号与会话后原子消费确认，仅修改预览 ID 中仍归本人的记录。"""
    r = cache.get_redis()
    raw = r.get(_confirm_key(confirm_id))
    if not raw:
        raise AppError("CONFIRM_EXPIRED", "确认已过期，请重新发起该操作", status_code=400)
    payload = json.loads(raw)
    if payload.get("user_id") != user.id:
        raise AppError("CONFIRM_FORBIDDEN", "该确认不属于当前账号", status_code=403)
    if payload.get("session_id") != session_id:
        raise AppError("CONFIRM_FORBIDDEN", "该确认不属于当前对话", status_code=403)
    target_ids = payload.get("target_ids")
    if not isinstance(target_ids, list) or not target_ids or not all(
        isinstance(target_id, str) and target_id for target_id in target_ids
    ):
        # 旧版确认没有目标快照，必须重新预览，不能重新执行旧 DSL。
        raise AppError("CONFIRM_EXPIRED", "确认已过期，请重新发起该操作", status_code=400)
    if not r.eval(_CONSUME_CONFIRM, 1, _confirm_key(confirm_id), raw):
        raise AppError("CONFIRM_EXPIRED", "确认已过期，请重新发起该操作", status_code=400)
    if not accepted:
        return "已取消该操作，数据未做任何改动。"

    entity = payload["entity"]
    action = payload["action"]
    if action == "delete":
        if entity == "favorites":
            n = db.query(Favorite).filter(
                Favorite.id.in_(target_ids), Favorite.user_id == user.id,
            ).delete(synchronize_session=False)
            db.commit()
            return f"已删除 {n} 条收藏记录。"
        if entity == "papers":
            n = db.query(Paper).filter(
                Paper.id.in_(target_ids), Paper.owner_id == user.id,
            ).delete(synchronize_session=False)
            db.commit()
            return f"已删除 {n} 份试卷及其关联记录。"
    if action == "update" and entity == "papers":
        new_name = payload["set_name"]
        n = db.query(Paper).filter(
            Paper.id.in_(target_ids), Paper.owner_id == user.id,
        ).update({"name": new_name}, synchronize_session=False)
        db.commit()
        return f"已把 {n} 份试卷改名为「{new_name}」。"
    raise AppError("CONFIRM_ACTION", "不支持的操作类型", status_code=400)
