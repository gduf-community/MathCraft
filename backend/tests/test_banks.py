"""题库与成员权限测试。"""
from conftest import create_bank, upload_markdown


def _me(client, headers):
    return client.get("/api/auth/me", headers=headers).json()["user"]


def test_create_and_list_bank(client, teacher):
    bank = create_bank(client, teacher, "高等数学")
    assert bank["my_role"] == "owner"
    assert bank["can_manage_members"] is True
    assert bank["code"].startswith("TK")

    owned = client.get("/api/banks?scope=owned", headers=teacher).json()
    assert len(owned) == 1
    assert owned[0]["id"] == bank["id"]


def test_join_bank_and_duplicate(client, teacher, student):
    bank = create_bank(client, teacher)
    resp = client.post("/api/banks/join", json={"code": bank["code"]}, headers=student)
    assert resp.status_code == 200
    assert resp.json()["my_role"] == "member"
    assert resp.json()["can_upload_document"] is False

    dup = client.post("/api/banks/join", json={"code": bank["code"]}, headers=student)
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "ALREADY_IN_BANK"

    joined = client.get("/api/banks?scope=joined", headers=student).json()
    assert len(joined) == 1


def test_join_by_unknown_code(client, student):
    resp = client.post("/api/banks/join", json={"code": "TK00000000"}, headers=student)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "BANK_CODE_NOT_FOUND"


def test_non_member_cannot_view_bank(client, teacher, student):
    bank = create_bank(client, teacher)
    resp = client.get(f"/api/banks/{bank['id']}", headers=student)
    assert resp.status_code == 404


def test_owner_can_list_members(client, teacher, student):
    bank = create_bank(client, teacher)
    client.post("/api/banks/join", json={"code": bank["code"]}, headers=student)

    resp = client.get(f"/api/banks/{bank['id']}/members", headers=teacher)
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 2
    assert any(m["is_creator"] for m in members)
    assert sum(1 for m in members if m["is_me"]) == 1


def test_admin_permissions_super_vs_normal(client, teacher, student):
    bank = create_bank(client, teacher)
    client.post("/api/banks/join", json={"code": bank["code"]}, headers=student)
    student_id = _me(client, student)["id"]

    # 设为管理员（题库默认 admin_level=super）
    assert client.put(
        f"/api/banks/{bank['id']}/members/{student_id}/role",
        json={"role": "admin"},
        headers=teacher,
    ).status_code == 204

    detail = client.get(f"/api/banks/{bank['id']}", headers=student).json()
    assert detail["my_role"] == "admin"
    assert detail["can_upload_document"] is True
    assert detail["can_delete_document"] is True
    assert detail["can_manage_members"] is False

    # 题库级别降为 normal 后，管理员不能删文档
    client.put(f"/api/banks/{bank['id']}", json={"admin_level": "normal"}, headers=teacher)
    detail = client.get(f"/api/banks/{bank['id']}", headers=student).json()
    assert detail["can_delete_document"] is False


def test_document_permissions_for_admin(client, teacher, student):
    bank = create_bank(client, teacher)
    client.post("/api/banks/join", json={"code": bank["code"]}, headers=student)
    student_id = _me(client, student)["id"]
    client.put(
        f"/api/banks/{bank['id']}/members/{student_id}/role",
        json={"role": "admin"},
        headers=teacher,
    )

    doc = upload_markdown(client, student, bank["id"])
    assert client.get(f"/api/banks/{bank['id']}/documents/{doc['document_id']}", headers=student).json()["status"] == "ready"

    # admin_level=super 时管理员可删文档
    assert client.delete(
        f"/api/banks/{bank['id']}/documents/{doc['document_id']}", headers=student
    ).status_code == 204


def test_member_cannot_upload_or_delete(client, teacher, student):
    bank = create_bank(client, teacher)
    client.post("/api/banks/join", json={"code": bank["code"]}, headers=student)

    resp = client.post(
        f"/api/banks/{bank['id']}/documents",
        files={"file": ("x.md", b"# hi", "text/markdown")},
        headers=student,
    )
    assert resp.status_code == 403

    doc = upload_markdown(client, teacher, bank["id"])
    assert client.delete(
        f"/api/banks/{bank['id']}/documents/{doc['document_id']}", headers=student
    ).status_code == 403


def test_transfer_bank(client, teacher, student):
    bank = create_bank(client, teacher)
    client.post("/api/banks/join", json={"code": bank["code"]}, headers=student)
    student_id = _me(client, student)["id"]

    assert client.post(
        f"/api/banks/{bank['id']}/transfer",
        json={"target_user_id": student_id},
        headers=teacher,
    ).status_code == 204

    teacher_detail = client.get(f"/api/banks/{bank['id']}", headers=teacher).json()
    assert teacher_detail["my_role"] == "admin"
    assert teacher_detail["can_manage_members"] is False

    student_detail = client.get(f"/api/banks/{bank['id']}", headers=student).json()
    assert student_detail["my_role"] == "owner"
    assert student_detail["can_manage_members"] is True

    # 转让后 creator_id 同步转移：双方看到的创建者都是学生
    assert student_detail["creator"]["id"] == student_id
    teacher_members = client.get(f"/api/banks/{bank['id']}/members", headers=teacher).json()
    student_members = client.get(f"/api/banks/{bank['id']}/members", headers=student).json()
    by_role = {m["user"]["id"]: m for m in teacher_members}
    assert by_role[student_id]["is_creator"] is True
    assert by_role[student_id]["admin_level"] == "super"
    teacher_mid = next(m["user"]["id"] for m in teacher_members if m["is_me"])
    assert by_role[teacher_mid]["is_creator"] is False
    assert by_role[teacher_mid]["is_admin"] is True
    assert by_role[teacher_mid]["admin_level"] == "super"
    # 学生视角的教师行：不是创建者，只是超级管理员
    s_by_id = {m["user"]["id"]: m for m in student_members}
    assert s_by_id[teacher_mid]["is_creator"] is False
    assert s_by_id[teacher_mid]["admin_level"] == "super"

    # 新 owner 不能退出，原 owner（现 admin）可以退出
    assert client.post(f"/api/banks/{bank['id']}/quit", headers=student).status_code == 403
    assert client.post(f"/api/banks/{bank['id']}/quit", headers=teacher).status_code == 204


def test_remove_member(client, teacher, student):
    bank = create_bank(client, teacher)
    client.post("/api/banks/join", json={"code": bank["code"]}, headers=student)
    student_id = _me(client, student)["id"]

    resp = client.delete(f"/api/banks/{bank['id']}/members/{student_id}", headers=teacher)
    assert resp.status_code == 204
    assert client.get(f"/api/banks/{bank['id']}", headers=student).status_code == 404

    members = client.get(f"/api/banks/{bank['id']}/members", headers=teacher).json()
    assert len(members) == 1


def test_owner_and_admin_cannot_be_removed(client, teacher, student):
    bank = create_bank(client, teacher)
    client.post("/api/banks/join", json={"code": bank["code"]}, headers=student)
    teacher_id = _me(client, teacher)["id"]

    # 不能移出创建者
    assert client.delete(f"/api/banks/{bank['id']}/members/{teacher_id}", headers=teacher).status_code == 403


def test_delete_bank(client, teacher):
    bank = create_bank(client, teacher)
    doc = upload_markdown(client, teacher, bank["id"])
    assert client.delete(f"/api/banks/{bank['id']}", headers=teacher).status_code == 204
    assert client.get(f"/api/banks/{bank['id']}", headers=teacher).status_code == 404
    assert client.get("/api/banks?scope=owned", headers=teacher).json() == []
