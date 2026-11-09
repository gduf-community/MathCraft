"""个人资料、头像与按用户模型配置接口。"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.deps import get_current_user
from app.errors import AppError
from app.models import User
from app.schemas.auth import (
    CurrentPasswordBody, EmailBindingBody, EmailChangeBody, EmailCommitBody,
    ModelSettingsBody, UserNoBody,
)
from app.api.auth_http import clear_refresh, refresh_belongs_to_user
from app.models import EmailChange
from app.models.base import new_id
from app.services import auth as auth_service
from app.services import auth_codes
from app.schemas.user import EmailChangeResult, UserPayload, UserUpdateBody
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


@router.put("", response_model=UserPayload)
def update_profile(
    body: UserUpdateBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """普通资料不得修改认证标识；写入前再次校验版本。"""
    auth_service.assert_version(db, user.id, user.auth_version)
    if body.display_name is not None:
        user.display_name = body.display_name.strip()
    if "gender" in body.model_fields_set:
        user.gender = body.gender
    if "phone" in body.model_fields_set:
        user.phone = body.phone
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
    limit = settings.max_avatar_mb * 1024 * 1024
    content = await file.read(limit + 1)
    if not content:
        raise AppError("EMPTY_FILE", "文件内容为空", status_code=400)
    if len(content) > limit:
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
    auth_service.assert_version(db, user.id, user.auth_version)
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


@router.put("/email-binding", status_code=204, response_model=None)
def bind_email(body: EmailBindingBody, request: Request, response: Response,
               user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """密码及新邮箱 proof 校验后，在同一事务绑定邮箱并撤销全部会话。"""
    version = user.auth_version
    auth_service.require_email_binding(user)
    if not auth_service.verify_password(body.current_password, user.password_hash):
        raise AppError("AUTH_FAILED", "当前密码不正确", 400)
    auth_service.assert_version(db, user.id, version)
    clear_cookie = refresh_belongs_to_user(request, db, user.id)
    auth_codes.verify(db, body.email, "email_bind", auth_service.email_binding(user, body.email),
                      body.challenge_id, body.code)
    auth_service.revoke_all(db, user, version)
    user.email = body.email
    user.email_normalized = body.email
    user.email_verified = True
    user.email_verified_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("EMAIL_IN_USE", "邮箱已被使用", 409) from exc
    response.headers["Cache-Control"] = "no-store"
    if clear_cookie:
        clear_refresh(response)


@router.delete("/email", status_code=204, response_model=None)
def unbind_email(body: CurrentPasswordBody, request: Request, response: Response,
                 user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """校验当前密码后清空邮箱及验证标记，并原子撤销全部会话。"""
    version = user.auth_version
    if not auth_service.verify_password(body.current_password, user.password_hash):
        raise AppError("AUTH_FAILED", "当前密码不正确", 400)
    clear_cookie = refresh_belongs_to_user(request, db, user.id)
    auth_service.revoke_all(db, user, version)
    user.email = None
    user.email_normalized = None
    user.email_verified = False
    user.email_verified_at = None
    db.commit()
    response.headers["Cache-Control"] = "no-store"
    if clear_cookie:
        clear_refresh(response)


@router.post("/email-change", status_code=201, response_model=EmailChangeResult)
def start_email_change(body: EmailChangeBody, user: User = Depends(get_current_user),
                       db: Session = Depends(get_db)):
    """建立十分钟双邮箱快照；后续发码由事务确定真实收件人。"""
    auth_service.assert_version(db, user.id, user.auth_version)
    if not auth_service.has_verified_email(user):
        raise AppError("AUTH_FAILED", "当前邮箱尚未完成验证", 400)
    if body.new_email == user.email_normalized:
        raise AppError("VALIDATION_ERROR", "新邮箱不能与当前邮箱相同", 400)
    if db.query(User).filter_by(email_normalized=body.new_email).first():
        raise AppError("EMAIL_IN_USE", "邮箱已被使用", 409)
    auth_service.cleanup_expired_records(db)
    change = EmailChange(id=new_id("ec"), user_id=user.id, old_email=user.email_normalized,
        new_email=body.new_email, auth_version=user.auth_version,
        expires_at=auth_service.now() + 600)
    db.add(change)
    db.commit()
    return {"change_id": change.id, "expires_in": 600}


@router.put("/email", status_code=204, response_model=None)
def commit_email_change(body: EmailCommitBody, request: Request, response: Response,
                        user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """双 proof、版本、邮箱写入和全部会话撤销位于同一事务。"""
    change = auth_service.get_change(db, user, body.change_id)
    version = user.auth_version
    auth_service.assert_version(db, user.id, version)
    clear_cookie = refresh_belongs_to_user(request, db, user.id)
    auth_codes.verify(db, change.old_email, "email_change_old",
        auth_service.change_binding(change, "email_change_old"), body.old_challenge_id, body.old_code)
    auth_codes.verify(db, change.new_email, "email_change_new",
        auth_service.change_binding(change, "email_change_new"), body.new_challenge_id, body.new_code)
    auth_service.revoke_all(db, user, version)
    user.email = change.new_email
    user.email_normalized = change.new_email
    user.email_verified = True
    user.email_verified_at = datetime.now(timezone.utc)
    change.status = "completed"
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("EMAIL_IN_USE", "邮箱已被使用", 409) from exc
    response.headers["Cache-Control"] = "no-store"
    if clear_cookie:
        clear_refresh(response)


@router.put("/user-no", response_model=UserPayload)
def change_user_no(body: UserNoBody, user: User = Depends(get_current_user),
                   db: Session = Depends(get_db)):
    """学工号增改删验证当前密码和原认证版本，保留用户身份归属。"""
    version = user.auth_version
    if not auth_service.verify_password(body.current_password, user.password_hash):
        raise AppError("AUTH_FAILED", "当前密码不正确", 400)
    auth_service.assert_version(db, user.id, version)
    user.user_no = body.user_no
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise AppError("USER_NO_IN_USE", "学工号已被使用", 409) from exc
    return user_payload(user)
