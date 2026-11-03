"""初始化测试账号：student / teacher，密码均为 123123。

用法：uv run python scripts/seed.py
幂等：已存在的账号跳过。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db import SessionLocal
from app.models import User, UserModelSetting
from app.models.base import new_id
from app.services.auth import hash_password

ACCOUNTS = [
    {
        "account": "teacher",
        "password": "123123",
        "role": "teacher",
        "identity": "教师",
        "display_name": "张老师",
        "user_no": "TK20240001",
        "gender": "男",
        "phone": "13800000001",
        "email": "teacher@mathcraft.dev",
        "school": "广东金融学院",
    },
    {
        "account": "student",
        "password": "123123",
        "role": "student",
        "identity": "学生",
        "display_name": "小明",
        "user_no": "ST20250001",
        "gender": "男",
        "phone": "13800000002",
        "email": "student@mathcraft.dev",
        "school": "广东金融学院",
    },
    {
        "account": "student2",
        "password": "123123",
        "role": "student",
        "identity": "学生",
        "display_name": "小红",
        "user_no": "ST20250002",
        "gender": "女",
        "phone": "13800000003",
        "email": "student2@mathcraft.dev",
        "school": "广东金融学院",
    },
]


def ensure_user(db, spec: dict) -> bool:
    exists = db.query(User).filter(User.account == spec["account"]).first()
    if exists:
        print(f"跳过已存在账号 {spec['account']}")
        return False
    user = User(
        id=new_id("u"),
        account=spec["account"],
        password_hash=hash_password(spec["password"]),
        role=spec["role"],
        identity=spec["identity"],
        display_name=spec["display_name"],
        gender=spec.get("gender"),
        user_no=spec.get("user_no"),
        phone=spec.get("phone"),
        email=spec.get("email"),
        school=spec.get("school"),
        status="active",
    )
    db.add(user)
    db.flush()
    db.add(UserModelSetting(user_id=user.id))
    db.commit()
    print(f"创建账号 {spec['account']} / {spec['password']}（{spec['identity']}）")
    return True


def main() -> None:
    db = SessionLocal()
    try:
        for spec in ACCOUNTS:
            ensure_user(db, spec)
    finally:
        db.close()


if __name__ == "__main__":
    main()
