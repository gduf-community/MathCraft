"""出题、题目、收藏、对话的请求模型。"""
from pydantic import BaseModel, Field


class TypeCountBody(BaseModel):
    type: str = Field(pattern="^(single|multiple|judge|blank|compute|essay)$")
    count: int = Field(ge=1, le=20)


class GenerateStartBody(BaseModel):
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


class ChatMessageBody(BaseModel):
    message: str = Field(min_length=1, max_length=2048)
    existing_stems: list[str] = Field(default=[], max_length=200)
