"""对话出题路由。消息体携带槽位状态，由前端保存并在每轮回传。"""
from fastapi import APIRouter, HTTPException

from schemas.question import ChatRequestBody
from services.chat_flow import handle_chat
from services.knowledge import list_documents

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(body: ChatRequestBody):
    docs = list_documents(body.kb_id)
    if not docs:
        raise HTTPException(422, "该知识库还没有可用文档，请先在正式知识库中完成索引")
    document = next((d for d in docs if d["doc_id"] == body.doc_id), None)
    if document is None:
        raise HTTPException(422, f"文档不存在或不属于知识库：{body.doc_id}")
    doc_name = document["doc_name"]
    try:
        return await handle_chat(
            body.kb_id,
            body.doc_id,
            doc_name,
            body.message,
            body.history,
            body.slot_state,
            existing_stems=body.existing_stems,
        )
    except Exception as exc:
        raise HTTPException(500, f"对话处理失败：{exc}") from exc
