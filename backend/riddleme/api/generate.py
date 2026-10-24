"""参数化快速出题路由。"""
from fastapi import APIRouter, HTTPException

from riddleme.schemas.question import GenerateParams
from riddleme.services.question_gen import NeedConfirmError, generate_questions
from riddleme.services.vectorstore import list_documents

router = APIRouter(prefix="/api", tags=["generate"])


@router.post("/generate")
def generate(params: GenerateParams):
    docs = list_documents(params.kb_id)
    doc_name = next((d["doc_name"] for d in docs if d["doc_id"] == params.doc_id), params.doc_id)
    try:
        questions = generate_questions(
            params,
            doc_name,
            scope=params.scope or None,
            existing_stems=params.existing_stems,
        )
    except NeedConfirmError as exc:
        # 原题数量不足：422 + 结构化信息，前端提示用户选择处理方式
        raise HTTPException(
            422,
            detail={
                "kind": "need_confirm",
                "message": f"材料中「{exc.type_label}」的原题只有 {exc.available} 道，不足 {exc.requested} 道。"
                "可以减少数量，或把来源模式改为改数据、改背景、全新题。",
                "type_label": exc.type_label,
                "available": exc.available,
                "requested": exc.requested,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"生成失败：{exc}") from exc
    return [q.model_dump() for q in questions]
