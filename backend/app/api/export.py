"""题目导出接口：把已生成题目输出为 Word 文档，仅登录校验，不触碰题库资源。"""
from fastapi import APIRouter, Depends
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.deps import get_current_user
from app.errors import AppError
from app.models import User
from app.schemas.auth import ErrorResponse
from app.schemas.question import Question, QuestionType
from app.services.export_docx import (
    WORD_MEDIA_TYPE,
    build_export_docx,
    docx_filename,
)

router = APIRouter(prefix="/api/export", tags=["export"])


class ExportDocxBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    include_answer: bool = True
    include_analysis: bool = True
    # inline=每题下方 end=文末集中
    placement: str = "inline"
    type_order: list[QuestionType] = Field(min_length=1, max_length=6)
    questions: list[Question] = Field(min_length=1, max_length=200)


@router.post(
    "/docx",
    response_class=Response,
    responses={
        200: {
            "description": "按题型分组生成的 Word 文档",
            "content": {WORD_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}},
            "headers": {
                "Content-Disposition": {
                    "description": "附件下载及 UTF-8 文件名",
                    "schema": {"type": "string"},
                },
                "Cache-Control": {"schema": {"type": "string", "const": "no-store"}},
            },
        },
        400: {"model": ErrorResponse, "description": "答案与解析位置不受支持"},
        401: {"model": ErrorResponse, "description": "未登录或会话已失效"},
    },
)
def export_docx(body: ExportDocxBody, user: User = Depends(get_current_user)) -> Response:
    """将请求内已校验的题目导出为 Word，不查询或修改题库。"""
    if body.placement not in ("inline", "end"):
        raise AppError("EXPORT_BAD_PLACEMENT", "答案与解析位置仅支持每题下方或文末", status_code=400)
    data = build_export_docx(
        body.title.strip() or "试卷",
        [t.value for t in body.type_order],
        body.questions,
        body.include_answer,
        body.include_analysis,
        body.placement,
    )
    return Response(
        content=data,
        media_type=WORD_MEDIA_TYPE,
        headers={"Content-Disposition": docx_filename(body.title), "Cache-Control": "no-store"},
    )
