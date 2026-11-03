"""命令行创建账号（v2 无用户管理模块，账号由此脚本或 seed 创建）。

用法：
  uv run python scripts/create_user.py --account lisi --password 123456 --role student --name 李四 --user-no ST20250002
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.models import User, UserModelSetting
from app.models.base import new_id
from app.services.auth import hash_password

ROLE_IDENTITY = {"student": "学生", "teacher": "教师"}


def main() -> None:
    p = argparse.ArgumentParser(description="创建 MathCraft 账号")
    p.add_argument("--account", required=True, help="登录账号（唯一）")
    p.add_argument("--password", required=True, help="密码（至少 6 位）")
    p.add_argument("--role", required=True, choices=["student", "teacher"])
    p.add_argument("--name", required=True, help="显示名")
    p.add_argument("--user-no", default=None, help="学号 / 工号")
    p.add_argument("--phone", default=None)
    p.add_argument("--email", default=None)
    p.add_argument("--school", default=None)
    p.add_argument("--gender", default="男", choices=["男", "女"])
    args = p.parse_args()

    if len(args.password) < 6:
        raise SystemExit("密码至少 6 位")

    db = SessionLocal()
    try:
        if db.query(User).filter(User.account == args.account).first():
            raise SystemExit(f"账号 {args.account} 已存在")
        user = User(
            id=new_id("u"),
            account=args.account,
            password_hash=hash_password(args.password),
            role=args.role,
            identity=ROLE_IDENTITY[args.role],
            display_name=args.name,
            gender=args.gender,
            user_no=args.user_no,
            phone=args.phone,
            email=args.email,
            school=args.school,
            status="active",
        )
        db.add(user)
        db.flush()
        db.add(UserModelSetting(user_id=user.id))
        db.commit()
        print(f"已创建 {args.role} 账号 {args.account}（{args.name}）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
