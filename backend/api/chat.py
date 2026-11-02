"""对话出题路由。消息体携带槽位状态，由前端保存并在每轮回传。"""
from fastapi import APIRouter, HTTPException

from schemas.question import ChatRequestBody, ChatResponse
from services.chat_flow import handle_chat
from services.knowledge import check_document
from MathCraft.services.rag.evidence import KnowledgeError

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequestBody) -> ChatResponse:
    try:
        readiness = await check_document(body.kb_id, body.doc_id)
        return ChatResponse.model_validate(
            await handle_chat(
                body.kb_id,
                body.doc_id,
                body.doc_id,
                body.message,
                body.history,
                body.slot_state,
                existing_stems=body.existing_stems,
                index_version=readiness["index_version"],
            )
        )
    except KnowledgeError as exc:
        return ChatResponse(reply=str(exc), slot_state=body.slot_state,
                            questions=[], done=False, error_type=exc.code)
    except Exception as exc:
        raise HTTPException(500, f"对话处理失败：{exc}") from exc
