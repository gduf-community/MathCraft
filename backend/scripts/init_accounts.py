"""从 .env 显式补建首个管理员、教师和学生账号。

用法：uv run python scripts/init_accounts.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import settings
from app.db import SessionLocal
from app.services.bootstrap import InitialAccount, initialize_accounts


def configured_accounts() -> list[InitialAccount]:
    return [
        InitialAccount(settings.initial_admin_account, settings.initial_admin_password, "admin", "平台管理员"),
        InitialAccount(settings.initial_teacher_account, settings.initial_teacher_password, "teacher", "初始教师"),
        InitialAccount(settings.initial_student_account, settings.initial_student_password, "student", "初始学生"),
    ]


def main() -> None:
    db = SessionLocal()
    try:
        result = initialize_accounts(db, configured_accounts())
    except ValueError as exc:
        print(f"初始化失败：{exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    finally:
        db.close()
    print(f"初始化完成：创建 {len(result.created)} 个账号，跳过 {len(result.skipped)} 个已有账号")


if __name__ == "__main__":
    main()
