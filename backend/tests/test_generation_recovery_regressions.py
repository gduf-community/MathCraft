"""认领故障、认证撤销、结果失效与旧版本恢复的行为回归。"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from alembic import command
from alembic.config import Config
from redis.exceptions import RedisError
from sqlalchemy import create_engine, event, inspect, text

from app.api import chat, generate
from app.config import settings
from app.db import SessionLocal, engine
from app.models import BankMember, ChatSession, Document, GenerationBatch, User
from app.models import Question as QuestionRow
from app.models.generation_task import GenerationTask
from app.schemas.api import GenerateStartBody
from app.services import cache, generation
from test_chat_modes import PNG
from test_generation_acid import fake_generation, resources, session_for


@pytest.mark.parametrize("failure", ["params", "claim_commit", "initial_read"])
def test_claim_failure_ends_task_and_releases_acceptance_gate(
    client, teacher, db, monkeypatch, failure,
):
    owner, body = resources(client, teacher, db)
    request = GenerateStartBody(**body)
    task = generation.accept_task(db, owner, request)
    task_id, run_id = task.id, task.run_id
    fake_generation(monkeypatch)
    if failure == "params":
        task.params_json = "{invalid"
        db.commit()
    elif failure == "claim_commit":
        def fail_once(session):
            event.remove(SessionLocal.class_, "before_commit", fail_once)
            raise RuntimeError("fake claim commit failure")

        event.listen(SessionLocal.class_, "before_commit", fail_once)
    else:
        def fail_read(connection, cursor, statement, parameters, context, executemany):
            if "FROM generation_tasks" in statement:
                event.remove(engine, "before_cursor_execute", fail_read)
                raise RuntimeError("fake claim read failure")

        event.listen(engine, "before_cursor_execute", fail_read)

    generation.run_generation_task(task_id, owner, "fake-key", request, run_id=run_id)
    db.expire_all()
    assert db.get(GenerationTask, task_id).status == "failed"
    assert generation.read_task(task_id, owner)["done"]
    assert cache.get_redis().get(cache.PREFIX_GEN_LOCK.format(user_id=owner)) is None
    assert db.query(GenerationBatch).count() == 0
    assert generation.accept_task(db, owner, request).id != task_id


def test_request_revoked_during_model_settings_lookup_cannot_accept_task(
    client, teacher, db, monkeypatch,
):
    owner, body = resources(client, teacher, db)
    original = generate.require_deepseek_key

    def revoke(session, user_id):
        key = original(session, user_id)
        session.rollback()
        with SessionLocal() as other:
            other.get(User, user_id).auth_version += 1
            other.commit()
        return key

    worker = Mock()
    monkeypatch.setattr(generate, "require_deepseek_key", revoke)
    monkeypatch.setattr(generation, "run_generation_task", worker)
    response = client.post("/api/generate/start", headers=teacher, json=body)
    assert response.status_code == 401, response.text
    assert response.json()["detail"]["code"] == "SESSION_REVOKED"
    worker.assert_not_called()
    assert db.query(GenerationTask).filter_by(user_id=owner).count() == 0


def test_queued_task_with_revoked_request_cannot_start_model(client, teacher, db, monkeypatch):
    owner, body = resources(client, teacher, db)
    request = GenerateStartBody(**body)
    version = db.get(User, owner).auth_version
    task = generation.accept_task(db, owner, request, auth_version=version)
    task_id, run_id = task.id, task.run_id
    db.get(User, owner).auth_version += 1
    db.commit()
    model = Mock()
    monkeypatch.setattr(generation.question_gen, "generate_questions", model)
    generation.run_generation_task(task_id, owner, "fake-revoked-key", request,
                                   run_id=run_id, auth_version=version)
    model.assert_not_called()
    db.expire_all()
    assert db.get(GenerationTask, task_id).status == "failed"
    assert "fake-revoked-key" not in db.get(GenerationTask, task_id).params_json


@pytest.mark.parametrize("invalid", ["user", "run", "running"])
def test_unclaimed_worker_cannot_fail_or_unlock_another_run(client, teacher, db, monkeypatch, invalid):
    owner, body = resources(client, teacher, db)
    request = GenerateStartBody(**body)
    task = generation.accept_task(db, owner, request)
    task_id, run_id = task.id, task.run_id
    if invalid == "running":
        task.status = "running"
        db.commit()
    model = Mock()
    monkeypatch.setattr(generation.question_gen, "generate_questions", model)
    generation.run_generation_task(
        task_id, "wrong-owner" if invalid == "user" else owner, "fake-key", request,
        run_id="wrong-run" if invalid == "run" else run_id,
    )
    model.assert_not_called()
    db.expire_all()
    assert db.get(GenerationTask, task_id).status == ("running" if invalid == "running" else "queued")
    assert cache.get_redis().get(cache.PREFIX_GEN_LOCK.format(user_id=owner)) == f"{task_id}:{run_id}"


def test_initial_read_failure_cannot_fail_another_owners_task(client, teacher, db, monkeypatch):
    owner, body = resources(client, teacher, db)
    request = GenerateStartBody(**body)
    task = generation.accept_task(db, owner, request)
    task_id, run_id = task.id, task.run_id

    def fail_read(connection, cursor, statement, parameters, context, executemany):
        if "FROM generation_tasks" in statement:
            event.remove(engine, "before_cursor_execute", fail_read)
            raise RuntimeError("fake claim read failure")

    event.listen(engine, "before_cursor_execute", fail_read)
    generation.run_generation_task(task_id, "wrong-owner", "fake-key", request, run_id=run_id)
    db.expire_all()
    assert db.get(GenerationTask, task_id).status == "queued"
    assert cache.get_redis().get(cache.PREFIX_GEN_LOCK.format(user_id=owner)) == f"{task_id}:{run_id}"


@pytest.mark.parametrize("change", ["batch", "question", "document", "membership", "cleared"])
def test_task_poll_cannot_return_deleted_or_unauthorized_result(
    client, teacher, db, monkeypatch, change,
):
    owner, body = resources(client, teacher, db)
    request = GenerateStartBody(**body)
    task = generation.accept_task(db, owner, request)
    task_id, run_id = task.id, task.run_id
    fake_generation(monkeypatch)
    generation.run_generation_task(task_id, owner, "fake-key", request, run_id=run_id)
    result = generation.read_task(task_id, owner)
    assert result["questions"]
    db.expire_all()
    if change == "batch":
        db.query(QuestionRow).filter_by(batch_id=result["batch_id"]).delete()
        db.query(GenerationBatch).filter_by(id=result["batch_id"]).delete()
    elif change == "question":
        db.query(QuestionRow).filter_by(batch_id=result["batch_id"]).delete()
    elif change == "cleared":
        task = db.get(GenerationTask, task_id)
        task.batch_id, task.result_json, task.review_json = None, None, None
    elif change == "document":
        db.query(Document).filter_by(id=body["document_id"]).delete()
    else:
        db.query(BankMember).filter_by(bank_id=body["bank_id"], user_id=owner).delete()
    db.commit()
    response = client.get(f"/api/generate/progress/{task_id}", headers=teacher)
    if change in ("batch", "question", "cleared"):
        assert response.status_code == 200, response.text
        assert response.json()["done"]
        assert response.json()["questions"] == []
        assert response.json()["batch_id"] is None
        assert response.json()["error"]["message"]
    else:
        assert response.status_code == 404, response.text
    assert "导数事务测试题" not in response.text


def test_chat_rechecks_original_auth_version_before_starting_model(
    client, teacher, db, monkeypatch,
):
    _, body = resources(client, teacher, db)
    session_id = session_for(client, teacher, body)
    original = chat.get_effective_deepseek_key

    def revoke(session, user_id):
        key = original(session, user_id)
        session.rollback()
        with SessionLocal() as other:
            other.get(User, user_id).auth_version += 1
            other.commit()
        return key

    detect = Mock()
    monkeypatch.setattr(chat, "get_effective_deepseek_key", revoke)
    monkeypatch.setattr(chat, "detect_intent", detect)
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": "继续出题"})
    assert response.status_code == 401, response.text
    detect.assert_not_called()
    db.expire_all()
    assert db.get(ChatSession, session_id).run_status == "idle"


def test_hyde_cache_write_failure_preserves_generated_context(
    client, teacher, db, monkeypatch, caplog,
):
    _, body = resources(client, teacher, db)
    r = cache.get_redis()
    original_set = r.set

    def fail_hyde(key, *args, **kwargs):
        if key.startswith("rag:hyde:"):
            raise RedisError("fake-sensitive-cache-detail")
        return original_set(key, *args, **kwargs)

    monkeypatch.setattr(r, "set", fail_hyde)
    expected = "假设段落：导数的定义与求导法则。"
    request = GenerateStartBody(**body)
    assert generation.get_hyde(generation.build_params(request), request, "fake-key") == expected
    assert "HyDE" in caplog.text
    assert "fake-sensitive-cache-detail" not in caplog.text


def test_chat_with_existing_scope_never_calls_hyde(client, teacher, db, monkeypatch):
    _, body = resources(client, teacher, db)
    session_id = session_for(client, teacher, body)
    s = db.get(ChatSession, session_id)
    s.mode, s.slot_state_json = "generate", json.dumps({"scope": "导数"})
    db.commit()

    def forbidden_hyde(*args, **kwargs):
        pytest.fail("对话链路不得调用 HyDE")

    monkeypatch.setattr(generation, "get_cached_hyde", forbidden_hyde)
    monkeypatch.setattr(generation, "get_hyde", forbidden_hyde)
    seen = []

    def run(ctx):
        seen.append(ctx.hyde_text)
        return {"reply": "完成", "done": True}

    monkeypatch.setattr(chat, "get_skill", lambda mode: SimpleNamespace(run=run))
    monkeypatch.setattr(chat, "detect_intent", lambda *a, **kw: {
        "intent": "generate", "confidence": "high",
    })
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": "继续"})
    assert response.status_code == 200, response.text
    assert seen == [None]


def test_legacy_redis_task_has_explicit_recovery_without_trusting_cached_owner(client, teacher):
    r = cache.get_redis()
    # HEAD 的实际 hash：没有 SQL task/run，认证和结果均不能取信于这些字段。
    r.hset(generation._task_key("legacy-task"), mapping={
        "user_id": "forged-owner", "bank_id": "legacy-bank", "document_id": "legacy-doc",
        "status": "done", "done": "1", "progress": 100, "batch_id": "forged-batch",
        "questions": '[{"stem":"untrusted cached question"}]',
    })
    response = client.get("/api/generate/progress/legacy-task", headers=teacher)
    assert response.status_code == 404
    message = response.json()["detail"]["message"]
    assert "最近" in message and "重新" in message
    assert "untrusted cached question" not in response.text


def test_legacy_pending_chat_requires_explicit_resend_and_ignores_redis(
    client, teacher, db, monkeypatch,
):
    _, body = resources(client, teacher, db)
    session_id = session_for(client, teacher, body)
    s = db.get(ChatSession, session_id)
    s.run_status = "interrupted"
    s.run_stage = "服务已升级，旧待续需求请重新发送文字和图片"
    db.commit()
    # 与旧 HEAD 一致的待续字段名，尤其是 pending_images 而非 *_json。
    cache.get_redis().hset(chat._slot_key(session_id), mapping={
        "mode": "generate", "slot_state": "{}", "pending_message": "旧请求",
        "pending_images": json.dumps([PNG]),
    })
    detect = Mock()
    monkeypatch.setattr(chat, "detect_intent", detect)
    progress = client.get(f"/api/chat/sessions/{session_id}/progress", headers=teacher)
    assert progress.status_code == 200
    assert "重新" in progress.json()["stage"]
    response = client.post(f"/api/chat/sessions/{session_id}/messages", headers=teacher,
                           json={"message": "切换", "mode": "qa", "switch_only": True})
    assert response.status_code == 200, response.text
    assert "重新" in response.json()["reply"] and "图片" in response.json()["reply"]
    detect.assert_not_called()
    db.expire_all()
    assert db.get(ChatSession, session_id).pending_message is None


@pytest.fixture
def historical_database(tmp_path, monkeypatch):
    """在 conftest 的禁网、假配置上下文中执行真实迁移，不创建子进程。"""
    database = tmp_path / "legacy.sqlite"
    monkeypatch.setattr(settings, "database_url", f"sqlite:///{database.as_posix()}")
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(config, "i4d5e6f7a890")
    historical = create_engine(settings.database_url)
    with historical.begin() as conn:
        conn.execute(text(
            "INSERT INTO users (id,account,password_hash,role,identity,display_name,status,"
            "created_at,updated_at) VALUES ('u','fake','fake','teacher','教师','合成教师',"
            "'active','2026-01-01','2026-01-01')",
        ))
        conn.execute(text(
            "INSERT INTO chat_sessions (id,user_id,bank_id,document_id,slot_state_json,"
            "created_at,updated_at) VALUES ('s','u','b','d','{\"scope\":\"导数\"}',"
            "'2026-01-01','2026-01-01')",
        ))
    yield config, historical
    historical.dispose()


def test_upgrade_marks_old_chat_interrupted_and_keeps_sql_slots(historical_database):
    config, historical = historical_database
    command.upgrade(config, "j5e6f7a8b901")
    with historical.connect() as conn:
        row = conn.execute(text(
            "SELECT slot_state_json,run_status,run_stage,pending_message,run_id FROM chat_sessions",
        )).one()
        assert json.loads(row[0]) == {"scope": "导数"}
        assert row[1] == "interrupted"
        assert "重新" in row[2] and "图片" in row[2]
        assert row[3:] == (None, None)
        assert conn.execute(text("SELECT COUNT(*) FROM generation_tasks")).scalar() == 0


@pytest.mark.parametrize("field,value", [
    ("mode", "qa"), ("pending_message", "待续需求"), ("pending_images_json", '["fake-image"]'),
    ("run_id", "run-old"), ("canceled_run_id", "run-canceled"), ("run_status", "running"),
    ("run_progress", 12), ("run_stage", "待恢复"),
])
def test_downgrade_refuses_chat_state_loss_before_dropping_any_schema(
    historical_database, field, value,
):
    config, historical = historical_database
    command.upgrade(config, "j5e6f7a8b901")
    with historical.begin() as conn:
        conn.execute(text("UPDATE chat_sessions SET run_status='idle',run_stage=''"))
        conn.execute(text(f"UPDATE chat_sessions SET {field}=:value"), {"value": value})
    with pytest.raises(RuntimeError, match="拒绝有损降级"):
        command.downgrade(config, "i4d5e6f7a890")
    with historical.connect() as conn:
        assert conn.execute(text(f"SELECT {field} FROM chat_sessions")).scalar() == value
        assert conn.execute(text("SELECT version_num FROM alembic_version")).scalar() == "j5e6f7a8b901"
        assert "generation_tasks" in inspect(conn).get_table_names()


def test_downgrade_without_new_chat_state_preserves_old_sql_slots(historical_database):
    config, historical = historical_database
    command.upgrade(config, "j5e6f7a8b901")
    with historical.begin() as conn:
        # 管理员已确认升级提示，不存在运行、模式或待续需求时可回退。
        conn.execute(text("UPDATE chat_sessions SET run_status='idle',run_stage=''"))
    command.downgrade(config, "i4d5e6f7a890")
    with historical.connect() as conn:
        assert json.loads(conn.execute(text("SELECT slot_state_json FROM chat_sessions")).scalar()) == {
            "scope": "导数",
        }
