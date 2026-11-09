"""受控历史账号审计 CLI；临时 SQLite、退出码、脱敏汇总与字节级只读。"""
from __future__ import annotations

from contextlib import closing
import sqlite3
import unittest

from test_auth_seed import AuthCommandCase

from app.auth_validators import normalize_email, normalize_user_no


class MigrationCommandTests(AuthCommandCase):
    def test_invalid_login_keys_block_release_without_loading_configuration(self) -> None:
        """CLI 必须采用登录键真实校验，并保持配置与凭据完全不被导入。"""
        (self.backend / "app" / "config.py").write_text(
            'raise RuntimeError("audit imported configuration")\n', encoding="utf-8",
        )
        (self.backend / "app" / "local_secrets.py").write_text(
            'raise RuntimeError("audit imported credentials")\n', encoding="utf-8",
        )
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("CREATE TABLE users (email TEXT, email_normalized TEXT, "
                       "email_verified_at TEXT, user_no TEXT, role TEXT, identity TEXT, "
                       "auth_version INTEGER)")
            cases = [
                ("not-an-address", "000T", "email_invalid"),
                ("person@example", "000T", "email_invalid"),
                ("a@.example.test", "000T", "email_invalid"),
                ("a@example..test", "000T", "email_invalid"),
                ("a@example.test.", "000T", "email_invalid"),
                ("a" * 116 + "@example.test", "000T", "email_invalid"),
                ("bad\x00@example.test", "000T", "email_invalid"),
                ("bad\x1f@example.test", "000T", "email_invalid"),
                ("bad\x7f@example.test", "000T", "email_invalid"),
                (b"person@example.test", "000T", "email_invalid"),
                ("person@example.test", "x" * 33, "user_no_invalid"),
                ("person@example.test", "A B", "user_no_invalid"),
                ("a\u0080@example.test", "000T", "email_invalid"),
                ("a@example\u009f.test", "000T", "email_invalid"),
                ("person@example.test", "A\u3000B", "user_no_invalid"),
                ("person@example.test", "A\u00a0B", "user_no_invalid"),
                ("person@example.test", "A\u0080B", "user_no_invalid"),
                ("person@example.test", "A\x00B", "user_no_invalid"),
                ("person@example.test", "A\x1fB", "user_no_invalid"),
                ("person@example.test", "A\x7fB", "user_no_invalid"),
                ("person@example.test", b"000T", "user_no_invalid"),
            ]
            for email, user_no, counter in cases:
                with self.subTest(counter=counter, email_type=type(email).__name__,
                                  number_type=type(user_no).__name__):
                    db.execute("DELETE FROM users")
                    db.execute("INSERT INTO users VALUES (?, ?, ?, ?, ?, ?, ?)", (
                        email, email, "2026-01-01T00:00:00+00:00", user_no,
                        "teacher", "教师", 0,
                    ))
                    db.commit()
                    before = self.database.read_bytes()
                    result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                                          "--database", str(self.database))
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn(f'"{counter}": 1', result.stdout)
                    self.assertEqual(self.database.read_bytes(), before)
                    self.assert_private(result)
                    self.assertNotIn("person@example.test", result.stdout + result.stderr)

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
        self.assertIn('"role_identity_invalid": 1', result.stdout)
        self.assertEqual(self.database.read_bytes(), before)
        self.assert_private(result)
        self.assertNotIn("legacy-", result.stdout + result.stderr)

    def _create_publishable_schema(self) -> None:
        """构造合成完整认证库及受控账号，不读取应用配置。"""
        self.create_schema()
        result = self.command("seed.py")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        from alembic.script import ScriptDirectory

        head = ScriptDirectory(str(self.backend / "alembic")).get_current_head()
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("CREATE TABLE alembic_version (version_num TEXT PRIMARY KEY)")
            db.execute("INSERT INTO alembic_version VALUES (?)", (head,))
            db.execute("UPDATE users SET account='controlled_' || role")
            db.execute("UPDATE users SET user_no='000t' WHERE role='student'")
            db.commit()

    def test_clean_accounts_allow_release_with_case_sensitive_user_numbers(self) -> None:
        self._create_publishable_schema()
        before = self.database.read_bytes()
        result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                              "--database", str(self.database))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"blocked": false', result.stdout)
        self.assertIn('"total": 2', result.stdout)
        self.assertEqual(self.database.read_bytes(), before)
        self.assert_private(result)

    def test_missing_and_unverified_email_are_informational_with_complete_schema(self) -> None:
        """邮箱不是账号密码通道的前置条件，审计仍计数但不阻断发布。"""
        self._create_publishable_schema()
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("UPDATE users SET email=NULL, email_normalized=NULL, "
                       "email_verified=0, email_verified_at=NULL WHERE role='student'")
            db.execute("UPDATE users SET email_verified=0, email_verified_at=NULL "
                       "WHERE role='teacher'")
            db.commit()
        before = self.database.read_bytes()
        result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                              "--database", str(self.database))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"blocked": false', result.stdout)
        self.assertIn('"missing_email": 1', result.stdout)
        self.assertIn('"unverified_email": 2', result.stdout)
        self.assertEqual(self.database.read_bytes(), before)
        self.assert_private(result)

    def test_development_accounts_block_release_even_with_complete_schema(self) -> None:
        self._create_publishable_schema()
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("UPDATE users SET account='dev_' || id")
            db.commit()
        before = self.database.read_bytes()
        result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                              "--database", str(self.database))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('"development_accounts": 2', result.stdout)
        self.assertEqual(self.database.read_bytes(), before)
        self.assert_private(result)

    def test_missing_auth_table_and_wrong_revision_block_release(self) -> None:
        self._create_publishable_schema()
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("DROP TABLE auth_proofs")
            db.commit()
        result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                              "--database", str(self.database))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('"schema_missing_tables": 1', result.stdout)
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("UPDATE alembic_version SET version_num='unknown-revision'")
            db.commit()
        result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                              "--database", str(self.database))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('"schema_revision_invalid": 1', result.stdout)

    def test_audit_tracks_new_annotated_migration_head(self) -> None:
        self._create_publishable_schema()
        with closing(sqlite3.connect(self.database)) as db:
            previous = db.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        (self.backend / "alembic/versions/synthetic_followup.py").write_text(
            f"revision: str = 'synthetic_followup'\ndown_revision: str = {previous!r}\n",
            encoding="utf-8",
        )
        result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                              "--database", str(self.database))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('"schema_revision_invalid": 1', result.stdout)
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("UPDATE alembic_version SET version_num='synthetic_followup'")
            db.commit()
        result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                              "--database", str(self.database))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_password_reminder_column_blocks_release(self) -> None:
        """即使版本标记正确，遗漏账号提醒列的数据库也不能通过审计。"""
        self._create_publishable_schema()
        with closing(sqlite3.connect(self.database)) as db:
            db.execute("ALTER TABLE users DROP COLUMN password_change_recommended")
            db.commit()
        before = self.database.read_bytes()
        result = self.command("auth_migration.py", "audit", "--operator-confirmed",
                              "--database", str(self.database))
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('"schema_incomplete_columns": 1', result.stdout)
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


class LoginIdentifierValidationTests(unittest.TestCase):
    """共享纯校验的拒绝边界与既有规范化行为。"""

    def test_user_numbers_reject_unicode_whitespace_and_controls(self) -> None:
        """内部 Unicode 空白和 C0、DEL、C1 控制字符均不能作为学工号。"""
        separators = (
            " ", "\t", "\n", "\x00", "\x1f", "\x7f", "\u0080", "\u0085", "\u009f",
            "\u00a0", "\u1680", "\u2003", "\u2028", "\u2029", "\u202f", "\u3000",
        )
        for separator in separators:
            with self.subTest(codepoint=f"U+{ord(separator):04X}"):
                with self.assertRaisesRegex(ValueError, "学工号"):
                    normalize_user_no(f"A{separator}B")
        for value in ("\u0080AB", "AB\u009f", "x" * 33):
            with self.subTest(value=ascii(value)):
                with self.assertRaisesRegex(ValueError, "学工号"):
                    normalize_user_no(value)

    def test_user_number_normalization_preserves_existing_identifiers(self) -> None:
        """保留去边空白、空值移除、前导零、大小写及合法 Unicode 字符。"""
        cases = (
            (None, None), ("", None), (" \t\u3000\u00a0", None),
            ("\u3000\u00a0000aB\u00a0\u3000", "000aB"),
            ("000T", "000T"), ("000t", "000t"),
            ("学号Ａ01", "学号Ａ01"), ("x" * 32, "x" * 32),
        )
        for value, expected in cases:
            with self.subTest(value=ascii(value)):
                self.assertEqual(normalize_user_no(value), expected)

    def test_email_domains_reject_empty_labels(self) -> None:
        """域名开头、内部或结尾的空标签都必须被拒绝。"""
        for value in (
            "a@.example.test", "a@example..test", "a@example.test.",
            "a@sub..example.test", "a@..example.test", "a@.",
            "a\u0080@example.test", "a@example\u009f.test",
        ):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "邮箱"):
                    normalize_email(value)

    def test_email_normalization_preserves_supported_addresses(self) -> None:
        """仅折叠大小写并去边空白，保留本地点号、加号及已有域名兼容性。"""
        cases = (
            ("\u3000A.B+Tag@Sub.Example.TEST\u00a0", "a.b+tag@sub.example.test"),
            ("a@sub.example.test", "a@sub.example.test"),
            ("a@sub_domain.example.test", "a@sub_domain.example.test"),
            ("用户@例子.测试", "用户@例子.测试"),
            ("a" * 115 + "@example.test", "a" * 115 + "@example.test"),
        )
        for value, expected in cases:
            with self.subTest(value=ascii(value)):
                self.assertEqual(normalize_email(value), expected)


if __name__ == "__main__":
    unittest.main()
