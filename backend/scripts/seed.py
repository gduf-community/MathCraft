"""显式初始化教师与学生开发账号；默认拒绝，绝不覆盖已有账号。

在 backend 下显式执行 python scripts/seed.py。要求 development、dev_accounts_enabled
和两组 dev_{teacher,student}_{email,user_no,password,display_name} 设置完整。
先校验两组配置与全部冲突，再于单事务创建用户及模型设置。重复运行只跳过同一
邮箱、学工号、角色、identity 且启用并已验证的账号；不改密码、角色或资料。
依赖 app.services.auth 的共享规范化与密码校验；兼容迁移未就绪即阻断。
新账号的 account 使用 dev_ 来源标记；发布审计据此阻断开发数据库进入生产。
退出码 0 成功（只输出角色结果），2 配置、依赖、冲突或数据库失败（不回显隐私）。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config import Settings
    from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@dataclass(frozen=True, repr=False)
class DevelopmentAccount:
    """已通过共享校验的开发输入，禁止默认 repr 泄露凭据。"""

    role: str
    identity: str
    email: str
    user_no: str
    password: str
    display_name: str


def _accounts(settings: Settings) -> list[DevelopmentAccount]:
    from app.services.auth import normalize_email, normalize_user_no, validate_password

    accounts = []
    for role, identity in (("teacher", "教师"), ("student", "学生")):
        prefix = f"dev_{role}_"
        email = normalize_email(getattr(settings, prefix + "email"))
        user_no = normalize_user_no(getattr(settings, prefix + "user_no"))
        password = validate_password(getattr(settings, prefix + "password"))
        name = getattr(settings, prefix + "display_name").strip()
        if not user_no or not name or len(name) > 64:
            raise ValueError("开发账号配置不完整")
        accounts.append(DevelopmentAccount(role, identity, email, user_no, password, name))
    if (accounts[0].email == accounts[1].email
            or accounts[0].user_no == accounts[1].user_no):
        raise ValueError("开发账号标识冲突")
    return accounts


def _initialize(db: Session, accounts: list[DevelopmentAccount]) -> list[str]:
    from sqlalchemy import select

    from app.models import User, UserModelSetting
    from app.models.base import new_id
    from app.services.auth import hash_password, normalize_email, normalize_user_no

    if not all(hasattr(User, field) for field in (
        "email_normalized", "email_verified_at", "auth_version",
    )):
        raise ValueError("兼容迁移未就绪")
    results = []
    pending = []
    # Python 共享规范化同时覆盖历史大小写/空白；不能仅查规范列遗漏旧记录。
    existing = db.scalars(select(User)).all()
    for spec in accounts:
        matches = []
        for user in existing:
            try:
                email = normalize_email(user.email) if user.email else None
                number = normalize_user_no(user.user_no)
            except ValueError:
                # 异常历史数据应先由受控审计处理，不在 seed 中修复。
                raise ValueError("历史标识异常") from None
            if (email == spec.email or user.email_normalized == spec.email
                    or number == spec.user_no):
                matches.append(user)
        if matches:
            if len(matches) != 1:
                raise ValueError("标识属于多个账号")
            user = matches[0]
            if (user.email != spec.email or user.email_normalized != spec.email
                    or user.user_no != spec.user_no or user.role != spec.role
                    or user.identity != spec.identity or user.status != "active"
                    or user.email_verified_at is None
                    or type(user.auth_version) is not int or user.auth_version < 0):
                raise ValueError("已有账号与预期不符")
            results.append(f"{spec.role}: unchanged")
        else:
            pending.append(spec)
            results.append(f"{spec.role}: created")
    for spec in pending:
        user = User(
            id=new_id("u"), account=new_id("dev"), email=spec.email,
            email_normalized=spec.email, email_verified_at=datetime.now(timezone.utc),
            auth_version=0, user_no=spec.user_no, role=spec.role, identity=spec.identity,
            password_hash=hash_password(spec.password), display_name=spec.display_name,
            status="active",
        )
        db.add(user)
        db.flush()
        db.add(UserModelSetting(user_id=user.id))
    db.commit()
    return results


def main(argv: list[str] | None = None) -> int:
    """显式校验设置后才打开数据库；失败不输出参数、标识或异常详情。"""
    args = sys.argv[1:] if argv is None else argv
    if args in (["--help"], ["-h"]):
        print(__doc__)
        return 0
    if args:
        print("初始化参数无效；此命令不接受账号、密码或数据库覆盖参数。", file=sys.stderr)
        return 2
    from sqlalchemy.exc import SQLAlchemyError

    try:
        from app.config import settings

        if (settings.app_env != "development" or settings.dev_accounts_enabled is not True):
            raise ValueError("只允许显式启用的开发环境")
        accounts = _accounts(settings)
        from app.db import SessionLocal

        with SessionLocal() as db:
            results = _initialize(db, accounts)
    except (ImportError, AttributeError, ValueError, TypeError):
        print("拒绝初始化：环境、配置、依赖或账号冲突；未更改账号。", file=sys.stderr)
        return 2
    except SQLAlchemyError:
        # SQLAlchemy 可能把 SQL 参数（邮箱、哈希等）包含在错误中，绝不打印详情。
        print("初始化失败：数据库操作未完成；未更改账号。", file=sys.stderr)
        return 2
    for result in results:
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
