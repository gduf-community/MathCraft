"""只用于 M4 页面联调：正式临时迁移库、假模型、fakeredis 与后端禁网。"""
# ruff: noqa: E402 -- 必须先由公共夹具隔离配置，再导入应用。
import argparse
from pathlib import Path
import json
import socket
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "backend/tests"))
import conftest as fixtures
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
import uvicorn

from app.config import settings
from app.db import SessionLocal
from app.models import User
from app.models.base import new_id
from app.services.auth import hash_password
from test_generation_runs import resources, body


def main() -> None:
    """创建新临时库并在回环随机端口服务，种子只含关联 ID，不写入凭据。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="新的合成种子输出目录")
    output = parser.parse_args().output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    seed_path = output / "ledger-seed.json"
    if seed_path.exists():
        parser.error("请使用新的输出目录，不能覆盖既有联调证据")
    patch = pytest.MonkeyPatch()
    fixtures.prohibit_network.__wrapped__(patch)
    models = fixtures.fake_models.__wrapped__(patch)
    redis = fixtures.isolated_redis.__wrapped__(patch)
    verification = fixtures.fake_auth_verification.__wrapped__()
    next(models)
    next(redis)
    next(verification)
    settings.turnstile_enabled = False
    settings.cors_origins = "http://127.0.0.1:5183"
    config = Config()
    config.set_main_option("script_location", str(ROOT / "backend/alembic"))
    command.upgrade(config, "head")
    with SessionLocal() as session:
        migration = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    fixtures._seed_users()
    with SessionLocal.begin() as session:
        session.add(User(
            id=new_id("u"), account="ops-e2e-admin", role="admin", identity="管理员",
            display_name="隔离运维管理员", status="active",
            password_hash=hash_password("Ops-test-only-123"),
        ))
    with TestClient(fixtures.fastapi_app) as client:
        response = client.post("/api/auth/login/account", json={
            "account": "teacher", "password": "123123",
            "turnstile_token": "test-turnstile-token",
        })
        response.raise_for_status()
        headers = {"Authorization": "Bearer " + response.json()["access_token"]}
        values = resources.__wrapped__(client, headers, patch)
    next(verification, None)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    seed_path.write_text(json.dumps({
        "backend": f"http://127.0.0.1:{port}", "resources": values, "body": body(values),
        "migration": migration, "database": str(fixtures.TEST_ROOT / "test.db"),
    }), encoding="utf-8")
    print(f"ISOLATED_LEDGER_READY seed={seed_path}", flush=True)
    try:
        server = uvicorn.Server(uvicorn.Config(
            fixtures.fastapi_app, log_level="warning", access_log=False,
        ))
        server.run(sockets=[listener])
    finally:
        listener.close()
        next(redis, None)
        next(models, None)
        patch.undo()


if __name__ == "__main__":
    main()
