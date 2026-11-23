"""按用户的模型配置：DeepSeek 密钥与 MinerU Token 的读取、掩码与生效值。"""
from urllib.parse import urlsplit

from sqlalchemy.orm import Session

from app import local_secrets
from app.errors import AppError
from app.models import User, UserModelSetting
from app.services.auth import has_verified_email
from app.services.rag.llm import LlmRuntime, ResolvedApiKey, resolve_llm_runtime


def get_setting(db: Session, user_id: str) -> UserModelSetting:
    """在调用者事务内获取或创建设置，不释放认证版本锁。"""
    row = db.get(UserModelSetting, user_id)
    if row is None:
        row = UserModelSetting(user_id=user_id)
        db.add(row)
        db.flush()
    return row


def get_effective_llm_runtime(db: Session, user_id: str) -> LlmRuntime:
    """读取个人配置并一次解析完整运行快照，不提交或释放调用者事务。"""
    row = db.get(UserModelSetting, user_id)
    if row and row.deepseek_api_key:
        runtime = resolve_llm_runtime(row.deepseek_api_key)
        base_url = getattr(row, "deepseek_base_url", None)
        if base_url:
            return LlmRuntime(
                runtime.api_key, base_url, runtime.model, "personal",
            )
        return runtime
    return resolve_llm_runtime(None)


def get_effective_deepseek_key(db: Session, user_id: str) -> str:
    """兼容旧调用链的字符串参数，完整凭据及来源仅附于内存对象。"""
    return ResolvedApiKey(get_effective_llm_runtime(db, user_id))


def validate_deepseek_base_url(value: str) -> str:
    """校验个人模型服务地址，禁止把凭据放入 URL。"""
    normalized = value.strip().rstrip("/")
    try:
        parts = urlsplit(normalized)
        _ = parts.port
    except ValueError as exc:
        raise AppError("INVALID_MODEL_BASE_URL", "DeepSeek Base URL 的地址格式无效", 422) from exc
    if (parts.scheme not in ("http", "https") or not parts.hostname
            or parts.username is not None or parts.password is not None
            or parts.query or parts.fragment or any(char.isspace() for char in normalized)):
        raise AppError(
            "INVALID_MODEL_BASE_URL",
            "DeepSeek Base URL 必须是完整的 HTTP(S) 地址，不能包含账号、密码、查询参数或片段",
            422,
        )
    return normalized


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
            "尚未配置 DeepSeek API Key，请到个人中心 → API 配置中填写",
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
        "identity": {"teacher": "教师", "student": "学生", "admin": "管理员"}[user.role],
        "display_name": user.display_name,
        "gender": user.gender,
        "phone": user.phone,
        "email": user.email,
        "email_verified": has_verified_email(user),
        "user_no": user.user_no,
        "school": user.school,
        "avatar_url": user.avatar_url,
        "password_change_recommended": getattr(user, "password_change_recommended", False),
    }
