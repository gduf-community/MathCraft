"""按用户的模型配置：DeepSeek 密钥与 MinerU Token 的读取、掩码与生效值。"""
from sqlalchemy.orm import Session

from app import local_secrets
from app.config import settings
from app.errors import AppError
from app.models import User, UserModelSetting


def get_setting(db: Session, user_id: str) -> UserModelSetting:
    row = db.get(UserModelSetting, user_id)
    if row is None:
        row = UserModelSetting(user_id=user_id)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def get_effective_deepseek_key(db: Session, user_id: str) -> str:
    """用户配置优先；环境变量仅作脚本与调试兜底。"""
    row = db.get(UserModelSetting, user_id)
    if row and row.deepseek_api_key:
        return row.deepseek_api_key
    return settings.deepseek_api_key


def get_effective_mineru_token(db: Session, user_id: str) -> str:
    row = db.get(UserModelSetting, user_id)
    if row and row.mineru_token:
        return row.mineru_token
    return local_secrets.MINERU_DEFAULT_TOKEN


def require_deepseek_key(db: Session, user_id: str) -> str:
    key = get_effective_deepseek_key(db, user_id)
    if not key:
        raise AppError(
            "DEEPSEEK_KEY_MISSING",
            "尚未配置 DeepSeek API Key，请到个人中心 → 模型配置中填写",
            status_code=400,
        )
    return key


def mask(secret: str | None) -> str | None:
    if not secret:
        return None
    if len(secret) <= 8:
        return "****"
    return f"{secret[:3]}****{secret[-4:]}"


def user_payload(user: User) -> dict:
    return {
        "id": user.id,
        "account": user.account,
        "role": user.role,
        "status": user.status,
        "identity": user.identity,
        "display_name": user.display_name,
        "gender": user.gender,
        "phone": user.phone,
        "email": user.email,
        "user_no": user.user_no,
        "school": user.school,
        "avatar_url": user.avatar_url,
    }
