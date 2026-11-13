"""MathCraft 后端入口。

启动：uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.errors import AppError
from app.schemas.auth import ErrorResponse
from app.services.rag import tokenizer  # 预热 jieba 词典
from app.services.rag.embeddings import EmbeddingError
from app.services.rag.vectorstore import VectorStoreError

from app.api import (
    admin,
    admin_rag,
    attempts,
    auth,
    banks,
    chat,
    documents,
    export,
    favorites,
    generate,
    health,
    notifications,
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
    # 收尾上次进程退出时中断的入库任务，避免文档永久停在「正在识别」
    from app.db import SessionLocal
    from app.models import Document
    from app.services.rag_settings import recover_interrupted_rebuild

    recover_interrupted_rebuild()

    db = SessionLocal()
    try:
        stuck = (
            db.query(Document)
            .filter(Document.status.in_(("uploaded", "parsing", "ocr", "chunking", "embedding")))
            .all()
        )
        for doc in stuck:
            doc.status = "failed"
            doc.stage = "服务重启，任务已中断"
            doc.error_message = "服务重启导致任务中断，请重新解析"
        if stuck:
            db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()
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
app.include_router(admin_rag.router)
app.include_router(users.router)
app.include_router(banks.router)
app.include_router(documents.router)
app.include_router(generate.router)
app.include_router(questions.router)
app.include_router(favorites.router)
app.include_router(export.router)
app.include_router(chat.router)
app.include_router(spaces.router)
app.include_router(papers.router)
app.include_router(urges.router)
app.include_router(notifications.router)
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
    if _request.url.path == "/api/auth/refresh" and exc.status_code == 401:
        result.delete_cookie("mc_refresh", path="/api/auth", httponly=True,
                             secure=settings.app_env == "production", samesite="lax")
    return result


@app.exception_handler(VectorStoreError)
@app.exception_handler(EmbeddingError)
async def rag_service_error_handler(
    _request: Request, exc: VectorStoreError | EmbeddingError,
) -> JSONResponse:
    """统一处理未在入口转换的 RAG 故障，固定文案避免回显底层异常及凭据。"""
    if isinstance(exc, VectorStoreError):
        code = "VECTOR_STORE_UNAVAILABLE"
        message = str(exc)
    else:
        code = "EMBEDDING_UNAVAILABLE"
        message = "向量服务暂不可用，请稍后重试或联系管理员"
    return JSONResponse(
        status_code=503, content={"detail": {"code": code, "message": message}},
        headers={"Cache-Control": "no-store"},
    )


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


def custom_openapi() -> dict:
    """由当前路由生成契约，将自动 422 响应对齐全局脱敏处理器。"""
    if app.openapi_schema is not None:
        return app.openapi_schema
    schema = get_openapi(
        title=app.title,
        version=app.version,
        openapi_version=app.openapi_version,
        description=app.description,
        routes=app.routes,
        tags=app.openapi_tags,
        servers=app.servers,
    )
    error_schema = ErrorResponse.model_json_schema(ref_template="#/components/schemas/{model}")
    definitions = error_schema.pop("$defs", {})
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    components.update(definitions)
    components["ErrorResponse"] = error_schema
    for path in schema.get("paths", {}).values():
        for operation in path.values():
            if not isinstance(operation, dict):
                continue
            response = operation.get("responses", {}).get("422", {})
            content = response.get("content", {}).get("application/json", {})
            if content.get("schema") == {"$ref": "#/components/schemas/HTTPValidationError"}:
                content["schema"] = {"$ref": "#/components/schemas/ErrorResponse"}
    # 依赖用业务错误保留缺失来源/CSRF 的 403 与未登录的 401；
    # 对合法调用者而言这些输入仍为必需，不能因依赖默认值误标可选。
    for path in ("/api/auth/refresh", "/api/auth/logout"):
        operation = schema.get("paths", {}).get(path, {}).get("post", {})
        required = {("header", "Origin"), ("header", "X-CSRF-Token"), ("cookie", "mc_csrf")}
        if path.endswith("logout"):
            required.add(("header", "Authorization"))
        for parameter in operation.get("parameters", []):
            if (parameter.get("in"), parameter.get("name")) in required:
                parameter["required"] = True
                parameter["schema"].pop("anyOf", None)
                parameter["schema"]["type"] = "string"
    app.openapi_schema = schema
    return schema


app.openapi = custom_openapi
