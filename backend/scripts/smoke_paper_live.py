"""真实服务组卷/作答/统计冒烟：直接插入题目，再走完整 API 流程。

前置：后端已在 127.0.0.1:8000 运行。
用法：uv run python scripts/smoke_paper_live.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx

from app.db import SessionLocal
from app.models import GenerationBatch, Question, User
from app.models.base import new_id

BASE = "http://127.0.0.1:8000"


def main() -> None:
    c = httpx.Client(base_url=BASE, timeout=60.0)
    teacher = c.post("/api/auth/login", json={"account": "teacher", "password": "123123", "role": "teacher"}).json()
    student = c.post("/api/auth/login", json={"account": "student", "password": "123123", "role": "student"}).json()
    th = {"Authorization": f"Bearer {teacher['token']}"}
    sh = {"Authorization": f"Bearer {student['token']}"}
    teacher_id = teacher["user"]["id"]

    db = SessionLocal()
    try:
        batch = GenerationBatch(
            id=new_id("batch"), user_id=teacher_id, bank_id="bank_smoke",
            document_id="doc_smoke", mode="parametric", params_json="{}",
            question_count=2, status="done",
        )
        db.add(batch)
        db.flush()
        qids = []
        for i in range(2):
            q = Question(
                id=new_id("q"), batch_id=batch.id, bank_id="bank_smoke", document_id="doc_smoke",
                type="single", score=5, difficulty="中", stem=f"冒烟题 {i + 1}",
                options_json=json.dumps([{"label": x, "text": x} for x in "ABCD"], ensure_ascii=False),
                answer="A", analysis="解析", knowledge_point="导数", created_by=teacher_id,
            )
            db.add(q)
            qids.append(q.id)
        db.commit()
    finally:
        db.close()
    print("已插入题目:", qids)

    space = c.post("/api/spaces", json={"name": "组卷冒烟班级", "capacity": 50}, headers=th).json()
    assert c.post("/api/spaces/join", json={"code": space["code"]}, headers=sh).status_code == 200
    paper_resp = c.post(
        "/api/papers",
        json={
            "name": "冒烟试卷", "questions": qids, "space_ids": [space["id"]],
            "save_to_records": True, "is_published": True,
        },
        headers=th,
    )
    paper_resp.raise_for_status()
    paper = paper_resp.json()
    print("组卷发布:", paper_resp.status_code, paper["status"], paper["question_count"], paper["total_score"])

    start = c.post(f"/api/papers/{paper['id']}/attempts", json={"space_id": space["id"]}, headers=sh)
    start.raise_for_status()
    attempt = start.json()
    answers = [
        {"paper_question_id": q["paper_question_id"], "choices": ["A"], "text": ""}
        for q in attempt["questions"]
    ]
    submit = c.post(f"/api/attempts/{attempt['attempt']['id']}/submit", json={"answers": answers}, headers=sh)
    submit.raise_for_status()
    print("学生交卷:", submit.status_code, submit.json()["score"], "/", submit.json()["total_score"])

    stats = c.get(f"/api/papers/{paper['id']}/statistics?space_id={space['id']}", headers=th)
    stats.raise_for_status()
    print("教师统计:", stats.status_code, stats.json()["submitted_count"], stats.json()["questions"][0]["option_counts"])

    # 清理
    c.delete(f"/api/papers/{paper['id']}", headers=th)
    c.delete(f"/api/spaces/{space['id']}", headers=th)
    db = SessionLocal()
    try:
        db.query(Question).filter(Question.id.in_(qids)).delete(synchronize_session=False)
        db.query(GenerationBatch).filter(GenerationBatch.id == batch.id).delete(synchronize_session=False)
        db.commit()
    finally:
        db.close()
    print("清理完成")


if __name__ == "__main__":
    main()
