"""真实 Alembic CLI 验收：独立合成库、历史归属保留与发布阻断。"""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

from test_auth_seed import AuthCommandCase


class AuthAlembicCommandTests(AuthCommandCase):
    """仅复制当前受测源码到沙箱，不加载工作区配置或共享夹具。"""

    def setUp(self) -> None:
        super().setUp()
        source = Path(__file__).resolve().parents[1]
        shutil.copytree(source / "alembic", self.backend / "alembic",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        shutil.copyfile(source / "alembic.ini", self.backend / "alembic.ini")
        self.env = {key: value for key, value in os.environ.items()
                    if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}}
        self.env.update({
            "PYTHONUTF8": "1",
            "APP_ENV": "test",
            "DATABASE_URL": f"sqlite:///{self.database.as_posix()}",
            "CORS_ORIGINS": "http://127.0.0.1:5173",
        })
        result = self.upgrade("e8b3c6d92a47")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def upgrade(self, revision: str) -> subprocess.CompletedProcess[str]:
        """执行实际迁移 CLI，不使用 create_all 或手工 stamp 替代升级。"""
        return subprocess.run(
            [sys.executable, "-m", "alembic", "-c", "alembic.ini", "upgrade", revision],
            cwd=self.backend, env=self.env, capture_output=True, text=True,
            encoding="utf-8", timeout=30, check=False,
        )

    def add_history(self, *, conflict: str | None = None) -> None:
        """用旧 schema 写教师、学生及教师拥有的题库，数据均为假值。"""
        emails = [None, "Student@EXAMPLE.invalid"]
        numbers = ["000T", "000S"]
        identities = ["教师", "学生"]
        if conflict == "email":
            emails = ["Student@example.invalid", "Student@EXAMPLE.invalid"]
        elif conflict == "user_no":
            numbers = ["000T", " 000T "]
        elif conflict == "identity":
            identities[1] = "教师"
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.executemany(
                "INSERT INTO users (id, account, password_hash, role, identity, display_name, "
                "email, user_no, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, "
                "'active', '2026-01-01', '2026-01-01')",
                [("legacy-teacher", "fake-teacher", "fake-hash-teacher", "teacher", identities[0],
                  "合成教师", emails[0], numbers[0]),
                 ("legacy-student", "fake-student", "fake-hash-student", "student", identities[1],
                  "合成学生", emails[1], numbers[1])],
            )
            db.execute(
                "INSERT INTO banks (id, name, code, creator_id, admin_level, capacity, status, "
                "created_at, updated_at) VALUES ('legacy-bank', '合成题库', 'fake-bank-code', "
                "'legacy-teacher', 'private', 100, 'active', '2026-01-01', '2026-01-01')",
            )
            db.commit()

    def assert_bank_ownership(self) -> None:
        """核对实际 owner 关联列 creator_id、外键定义及参照完整性。"""
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("PRAGMA foreign_keys=ON")
            self.assertEqual(db.execute(
                "SELECT banks.id, users.id, users.role FROM banks "
                "JOIN users ON banks.creator_id=users.id",
            ).fetchall(), [("legacy-bank", "legacy-teacher", "teacher")])
            foreign_keys = db.execute("PRAGMA foreign_key_list(banks)").fetchall()
            self.assertTrue(any(row[2:5] == ("users", "creator_id", "id")
                                for row in foreign_keys))
            self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_upgrade_preserves_user_ids_bank_owner_and_unverified_history(self) -> None:
        self.add_history()
        users_before = self.rows("SELECT * FROM users ORDER BY id")
        banks_before = self.rows("SELECT * FROM banks ORDER BY id")
        result = self.upgrade("head")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.rows("SELECT version_num FROM alembic_version"),
                         [("c3e8a1f5b279",)])
        # 新增列以外的所有历史字段必须保留；不能仅证明当前 ID 仍可查到。
        old_columns = ("id, account, password_hash, role, identity, display_name, gender, phone, "
                       "email, user_no, school, avatar_url, status, created_at, updated_at")
        self.assertEqual(self.rows(f"SELECT {old_columns} FROM users ORDER BY id"), users_before)
        self.assertEqual(self.rows("SELECT * FROM banks ORDER BY id"), banks_before)
        self.assertEqual(self.rows(
            "SELECT id, email_normalized, email_verified, email_verified_at, auth_version "
            "FROM users ORDER BY id",
        ), [("legacy-student", "student@example.invalid", 0, None, 0),
            ("legacy-teacher", None, 0, None, 0)])
        self.assert_bank_ownership()
        before_audit = self.database.read_bytes()
        audit = self.command("auth_migration.py", "audit", "--operator-confirmed",
                             "--database", str(self.database))
        self.assertEqual(audit.returncode, 1, audit.stdout + audit.stderr)
        summary = json.loads(audit.stdout)
        self.assertTrue(summary["blocked"])
        self.assertEqual(summary["missing_email"], 1)
        self.assertEqual(summary["unverified_email"], 2)
        self.assertEqual(self.database.read_bytes(), before_audit)
        self.assert_private(audit)
        self.assertNotIn("legacy-", audit.stdout + audit.stderr)
        self.assertNotIn("example.invalid", audit.stdout + audit.stderr)

    def assert_conflict_blocks_upgrade(self, conflict: str) -> None:
        """DDL 前拒绝脏历史，同时保持旧 revision、用户及资源记录。"""
        self.add_history(conflict=conflict)
        users_before = self.rows("SELECT * FROM users ORDER BY id")
        banks_before = self.rows("SELECT * FROM banks ORDER BY id")
        columns_before = self.rows("PRAGMA table_info(users)")
        result = self.upgrade("head")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.rows("SELECT version_num FROM alembic_version"),
                         [("e8b3c6d92a47",)])
        self.assertEqual(self.rows("SELECT * FROM users ORDER BY id"), users_before)
        self.assertEqual(self.rows("SELECT * FROM banks ORDER BY id"), banks_before)
        self.assertEqual(self.rows("PRAGMA table_info(users)"), columns_before)
        self.assert_bank_ownership()

    def test_email_case_collision_blocks_before_ddl(self) -> None:
        self.assert_conflict_blocks_upgrade("email")

    def test_trimmed_user_number_collision_blocks_before_ddl(self) -> None:
        self.assert_conflict_blocks_upgrade("user_no")

    def test_role_identity_mismatch_blocks_before_ddl(self) -> None:
        self.assert_conflict_blocks_upgrade("identity")
