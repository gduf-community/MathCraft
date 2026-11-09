"""受控历史账号只读发布审计，不修复、不猜测、不自动验证历史邮箱。

操作者先备份并在受控维护窗口取得数据库文件的操作系统读取权限，再运行：
    python backend/scripts/auth_migration.py audit --operator-confirmed --database <副本路径>

--operator-confirmed 是操作确认，不是认证或授权机制；不得通过公开 HTTP 暴露。
--database 必须显式指定已有 SQLite 文件，不读取应用配置，不访问 Redis。
退出码：0 可发布；1 数据或兼容字段异常、阻断发布；2 参数或读取失败。
补齐由数据拥有者核实归属后走正式邮件验证或独立审批的证明流程；本命令没有写入选项。
缺失认证表、列、约束或迁移版本异常均阻断；dev_ 来源开发账号必须由拥有者处置。
所有启用账号可走账号密码通道；缺失或未验证邮箱仅作信息提示，不阻断发布。
仅输出数量；各类数量可重叠，冲突数量按涉及的账号数而不是冲突组数统计。
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys

# 直接执行脚本时只定位源码包，纯校验模块不导入应用配置。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.auth_validators import normalize_email, normalize_user_no  # noqa: E402


REQUIRED_COLUMNS = {
    "email", "email_normalized", "email_verified_at", "user_no", "role", "identity",
    "auth_version",
}
ROLE_IDENTITIES = {"teacher": "教师", "student": "学生", "admin": "管理员"}
AUTH_COLUMNS = {
    "users": REQUIRED_COLUMNS | {
        "id", "account", "password_hash", "status", "email_verified", "display_name",
        "gender", "phone", "school", "avatar_url", "created_at", "updated_at",
        "password_change_recommended",
    },
    "auth_sessions": {"id", "user_id", "auth_version", "status", "created_at",
                      "expires_at", "refresh_digest"},
    "auth_refresh_uses": {"digest", "session_id", "expires_at"},
    "auth_proofs": {"challenge_id", "purpose", "consumed_at"},
    "auth_email_changes": {"id", "user_id", "old_email", "new_email", "auth_version",
                           "expires_at", "status"},
}
UNIQUE_KEYS = {
    "users": [("id",), ("account",), ("email",), ("email_normalized",), ("user_no",)],
    "auth_sessions": [("id",), ("refresh_digest",)],
    "auth_refresh_uses": [("digest",)],
    "auth_proofs": [("challenge_id",)],
    "auth_email_changes": [("id",)],
}
FOREIGN_KEYS = {
    "auth_sessions": ("users", "user_id", "id"),
    "auth_refresh_uses": ("auth_sessions", "session_id", "id"),
    "auth_email_changes": ("users", "user_id", "id"),
}


def _expected_heads() -> set[str]:
    """只解析当前发布源码的迁移标识，不执行迁移或导入应用配置。"""
    revisions: set[str] = set()
    parents: set[str] = set()
    directory = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    for path in directory.glob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8-sig")).body:
            if isinstance(node, ast.Assign):
                targets = node.targets
            elif isinstance(node, ast.AnnAssign):
                targets = [node.target]
            else:
                continue
            names = {target.id for target in targets if isinstance(target, ast.Name)}
            if "revision" in names:
                revisions.add(ast.literal_eval(node.value))
            elif "down_revision" in names:
                value = ast.literal_eval(node.value)
                if isinstance(value, str):
                    parents.add(value)
                elif value:
                    parents.update(value)
    heads = revisions - parents
    if len(heads) != 1:
        raise ValueError("发布迁移必须具有唯一 head")
    return heads


def _schema_audit(db: sqlite3.Connection) -> dict[str, int]:
    """核对发布 revision、认证表列、唯一键与外键，不能只相信版本标记。"""
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    counts = {
        "schema_missing_tables": len(AUTH_COLUMNS.keys() - tables),
        "schema_incomplete_columns": 0, "schema_missing_constraints": 0,
        "schema_revision_invalid": 1, "schema_foreign_key_errors": 0,
        "schema_migration_residue": sum(name.startswith("_alembic_tmp_") for name in tables),
    }
    if "alembic_version" in tables:
        version_columns = {row[1] for row in db.execute("PRAGMA table_info(alembic_version)")}
        if "version_num" in version_columns:
            versions = db.execute("SELECT version_num FROM alembic_version").fetchall()
            counts["schema_revision_invalid"] = int(
                {row[0] for row in versions} != _expected_heads() or len(versions) != 1
            )
    for table, required in AUTH_COLUMNS.items():
        if table not in tables:
            continue
        columns = list(db.execute(f'PRAGMA table_info("{table}")'))
        counts["schema_incomplete_columns"] += len(required - {row[1] for row in columns})
        keys = {tuple(row[1] for row in sorted(columns, key=lambda row: row[5]) if row[5])}
        for index in db.execute(f'PRAGMA index_list("{table}")'):
            if index[2] and not index[4]:
                name = index[1].replace('"', '""')
                keys.add(tuple(row[2] for row in db.execute(f'PRAGMA index_info("{name}")')))
        counts["schema_missing_constraints"] += sum(
            key not in keys for key in UNIQUE_KEYS[table]
        )
        if table in FOREIGN_KEYS:
            foreign_keys = {tuple(row[2:5]) for row in db.execute(
                f'PRAGMA foreign_key_list("{table}")'
            )}
            counts["schema_missing_constraints"] += int(FOREIGN_KEYS[table] not in foreign_keys)
    try:
        counts["schema_foreign_key_errors"] = len(db.execute("PRAGMA foreign_key_check").fetchall())
    except sqlite3.DatabaseError:
        counts["schema_foreign_key_errors"] = 1
    return counts


def _verified(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        verified_at = datetime.fromisoformat(value)
        if verified_at.tzinfo is None:
            verified_at = verified_at.replace(tzinfo=timezone.utc)
        return verified_at <= datetime.now(timezone.utc)
    except ValueError:
        return False


def audit(database: Path) -> dict[str, int]:
    """以 SQLite mode=ro 和 query_only 双重限制读取一致快照，只返回数量。"""
    path = database.resolve(strict=True)
    if not path.is_file():
        raise ValueError("需要已有数据库文件")
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        columns = {row[1] for row in db.execute("PRAGMA table_info(users)")}
        missing = REQUIRED_COLUMNS - columns
        counts = {"schema_missing_columns": len(missing), **_schema_audit(db)}
        if missing:
            return counts
        account_column = "account" if "account" in columns else "NULL"
        status_column = "status" if "status" in columns else "NULL"
        rows = db.execute(
            "SELECT email, email_normalized, email_verified_at, user_no, role, identity, "
            f"auth_version, {account_column}, {status_column} FROM users"
        ).fetchall()
    counts.update({
        "total": len(rows), "missing_email": 0, "unverified_email": 0,
        "email_invalid": 0, "email_not_normalized": 0, "email_conflicts": 0,
        "user_no_invalid": 0, "user_no_not_normalized": 0, "user_no_conflicts": 0,
        "role_identity_invalid": 0, "auth_version_invalid": 0, "development_accounts": 0,
    })
    emails: Counter[str] = Counter()
    numbers: Counter[str] = Counter()
    for email, normalized, verified_at, user_no, role, identity, version, account, status in rows:
        development = isinstance(account, str) and account.startswith("dev_")
        counts["development_accounts"] += int(development)
        if email is None or (isinstance(email, str) and not email.strip()):
            counts["missing_email"] += 1
        elif not isinstance(email, str):
            counts["email_invalid"] += 1
        else:
            try:
                canonical = normalize_email(email)
            except ValueError:
                counts["email_invalid"] += 1
            else:
                emails[canonical] += 1
                if email != canonical or normalized != canonical:
                    counts["email_not_normalized"] += 1
        if not _verified(verified_at):
            counts["unverified_email"] += 1
        if user_no is not None:
            if not isinstance(user_no, str):
                counts["user_no_invalid"] += 1
            else:
                try:
                    number = normalize_user_no(user_no)
                except ValueError:
                    counts["user_no_invalid"] += 1
                else:
                    if not number or number != user_no:
                        counts["user_no_not_normalized"] += 1
                    if number:
                        numbers[number] += 1
        if role not in ROLE_IDENTITIES or identity != ROLE_IDENTITIES.get(role):
            counts["role_identity_invalid"] += 1
        if type(version) is not int or version < 0:
            counts["auth_version_invalid"] += 1
    counts["email_conflicts"] = sum(size for size in emails.values() if size > 1)
    counts["user_no_conflicts"] = sum(size for size in numbers.values() if size > 1)
    return counts


class AuditArgumentParser(argparse.ArgumentParser):
    """参数错误不回显可能含路径、标识或凭据的实参。"""

    def error(self, message: str) -> None:
        self.exit(2, "审计参数无效；需要 audit、--operator-confirmed 与 --database。\n")


def main(argv: list[str] | None = None) -> int:
    """审计为唯一子命令；未明确确认的操作者在打开文件前被拒绝。"""
    parser = AuditArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    command = subparsers.add_parser("audit", help="只读审计；任何异常阻断发布")
    command.add_argument("--operator-confirmed", action="store_true", required=True)
    command.add_argument("--database", required=True, help="受控 SQLite 备份或副本路径")
    # 自定义 parser 的错误处理也覆盖子命令，避免参数回显泄露隐私。
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code or 0)
    try:
        counts = audit(Path(args.database))
    except (OSError, ValueError, SyntaxError, sqlite3.Error):
        print("审计失败：无法读取指定数据库；发布阻断。", file=sys.stderr)
        return 2
    blocked = any(count for key, count in counts.items() if key not in {"total", "missing_email", "unverified_email"})
    print(json.dumps({"blocked": blocked, **counts}, ensure_ascii=True, sort_keys=True))
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
