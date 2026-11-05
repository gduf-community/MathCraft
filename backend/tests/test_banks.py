from conftest import create_bank, upload_markdown


def _me(client, headers):
    return client.get("/api/auth/me", headers=headers).json()["user"]


def add_member(client, owner_headers, bank_id, account="student", role="readonly"):
    return client.post(
        f"/api/banks/{bank_id}/members",
        json={"account": account, "role": role},
        headers=owner_headers,
    )


def test_only_teacher_can_create_bank(client, teacher, student):
    bank = create_bank(client, teacher, "高等数学")
    assert bank["my_role"] == "creator"
    assert bank["can_manage_members"] is True
    assert bank["code"].startswith("TK")
    assert client.post("/api/banks", json={"name": "学生题库"}, headers=student).status_code == 403


def test_creator_adds_member_by_login_account(client, teacher, student):
    bank = create_bank(client, teacher)
    added = add_member(client, teacher, bank["id"])
    assert added.status_code == 201, added.text
    assert added.json()["role"] == "readonly"
    assert added.json()["user"]["account"] == "student"

    duplicate = add_member(client, teacher, bank["id"])
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "ALREADY_IN_BANK"

    assert client.post("/api/banks/join", json={"code": bank["code"]}, headers=student).status_code == 404


def test_unknown_account_cannot_be_added(client, teacher):
    bank = create_bank(client, teacher)
    response = add_member(client, teacher, bank["id"], account="missing")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "USER_NOT_FOUND"


def test_three_member_roles_have_expected_capabilities(client, teacher, student):
    bank = create_bank(client, teacher)
    assert add_member(client, teacher, bank["id"], role="editor").status_code == 201

    editor = client.get(f"/api/banks/{bank['id']}", headers=student)
    assert editor.status_code == 200
    assert editor.json()["my_role"] == "editor"
    assert editor.json()["can_upload_document"] is True
    assert editor.json()["can_delete_document"] is True
    assert editor.json()["can_download_document"] is True
    assert editor.json()["can_manage_members"] is False
    assert editor.json()["can_delete_bank"] is False

    student_id = _me(client, student)["id"]
    assert client.put(
        f"/api/banks/{bank['id']}/members/{student_id}/role",
        json={"role": "readonly"},
        headers=teacher,
    ).status_code == 204
    readonly = client.get(f"/api/banks/{bank['id']}", headers=student).json()
    assert readonly["my_role"] == "readonly"
    assert readonly["can_upload_document"] is False
    assert readonly["can_delete_document"] is False
    assert readonly["can_download_document"] is True


def test_editor_can_modify_documents_but_cannot_manage_members(client, teacher, student):
    bank = create_bank(client, teacher)
    student_id = _me(client, student)["id"]
    assert add_member(client, teacher, bank["id"], role="editor").status_code == 201

    document = upload_markdown(client, student, bank["id"])
    assert client.get(
        f"/api/banks/{bank['id']}/documents/{document['document_id']}", headers=student
    ).json()["status"] == "ready"
    assert client.delete(
        f"/api/banks/{bank['id']}/documents/{document['document_id']}", headers=student
    ).status_code == 204
    assert client.post(
        f"/api/banks/{bank['id']}/members",
        json={"account": "teacher", "role": "readonly"},
        headers=student,
    ).status_code == 403


def test_readonly_can_read_but_cannot_modify_documents(client, teacher, student):
    bank = create_bank(client, teacher)
    assert add_member(client, teacher, bank["id"], role="readonly").status_code == 201
    document = upload_markdown(client, teacher, bank["id"])

    assert client.get(f"/api/banks/{bank['id']}/documents", headers=student).status_code == 200
    assert client.get(
        f"/api/banks/{bank['id']}/documents/{document['document_id']}/download", headers=student
    ).status_code == 200
    assert client.post(
        f"/api/banks/{bank['id']}/documents",
        files={"file": ("x.md", b"# hi", "text/markdown")},
        headers=student,
    ).status_code == 403
    assert client.delete(
        f"/api/banks/{bank['id']}/documents/{document['document_id']}", headers=student
    ).status_code == 403


def test_non_member_cannot_view_or_use_bank(client, teacher, student):
    bank = create_bank(client, teacher)
    assert client.get(f"/api/banks/{bank['id']}", headers=student).status_code == 404
    assert client.get(f"/api/banks/{bank['id']}/documents", headers=student).status_code == 404
    assert client.post(
        f"/api/banks/{bank['id']}/search",
        json={"query": "导数"},
        headers=student,
    ).status_code == 404


def test_removed_member_cannot_restore_membership(client, teacher, student):
    bank = create_bank(client, teacher)
    assert add_member(client, teacher, bank["id"]).status_code == 201
    student_id = _me(client, student)["id"]
    assert client.delete(f"/api/banks/{bank['id']}/members/{student_id}", headers=teacher).status_code == 204
    assert client.get(f"/api/banks/{bank['id']}", headers=student).status_code == 404
    assert client.post("/api/banks/join", json={"code": bank["code"]}, headers=student).status_code == 404
    assert add_member(client, teacher, bank["id"]).status_code == 201


def test_historical_student_resource_remains_accessible(client, db, student):
    from app.models import Bank, BankMember
    from app.models.base import new_id

    bank = Bank(
        id=new_id("bank"),
        name="历史学生题库",
        code="TKHISTORY001",
        creator_id=_me(client, student)["id"],
        admin_level="super",
        capacity=200,
        status="active",
    )
    db.add(bank)
    db.add(BankMember(id=new_id("bm"), bank_id=bank.id, user_id=bank.creator_id, role="creator", status="active"))
    db.commit()

    response = client.get(f"/api/banks/{bank.id}", headers=student)
    assert response.status_code == 200
    assert response.json()["my_role"] == "creator"


def test_creator_can_remove_member_but_cannot_remove_self(client, teacher, student):
    bank = create_bank(client, teacher)
    assert add_member(client, teacher, bank["id"]).status_code == 201
    student_id = _me(client, student)["id"]
    assert client.delete(f"/api/banks/{bank['id']}/members/{student_id}", headers=teacher).status_code == 204
    teacher_id = _me(client, teacher)["id"]
    assert client.delete(f"/api/banks/{bank['id']}/members/{teacher_id}", headers=teacher).status_code == 403
