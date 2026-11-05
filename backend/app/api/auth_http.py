"""认证路由共享的 HTTP Cookie 响应辅助函数。"""
from fastapi import Response

from app.config import settings


def clear_refresh(response: Response) -> None:
    """清除当前浏览器刷新 Cookie，不承载认证业务逻辑。"""
    response.delete_cookie("mc_refresh", path="/api/auth", httponly=True,
                          secure=settings.app_env == "production", samesite="lax")
    response.headers["Cache-Control"] = "no-store"
