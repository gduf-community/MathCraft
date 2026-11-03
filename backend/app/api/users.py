"""个人资料、头像与按用户模型配置接口。"""
from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.errors import AppError
from app.models import User
from app.schemas.auth import ModelSettingsBody
from app.schemas.user import UserUpdateBody
from app.services.model_settings import get_effective_mineru_token, get_setting, mask, user_payload

router = APIRouter(prefix="/api/users/me", tags=["users"])

# 硅基流动 / 向量 / 重排为系统内置，不提供配置入口（v2 文档 8.1）
SYSTEM_BUILTIN = {
    "embedding_model": "BAAI/bge-m3",
    "rerank_model": "BAAI/bge-reranker-v2-m3",
    "embedding_configurable": False,
    "rerank_configurable": False,
}
MINERU_LIMITS = {"max_file_mb": 200, "max_pages": 200}

AVATAR_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}


@router.put("")
def update_profile(
    body: UserUpdateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """修改昵称、性别、手机号、邮箱、学校。"""
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if body.gender is not None:
        user.gender = body.gender
    if body.phone is not None:
        user.phone = body.phone
    if body.email is not None:
        user.email = body.email.strip()
    if body.school is not None:
        user.school = body.school.strip()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("DUPLICATE_FIELD", "手机号或邮箱已被其他账号使用", status_code=409) from exc
    db.refresh(user)
    return user_payload(user)


@router.post("/avatar")
async def upload_avatar(
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """上传头像：PNG / JPG / WebP，≤5MB，保存后返回可访问 URL。"""
    ext = AVATAR_TYPES.get((file.content_type or "").lower())
    if ext is None:
        raise AppError("UNSUPPORTED_FORMAT", "仅支持 PNG / JPG / WebP 图片", status_code=400)
    content = await file.read()
    if not content:
        raise AppError("EMPTY_FILE", "文件内容为空", status_code=400)
    if len(content) > settings.max_avatar_mb * 1024 * 1024:
        raise AppError("DOCUMENT_TOO_LARGE", f"头像不能超过 {settings.max_avatar_mb} MB", status_code=422)

    dest = settings.avatar_path() / f"{user.id}{ext}"
    dest.write_bytes(content)
    user.avatar_url = f"/media/{dest.name}"
    db.commit()
    return {"avatar_url": user.avatar_url}


@router.get("/model-settings")
def read_model_settings(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    row = get_setting(db, user.id)
    return {
        "deepseek_model": settings.deepseek_display_name,
        "deepseek_model_id": settings.deepseek_model,
        "deepseek_key_configured": bool(row.deepseek_api_key),
        "deepseek_key_masked": mask(row.deepseek_api_key),
        "mineru_token_configured": bool(row.mineru_token),
        "mineru_token_masked": mask(row.mineru_token),
        "mineru_using_default": not row.mineru_token,
        "mineru_limits": MINERU_LIMITS,
        **SYSTEM_BUILTIN,
    }


@router.put("/model-settings")
def save_model_settings(
    body: ModelSettingsBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = get_setting(db, user.id)
    if body.deepseek_api_key is not None:
        row.deepseek_api_key = body.deepseek_api_key.strip() or None
    if body.mineru_token is not None:
        row.mineru_token = body.mineru_token.strip() or None
    db.commit()
    return {"saved": True}


@router.post("/model-settings/test-deepseek")
def test_deepseek(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services.rag import llm

    row = get_setting(db, user.id)
    key = row.deepseek_api_key or settings.deepseek_api_key
    if not key:
        raise AppError("DEEPSEEK_KEY_MISSING", "请先填写 DeepSeek API Key", status_code=400)
    try:
        reply = llm.chat_text(
            [{"role": "user", "content": "ping"}],
            api_key=key,
            temperature=0.0,
            max_tokens=8,
        )
    except Exception as exc:
        raise AppError("LLM_ERROR", f"DeepSeek 连接失败：{exc}", status_code=400) from exc
    return {"ok": True, "model": settings.deepseek_display_name, "reply": (reply or "")[:32]}


@router.post("/model-settings/test-mineru")
def test_mineru(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    from app.services import mineru

    token = get_effective_mineru_token(db, user.id)
    if not token:
        raise AppError("MINERU_TOKEN_MISSING", "请先填写 MinerU Token", status_code=400)
    ok, detail = mineru.ping_token(token)
    if not ok:
        raise AppError("LLM_ERROR", f"MinerU Token 无效：{detail}", status_code=400)
    return {"ok": True, "limits": MINERU_LIMITS}
