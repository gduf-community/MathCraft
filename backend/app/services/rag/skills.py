"""对话技能注册表：Router 只做模式分发，四个模式各自封装执行体。

分段控制器是最高选择层级：显式 mode 参数直接查表进入对应技能；
意图识别只产建议，不在这里抢控制权。每个技能自行决定要消费的上下文字段，
Router 统一兜底 ChatCanceled、NeedConfirmError 与 LLMError。
技能内部延迟导入服务函数，测试可按模块属性替换实现。
"""
from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from app.models import ChatSession, User
from app.schemas.question import GenerateParams
from app.services.rag.chat_flow import ChatCanceled
from app.services.rag.modes import MODES, mode_label


@dataclass(frozen=True)
class ChatContext:
    """一次对话请求的全部执行要素；技能按需取用，多余字段忽略。"""

    db: Session
    user: User
    session: ChatSession
    doc_name: str
    message: str
    history: list[dict]
    slot_state: dict
    existing_stems: list[str] | None
    api_key: str | None
    hyde_text: str | None
    images: list[str] | None
    progress_cb: Callable[[int, str], None]
    cancel_check: Callable[[], bool]
    on_generate: Callable[[GenerateParams], None] | None = None


def run_generate(ctx: ChatContext) -> dict:
    """快速出题：槽位齐备后走检索、生成与审核。"""
    from app.services.rag.chat_flow import handle_chat

    return handle_chat(
        ctx.session.bank_id,
        ctx.session.document_id,
        ctx.doc_name,
        ctx.message,
        ctx.history,
        ctx.slot_state,
        existing_stems=ctx.existing_stems,
        api_key=ctx.api_key,
        hyde_text=ctx.hyde_text,
        images=ctx.images,
        progress_cb=ctx.progress_cb,
        cancel_check=ctx.cancel_check,
        on_generate=ctx.on_generate,
    )


def run_creative(ctx: ChatContext) -> dict:
    """创新命题：固定单题，审核与快速出题共用。"""
    from app.services.rag.chat_flow import handle_creative

    return handle_creative(
        ctx.session.bank_id,
        ctx.session.document_id,
        ctx.doc_name,
        ctx.message,
        ctx.history,
        ctx.slot_state,
        existing_stems=ctx.existing_stems,
        api_key=ctx.api_key,
        hyde_text=ctx.hyde_text,
        images=ctx.images,
        progress_cb=ctx.progress_cb,
        cancel_check=ctx.cancel_check,
        on_generate=ctx.on_generate,
    )


def run_qa(ctx: ChatContext) -> dict:
    """知识答疑：检索当前文档作答，不出题不落库。异常转可读文案，不抛 500。"""
    from app.services.rag.llm import LLMError, friendly_error
    from app.services.rag.qa import answer_question

    try:
        reply = answer_question(
            ctx.session.bank_id, ctx.session.document_id, ctx.message,
            ctx.history, api_key=ctx.api_key, progress_cb=ctx.progress_cb,
        )
    except ChatCanceled:
        return {"reply": "已暂停本次生成，未写入题目预览。", "done": True}
    except LLMError as exc:
        return {"reply": friendly_error(exc), "done": True}
    except Exception:  # noqa: BLE001  答疑链路保持整段可用，不把内部异常抛给前端
        return {"reply": "答疑服务异常，请稍后再试。", "done": True}
    return {"reply": reply, "done": True}


def run_data(ctx: ChatContext) -> dict:
    """数据管理：自然语言转结构化查询；写操作返回确认预览。"""
    from app.services.rag.data_agent import run_data_request

    return run_data_request(ctx.db, ctx.user, ctx.message, ctx.api_key, session_id=ctx.session.id)


@dataclass(frozen=True)
class ChatSkill:
    mode: str
    label: str
    run: Callable[[ChatContext], dict]


SKILLS: dict[str, ChatSkill] = {
    skill.mode: skill
    for skill in (
        ChatSkill("generate", mode_label("generate"), run_generate),
        ChatSkill("creative", mode_label("creative"), run_creative),
        ChatSkill("qa", mode_label("qa"), run_qa),
        ChatSkill("data", mode_label("data"), run_data),
    )
}


def get_skill(mode: str) -> ChatSkill:
    """按显式选择查表；未知模式回退快速出题。"""
    if mode in SKILLS:
        return SKILLS[mode]
    return SKILLS["generate"]


def skill_labels() -> dict[str, str]:
    """供 Router 或调试使用：mode → 中文名。"""
    return {mode: SKILLS[mode].label for mode in MODES}
