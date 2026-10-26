"""Teacher profile routes, separate from model configuration and identity."""

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from math_q_agent.services.profile import MAX_AVATAR_BYTES, InvalidAvatar, ProfileService
from schemas.profile import UserProfile, UserProfileUpdate

from .auth import require_auth

router = APIRouter(
    dependencies=[Depends(require_auth)],
    responses={503: {"description": "Profile storage is unavailable"}},
)


def storage_unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="个人资料暂时无法保存或读取，请稍后重试")


@router.get("", response_model=UserProfile)
def get_profile() -> UserProfile:
    try:
        return ProfileService().read()
    except (OSError, ValidationError):
        raise storage_unavailable() from None


@router.put("", response_model=UserProfile)
def put_profile(details: UserProfileUpdate) -> UserProfile:
    try:
        return ProfileService().update(details)
    except (OSError, ValidationError):
        raise storage_unavailable() from None


@router.post("/avatar", response_model=UserProfile, responses={
    400: {"description": "Invalid image, format, filename or dimensions"},
    413: {"description": "Avatar exceeds 5 MiB"},
})
async def upload_avatar(file: UploadFile = File(...)) -> UserProfile:
    try:
        payload = await file.read(MAX_AVATAR_BYTES + 1)
        return await run_in_threadpool(
            ProfileService().save_avatar, payload, file.filename, file.content_type,
        )
    except InvalidAvatar as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from None
    except (OSError, ValidationError):
        raise storage_unavailable() from None
    finally:
        await file.close()


@router.get("/avatar", response_class=Response, responses={
    200: {"content": {"image/png": {}}, "description": "Saved avatar"},
    404: {"description": "No saved avatar"},
})
def get_avatar() -> Response:
    try:
        payload = ProfileService().read_avatar()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="未设置头像") from None
    except OSError:
        raise storage_unavailable() from None
    return Response(payload, media_type="image/png", headers={
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
    })
