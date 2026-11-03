"""出题任务、批次落库、题目 CRUD 测试。"""
from app.models import Document
from app.models.base import new_id
from app.services import generation
from conftest import create_bank, upload_markdown

GEN_BODY_TEMPLATE = {
    "bank_id": "",
    "document_id": "",
    "types": [{"type": "single", "count": 2}],
    "difficulty": "中",
    "scope": "导数",
    "source_mode": "variant_data",
    "existing_stems": [],
}


def _setup(client, teacher, db=None):
    bank = create_bank(client, teacher)
    doc = upload_markdown(client, teacher, bank["id"])
    client.put(
        "/api/users/me/model-settings",
        json={"deepseek_api_key": "sk-test-deepseek"},
        headers=teacher,
    )
    return bank, doc


def _body(bank, doc, **overrides):
    body = dict(GEN_BODY_TEMPLATE)
    body["bank_id"] = bank["id"]
    body["document_id"] = doc["document_id"]
    body.update(overrides)
    return body


def test_async_generation_progress_and_persistence(client, teacher):
    bank, doc = _setup(client, teacher)

    resp = client.post("/api/generate/start", json=_body(bank, doc), headers=teacher)
    assert resp.status_code == 202, resp.text
    task_id = resp.json()["task_id"]

    progress = client.get(f"/api/generate/progress/{task_id}", headers=teacher).json()
    assert progress["done"] is True
    assert progress["error"] is None
    assert len(progress["questions"]) == 2
    assert progress["batch_id"].startswith("batch_")

    batch_id = progress["batch_id"]
    listing = client.get(f"/api/questions?batch_id={batch_id}", headers=teacher).json()
    assert listing["total"] == 2
    assert len(listing["items"]) == 2
    assert listing["items"][0]["type"] == "single"
    assert listing["items"][0]["options"]

    latest = client.get(
        f"/api/generate/batches/latest?bank_id={bank['id']}&document_id={doc['document_id']}",
        headers=teacher,
    ).json()
    assert latest["batch_id"] == batch_id
    assert len(latest["questions"]) == 2


def test_question_update_and_delete(client, teacher):
    bank, doc = _setup(client, teacher)
    client.post("/api/generate/start", json=_body(bank, doc), headers=teacher)
    latest = client.get("/api/generate/batches/latest", headers=teacher).json()
    q = latest["questions"][0]

    resp = client.put(
        f"/api/questions/{q['id']}",
        json={"score": 10, "stem": "修改后的题干"},
        headers=teacher,
    )
    assert resp.status_code == 200
    assert resp.json()["score"] == 10
    assert resp.json()["stem"] == "修改后的题干"

    assert client.delete(f"/api/questions/{q['id']}", headers=teacher).status_code == 204
    remaining = client.get("/api/questions", headers=teacher).json()["items"]
    assert all(item["id"] != q["id"] for item in remaining)


def test_batch_delete_questions(client, teacher):
    bank, doc = _setup(client, teacher)
    client.post("/api/generate/start", json=_body(bank, doc), headers=teacher)
    latest = client.get("/api/generate/batches/latest", headers=teacher).json()
    ids = [q["id"] for q in latest["questions"]]
    assert len(ids) == 2

    resp = client.post("/api/questions/batch-delete", json={"question_ids": ids}, headers=teacher)
    assert resp.status_code == 204
    assert client.get("/api/questions", headers=teacher).json()["total"] == 0


def test_generation_requires_deepseek_key(client, teacher, student):
    bank, doc = _setup(client, teacher)
    client.post("/api/banks/join", json={"code": bank["code"]}, headers=student)

    resp = client.post("/api/generate/start", json=_body(bank, doc), headers=student)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "DEEPSEEK_KEY_MISSING"


def test_generation_requires_ready_document(client, teacher, db):
    bank = create_bank(client, teacher)
    doc = Document(
        id=new_id("doc"),
        bank_id=bank["id"],
        name="未完成.pdf",
        format="PDF",
        size_bytes=1,
        storage_path="data/uploads/x.pdf",
        status="parsing",
        uploader_id=client.get("/api/auth/me", headers=teacher).json()["user"]["id"],
    )
    db.add(doc)
    db.commit()

    client.put(
        "/api/users/me/model-settings",
        json={"deepseek_api_key": "sk-test-deepseek"},
        headers=teacher,
    )
    resp = client.post(
        "/api/generate/start",
        json=_body(bank, {"document_id": doc.id}),
        headers=teacher,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == "DOCUMENT_NOT_READY"


def test_generation_busy(client, teacher, monkeypatch):
    bank, doc = _setup(client, teacher)
    monkeypatch.setattr(generation, "acquire_lock", lambda user_id: False)
    resp = client.post("/api/generate/start", json=_body(bank, doc), headers=teacher)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "GENERATION_BUSY"


def test_sync_generation(client, teacher):
    bank, doc = _setup(client, teacher)
    resp = client.post("/api/generate", json=_body(bank, doc), headers=teacher)
    assert resp.status_code == 200, resp.text
    questions = resp.json()
    assert len(questions) == 2
    assert questions[0]["type"] == "single"


def test_sync_generation_non_member(client, teacher, student):
    bank, doc = _setup(client, teacher)
    resp = client.post("/api/generate", json=_body(bank, doc), headers=student)
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == "BANK_NOT_FOUND"
