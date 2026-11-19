"""在独立历史数据库验证 ACID 迁移保留答案并固定作答快照。"""
from contextlib import closing
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import warnings

from alembic.script import ScriptDirectory

from test_auth_seed import AuthCommandCase


def test_main_and_ops_revisions_form_one_unambiguous_history() -> None:
    """主线与智能体历史汇合，对话轮次迁移成为唯一 head。"""
    versions = Path(__file__).resolve().parents[1] / "alembic"
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "error", message=r"Revision .* is present more than once", category=UserWarning,
        )
        scripts = ScriptDirectory(str(versions))
        assert scripts.get_heads() == ["q2d3e4f56789"]
        assert scripts.get_revision("q2d3e4f56789").down_revision == "p1c2d3e45678"
        assert scripts.get_revision("p1c2d3e45678").down_revision == (
            "o0b1c2d34567", "j5f6g7h8i900",
        )
        assert scripts.get_revision("o0b1c2d34567").down_revision == "n9a0b1c23456"
        assert scripts.get_revision("n9a0b1c23456").down_revision == "m8f9a0b12345"
        assert scripts.get_revision("m8f9a0b12345").down_revision == (
            "k6f7a8b90123", "j5e6f7a8b901",
        )
        acid = scripts.get_revision("j5e6f7a8b901")
        assert Path(acid.path).name == "j5e6f7a8b901_acid_recovery.py"
        assert acid.down_revision == "i4d5e6f7a890"


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

    def test_upgrade_from_acid_history_preserves_existing_state(self) -> None:
        result = self.migrate("upgrade", "j5e6f7a8b901")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with closing(sqlite3.connect(self.database)) as db:
            db.execute(
                "INSERT INTO users (id,account,password_hash,role,identity,display_name,"
                "status,created_at,updated_at) VALUES ('u','fake','fake-hash','teacher',"
                "'教师','合成教师','active','2026-01-01','2026-01-01')",
            )
            db.execute(
                "INSERT INTO papers (id,name,owner_id,status,saved_to_records,question_count,"
                "total_score,created_at,updated_at,closed) VALUES "
                "('p','历史试卷','u','draft',1,0,0,'2026-01-01','2026-01-01',1)",
            )
            db.commit()
            before = db.execute("SELECT * FROM papers").fetchall()
        result = self.migrate("upgrade", "head")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT * FROM papers").fetchall(), before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM ops_runs").fetchone(), (0,))
            self.assertEqual(db.execute("SELECT COUNT(*) FROM generation_runs").fetchone(), (0,))
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(db.execute("SELECT version_num FROM alembic_version").fetchone(),
                             ("q2d3e4f56789",))

    def test_legacy_ops_revision_requires_reconciliation_before_upgrade(self) -> None:
        """旧 V2 同号数据库不会被新版本图自动识别，也不能覆盖旧台账。"""
        current = self.backend / "current_alembic"
        (self.backend / "alembic").rename(current)
        legacy = self.backend / "alembic"
        shutil.copytree(current, legacy)
        versions = legacy / "versions"
        for filename in (
            "j5e6f7a8b901_acid_recovery.py",
            "j5e6f7a89012_source_evidence.py",
            "k6f7a8b90123_generation_runs.py",
            "m8f9a0b12345_merge_generation_acid.py",
            "o0b1c2d34567_generation_cancellation.py",
            "j5f6g7h8i900_platform_llm_settings.py",
            "p1c2d3e45678_merge_agent_platform.py",
            "q2d3e4f56789_chat_requests.py",
        ):
            (versions / filename).unlink()
        ops = versions / "n9a0b1c23456_add_ops_runs.py"
        legacy_source = ops.read_text(encoding="utf-8")
        legacy_source = legacy_source.replace(
            'revision = "n9a0b1c23456"', 'revision = "j5e6f7a8b901"',
        ).replace(
            'down_revision = "m8f9a0b12345"', 'down_revision = "i4d5e6f7a890"',
        )
        ops.write_text(legacy_source, encoding="utf-8")
        ops.rename(versions / "j5e6f7a8b901_add_ops_runs.py")
        result = self.migrate("upgrade", "head")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with closing(sqlite3.connect(self.database)) as db:
            db.execute(
                "INSERT INTO users (id,account,password_hash,role,identity,display_name,"
                "status,created_at,updated_at) VALUES ('u','fake','fake-hash','teacher',"
                "'教师','合成教师','active','2026-01-01','2026-01-01')",
            )
            db.execute(
                "INSERT INTO ops_runs (run_id,entrypoint,owner_user_id,bank_id,document_id,"
                "status,requested_count,accepted_at,last_observed_at) VALUES "
                "('r','parameterized','u','b','d','accepted',1,"
                "'2026-01-01','2026-01-01')",
            )
            db.commit()
            before = db.execute("SELECT * FROM ops_runs").fetchall()
            self.assertNotIn("closed", {row[1] for row in db.execute("PRAGMA table_info(papers)")})
        legacy.rename(self.backend / "legacy_alembic")
        current.rename(self.backend / "alembic")
        result = self.migrate("upgrade", "head")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already exists", result.stderr)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute("SELECT * FROM ops_runs").fetchall(), before)
            self.assertEqual(db.execute("SELECT version_num FROM alembic_version").fetchone(),
                             ("j5e6f7a8b901",))
            self.assertNotIn("closed", {row[1] for row in db.execute("PRAGMA table_info(papers)")})
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

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
                             ("q2d3e4f56789",))

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
                             ("q2d3e4f56789",))
