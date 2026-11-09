"""显式交互创建无邮箱管理员：python scripts/create_admin.py。

先完成数据库迁移。此命令没有默认账号，不接受任何账号、密码或数据库参数；
账号与名称交互输入，密码通过 getpass 隐藏输入两次，绝不覆盖已有账号。
仅使用应用现有数据库配置，不初始化数据库、不修改或验证历史邮箱。
"""
from __future__ import annotations

import getpass
from pathlib import Path
import sys
import warnings

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main(argv: list[str] | None = None) -> int:
    """由本机操作者显式执行；所有失败只输出固定信息，不回显输入。"""
    args = sys.argv[1:] if argv is None else argv
    if args in (["--help"], ["-h"]):
        print(__doc__)
        return 0
    if args:
        print("此命令仅支持交互输入，禁止通过命令行提供密码或配置。", file=sys.stderr)
        return 2
    try:
        account = input("登录账号：").strip()
        name = input("显示名称：").strip()
        # 无隐藏输入能力时拒绝，禁止 getpass 降级为回显密码。
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("初始密码：")
            confirmation = getpass.getpass("再次输入初始密码：")
        if password != confirmation:
            print("两次密码不一致，未创建账号。", file=sys.stderr)
            return 2

        from sqlalchemy.exc import SQLAlchemyError

        from app.db import SessionLocal
        from app.models import User, UserModelSetting
        from app.models.base import new_id
        from app.schemas.admin import AccountCreateBody
        from app.services.auth import hash_password

        body = AccountCreateBody(
            account=account, display_name=name, password=password, role="admin",
        )
        try:
            with SessionLocal.begin() as db:
                if db.query(User).filter(User.account == body.account).first() is not None:
                    print("账号已存在，未修改已有账号。", file=sys.stderr)
                    return 2
                user = User(
                    id=new_id("u"), account=body.account, display_name=body.display_name,
                    password_hash=hash_password(body.password), role="admin", identity="管理员",
                    status="active", password_change_recommended=True,
                )
                db.add(user)
                db.flush()
                db.add(UserModelSetting(user_id=user.id))
        except SQLAlchemyError:
            print("数据库操作失败，请检查配置及迁移状态；未完成创建。", file=sys.stderr)
            return 2
    except (EOFError, KeyboardInterrupt, getpass.GetPassWarning):
        print("交互已取消或无法隐藏密码输入，未创建账号。", file=sys.stderr)
        return 2
    except (ImportError, ValueError):
        print("输入、配置或依赖无效；密码须为 8–64 字符且 UTF-8 不超过 72 字节。",
              file=sys.stderr)
        return 2
    print("管理员已创建，请通过账号登录，并在登录后修改初始密码。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
