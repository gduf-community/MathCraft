"""参数化快速出题路由。"""
from fastapi import APIRouter, HTTPException

from schemas.question import GenerateParams, Question
from services.question_gen import NeedConfirmError, generate_questions
from services.knowledge import check_document
from MathCraft.services.rag.evidence import KnowledgeError

router = APIRouter(prefix="/api", tags=["generate"])


@router.post("/generate", response_model=list[Question])
async def generate(params: GenerateParams) -> list[Question]:
    try:
        readiness = await check_document(params.kb_id, params.doc_id)
        questions = await generate_questions(
            params,
            params.doc_id,
            scope=params.scope or None,
            existing_stems=params.existing_stems,
            index_version=readiness["index_version"],
        )
    except KnowledgeError as exc:
        raise HTTPException(422, exc.detail()) from exc
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
