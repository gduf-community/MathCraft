"""组卷快照、发布、停止恢复、删除测试。"""
from conftest import make_questions

EXAM = {
    "exam_start": "2030-01-01T09:00:00+08:00",
    "exam_end": "2030-01-01T11:00:00+08:00",
}


def _me(client, headers):
    return client.get("/api/auth/me", headers=headers).json()["user"]


def _setup_space(client, teacher, student):
    resp = client.post("/api/spaces", json={"name": "测试班级", "capacity": 50}, headers=teacher)
    assert resp.status_code == 201
    space = resp.json()
    assert client.post("/api/spaces/join", json={"code": space["code"]}, headers=student).status_code == 200
    return space


def _create_paper(client, headers, questions, space_ids=None, published=True, name="导数单元测试"):
    body = {
        "name": name,
        "questions": questions,
        "space_ids": space_ids or [],
        "save_to_records": True,
        "is_published": published,
    }
    if published:
        body.update(EXAM)
    resp = client.post("/api/papers", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_create_published_paper_snapshot(client, teacher, student, db):
    space = _setup_space(client, teacher, student)
    teacher_id = _me(client, teacher)["id"]
    qids = make_questions(
        db,
        teacher_id,
        [("single", "A", 5), ("multiple", "AB", 8), ("judge", "A", 3)],
    )
    paper = _create_paper(client, teacher, qids, [space["id"]])
    assert paper["status"] == "published"
    assert paper["question_count"] == 3
    assert paper["total_score"] == 16
    assert len(paper["spaces"]) == 1
    assert paper["spaces"][0]["space_id"] == space["id"]
    assert all("answer" in q for q in paper["questions"])
    assert [q["no"] for q in paper["questions"]] == [1, 2, 3]

    # 学生能看到已发布试卷，但未交卷时答案隐藏
    detail = client.get(f"/api/papers/{paper['id']}", headers=student)
    assert detail.status_code == 200
    assert all("answer" not in q for q in detail.json()["questions"])

    # 组卷记录严格按账号隔离：学生记录不包含教师发布的试卷
    listing = client.get("/api/papers", headers=student).json()
    assert all(p["id"] != paper["id"] for p in listing)

    # 空间试卷列表包含作答人数
    space_papers = client.get(f"/api/spaces/{space['id']}/papers", headers=student).json()
    assert len(space_papers) == 1
    assert space_papers[0]["submitted_count"] == 0
    assert space_papers[0]["student_count"] == 1
    assert space_papers[0]["stopped"] is False


def test_publish_duplicate_rejected(client, teacher, student, db):
    space = _setup_space(client, teacher, student)
    teacher_id = _me(client, teacher)["id"]
    qids = make_questions(db, teacher_id, [("single", "A", 5)])
    paper = _create_paper(client, teacher, qids, [space["id"]], published=False)
    assert paper["status"] == "draft"

    resp = client.post(
        f"/api/papers/{paper['id']}/publish",
        json={"space_ids": [space["id"]], **EXAM},
        headers=teacher,
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "published"

    dup = client.post(
        f"/api/papers/{paper['id']}/publish",
        json={"space_ids": [space["id"]]},
        headers=teacher,
    )
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "ALREADY_PUBLISHED"


def test_student_personal_paper_cannot_publish(client, student, db):
    student_id = _me(client, student)["id"]
    qids = make_questions(db, student_id, [("single", "A", 5)])
    resp = client.post(
        "/api/papers",
        json={
            "name": "个人练习",
            "questions": qids,
            "space_ids": [],
            "is_published": True,
            "save_to_records": False,
        },
        headers=student,
    )
    assert resp.status_code == 201, resp.text
    paper = resp.json()
    assert paper["status"] == "draft"
    assert paper["spaces"] == []
    assert paper["saved_to_records"] is True


def test_update_paper_name_and_remove_question(client, teacher, db):
    teacher_id = _me(client, teacher)["id"]
    qids = make_questions(db, teacher_id, [("single", "A", 5), ("judge", "A", 3)])
    paper = _create_paper(client, teacher, qids, published=False, name="旧名字")
    pq_ids = [q["paper_question_id"] for q in paper["questions"]]

    resp = client.put(
        f"/api/papers/{paper['id']}",
        json={"name": "新名字", **EXAM},
        headers=teacher,
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "新名字"
    assert resp.json()["exam_window"]["start"] is not None

    resp = client.post(
        f"/api/papers/{paper['id']}/questions/remove",
        json={"paper_question_ids": [pq_ids[0]]},
        headers=teacher,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["question_count"] == 1
    assert data["total_score"] == 3
    assert [q["no"] for q in data["questions"]] == [1]


def test_paper_permissions(client, teacher, student, db):
    space = _setup_space(client, teacher, student)
    teacher_id = _me(client, teacher)["id"]
    qids = make_questions(db, teacher_id, [("single", "A", 5)])
    paper = _create_paper(client, teacher, qids, [space["id"]])

    assert client.put(
        f"/api/papers/{paper['id']}", json={"name": "学生修改"}, headers=student
    ).status_code == 403
    assert client.delete(f"/api/papers/{paper['id']}", headers=student).status_code == 403


def test_stop_resume_and_delete_publication(client, teacher, student, db):
    space = _setup_space(client, teacher, student)
    teacher_id = _me(client, teacher)["id"]
    qids = make_questions(db, teacher_id, [("single", "A", 5)])
    paper = _create_paper(client, teacher, qids, [space["id"]])

    # 未停止不能从空间删除
    resp = client.delete(
        f"/api/papers/{paper['id']}/publications/{space['id']}", headers=teacher
    )
    assert resp.status_code == 403

    assert client.post(
        f"/api/papers/{paper['id']}/publications/{space['id']}/stop", headers=teacher
    ).status_code == 204
    space_papers = client.get(f"/api/spaces/{space['id']}/papers", headers=student).json()
    assert space_papers[0]["stopped"] is True

    assert client.post(
        f"/api/papers/{paper['id']}/publications/{space['id']}/resume", headers=teacher
    ).status_code == 204
    assert client.get(f"/api/spaces/{space['id']}/papers", headers=student).json()[0]["stopped"] is False

    assert client.post(
        f"/api/papers/{paper['id']}/publications/{space['id']}/stop", headers=teacher
    ).status_code == 204
    assert client.delete(
        f"/api/papers/{paper['id']}/publications/{space['id']}", headers=teacher
    ).status_code == 204
    assert client.get(f"/api/spaces/{space['id']}/papers", headers=student).json() == []
    assert client.get(f"/api/papers/{paper['id']}", headers=teacher).json()["status"] == "draft"


def test_saved_filter(client, teacher, db):
    teacher_id = _me(client, teacher)["id"]
    qids = make_questions(db, teacher_id, [("single", "A", 5), ("judge", "A", 3)])
    _create_paper(client, teacher, qids, published=False, name="不保存")
    # 更新 saved_to_records 没有接口，直接构造一个不保存的试卷
    from app.models import Paper, PaperQuestion
    from app.models.base import new_id

    paper = Paper(
        id=new_id("paper"),
        name="隐藏试卷",
        owner_id=teacher_id,
        status="draft",
        saved_to_records=False,
        question_count=0,
        total_score=0,
    )
    db.add(paper)
    db.commit()

    assert len(client.get("/api/papers", headers=teacher).json()) == 2
    saved = client.get("/api/papers?saved=true", headers=teacher).json()
    assert len(saved) == 1
    assert saved[0]["name"] == "不保存"


def test_batch_delete_papers(client, teacher, db):
    teacher_id = _me(client, teacher)["id"]
    qids = make_questions(db, teacher_id, [("single", "A", 5), ("judge", "A", 3)])
    p1 = _create_paper(client, teacher, qids, published=False, name="卷1")
    p2 = _create_paper(client, teacher, qids, published=False, name="卷2")

    resp = client.post(
        "/api/papers/batch-delete", json={"paper_ids": [p1["id"], p2["id"]]}, headers=teacher
    )
    assert resp.status_code == 204
    assert client.get("/api/papers", headers=teacher).json() == []


def test_delete_paper(client, teacher, db):
    teacher_id = _me(client, teacher)["id"]
    qids = make_questions(db, teacher_id, [("single", "A", 5)])
    paper = _create_paper(client, teacher, qids, published=False)
    assert client.delete(f"/api/papers/{paper['id']}", headers=teacher).status_code == 204
    assert client.get(f"/api/papers/{paper['id']}", headers=teacher).status_code == 404


def test_delete_record_keeps_published_paper(client, teacher, student, db):
    """删除组卷记录仅移除记录本身，学习空间已发布试卷不受影响。"""
    space = _setup_space(client, teacher, student)
    teacher_id = _me(client, teacher)["id"]
    qids = make_questions(db, teacher_id, [("single", "A", 5)])
    paper = _create_paper(client, teacher, qids, [space["id"]])

    # 默认 mode=record：归档记录，空间试卷保留
    assert client.delete(f"/api/papers/{paper['id']}", headers=teacher).status_code == 204
    detail = client.get(f"/api/papers/{paper['id']}", headers=teacher).json()
    assert detail["saved_to_records"] is False
    assert detail["status"] == "published"
    space_papers = client.get(f"/api/spaces/{space['id']}/papers", headers=student).json()
    assert [p["id"] for p in space_papers] == [paper["id"]]

    # mode=paper：整卷删除
    assert client.delete(f"/api/papers/{paper['id']}?mode=paper", headers=teacher).status_code == 204
    assert client.get(f"/api/papers/{paper['id']}", headers=teacher).status_code == 404
    assert client.get(f"/api/spaces/{space['id']}/papers", headers=student).json() == []


def test_urge_paper_flow(client, teacher, student, db):
    """催交：创建者可催、24 小时冷却、学生端通知与清除红点。"""
    space = _setup_space(client, teacher, student)
    teacher_id = _me(client, teacher)["id"]
    qids = make_questions(db, teacher_id, [("single", "A", 5)])
    paper = _create_paper(client, teacher, qids, [space["id"]])

    # 学生不能催交
    assert (
        client.post(f"/api/papers/{paper['id']}/publications/{space['id']}/urge", headers=student).status_code
        == 403
    )

    # 教师首次催交成功
    resp = client.post(f"/api/papers/{paper['id']}/publications/{space['id']}/urge", headers=teacher)
    assert resp.status_code == 201, resp.text

    # 24 小时冷却内重复催交被拒
    again = client.post(f"/api/papers/{paper['id']}/publications/{space['id']}/urge", headers=teacher)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "URGE_COOLDOWN"

    # 空间试卷载荷带最近催交时间
    space_papers = client.get(f"/api/spaces/{space['id']}/papers", headers=teacher).json()
    assert space_papers[0]["last_urge_at"] is not None

    # 学生通知：未读 1，内容含教师与试卷名，最早在前
    feed = client.get("/api/urges", headers=student).json()
    assert feed["unread_count"] == 1
    assert len(feed["items"]) == 1
    item = feed["items"][0]
    assert item["paper_id"] == paper["id"]
    assert item["teacher_name"] == "张老师"
    assert item["space_id"] == space["id"]

    # 清除红点后未读归零，记录仍在
    assert client.post("/api/urges/clear", headers=student).status_code == 204
    feed2 = client.get("/api/urges", headers=student).json()
    assert feed2["unread_count"] == 0
    assert len(feed2["items"]) == 1


def test_urge_single_read_and_delete(client, teacher, student, db):
    """单条已读消除对应角标；单条删除直接移除记录。"""
    space = _setup_space(client, teacher, student)
    teacher_id = _me(client, teacher)["id"]
    qids = make_questions(db, teacher_id, [("single", "A", 5)])
    paper = _create_paper(client, teacher, qids, [space["id"]])
    assert client.post(f"/api/papers/{paper['id']}/publications/{space['id']}/urge", headers=teacher).status_code == 201

    # 单条已读：角标归零，列表保留
    feed = client.get("/api/urges", headers=student).json()
    assert feed["unread_count"] == 1
    urge_id = feed["items"][0]["id"]
    assert client.post(f"/api/urges/{urge_id}/read", headers=student).status_code == 204
    feed2 = client.get("/api/urges", headers=student).json()
    assert feed2["unread_count"] == 0
    assert len(feed2["items"]) == 1

    # 创建教师可删除该条；删除后学生列表为空，重复删除 404
    resp = client.delete(f"/api/urges/{urge_id}", headers=teacher)
    assert resp.status_code == 204
    assert client.get("/api/urges", headers=student).json()["items"] == []
    assert client.delete(f"/api/urges/{urge_id}", headers=student).status_code == 404
