"""学习空间接口与权限测试。"""
def _me(client, headers):
    return client.get("/api/auth/me", headers=headers).json()["user"]


def _create_space(client, headers, name="24软工1班", capacity=50):
    resp = client.post("/api/spaces", json={"name": name, "capacity": capacity}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_teacher_create_and_detail(client, teacher):
    space = _create_space(client, teacher)
    assert space["code"].startswith("SP")
    assert space["my_role"] == "creator"
    assert space["can_edit_space"] is True
    assert space["can_publish_paper"] is True
    assert space["can_answer_paper"] is False
    assert space["member_count"] == 1
    assert space["student_count"] == 0

    # 同一教师不允许创建重名空间；不同教师不受影响
    dup = client.post("/api/spaces", json={"name": "24软工1班", "capacity": 50}, headers=teacher)
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "SPACE_NAME_EXISTS"

    # 重命名撞名同样被拒
    other = _create_space(client, teacher, name="24软工2班")
    rename = client.put(f"/api/spaces/{other['id']}", json={"name": "24软工1班"}, headers=teacher)
    assert rename.status_code == 409


def test_student_cannot_create_teacher_cannot_join(client, teacher, student):
    resp = client.post("/api/spaces", json={"name": "学生空间", "capacity": 10}, headers=student)
    assert resp.status_code == 403

    space = _create_space(client, teacher)
    resp = client.post("/api/spaces/join", json={"code": space["code"]}, headers=teacher)
    assert resp.status_code == 403


def test_student_join_and_duplicate(client, teacher, student):
    space = _create_space(client, teacher)
    resp = client.post("/api/spaces/join", json={"code": space["code"]}, headers=student)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["my_role"] == "member"
    assert data["can_answer_paper"] is True
    assert data["can_leave_space"] is True
    assert data["can_edit_space"] is False

    dup = client.post("/api/spaces/join", json={"code": space["code"]}, headers=student)
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "ALREADY_IN_SPACE"


def test_join_unknown_code(client, student):
    resp = client.post("/api/spaces/join", json={"code": "SP999999"}, headers=student)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "SPACE_CODE_NOT_FOUND"


def test_space_capacity_full(client, teacher, student):
    space = _create_space(client, teacher, capacity=1)
    resp = client.post("/api/spaces/join", json={"code": space["code"]}, headers=student)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "SPACE_FULL"


def test_space_lists_by_role(client, teacher, student):
    space = _create_space(client, teacher)
    client.post("/api/spaces/join", json={"code": space["code"]}, headers=student)

    teacher_list = client.get("/api/spaces", headers=teacher).json()
    student_list = client.get("/api/spaces", headers=student).json()
    assert len(teacher_list) == 1
    assert len(student_list) == 1
    assert teacher_list[0]["my_role"] == "creator"
    assert student_list[0]["my_role"] == "member"


def test_rename_permissions(client, teacher, student):
    space = _create_space(client, teacher)
    client.post("/api/spaces/join", json={"code": space["code"]}, headers=student)

    assert client.put(
        f"/api/spaces/{space['id']}", json={"name": "24软工2班"}, headers=teacher
    ).status_code == 200
    updated = client.get(f"/api/spaces/{space['id']}", headers=teacher).json()
    assert updated["name"] == "24软工2班"

    resp = client.put(f"/api/spaces/{space['id']}", json={"name": "学生改名"}, headers=student)
    assert resp.status_code == 403


def test_members_and_remove(client, teacher, student):
    space = _create_space(client, teacher)
    client.post("/api/spaces/join", json={"code": space["code"]}, headers=student)
    student_id = _me(client, student)["id"]

    members = client.get(f"/api/spaces/{space['id']}/members", headers=teacher).json()
    assert len(members) == 2
    assert any(m["is_creator"] for m in members)

    assert client.delete(
        f"/api/spaces/{space['id']}/members/{student_id}", headers=teacher
    ).status_code == 204
    assert client.get(f"/api/spaces/{space['id']}", headers=student).status_code == 404


def test_student_leave(client, teacher, student):
    space = _create_space(client, teacher)
    client.post("/api/spaces/join", json={"code": space["code"]}, headers=student)
    assert client.post(f"/api/spaces/{space['id']}/leave", headers=student).status_code == 204
    assert client.get(f"/api/spaces/{space['id']}", headers=student).status_code == 404
    assert client.post(f"/api/spaces/{space['id']}/leave", headers=teacher).status_code == 403


def test_teacher_cannot_leave_as_creator(client, teacher):
    space = _create_space(client, teacher)
    resp = client.post(f"/api/spaces/{space['id']}/leave", headers=teacher)
    assert resp.status_code == 403


def test_dissolve_space(client, teacher, student):
    space = _create_space(client, teacher)
    client.post("/api/spaces/join", json={"code": space["code"]}, headers=student)

    assert client.delete(f"/api/spaces/{space['id']}", headers=teacher).status_code == 204
    assert client.get(f"/api/spaces/{space['id']}", headers=teacher).status_code == 404
    assert client.get("/api/spaces", headers=student).json() == []


def test_non_member_cannot_view_space(client, teacher, student):
    space = _create_space(client, teacher)
    assert client.get(f"/api/spaces/{space['id']}", headers=student).status_code == 404
