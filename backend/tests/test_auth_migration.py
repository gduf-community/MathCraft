"""受控历史账号审计 CLI；临时 SQLite、退出码、脱敏汇总与字节级只读。"""
from __future__ import annotations

from contextlib import closing
import sqlite3
import unittest

from test_auth_seed import AuthCommandCase


class MigrationCommandTests(AuthCommandCase):
    def test_missing_operator_acknowledgement_never_opens_database(self) -> None:
        result = self.command("auth_migration.py", "audit", "--database", str(self.database))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.database.exists())
        self.assert_private(result)

    def test_dirty_legacy_accounts_block_release_without_modifying_rows(self) -> None:
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("""CREATE TABLE users (
                id TEXT PRIMARY KEY, email TEXT, email_normalized TEXT,
                email_verified_at TEXT, user_no TEXT, role TEXT, identity TEXT,
                auth_version INTEGER
            )""")
            db.executemany("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                ("legacy-one", "Teacher@EXAMPLE.invalid", "teacher@example.invalid",
                 None, "000T", "teacher", "教师", 0),
                ("legacy-two", "teacher@example.invalid", "teacher@example.invalid",
                 "2026-01-01 00:00:00", " 000T ", "student", "教师", 0),
                ("legacy-three", None, None, None, None, "admin", "管理员", 0),
            ])
            db.commit()
        before = self.database.read_bytes()
        result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                              "--database", str(self.database))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('"missing_email": 1', result.stdout)
        self.assertIn('"unverified_email": 2', result.stdout)
        self.assertIn('"email_conflicts": 2', result.stdout)
        self.assertIn('"user_no_conflicts": 2', result.stdout)
        self.assertIn('"role_identity_invalid": 2', result.stdout)
        self.assertEqual(self.database.read_bytes(), before)
        self.assert_private(result)
        self.assertNotIn("legacy-", result.stdout + result.stderr)

    def test_clean_accounts_allow_release_with_case_sensitive_user_numbers(self) -> None:
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT, "
                       "email_normalized TEXT, email_verified_at TEXT, user_no TEXT, "
                       "role TEXT, identity TEXT, auth_version INTEGER)")
            db.executemany("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?)", [
                ("one", "teacher@example.invalid", "teacher@example.invalid",
                 "2026-01-01T00:00:00+00:00", "000T", "teacher", "教师", 0),
                ("two", "student@example.invalid", "student@example.invalid",
                 "2026-01-01T00:00:00+00:00", "000t", "student", "学生", 2),
            ])
            db.commit()
        before = self.database.read_bytes()
        result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                              "--database", str(self.database))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"blocked": false', result.stdout)
        self.assertIn('"total": 2', result.stdout)
        self.assertEqual(self.database.read_bytes(), before)
        self.assert_private(result)

    def test_missing_compatibility_fields_block_release(self) -> None:
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("CREATE TABLE users (id TEXT PRIMARY KEY, email TEXT)")
            db.commit()
        before = self.database.read_bytes()
        result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                              "--database", str(self.database))
        self.assertEqual(result.returncode, 1)
        self.assertIn('"schema_missing_columns": 6', result.stdout)
        self.assertEqual(self.database.read_bytes(), before)
        self.assert_private(result)

    def test_untrusted_verification_markers_and_invalid_versions_block_release(self) -> None:
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("CREATE TABLE users (email TEXT, email_normalized TEXT, "
                       "email_verified_at TEXT, user_no TEXT, role TEXT, identity TEXT, "
                       "auth_version INTEGER)")
            db.executemany("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)", [
                ("first@example.invalid", "first@example.invalid", "", "", "student", "学生", -1),
                ("second@example.invalid", "second@example.invalid", "2099-01-01T00:00:00Z",
                 None, "teacher", "教师", 0),
                ("third@example.invalid", "third@example.invalid", "true",
                 None, "student", "学生", 0),
            ])
            db.commit()
        result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                              "--database", str(self.database))
        self.assertEqual(result.returncode, 1)
        self.assertIn('"unverified_email": 3', result.stdout)
        self.assertIn('"auth_version_invalid": 1', result.stdout)
        self.assertIn('"user_no_not_normalized": 1', result.stdout)
        self.assert_private(result)

    def test_missing_database_is_never_created_or_disclosed(self) -> None:
        result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                              "--database", str(self.database))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.database.exists())
        self.assert_private(result)

    def test_unknown_write_options_are_rejected_without_echoing_secrets(self) -> None:
        result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                              "--database", str(self.database), "--mark-verified",
                              self.env["DEV_TEACHER_PASSWORD"])
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.database.exists())
        self.assert_private(result)


if __name__ == "__main__":
    unittest.main()
