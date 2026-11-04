"""MathCraft 后端入口。

启动：uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.errors import AppError
from app.services.rag import tokenizer  # 预热 jieba 词典

from app.api import (
    attempts,
    auth,
    banks,
    chat,
    documents,
    favorites,
    generate,
    health,
    papers,
    questions,
    spaces,
    urges,
    users,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 确保 jieba 词典在服务启动时构建完成，避免首个请求卡顿
    tokenizer.tokenize("预热")
    yield


app = FastAPI(title="MathCraft Backend", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(banks.router)
app.include_router(documents.router)
app.include_router(generate.router)
app.include_router(questions.router)
app.include_router(favorites.router)
app.include_router(chat.router)
app.include_router(spaces.router)
app.include_router(papers.router)
app.include_router(urges.router)
app.include_router(attempts.router)

# 头像等本地媒体文件
app.mount("/media", StaticFiles(directory=str(settings.avatar_path())), name="media")


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError):
    headers = {"Cache-Control": "no-store"}
    if exc.status_code == 429:
        headers["Retry-After"] = str(exc.extra.get("retry_after", 60))
    result = JSONResponse(status_code=exc.status_code, content={"detail": exc.to_detail()},
                          headers=headers)
    if _request.url.path in {"/api/auth/refresh", "/api/auth/logout"} and exc.status_code == 401:
        result.delete_cookie("mc_refresh", path="/api/auth", httponly=True,
                             secure=settings.app_env == "production", samesite="lax")
    return result


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, _exc: RequestValidationError):
    # 不回显 Pydantic input：请求体可能携带密码、验证码或人机 token。
    return JSONResponse(status_code=422, content={"detail": {
        "code": "VALIDATION_ERROR", "message": "请求字段格式错误或包含不允许的字段"}})


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_request: Request, exc: SQLAlchemyError):
    if isinstance(exc, IntegrityError):
        return JSONResponse(status_code=409, content={"detail": {
            "code": "AUTH_FAILED", "message": "请求已处理或存在并发冲突，请重新操作"}})
    return JSONResponse(status_code=503, content={"detail": {
        "code": "AUTH_SERVICE_UNAVAILABLE", "message": "数据服务暂不可用，请稍后重试"}})
