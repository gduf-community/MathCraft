"""学生作答、交卷、DeepSeek 批卷、复盘、统计测试。"""
from app.services import grading
from conftest import make_questions

NO_TIME = {"exam_start": None, "exam_end": None}
FUTURE = {
    "exam_start": "2030-01-01T09:00:00+08:00",
    "exam_end": "2030-01-01T11:00:00+08:00",
}
PAST = {
    "exam_start": "2020-01-01T09:00:00+08:00",
    "exam_end": "2020-01-01T11:00:00+08:00",
}


def _me(client, headers):
    return client.get("/api/auth/me", headers=headers).json()["user"]


def _setup(client, teacher, student, db, specs, exam=None, space_name="作答班级"):
    space_resp = client.post("/api/spaces", json={"name": space_name, "capacity": 50}, headers=teacher)
    assert space_resp.status_code == 201
    space = space_resp.json()
    client.post("/api/spaces/join", json={"code": space["code"]}, headers=student)

    teacher_id = _me(client, teacher)["id"]
    qids = make_questions(db, teacher_id, specs)
    body = {
        "name": "作答测试卷",
        "questions": qids,
        "space_ids": [space["id"]],
        "save_to_records": True,
        "is_published": True,
    }
    if exam:
        body.update(exam)
    paper = client.post("/api/papers", json=body, headers=teacher)
    assert paper.status_code == 201, paper.text
    return space, paper.json()


def test_attempt_lifecycle_objective_and_subjective(client, teacher, student, db, monkeypatch):
    space, paper = _setup(
        client,
        teacher,
        student,
        db,
        [("single", "A", 5), ("multiple", "AB", 8), ("judge", "A", 3), ("essay", "导数的定义", 10)],
    )

    # 打开作答页：题目和选项可见，答案隐藏
    resp = client.get(
        f"/api/papers/{paper['id']}/attempt?space_id={space['id']}", headers=student
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["attempt"] is None
    assert len(data["questions"]) == 4
    assert all("answer" not in q for q in data["questions"])

    # 开始作答
    start = client.post(
        f"/api/papers/{paper['id']}/attempts",
        json={"space_id": space["id"]},
        headers=student,
    )
    assert start.status_code == 201, start.text
    attempt = start.json()
    attempt_id = attempt["attempt"]["id"]
    pq_ids = [q["paper_question_id"] for q in attempt["questions"]]

    # 未配置 DeepSeek 密钥时，填写了主观题答案应拒绝交卷
    payload = {
        "answers": [
            {"paper_question_id": pq_ids[0], "choices": ["A"], "text": ""},
            {"paper_question_id": pq_ids[1], "choices": ["A", "B"], "text": ""},
            {"paper_question_id": pq_ids[2], "choices": ["A"], "text": ""},
            {"paper_question_id": pq_ids[3], "choices": [], "text": "导数的定义是差商的极限"},
        ]
    }
    resp = client.post(f"/api/attempts/{attempt_id}/submit", json=payload, headers=student)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "DEEPSEEK_KEY_MISSING"

    # 配置密钥后，主观题打桩给 8 分
    client.put(
        "/api/users/me/model-settings",
        json={"deepseek_api_key": "sk-test-student"},
        headers=student,
    )
    monkeypatch.setattr(
        grading,
        "chat_json",
        lambda *a, **k: {"score": 8, "comment": "步骤基本正确"},
    )
    resp = client.post(f"/api/attempts/{attempt_id}/submit", json=payload, headers=student)
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["score"] == 5 + 8 + 3 + 8
    assert result["total_score"] == 26
    assert len(result["detail"]) == 4

    # 复盘包含答案与解析
    review = client.get(f"/api/attempts/{attempt_id}/review", headers=student)
    assert review.status_code == 200
    review_data = review.json()
    assert all("answer" in q for q in review_data["questions"])
    assert review_data["attempt"]["status"] == "submitted"

    # 重复交卷
    again = client.post(f"/api/attempts/{attempt_id}/submit", json=payload, headers=student)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "ALREADY_SUBMITTED"

    # 空间试卷列表显示已作答（组卷记录按账号隔离，学生记录不含教师发布的试卷）
    records = client.get("/api/papers", headers=student).json()
    assert all(p["id"] != paper["id"] for p in records)
    space_papers = client.get(f"/api/spaces/{space['id']}/papers", headers=student).json()
    target = next(p for p in space_papers if p["id"] == paper["id"])
    assert target["answered"] is True

    # 教师统计来自真实作答
    stats = client.get(
        f"/api/papers/{paper['id']}/statistics?space_id={space['id']}", headers=teacher
    )
    assert stats.status_code == 200, stats.text
    stats_data = stats.json()
    assert stats_data["submitted_count"] == 1
    assert stats_data["student_count"] == 1
    assert len(stats_data["questions"]) == 4
    single = stats_data["questions"][0]
    assert single["option_counts"][0] == {"label": "A", "count": 1}
    assert single["average_score"] == 5.0


def test_restart_attempt_marks_unanswered(client, teacher, student, db):
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)], exam=NO_TIME)
    start = client.post(
        f"/api/papers/{paper['id']}/attempts", json={"space_id": space["id"]}, headers=student
    ).json()
    attempt_id = start["attempt"]["id"]
    pq_id = start["questions"][0]["paper_question_id"]
    assert client.post(
        f"/api/attempts/{attempt_id}/submit",
        json={"answers": [{"paper_question_id": pq_id, "choices": ["A"], "text": ""}]},
        headers=student,
    ).status_code == 200

    # 未勾选「允许修改答案并重新提交」时，重做被拒绝
    denied = client.post(f"/api/papers/{paper['id']}/attempts", json={"space_id": space["id"]}, headers=student)
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "RETAKE_NOT_ALLOWED"

    # 教师勾选「允许修改答案并重新提交」后可重做，且带上一次提交的答案
    assert client.put(
        f"/api/papers/{paper['id']}", json={"allow_retake": True}, headers=teacher
    ).status_code == 200
    new_start = client.post(
        f"/api/papers/{paper['id']}/attempts", json={"space_id": space["id"]}, headers=student
    )
    assert new_start.status_code == 201
    data = new_start.json()
    assert data["attempt"]["status"] == "answering"
    # 上一次提交的答案被预填，可直接修改后重新交卷
    assert data["answers"][0]["choices"] == ["A"]
    space_papers = client.get(f"/api/spaces/{space['id']}/papers", headers=student).json()
    target = next(p for p in space_papers if p["id"] == paper["id"])
    assert target["answered"] is False


def test_review_gated_by_allow_review(client, teacher, student, db):
    """未勾选「允许交卷后查看答案和解析」时，交卷后不下发答案且复盘接口拒绝。"""
    space_resp = client.post("/api/spaces", json={"name": "复盘班级", "capacity": 50}, headers=teacher)
    space = space_resp.json()
    client.post("/api/spaces/join", json={"code": space["code"]}, headers=student)
    teacher_id = _me(client, teacher)["id"]
    qids = make_questions(db, teacher_id, [("single", "A", 5)])
    paper = client.post(
        "/api/papers",
        json={
            "name": "无解析卷",
            "questions": qids,
            "space_ids": [space["id"]],
            "is_published": True,
            "allow_review": False,
            "allow_retake": True,
        },
        headers=teacher,
    ).json()
    start = client.post(
        f"/api/papers/{paper['id']}/attempts", json={"space_id": space["id"]}, headers=student
    ).json()
    attempt_id = start["attempt"]["id"]
    pq_id = start["questions"][0]["paper_question_id"]
    submit = client.post(
        f"/api/attempts/{attempt_id}/submit",
        json={"answers": [{"paper_question_id": pq_id, "choices": ["A"], "text": ""}]},
        headers=student,
    )
    assert submit.status_code == 200
    assert all("answer" not in d for d in submit.json()["detail"])

    # 复盘接口拒绝
    review = client.get(f"/api/attempts/{attempt_id}/review", headers=student)
    assert review.status_code == 403
    assert review.json()["detail"]["code"] == "REVIEW_NOT_ALLOWED"

    # 打开作答页同样不下发答案
    opened = client.get(
        f"/api/papers/{paper['id']}/attempt?space_id={space['id']}", headers=student
    ).json()
    assert all("answer" not in q for q in opened["questions"])


def test_attempt_time_window_and_stopped(client, teacher, student, db):
    # 未开始
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)], exam=FUTURE)
    resp = client.get(
        f"/api/papers/{paper['id']}/attempt?space_id={space['id']}", headers=student
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "EXAM_NOT_STARTED"

    # 已结束：禁止进入作答
    space3, paper3 = _setup(client, teacher, student, db, [("single", "A", 5)], exam=PAST, space_name="已结束班级")
    resp = client.get(
        f"/api/papers/{paper3['id']}/attempt?space_id={space3['id']}", headers=student
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "EXAM_ENDED"
    assert resp.json()["detail"]["message"] == "已过作答时间"

    # 停止作答
    space2, paper2 = _setup(client, teacher, student, db, [("single", "A", 5)], exam=NO_TIME, space_name="停止班级")
    client.post(f"/api/papers/{paper2['id']}/publications/{space2['id']}/stop", headers=teacher)
    resp = client.get(
        f"/api/papers/{paper2['id']}/attempt?space_id={space2['id']}", headers=student
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "PAPER_STOPPED"


def test_non_member_and_teacher_cannot_answer(client, teacher, student, db):
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)], exam=NO_TIME)
    # 学生退出空间后不能作答
    client.post(f"/api/spaces/{space['id']}/leave", headers=student)
    resp = client.get(
        f"/api/papers/{paper['id']}/attempt?space_id={space['id']}", headers=student
    )
    assert resp.status_code == 403
    assert resp.json()["detail"]["code"] == "NOT_SPACE_MEMBER"

    # 教师不能作答
    resp = client.get(
        f"/api/papers/{paper['id']}/attempt?space_id={space['id']}", headers=teacher
    )
    assert resp.status_code == 403


def test_student_personal_practice_attempt(client, student, db):
    student_id = _me(client, student)["id"]
    qids = make_questions(db, student_id, [("single", "A", 5), ("judge", "A", 3)])
    resp = client.post(
        "/api/papers",
        json={
            "name": "个人练习",
            "questions": qids,
            "space_ids": [],
            "is_published": True,
            "save_to_records": True,
        },
        headers=student,
    )
    assert resp.status_code == 201
    paper = resp.json()
    assert paper["status"] == "draft"

    attempt = client.post(
        f"/api/papers/{paper['id']}/attempts", json={"space_id": None}, headers=student
    )
    assert attempt.status_code == 201
    data = attempt.json()
    attempt_id = data["attempt"]["id"]
    pq_ids = [q["paper_question_id"] for q in data["questions"]]
    submit = client.post(
        f"/api/attempts/{attempt_id}/submit",
        json={
            "answers": [
                {"paper_question_id": pq_ids[0], "choices": ["A"], "text": ""},
                {"paper_question_id": pq_ids[1], "choices": ["A"], "text": ""},
            ]
        },
        headers=student,
    )
    assert submit.status_code == 200
    assert submit.json()["score"] == 8


def test_statistics_permissions(client, teacher, student, db):
    space, paper = _setup(client, teacher, student, db, [("single", "A", 5)], exam=NO_TIME)
    assert client.get(
        f"/api/papers/{paper['id']}/statistics?space_id={space['id']}", headers=student
    ).status_code == 403
    assert client.get(
        f"/api/papers/{paper['id']}/statistics?space_id=sp_none", headers=teacher
    ).status_code == 404
