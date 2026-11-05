"""显式初始化平台初始账号。"""
from dataclasses import dataclass
import re

from sqlalchemy.orm import Session

from app.models import User, UserModelSetting
from app.models.base import new_id
from app.services.auth import hash_password


@dataclass(frozen=True)
class InitialAccount:
    account: str
    password: str
    role: str
    display_name: str


@dataclass(frozen=True)
class InitializationResult:
    created: list[str]
    skipped: list[str]


ROLE_LABELS = {
    "admin": "管理员",
    "teacher": "教师",
    "student": "学生",
}


def _validate_specs(specs: list[InitialAccount]) -> None:
    if len(specs) != 3:
        raise ValueError("初始账号配置必须包含管理员、教师和学生各一个")
    if {spec.role for spec in specs} != set(ROLE_LABELS):
        raise ValueError("初始账号配置必须包含管理员、教师和学生")
    accounts = [spec.account.strip() for spec in specs]
    if any(not account for account in accounts):
        raise ValueError("初始账号不能为空")
    if any(not spec.password for spec in specs):
        raise ValueError("初始密码不能为空")
    if len(set(accounts)) != len(accounts):
        raise ValueError("初始账号不能重复")
    for account, spec in zip(accounts, specs):
        if len(account) > 64 or any(char.isspace() for char in account) or not re.fullmatch(r"^[\u4e00-\u9fffA-Za-z0-9_.-]+$", account):
            raise ValueError("初始账号长度或格式不符合要求")
        if len(spec.password) > 128:
            raise ValueError("初始密码长度不符合要求")


def initialize_accounts(db: Session, specs: list[InitialAccount]) -> InitializationResult:
    """按配置补建初始账号，不覆盖已有账号。"""
    _validate_specs(specs)
    created: list[str] = []
    skipped: list[str] = []
    for spec in specs:
        account = spec.account.strip()
        existing = db.query(User).filter(User.account == account).one_or_none()
        if existing is not None:
            if existing.role != spec.role:
                raise ValueError(f"账号 {account} 已存在但角色不匹配")
            skipped.append(account)
            continue
        user = User(
            id=new_id("u"),
            account=account,
            password_hash=hash_password(spec.password),
            role=spec.role,
            identity=ROLE_LABELS[spec.role],
            display_name=spec.display_name,
            status="active",
        )
        db.add(user)
        db.flush()
        db.add(UserModelSetting(user_id=user.id))
        created.append(account)
    db.commit()
    return InitializationResult(created=created, skipped=skipped)
