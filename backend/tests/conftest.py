"""pytest 公共夹具：临时 SQLite + 进程内隔离 Redis，外部模型全部打桩。"""
import os
import re
import sys
import tempfile
from pathlib import Path
from types import ModuleType

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 必须在导入 app 之前设置环境变量（settings 在模块导入时实例化）
TEST_ROOT = Path(tempfile.mkdtemp(prefix="mathcraft_test_", dir=os.environ.get("TEMP")))
os.environ["DATABASE_URL"] = f"sqlite:///{(TEST_ROOT / 'test.db').as_posix()}?check_same_thread=false"
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/15"
os.environ["APP_ENV"] = "test"
os.environ["AUTH_JWT_SECRET"] = "test-only-jwt-secret-not-for-production-0123456789"
os.environ["AUTH_CODE_SECRET"] = "test-only-code-secret-not-for-production-0123456789"
os.environ["CHROMA_DIR"] = str(TEST_ROOT / "chroma")
os.environ["UPLOAD_DIR"] = str(TEST_ROOT / "uploads")
os.environ["OCR_DIR"] = str(TEST_ROOT / "ocr")
os.environ["AVATAR_DIR"] = str(TEST_ROOT / "avatars")
os.environ["DEEPSEEK_API_KEY"] = ""
os.environ["CORS_ORIGINS"] = "http://127.0.0.1:5173"

# 测试从不读取个人 local_secrets.py；外部凭据固定为空。
_test_secrets = ModuleType("app.local_secrets")
_test_secrets.SILICONFLOW_API_KEY = ""
_test_secrets.MINERU_DEFAULT_TOKEN = ""
sys.modules["app.local_secrets"] = _test_secrets

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import Base, FTS_CREATE_SQL, SessionLocal, engine
from app.main import app as fastapi_app
import app.models  # noqa: F401
from app.models import User, UserModelSetting
from app.models.base import new_id
from app.services.auth import hash_password
from app.services import cache
from app.services.rag import embeddings, llm, question_gen, rerank, slots


# ---------------- 外部模型打桩 ----------------

def fake_embed_texts(texts: list[str]) -> list[list[float]]:
    """确定性 1024 维向量，保证 Chroma 可正常检索且不访问网络。"""
    out = []
    for text in texts:
        vec = [0.0] * 1024
        vec[0] = 0.5
        for i, ch in enumerate(text[:128]):
            vec[(ord(ch) + i * 17) % 1024] += 1.0
        out.append(vec)
    return out


def fake_rerank(query: str, documents: list[str], top_n: int | None = None) -> list[dict]:
    qchars = set(query)
    scored = []
    for i, doc in enumerate(documents):
        score = len(qchars & set(doc)) / max(1, len(qchars))
        scored.append((i, score))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [{"index": i, "score": s} for i, s in scored[: (top_n or len(documents))]]


def fake_question_chat_json(messages, api_key=None, retries=1) -> dict:
    prompt = messages[-1]["content"]
    m = re.search(r"必须严格为 ([a-z]+)", prompt)
    qtype = m.group(1) if m else "single"
    m2 = re.search(r"数量：(\d+)", prompt)
    count = int(m2.group(1)) if m2 else 1

    questions = []
    for i in range(count):
        base = {
            "type": qtype,
            "score": 5,
            "difficulty": "中",
            "stem": f"第{i + 1}题：函数 $f(x)=x^{i + 2}$ 的导数是什么？",
            "options": [],
            "answer": f"${i + 2}x^{i + 1}$",
            "analysis": "由幂函数求导法则可得。",
            "knowledgePoint": "导数",
        }
        if qtype in ("single", "multiple"):
            base["options"] = [
                {"label": "A", "text": "$x$"},
                {"label": "B", "text": "$2x$"},
                {"label": "C", "text": "$3x^2$"},
                {"label": "D", "text": "$0$"},
            ]
            base["answer"] = "A" if qtype == "single" else "AB"
        elif qtype == "judge":
            base["options"] = [{"label": "A", "text": "正确"}, {"label": "B", "text": "错误"}]
            base["answer"] = "A"
        questions.append(base)
    return {"questions": questions}


def fake_slot_chat_json(messages, api_key=None, retries=1) -> dict:
    return {
        "types": [{"type": "single", "count": 2}],
        "scope": "导数",
        "source_mode": "variant_data",
        "difficulty": "中",
        "mixed_difficulty": False,
    }


@pytest.fixture(autouse=True)
def fake_models(monkeypatch):
    monkeypatch.setattr(embeddings, "embed_texts", fake_embed_texts)
    monkeypatch.setattr(embeddings, "embed_one", lambda t: fake_embed_texts([t])[0])
    monkeypatch.setattr(rerank, "rerank", fake_rerank)
    monkeypatch.setattr(llm, "chat_text", lambda *a, **k: "假设段落：导数的定义与求导法则。")
    monkeypatch.setattr(llm, "chat_json", lambda *a, **k: {})
    monkeypatch.setattr(question_gen, "chat_json", fake_question_chat_json)
    monkeypatch.setattr(slots, "chat_json", fake_slot_chat_json)
    yield


# ---------------- 数据库与账号 ----------------

def _reset_database() -> None:
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS document_chunks_fts"))
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        conn.execute(text(FTS_CREATE_SQL))


def _seed_users() -> None:
    db = SessionLocal()
    try:
        for account, role, name, user_no in [
            ("teacher", "teacher", "张老师", "TK20240001"),
            ("student", "student", "小明", "ST20250001"),
        ]:
            user = User(
                id=new_id("u"),
                account=account,
                password_hash=hash_password("123123"),
                role=role,
                identity="教师" if role == "teacher" else "学生",
                display_name=name,
                user_no=user_no,
                school="广东金融学院",
                status="active",
            )
            db.add(user)
            db.flush()
            db.add(UserModelSetting(user_id=user.id))
        db.commit()
    finally:
        db.close()


@pytest.fixture(autouse=True)
def isolated_redis(monkeypatch):
    """每个测试使用独立内存 Redis，绝不连接或清空本机实例。"""
    instance = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache, "get_redis", lambda: instance)
    yield instance
    instance.close()


@pytest.fixture()
def client():
    _reset_database()
    _seed_users()
    with TestClient(fastapi_app) as c:
        yield c


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def auth(client):
    def _login(account: str, role: str, password: str = "123123") -> dict:
        resp = client.post("/api/auth/login", json={"account": account, "password": password, "role": role})
        assert resp.status_code == 200, resp.text
        return {"Authorization": f"Bearer {resp.json()['token']}"}

    return _login


@pytest.fixture()
def teacher(auth):
    return auth("teacher", "teacher")


@pytest.fixture()
def student(auth):
    return auth("student", "student")


# ---------------- 常用辅助 ----------------

def create_bank(client, headers, name="测试题库") -> dict:
    resp = client.post("/api/banks", json={"name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def upload_markdown(client, headers, bank_id: str, name="notes.md") -> dict:
    content = """# 导数与微分

## 导数的定义

函数 $f(x)$ 在点 $x_0$ 处的导数定义为差商的极限。导数刻画函数在该点的瞬时变化率。

## 求导法则

幂函数求导法则：$(x^n)' = n x^{n-1}$。乘积法则与商法则用于复合结构的求导。

## 隐函数求导

方程两边同时对 $x$ 求导，再解出 $y'$。这是隐函数求导的基本方法。

## 应用

导数可用于判断单调性、求极值与最值，也可用于近似计算。
"""
    resp = client.post(
        f"/api/banks/{bank_id}/documents",
        files={"file": (name, content.encode("utf-8"), "text/markdown")},
        headers=headers,
    )
    assert resp.status_code == 202, resp.text
    return resp.json()


def make_questions(db, user_id: str, specs: list[tuple[str, str, int]]) -> list[str]:
    """直接插入题目，返回题目 id 列表。specs: [(type, answer, score)]。"""
    import json

    from app.models import GenerationBatch, Question
    from app.models.base import new_id

    batch = GenerationBatch(
        id=new_id("batch"),
        user_id=user_id,
        bank_id="bank_test",
        document_id="doc_test",
        mode="parametric",
        params_json="{}",
        question_count=len(specs),
        status="done",
    )
    db.add(batch)
    db.flush()
    ids = []
    for i, (qtype, answer, score) in enumerate(specs):
        options = []
        if qtype in ("single", "multiple"):
            options = [
                {"label": "A", "text": "选项 A"},
                {"label": "B", "text": "选项 B"},
                {"label": "C", "text": "选项 C"},
                {"label": "D", "text": "选项 D"},
            ]
        elif qtype == "judge":
            options = [{"label": "A", "text": "正确"}, {"label": "B", "text": "错误"}]
        q = Question(
            id=new_id("q"),
            batch_id=batch.id,
            bank_id="bank_test",
            document_id="doc_test",
            type=qtype,
            score=score,
            difficulty="中",
            stem=f"测试题目 {i + 1}",
            options_json=json.dumps(options, ensure_ascii=False) if options else None,
            answer=answer,
            analysis="测试解析",
            knowledge_point="导数",
            source_mode="variant_data",
            created_by=user_id,
        )
        db.add(q)
        ids.append(q.id)
    db.commit()
    return ids
