"""收藏分组与收藏接口测试。"""
import json

from app.models import GenerationBatch, Question
from app.models.base import new_id


def _teacher_id(client, teacher):
    return client.get("/api/auth/me", headers=teacher).json()["user"]["id"]


def _insert_questions(db, user_id, count=3):
    batch = GenerationBatch(
        id=new_id("batch"),
        user_id=user_id,
        bank_id="bank_test",
        document_id="doc_test",
        mode="parametric",
        params_json="{}",
        question_count=count,
        status="done",
    )
    db.add(batch)
    db.flush()
    ids = []
    for i in range(count):
        q = Question(
            id=new_id("q"),
            batch_id=batch.id,
            bank_id="bank_test",
            document_id="doc_test",
            type="single",
            score=5,
            difficulty="中",
            stem=f"测试题干 {i + 1}",
            options_json=json.dumps(
                [{"label": "A", "text": "1"}, {"label": "B", "text": "2"}], ensure_ascii=False
            ),
            answer="A",
            analysis="解析",
            knowledge_point="导数",
            source_mode="variant_data",
            created_by=user_id,
        )
        db.add(q)
        ids.append(q.id)
    db.commit()
    return ids


def test_default_group_exists(client, teacher):
    resp = client.get("/api/favorite-groups", headers=teacher)
    assert resp.status_code == 200
    groups = resp.json()
    assert len(groups) == 1
    assert groups[0]["is_default"] is True
    assert groups[0]["name"] == "默认"


def test_create_favorite_and_move_group(client, teacher, db):
    tid = _teacher_id(client, teacher)
    qids = _insert_questions(db, tid)

    group = client.post("/api/favorite-groups", json={"name": "错题"}, headers=teacher).json()
    assert group["name"] == "错题"

    resp = client.post(
        "/api/favorites", json={"question_id": qids[0], "group_id": "default"}, headers=teacher
    )
    assert resp.status_code == 201
    assert resp.json()["moved"] is False

    favs = client.get("/api/favorites", headers=teacher).json()
    assert len(favs) == 1
    assert favs[0]["id"] == qids[0]
    assert favs[0]["starred"] is True

    # 换组
    resp = client.put(f"/api/favorites/{qids[0]}", json={"group_id": group["id"]}, headers=teacher)
    assert resp.status_code == 204
    moved = client.get(f"/api/favorites?group_id={group['id']}", headers=teacher).json()
    assert len(moved) == 1
    assert moved[0]["favorite_group_id"] == group["id"]


def test_duplicate_favorite_moves_instead_of_duplicating(client, teacher, db):
    tid = _teacher_id(client, teacher)
    qids = _insert_questions(db, tid)
    first = client.post("/api/favorites", json={"question_id": qids[0], "group_id": "default"}, headers=teacher)
    assert first.status_code == 201
    second = client.post("/api/favorites", json={"question_id": qids[0], "group_id": "default"}, headers=teacher)
    assert second.status_code == 201
    assert second.json()["moved"] is True
    assert len(client.get("/api/favorites", headers=teacher).json()) == 1


def test_rename_and_delete_group_moves_to_default(client, teacher, db):
    tid = _teacher_id(client, teacher)
    qids = _insert_questions(db, tid)
    group = client.post("/api/favorite-groups", json={"name": "临时组"}, headers=teacher).json()

    client.post("/api/favorites", json={"question_id": qids[0], "group_id": group["id"]}, headers=teacher)

    resp = client.put(f"/api/favorite-groups/{group['id']}", json={"name": "重点题"}, headers=teacher)
    assert resp.status_code == 200
    assert resp.json()["name"] == "重点题"

    assert client.delete(f"/api/favorite-groups/{group['id']}", headers=teacher).status_code == 204
    favs = client.get("/api/favorites", headers=teacher).json()
    default_group = client.get("/api/favorite-groups", headers=teacher).json()[0]
    assert favs[0]["favorite_group_id"] == default_group["id"]


def test_default_group_protected(client, teacher):
    groups = client.get("/api/favorite-groups", headers=teacher).json()
    default_id = groups[0]["id"]

    assert client.delete(f"/api/favorite-groups/{default_id}", headers=teacher).status_code == 403
    assert client.put(
        f"/api/favorite-groups/{default_id}", json={"name": "新名字"}, headers=teacher
    ).status_code == 403


def test_duplicate_group_name_rejected(client, teacher):
    client.post("/api/favorite-groups", json={"name": "错题"}, headers=teacher)
    resp = client.post("/api/favorite-groups", json={"name": "错题"}, headers=teacher)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "GROUP_EXISTS"


def test_unfavorite(client, teacher, db):
    tid = _teacher_id(client, teacher)
    qids = _insert_questions(db, tid)
    client.post("/api/favorites", json={"question_id": qids[0], "group_id": "default"}, headers=teacher)

    assert client.delete(f"/api/favorites/{qids[0]}", headers=teacher).status_code == 204
    assert client.get("/api/favorites", headers=teacher).json() == []


def test_cannot_favorite_other_users_question(client, teacher, student, db):
    tid = _teacher_id(client, teacher)
    qids = _insert_questions(db, tid)
    resp = client.post(
        "/api/favorites", json={"question_id": qids[0], "group_id": "default"}, headers=student
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "FORBIDDEN"


def test_favorites_group_count(client, teacher, db):
    tid = _teacher_id(client, teacher)
    qids = _insert_questions(db, tid)
    group = client.post("/api/favorite-groups", json={"name": "组A"}, headers=teacher).json()
    client.post("/api/favorites", json={"question_id": qids[0], "group_id": group["id"]}, headers=teacher)
    client.post("/api/favorites", json={"question_id": qids[1], "group_id": group["id"]}, headers=teacher)

    groups = client.get("/api/favorite-groups", headers=teacher).json()
    target = next(g for g in groups if g["id"] == group["id"])
    assert target["count"] == 2
