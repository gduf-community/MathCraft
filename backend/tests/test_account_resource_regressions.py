"""账号整合后的资源隔离回归，全部使用临时数据库和假服务。"""
import re

from app.models import BankMember, Paper, PaperAttempt, User
from app.models.base import new_id
from conftest import create_bank, make_questions


def test_transfer_keeps_previous_creator_edit_access(client, teacher, db):
    bank = create_bank(client, teacher)
    target = User(id=new_id("u"), account="second-teacher", password_hash="fake-hash",
                  role="teacher", identity="教师", display_name="接收者", status="active")
    db.add(target)
    db.flush()
    db.add(BankMember(id=new_id("bm"), bank_id=bank["id"], user_id=target.id,
                      role="readonly", status="active"))
    db.commit()
    response = client.post(f"/api/banks/{bank['id']}/transfer", headers=teacher,
                           json={"target_user_id": target.id})
    assert response.status_code == 204, response.text
    detail = client.get(f"/api/banks/{bank['id']}", headers=teacher).json()
    assert detail["my_role"] == "editor"
    assert detail["can_upload_document"] is True
    assert detail["can_manage_members"] is False


def test_removed_student_cannot_rejoin_space(client, teacher, student):
    space = client.post("/api/spaces", headers=teacher,
                        json={"name": "隔离班级", "capacity": 50}).json()
    assert re.fullmatch(r"SP[0-9A-F]{24}", space["code"])
    assert client.post("/api/spaces/join", headers=student,
                       json={"code": space["code"]}).status_code == 200
    student_id = client.get("/api/auth/me", headers=student).json()["user"]["id"]
    assert client.delete(f"/api/spaces/{space['id']}/members/{student_id}",
                         headers=teacher).status_code == 204
    assert client.post("/api/spaces/join", headers=student,
                       json={"code": space["code"]}).status_code == 403


def test_platform_admin_cannot_be_added_to_bank(client, teacher, db):
    db.add(User(id=new_id("u"), account="operations-only", password_hash="fake-hash",
                role="admin", identity="管理员", display_name="运维", status="active"))
    db.commit()
    bank = create_bank(client, teacher)
    response = client.post(f"/api/banks/{bank['id']}/members", headers=teacher,
                           json={"account": "operations-only", "role": "editor"})
    assert response.status_code == 403


def test_submitted_paper_respects_review_flag(client, teacher, student, db):
    teacher_id = client.get("/api/auth/me", headers=teacher).json()["user"]["id"]
    student_id = client.get("/api/auth/me", headers=student).json()["user"]["id"]
    space = client.post("/api/spaces", headers=teacher,
                        json={"name": "复盘班级", "capacity": 50}).json()
    client.post("/api/spaces/join", headers=student, json={"code": space["code"]})
    questions = make_questions(db, teacher_id, [("single", "A", 5)])
    response = client.post("/api/papers", headers=teacher, json={
        "name": "关闭复盘", "questions": questions, "space_ids": [space["id"]],
        "is_published": True, "save_to_records": True, "allow_review": False,
    })
    assert response.status_code == 201, response.text
    paper_id = response.json()["id"]
    db.add(PaperAttempt(id=new_id("pa"), paper_id=paper_id, space_id=space["id"],
                        student_id=student_id, status="submitted", total_score=5))
    db.commit()
    detail = client.get(f"/api/papers/{paper_id}", headers=student)
    assert detail.status_code == 200
    assert all("answer" not in q and "analysis" not in q for q in detail.json()["questions"])
    paper = db.get(Paper, paper_id)
    paper.allow_review = True
    db.commit()
    detail = client.get(f"/api/papers/{paper_id}", headers=student)
    assert all("answer" in q and "analysis" in q for q in detail.json()["questions"])
