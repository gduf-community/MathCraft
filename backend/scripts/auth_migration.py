"""受控历史账号只读发布审计，不修复、不猜测、不自动验证历史邮箱。

操作者先备份并在受控维护窗口取得数据库文件的操作系统读取权限，再运行：
    python backend/scripts/auth_migration.py audit --operator-confirmed --database <副本路径>

--operator-confirmed 是操作确认，不是认证或授权机制；不得通过公开 HTTP 暴露。
--database 必须显式指定已有 SQLite 文件，不读取应用配置，不访问 Redis。
退出码：0 可发布；1 数据或兼容字段异常、阻断发布；2 参数或读取失败。
补齐由数据拥有者核实归属后走正式邮件验证或独立审批的证明流程；本命令没有写入选项。
缺失 email_verified_at/email_normalized/auth_version 也阻断，先部署兼容迁移再审计。
仅输出数量；各类数量可重叠，冲突数量按涉及的账号数而不是冲突组数统计。
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys


REQUIRED_COLUMNS = {
    "email", "email_normalized", "email_verified_at", "user_no", "role", "identity",
    "auth_version",
}
ROLE_IDENTITIES = {"teacher": "教师", "student": "学生"}


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
        counts = {"schema_missing_columns": len(missing)}
        if missing:
            return counts
        rows = db.execute(
            "SELECT email, email_normalized, email_verified_at, user_no, role, identity, "
            "auth_version FROM users"
        ).fetchall()
    counts.update({
        "total": len(rows), "missing_email": 0, "unverified_email": 0,
        "email_not_normalized": 0, "email_conflicts": 0,
        "user_no_not_normalized": 0, "user_no_conflicts": 0,
        "role_identity_invalid": 0, "auth_version_invalid": 0,
    })
    emails: Counter[str] = Counter()
    numbers: Counter[str] = Counter()
    for email, normalized, verified_at, user_no, role, identity, version in rows:
        # 此处审计历史存储是否符合登录键策略，不替代注册入口的输入校验器。
        canonical = email.strip().lower() if isinstance(email, str) else ""
        if not canonical:
            counts["missing_email"] += 1
        else:
            emails[canonical] += 1
            if email != canonical or normalized != canonical:
                counts["email_not_normalized"] += 1
        if not _verified(verified_at):
            counts["unverified_email"] += 1
        if user_no is not None:
            number = user_no.strip() if isinstance(user_no, str) else ""
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
    except (OSError, ValueError, sqlite3.Error):
        print("审计失败：无法读取指定数据库；发布阻断。", file=sys.stderr)
        return 2
    blocked = any(count for key, count in counts.items() if key != "total")
    print(json.dumps({"blocked": blocked, **counts}, ensure_ascii=True, sort_keys=True))
    return 1 if blocked else 0


if __name__ == "__main__":
    raise SystemExit(main())
