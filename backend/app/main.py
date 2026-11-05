"""MathCraft 后端入口。

启动：uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.errors import AppError
from app.services.rag import tokenizer  # 预热 jieba 词典

from app.api import (
    admin,
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
app.include_router(admin.router)
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
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.to_detail()})

