"""MathCraft 出题服务入口。启动：``python -m main``。"""

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import chat, generate, kb
from config import settings

app = FastAPI(title="MathCraft 出题服务", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(kb.router)
app.include_router(generate.router)
app.include_router(chat.router)


@app.get("/api/health")
def health():
    """组件连通性自检：ollama 向量模型、DeepSeek 配置。"""
    status = {"chroma_dir": str(settings.chroma_path()), "deepseek_key": bool(settings.deepseek_api_key)}
    try:
        from services.embeddings import embed_one

        dim = len(embed_one("ping"))
        status["ollama_embedding"] = f"ok({dim}d)"
    except Exception as exc:
        status["ollama_embedding"] = f"fail: {exc}"
    return status


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host=os.getenv("QUESTION_BACKEND_HOST", "127.0.0.1"),
        port=int(os.getenv("QUESTION_BACKEND_PORT", "8000")),
        reload=os.getenv("MATH_Q_RELOAD", "").lower() in {"1", "true", "yes"},
    )
