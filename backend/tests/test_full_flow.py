"""学生与教师全流程 E2E：建库 → 上传 → 出题 → 组卷发布 → 作答 → 统计。"""
from conftest import create_bank, upload_markdown


def _me(client, headers):
    return client.get("/api/auth/me", headers=headers).json()["user"]


def test_full_teacher_student_flow(client, teacher, student):
    # 1. 教师建库、上传文档、配置 DeepSeek 密钥
    bank = create_bank(client, teacher, "全流程题库")
    doc = upload_markdown(client, teacher, bank["id"])
    client.put(
        "/api/users/me/model-settings",
        json={"deepseek_api_key": "sk-test-teacher"},
        headers=teacher,
    )

    # 2. 生成题目
    gen = client.post(
        "/api/generate/start",
        json={
            "bank_id": bank["id"],
            "document_id": doc["document_id"],
            "types": [{"type": "single", "count": 2}],
            "difficulty": "中",
            "scope": "导数",
            "source_mode": "variant_data",
            "existing_stems": [],
        },
        headers=teacher,
    )
    assert gen.status_code == 202, gen.text
    task_id = gen.json()["task_id"]
    progress = client.get(f"/api/generate/progress/{task_id}", headers=teacher).json()
    assert progress["done"] is True
    assert len(progress["questions"]) == 2
    question_ids = [q["id"] for q in progress["questions"]]

    # 3. 建空间，学生加入
    space_resp = client.post("/api/spaces", json={"name": "全流程班级", "capacity": 50}, headers=teacher)
    assert space_resp.status_code == 201
    space = space_resp.json()
    assert client.post("/api/spaces/join", json={"code": space["code"]}, headers=student).status_code == 200

    # 4. 教师组卷并发布
    paper_resp = client.post(
        "/api/papers",
        json={
            "name": "全流程试卷",
            "questions": question_ids,
            "space_ids": [space["id"]],
            "save_to_records": True,
            "is_published": True,
        },
        headers=teacher,
    )
    assert paper_resp.status_code == 201, paper_resp.text
    paper = paper_resp.json()
    assert paper["status"] == "published"
    assert paper["question_count"] == 2

    # 5. 学生看到试卷并作答
    space_papers = client.get(f"/api/spaces/{space['id']}/papers", headers=student).json()
    assert len(space_papers) == 1
    assert space_papers[0]["id"] == paper["id"]

    attempt_resp = client.post(
        f"/api/papers/{paper['id']}/attempts",
        json={"space_id": space["id"]},
        headers=student,
    )
    assert attempt_resp.status_code == 201, attempt_resp.text
    attempt = attempt_resp.json()
    attempt_id = attempt["attempt"]["id"]
    answers = [
        {"paper_question_id": q["paper_question_id"], "choices": ["A"], "text": ""}
        for q in attempt["questions"]
    ]
    submit = client.post(
        f"/api/attempts/{attempt_id}/submit", json={"answers": answers}, headers=student
    )
    assert submit.status_code == 200, submit.text
    assert submit.json()["score"] == 10

    # 6. 学生复盘与空间试卷状态（组卷记录按账号隔离，不含该试卷）
    review = client.get(f"/api/attempts/{attempt_id}/review", headers=student)
    assert review.status_code == 200
    records = client.get("/api/papers", headers=student).json()
    assert all(p["id"] != paper["id"] for p in records)
    space_papers = client.get(f"/api/spaces/{space['id']}/papers", headers=student).json()
    assert next(p for p in space_papers if p["id"] == paper["id"])["answered"] is True

    # 7. 教师讲解统计
    stats = client.get(
        f"/api/papers/{paper['id']}/statistics?space_id={space['id']}", headers=teacher
    )
    assert stats.status_code == 200
    data = stats.json()
    assert data["submitted_count"] == 1
    assert data["student_count"] == 1
    assert len(data["questions"]) == 2
    assert data["questions"][0]["option_counts"][0] == {"label": "A", "count": 1}

    # 8. 教师停止作答，学生不能再作答
    assert client.post(
        f"/api/papers/{paper['id']}/publications/{space['id']}/stop", headers=teacher
    ).status_code == 204
    blocked = client.get(
        f"/api/papers/{paper['id']}/attempt?space_id={space['id']}", headers=student
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "PAPER_STOPPED"

    # 9. 教师解散空间，学生空间列表清空
    assert client.delete(f"/api/spaces/{space['id']}", headers=teacher).status_code == 204
    assert client.get("/api/spaces", headers=student).json() == []

    # 10. 删除题库后历史试卷快照仍可打开
    assert client.delete(f"/api/banks/{bank['id']}", headers=teacher).status_code == 204
    paper_detail = client.get(f"/api/papers/{paper['id']}", headers=teacher)
    assert paper_detail.status_code == 200
    assert len(paper_detail.json()["questions"]) == 2
    assert all(q["source_question_id"] is None for q in paper_detail.json()["questions"])
