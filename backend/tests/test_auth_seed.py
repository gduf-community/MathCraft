"""开发账号命令外部行为；单独运行时必须传 pytest --noconftest。"""
from __future__ import annotations

from contextlib import closing
import os
import sqlite3
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class AuthCommandCase(unittest.TestCase):
    """把受测源码复制到无配置、无真实数据的命令沙箱。"""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="mathcraft_auth_command_")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.backend = self.root / "backend"
        source = Path(__file__).resolve().parents[1]
        shutil.copytree(
            source / "app", self.backend / "app",
            ignore=shutil.ignore_patterns(
                "local_secrets.py", ".env", "__pycache__", "*.pyc", "*.db", "*.sqlite*",
            ),
        )
        shutil.copytree(source / "scripts", self.backend / "scripts")
        shutil.copytree(source / "alembic", self.backend / "alembic",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        # 只在临时沙箱写明确假值；绝不读取工作区真实 local_secrets.py。
        (self.backend / "app" / "local_secrets.py").write_text(
            'SILICONFLOW_API_KEY = ""\nMINERU_DEFAULT_TOKEN = ""\n', encoding="utf-8",
        )
        self.database = self.root / "synthetic.sqlite"
        self.env = {
            key: value for key, value in os.environ.items()
            if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
        }
        self.env.update({
            "PYTHONUTF8": "1",
            "CORS_ORIGINS": "http://127.0.0.1:5173",
            "DATABASE_URL": f"sqlite:///{self.database.as_posix()}",
            "APP_ENV": "development",
            "DEV_ACCOUNTS_ENABLED": "true",
            "DEV_TEACHER_EMAIL": "teacher@example.invalid",
            "DEV_TEACHER_USER_NO": "000T",
            "DEV_TEACHER_PASSWORD": "Fake-Teacher-123!",
            "DEV_TEACHER_DISPLAY_NAME": "测试教师",
            "DEV_STUDENT_EMAIL": "student@example.invalid",
            "DEV_STUDENT_USER_NO": "000S",
            "DEV_STUDENT_PASSWORD": "Fake-Student-123!",
            "DEV_STUDENT_DISPLAY_NAME": "测试学生",
        })

    def command(self, script: str, *args: str) -> subprocess.CompletedProcess[str]:
        """运行真实脚本入口，截获标准输出、标准错误和退出码。"""
        return subprocess.run(
            [sys.executable, str(self.backend / "scripts" / script), *args],
            cwd=self.root, env=self.env, capture_output=True, text=True,
            encoding="utf-8", timeout=30, check=False,
        )

    def assert_private(self, result: subprocess.CompletedProcess[str]) -> None:
        """任何返回路径都不得泄露配置与账号标识。"""
        output = result.stdout + result.stderr
        for key, value in self.env.items():
            if key.startswith("DEV_") and key != "DEV_ACCOUNTS_ENABLED":
                self.assertNotIn(value, output)
        self.assertNotIn(str(self.database), output)
        self.assertNotIn("Traceback", output)

    def create_schema(self) -> None:
        """在子进程通过真实 ORM 创建纯合成数据库。"""
        result = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, 'backend'); "
             "from app.db import Base, engine; import app.models; "
             "Base.metadata.create_all(engine); engine.dispose()"],
            cwd=self.root, env=self.env, capture_output=True, text=True,
            encoding="utf-8", timeout=30, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def rows(self, query: str) -> list[tuple]:
        """只读取当前测试自己生成的数据库。"""
        with closing(sqlite3.connect(self.database)) as db:
            return db.execute(query).fetchall()


class SeedCommandTests(AuthCommandCase):
    def test_production_refuses_before_opening_database(self) -> None:
        self.env["APP_ENV"] = "production"
        result = self.command("seed.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.database.exists())
        self.assert_private(result)

    def test_help_and_unknown_arguments_never_open_database(self) -> None:
        help_result = self.command("seed.py", "--help")
        self.assertEqual(help_result.returncode, 0)
        self.assertFalse(self.database.exists())
        self.assert_private(help_result)
        rejected = self.command("seed.py", "--password", self.env["DEV_TEACHER_PASSWORD"])
        self.assertEqual(rejected.returncode, 2)
        self.assertFalse(self.database.exists())
        self.assert_private(rejected)

    def test_disabled_and_invalid_settings_do_not_open_database(self) -> None:
        for changes in (
            {"DEV_ACCOUNTS_ENABLED": "false"},
            {"DEV_STUDENT_PASSWORD": "short"},
            {"DEV_STUDENT_EMAIL": "invalid-address"},
            {"DEV_STUDENT_USER_NO": " "},
            {"DEV_TEACHER_DISPLAY_NAME": " "},
            {"DEV_TEACHER_PASSWORD": "密" * 25},
            {"DEV_TEACHER_PASSWORD": "x" * 65},
            {"DEV_STUDENT_EMAIL": " TEACHER@example.invalid "},
            {"DEV_STUDENT_USER_NO": "000T"},
        ):
            with self.subTest(fields=tuple(changes)):
                previous = self.env.copy()
                self.env.update(changes)
                result = self.command("seed.py")
                self.assertEqual(result.returncode, 2)
                self.assertFalse(self.database.exists())
                self.assert_private(result)
                self.env = previous

    def test_create_both_roles_with_verified_email_and_model_settings(self) -> None:
        self.create_schema()
        result = self.command("seed.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        users = self.rows(
            "SELECT role, identity, user_no, email_normalized, "
            "email_verified_at IS NOT NULL, auth_version FROM users ORDER BY role"
        )
        self.assertEqual(users, [
            ("student", "学生", "000S", "student@example.invalid", 1, 0),
            ("teacher", "教师", "000T", "teacher@example.invalid", 1, 0),
        ])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM user_model_settings"), [(2,)])
        self.assert_private(result)

    def test_rerun_never_resets_password_role_or_profile(self) -> None:
        self.create_schema()
        first = self.command("seed.py")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        before = self.rows("SELECT * FROM users ORDER BY id")
        self.env["DEV_TEACHER_PASSWORD"] = "Different-Fake-123!"
        self.env["DEV_TEACHER_DISPLAY_NAME"] = "新的测试显示名"
        again = self.command("seed.py")
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertEqual(again.stdout.splitlines(), ["teacher: unchanged", "student: unchanged"])
        self.assertEqual(self.rows("SELECT * FROM users ORDER BY id"), before)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM user_model_settings"), [(2,)])
        self.assert_private(again)

    def test_shared_normalization_preserves_case_sensitive_number(self) -> None:
        self.create_schema()
        self.env["DEV_TEACHER_EMAIL"] = " Teacher@EXAMPLE.invalid "
        self.env["DEV_TEACHER_USER_NO"] = " 000t "
        self.env["DEV_STUDENT_USER_NO"] = "000T"
        result = self.command("seed.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.rows("SELECT user_no FROM users ORDER BY role"),
                         [("000T",), ("000t",)])
        self.assert_private(result)

    def test_existing_identity_conflicts_never_create_partial_teacher(self) -> None:
        self.create_schema()
        result = self.command("seed.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for statement in (
            "UPDATE users SET role='teacher' WHERE role='student'",
            "UPDATE users SET email='Elsewhere@EXAMPLE.invalid' WHERE role='student'",
            "UPDATE users SET identity='教师' WHERE role='student'",
            "UPDATE users SET email_verified_at=NULL WHERE role='student'",
            "UPDATE users SET status='disabled' WHERE role='student'",
        ):
            with self.subTest(change=statement):
                snapshot = self.database.read_bytes()
                with closing(sqlite3.connect(self.database)) as db:
                    db.execute("DELETE FROM user_model_settings WHERE user_id IN "
                               "(SELECT id FROM users WHERE role='teacher')")
                    db.execute("DELETE FROM users WHERE role='teacher'")
                    db.execute(statement)
                    db.commit()
                before = self.rows("SELECT * FROM users ORDER BY id")
                rejected = self.command("seed.py")
                self.assertEqual(rejected.returncode, 2)
                self.assertEqual(self.rows("SELECT * FROM users ORDER BY id"), before)
                self.assertEqual(self.rows("SELECT COUNT(*) FROM user_model_settings"), [(1,)])
                self.assert_private(rejected)
                self.database.write_bytes(snapshot)

    def test_split_email_and_number_ownership_is_a_conflict(self) -> None:
        self.create_schema()
        first = self.command("seed.py")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("UPDATE users SET user_no='other-number' WHERE role='teacher'")
            db.execute("UPDATE users SET user_no='000T' WHERE role='student'")
            db.commit()
        before = self.rows("SELECT * FROM users ORDER BY id")
        result = self.command("seed.py")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.rows("SELECT * FROM users ORDER BY id"), before)
        self.assert_private(result)

    def test_database_constraint_failure_rolls_back_both_accounts(self) -> None:
        self.create_schema()
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("CREATE TRIGGER reject_student BEFORE INSERT ON users "
                       "WHEN NEW.role='student' BEGIN "
                       "SELECT RAISE(ABORT, 'synthetic rejection'); END")
            db.commit()
        result = self.command("seed.py")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.rows("SELECT COUNT(*) FROM users"), [(0,)])
        self.assertEqual(self.rows("SELECT COUNT(*) FROM user_model_settings"), [(0,)])
        self.assert_private(result)


if __name__ == "__main__":
    unittest.main()
