"""最近批次恢复不能重新暴露删除中资料或已撤权题库的题目。"""
import pytest

from app.models import Bank, BankMember, DeletionOperation, Document, GenerationBatch, User
from app.models import Question as QuestionRow
from app.models.base import new_id
from app.schemas.api import GenerateStartBody
from app.services import generation
from app.services.rag import vectorstore
from test_deletion_retry_acid import material
from conftest import create_bank
from test_generation_acid import fake_generation, one_question


@pytest.fixture
def completed_generation(client, teacher, db, material, monkeypatch):
    """真实完成 SQL 任务；原件、向量和模型由隔离夹具提供。"""
    bank_id, document_id, _ = material
    owner = db.query(User).filter_by(account="teacher").one()
    body = GenerateStartBody(
        bank_id=bank_id, document_id=document_id,
        types=[{"type": "single", "count": 1}], difficulty="中", scope="导数",
    )
    fake_generation(monkeypatch)
    task = generation.accept_task(db, owner.id, body)
    generation.run_generation_task(task.id, owner.id, "fake-test-key", body, run_id=task.run_id)
    result = generation.read_task(task.id, owner.id)
    assert result["done"] and result["error"] is None
    assert len(result["questions"]) == 1
    before = client.get("/api/generate/batches/latest", headers=teacher)
    assert before.status_code == 200, before.text
    assert before.json()["batch_id"] == result["batch_id"]
    assert len(before.json()["questions"]) == 1
    return bank_id, document_id, owner.id, result["batch_id"], task.id


def _filters(bank_id: str, document_id: str, scope: str) -> dict[str, str]:
    if scope == "bank":
        return {"bank_id": bank_id}
    if scope == "document":
        return {"bank_id": bank_id, "document_id": document_id}
    return {}


@pytest.mark.parametrize("resource", ["document", "bank"])
@pytest.mark.parametrize("scope", ["all", "bank", "document"])
def test_latest_batch_refuses_restore_after_vector_delete_failure(
    client, teacher, db, completed_generation, monkeypatch, resource, scope,
):
    bank_id, document_id, _, batch_id, task_id = completed_generation

    def fail_vectors(*args):
        raise vectorstore.VectorStoreError("delete", "FakeVectorDeleteFailure")

    operation = "delete_document_chunks" if resource == "document" else "delete_bank_collection"
    monkeypatch.setattr(vectorstore, operation, fail_vectors)
    url = f"/api/banks/{bank_id}" + (f"/documents/{document_id}" if resource == "document" else "")
    deleted = client.delete(url, headers=teacher)
    assert deleted.status_code == 503, deleted.text
    db.expire_all()
    assert db.query(DeletionOperation).one().status == "pending"
    target = db.get(Document, document_id) if resource == "document" else db.get(Bank, bank_id)
    assert target.status == "deleting"
    # SQL 尚未清理：批次和题目副本还在，刷新入口必须独立执行资源复核。
    assert db.get(GenerationBatch, batch_id) is not None
    response = client.get("/api/generate/batches/latest", headers=teacher,
                          params=_filters(bank_id, document_id, scope))
    assert response.status_code == 200, response.text
    assert response.json() == {"batch_id": None, "questions": []}
    assert client.get(f"/api/generate/progress/{task_id}", headers=teacher).status_code == 404
    for params in ({}, {"batch_id": batch_id}):
        listing = client.get("/api/questions", headers=teacher, params=params)
        assert listing.status_code == 200, listing.text
        assert listing.json()["total"] == 0
        assert listing.json()["items"] == []


@pytest.mark.parametrize("membership", ["removed", "quit"])
@pytest.mark.parametrize("scope", ["all", "document"])
def test_latest_batch_does_not_disclose_owned_batch_after_membership_revoked(
    client, teacher, db, completed_generation, membership, scope,
):
    bank_id, document_id, owner_id, batch_id, _ = completed_generation
    member = db.query(BankMember).filter_by(bank_id=bank_id, user_id=owner_id).one()
    if membership == "removed":
        db.delete(member)
    else:
        member.status = "quit"
    db.commit()
    assert db.get(GenerationBatch, batch_id) is not None
    response = client.get("/api/generate/batches/latest", headers=teacher,
                          params=_filters(bank_id, document_id, scope))
    assert response.status_code == 200, response.text
    assert response.json() == {"batch_id": None, "questions": []}
    # 私人题目列表保留既有 created_by 读取政策，不引入新的成员门禁。
    listing = client.get("/api/questions", headers=teacher, params={"batch_id": batch_id})
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == len(listing.json()["items"]) == 1


def test_latest_batch_refuses_orphaned_source_document(client, teacher, db, completed_generation):
    _, document_id, _, batch_id, _ = completed_generation
    db.delete(db.get(Document, document_id))
    db.commit()
    assert db.get(GenerationBatch, batch_id) is not None
    response = client.get("/api/generate/batches/latest", headers=teacher)
    assert response.status_code == 200, response.text
    assert response.json() == {"batch_id": None, "questions": []}
    listing = client.get("/api/questions", headers=teacher, params={"batch_id": batch_id})
    assert listing.status_code == 200, listing.text
    assert listing.json()["total"] == 0
    assert listing.json()["items"] == []


@pytest.mark.parametrize("status", ["parsing", "embedding", "failed"])
def test_private_question_list_keeps_old_questions_during_reprocessing(
    client, teacher, student, db, completed_generation, status,
):
    _, document_id, _, batch_id, _ = completed_generation
    db.get(Document, document_id).status = status
    db.commit()
    response = client.get("/api/questions", headers=teacher, params={"batch_id": batch_id})
    assert response.status_code == 200, response.text
    assert response.json()["total"] == len(response.json()["items"]) == 1
    others = client.get("/api/questions", headers=student, params={"batch_id": batch_id})
    assert others.status_code == 200, others.text
    assert others.json()["total"] == 0 and others.json()["items"] == []


def test_question_list_hides_document_moved_to_another_bank(client, teacher, db, completed_generation):
    _, document_id, _, batch_id, _ = completed_generation
    other_bank = create_bank(client, teacher, "其他题库")
    db.get(Document, document_id).bank_id = other_bank["id"]
    db.commit()
    for params in ({}, {"batch_id": batch_id}):
        response = client.get("/api/questions", headers=teacher, params=params)
        assert response.status_code == 200, response.text
        assert response.json()["total"] == 0 and response.json()["items"] == []


def test_question_pagination_counts_only_current_available_material(
    client, teacher, db, completed_generation,
):
    bank_id, document_id, owner_id, old_batch_id, _ = completed_generation
    current = Document(
        id=new_id("doc"), bank_id=bank_id, name="可用资料.md", format="MD", size_bytes=1,
        storage_path="fake-unused.md", status="ready", uploader_id=owner_id,
    )
    db.add(current)
    db.flush()
    body = GenerateStartBody(bank_id=bank_id, document_id=current.id,
                             types=[{"type": "single", "count": 2}], difficulty="中")
    batch = generation.persist_batch(
        db, owner_id, bank_id, current.id, "parametric", generation.build_params(body), None,
        [one_question(), one_question().model_copy(update={"stem": "第二道可用题目"})],
    )
    expected_ids = {q.id for q in db.query(QuestionRow).filter_by(batch_id=batch.id)}
    db.get(Document, document_id).status = "deleting"
    db.commit()
    seen = set()
    for page in (1, 2, 3):
        response = client.get("/api/questions", headers=teacher,
                              params={"bank_id": bank_id, "page_size": 1, "page": page})
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["total"] == 2
        assert len(data["items"]) == (1 if page <= 2 else 0)
        seen.update(q["id"] for q in data["items"])
        assert all(q["batch_id"] != old_batch_id for q in data["items"])
    assert seen == expected_ids
