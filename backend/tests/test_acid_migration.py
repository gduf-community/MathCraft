"""在独立历史数据库验证 ACID 迁移保留答案并固定作答快照。"""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from test_auth_seed import AuthCommandCase


class AcidMigrationTests(AuthCommandCase):
    """运行真实 Alembic CLI，不访问工作区配置或数据。"""

    def migrate(self, direction: str, revision: str) -> subprocess.CompletedProcess[str]:
        """使用沙箱中的假凭据和临时数据库执行迁移。"""
        return subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", direction, revision],
            cwd=self.backend, env=self.env, capture_output=True, text=True,
            encoding="utf-8", timeout=45, check=False,
        )

    def setUp(self) -> None:
        super().setUp()
        source = Path(__file__).resolve().parents[1]
        shutil.copyfile(source / "alembic.ini", self.backend / "alembic.ini")
        self.env["APP_ENV"] = "test"
        result = self.migrate("upgrade", "i4d5e6f7a890")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_upgrade_from_generation_history_preserves_existing_run(self) -> None:
        result = self.migrate("upgrade", "k6f7a8b90123")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with closing(sqlite3.connect(self.database)) as db:
            db.execute(
                "INSERT INTO users (id, account, password_hash, role, identity, display_name, "
                "status, created_at, updated_at) VALUES ('u', 'fake', 'fake-hash', 'teacher', "
                "'教师', '合成教师', 'active', '2026-01-01', '2026-01-01')",
            )
            db.execute(
                "INSERT INTO generation_runs (id,user_id,bank_id,document_id,params_json,"
                "created_at,updated_at) VALUES ('r','u','b','d','{}','2026-01-01','2026-01-01')",
            )
            db.commit()
            before = db.execute("SELECT * FROM generation_runs").fetchall()
        result = self.migrate("upgrade", "head")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT * FROM generation_runs").fetchall(), before)
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(db.execute("SELECT version_num FROM alembic_version").fetchone(),
                             ("m8f9a0b12345",))

    def test_upgrade_preserves_answers_and_backfills_snapshot(self) -> None:
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute(
                "INSERT INTO users (id, account, password_hash, role, identity, display_name, "
                "status, created_at, updated_at) VALUES ('u', 'fake', 'fake-hash', 'student', "
                "'学生', '合成学生', 'active', '2026-01-01', '2026-01-01')",
            )
            db.execute(
                "INSERT INTO papers (id,name,owner_id,status,saved_to_records,question_count, "
                "total_score,created_at,updated_at) VALUES "
                "('p','历史练习','u','draft',1,1,5,'2026-01-01','2026-01-01')",
            )
            db.execute(
                "INSERT INTO paper_questions (id,paper_id,order_no,module_type,type,score,"
                "difficulty,stem,answer,analysis) VALUES "
                "('pq','p',1,'single','single',5,'中','合成题','A','合成解析')",
            )
            db.execute(
                "INSERT INTO paper_attempts (id,paper_id,student_id,status,score,total_score,"
                "started_at,submitted_at,created_at,updated_at) VALUES "
                "('a','p','u','submitted',5,5,'2026-01-01','2026-01-01',"
                "'2026-01-01','2026-01-01')",
            )
            db.execute(
                "INSERT INTO attempt_answers (id,attempt_id,paper_question_id,choices_json,"
                "score,is_correct,graded_by,created_at) VALUES "
                "('ans','a','pq','[\"A\"]',5,1,'rule','2026-01-01')",
            )
            db.commit()
            before = db.execute("SELECT * FROM attempt_answers").fetchall()
        result = self.migrate("upgrade", "head")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT * FROM attempt_answers").fetchall(), before)
            self.assertEqual(json.loads(db.execute(
                "SELECT question_ids_json FROM paper_attempts WHERE id='a'",
            ).fetchone()[0]), ["pq"])
            self.assertEqual(db.execute("SELECT closed,deleted FROM papers").fetchone(), (0, 0))
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            db.execute("UPDATE papers SET closed=1 WHERE id='p'")
            db.commit()
        blocked = self.migrate("downgrade", "i4d5e6f7a890")
        self.assertNotEqual(blocked.returncode, 0)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT * FROM attempt_answers").fetchall(), before)
            self.assertEqual(db.execute("SELECT version_num FROM alembic_version").fetchone(),
                             ("m8f9a0b12345",))
