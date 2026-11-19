"""出题、题目、收藏、对话的请求模型。"""
import base64
from binascii import Error as Base64Error
from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.question import Difficulty, Question, QuestionType


class TypeCountBody(BaseModel):
    type: str = Field(pattern="^(single|multiple|judge|blank|compute|essay)$")
    # 高压长任务：单题型上限放宽到 100，与 TypeCount 一致
    count: int = Field(ge=1, le=100)
    # 题型级难度；缺省回退整体 difficulty
    difficulty: str | None = Field(default=None, pattern="^(低|中|高|地狱)$")


class GenerateStartBody(BaseModel):
    request_id: UUID | None = None
    # 新前端使用 bank_id / document_id；旧前端仍可只传 kb_id / doc_id
    bank_id: str = Field(default="", max_length=40)
    document_id: str = Field(default="", max_length=40)
    types: list[TypeCountBody] = Field(min_length=1)
    difficulty: str = Field(default="中", pattern="^(低|中|高|地狱)$")
    scope: str = Field(default="", max_length=512)
    source_mode: str = Field(default="variant_data", pattern="^(original|variant_data|variant_context|new)$")
    existing_stems: list[str] = Field(default=[], max_length=200)
    doc_name: str = Field(default="", max_length=255)
    # 兼容旧前端的字段名
    kb_id: str | None = None
    doc_id: str | None = None


class GenerateTaskResponse(BaseModel):
    """可恢复的参数化任务标识。"""

    task_id: str


class GenerationReviewStats(BaseModel):
    """生成审核的计数摘要。"""

    duplicates: int
    repaired: int
    regenerated: int
    solved: int


class GenerationError(BaseModel):
    """脱敏任务错误及原题不足提示。"""

    message: str


class GenerationConfirmationError(GenerationError):
    """原题数量不足时的结构化确认信息。"""

    kind: str
    available: int
    requested: int


class GenerateProgressResponse(BaseModel):
    """业务状态和执行退出分别报告，done 代表两者均已结束。"""

    status: Literal["queued", "running", "canceling", "canceled", "done", "failed", "interrupted"]
    execution_finished: bool
    progress: int
    stage: str
    done: bool
    batch_id: str | None
    questions: list[Question]
    review: GenerationReviewStats | None
    error: GenerationConfirmationError | GenerationError | None


class GenerateCancellationResponse(GenerateProgressResponse):
    """取消后仍存在的本任务题目 ID，供清空覆盖部分删除批次。"""

    question_ids: list[str]


class QuestionUpdateBody(BaseModel):
    type: str | None = Field(default=None, pattern="^(single|multiple|judge|blank|compute|essay)$")
    score: int | None = Field(default=None, ge=1, le=100)
    difficulty: str | None = Field(default=None, pattern="^(低|中|高|地狱)$")
    stem: str | None = Field(default=None, min_length=1)
    options: list[dict] | None = None
    answer: str | None = None
    analysis: str | None = None
    knowledge_point: str | None = Field(default=None, max_length=255)


class BatchDeleteBody(BaseModel):
    question_ids: list[str] = Field(min_length=1, max_length=200)


class FavoriteGroupBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class FavoriteGroupRenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class FavoriteAddBody(BaseModel):
    question_id: str = Field(min_length=1)
    group_id: str = Field(default="default", min_length=1)


class FavoriteMoveBody(BaseModel):
    group_id: str = Field(min_length=1)


class ChatSessionCreateBody(BaseModel):
    bank_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)


class ChatHistoryMessageResponse(BaseModel):
    """历史消息的持久化展示字段。"""

    id: str
    role: Literal["user", "assistant"]
    text: str
    batch_id: str | None
    created_at: datetime


class ChatSessionDetailResponse(BaseModel):
    """恢复会话时同时恢复服务端模式，避免发送时隐式切换。"""

    session_id: str
    bank_id: str
    document_id: str
    mode: Literal["generate", "creative", "qa", "data"]
    messages: list[ChatHistoryMessageResponse]


class ChatMessageBody(BaseModel):
    request_id: UUID | None = None
    message: str = Field(
        max_length=2048, description="消息文本；仅发送图片时可为空，文本与图片不可同时为空",
    )
    existing_stems: list[str] = Field(default=[], max_length=200)
    # base64 data URL 图片，随消息一起传给多模态模型
    images: list[str] = Field(default=[], max_length=4)
    # 分段控制器当前模式：generate/creative/qa/data
    mode: str = Field(default="generate")
    # 前端切换模式后的告知消息：只更新会话模式，不执行任何业务流程
    switch_only: bool = False

    @field_validator("mode")
    @classmethod
    def normalize_mode(cls, value: str) -> str:
        return value if value in ("generate", "creative", "qa", "data") else "generate"

    @field_validator("images")
    @classmethod
    def validate_images(cls, value: list[str]) -> list[str]:
        """只接受常见图片格式的 data URL，单张解码后不超过 5MB。"""
        allowed = ("image/png", "image/jpeg", "image/webp")
        for item in value:
            header, _, payload = item.partition(",")
            if header not in tuple(f"data:{mime};base64" for mime in allowed) or not payload:
                raise ValueError("图片必须是 data URL 格式")
            mime = header.removeprefix("data:").split(";", 1)[0]
            if mime not in allowed:
                raise ValueError(f"不支持的图片格式 {mime}，只接受 PNG/JPEG/WebP")
            try:
                size = len(base64.b64decode(payload, validate=True))
            except (Base64Error, ValueError) as exc:
                raise ValueError("图片 base64 编码无效") from exc
            if size == 0:
                raise ValueError("图片内容不能为空")
            if size > 5 * 1024 * 1024:
                raise ValueError("单张图片不能超过 5MB")
        return value

    @model_validator(mode="after")
    def require_content(self) -> Self:
        """文本与已通过格式校验的图片至少提供一种。"""
        if not self.message.strip() and not self.images:
            raise ValueError("请提供消息文本或图片")
        return self


class ChatOperationPreview(BaseModel):
    """已发布的操作确认预览。"""

    id: str
    action: Literal["delete", "update"]
    entity: str
    entity_label: str
    affected: int
    samples: list[str]
    explanation: str


class ChatSavedQuestion(BaseModel):
    """题库中当前保存的对话题目。"""

    id: str
    type: QuestionType
    score: int
    difficulty: Difficulty
    difficulty_score: float
    difficulty_review: dict[str, object] | None
    stem: str
    options: list[dict[str, object]]
    answer: str
    analysis: str
    knowledge_point: str
    starred: bool
    favorite_group_id: str | None
    doc_name: str
    bank_id: str
    document_id: str
    batch_id: str
    created_at: datetime


class ChatMessageResponse(BaseModel):
    """消息接口与状态查询共用的已发布回复。"""

    reply: str
    questions: list[ChatSavedQuestion | Question]
    done: bool
    batch_id: str | None
    slot_state: dict[str, object]
    kind: Literal["reply", "mode_mismatch", "mode_confirm"]
    mode: Literal["generate", "creative", "qa", "data"]
    mode_changed: bool
    suggested_template: Literal["generate", "creative", "qa", "data", "none"] | None
    confirm: ChatOperationPreview | None


class ChatRequestResponse(BaseModel):
    """指定轮次的业务状态及执行退出事实。"""

    status: Literal["running", "canceled", "done", "failed", "interrupted"]
    execution_finished: bool
    batch_id: str | None
    result: ChatMessageResponse | None


class ChatConfirmBody(BaseModel):
    """数据管理高危操作的确认：接受执行 / 拒绝取消。"""

    confirm_id: str = Field(min_length=1, max_length=40)
    accepted: bool
