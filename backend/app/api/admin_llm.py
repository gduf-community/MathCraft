"""平台级 LLM 凭据管理：学校自部署模型接入，API Key 静态加密存储（Fernet）。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.deps import require_admin, get_db
from app.errors import AppError
from app.models import User
from app.models.platform_llm import PlatformLlmSetting
from app.services.rag.llm import invalidate_platform_cache
from app.services.secure_store import MASK_PLACEHOLDER, decrypt_secret, encrypt_secret, mask_secret

router = APIRouter(prefix="/api/admin/llm-settings", tags=["admin"])


class LlmSettingsBody(BaseModel):
    base_url: str = Field(default="", max_length=255)
    model: str = Field(default="", max_length=120)
    display_name: str = Field(default="", max_length=120)
    # 传 MASK_PLACEHOLDER 表示保持原 key 不变；空串表示清除
    api_key: str = Field(default="", max_length=512)


class LlmSettingsResult(BaseModel):
    base_url: str
    model: str
    display_name: str
    api_key_masked: str
    configured: bool
    updated_at: str | None = None


def _row(db: Session) -> PlatformLlmSetting:
    row = db.get(PlatformLlmSetting, 1)
    if row is None:
        row = PlatformLlmSetting(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _payload(row: PlatformLlmSetting) -> dict:
    configured = bool(row.encrypted_key)
    return {
        "base_url": row.base_url,
        "model": row.model,
        "display_name": row.display_name,
        "api_key_masked": mask_secret(decrypt_secret(row.encrypted_key)),
        "configured": configured,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("", response_model=LlmSettingsResult)
def read_llm_settings(
    _user: User = Depends(require_admin), db: Session = Depends(get_db),
):
    """掩码返回平台模型配置，密钥明文不出库。"""
    return _payload(_row(db))


@router.put("", response_model=LlmSettingsResult)
def save_llm_settings(
    body: LlmSettingsBody,
    _user: User = Depends(require_admin), db: Session = Depends(get_db),
):
    """保存平台模型凭据：api_key 加密落库；传掩码占位符则保持原值。"""
    row = _row(db)
    if body.api_key == MASK_PLACEHOLDER:
        if not row.encrypted_key:
            raise AppError("LLM_KEY_MISSING", "尚无已保存的密钥，请填写新的 API Key", status_code=400)
    elif body.api_key:
        row.encrypted_key = encrypt_secret(body.api_key.strip())
    elif body.api_key == "":
        row.encrypted_key = ""
    if body.base_url or body.model or body.display_name or body.api_key:
        row.base_url = body.base_url.strip()
        row.model = body.model.strip()
        row.display_name = body.display_name.strip()
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    invalidate_platform_cache()
    return _payload(row)
