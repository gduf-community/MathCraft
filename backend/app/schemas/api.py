"""出题、题目、收藏、对话的请求模型。"""
import base64

from pydantic import BaseModel, Field, field_validator


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
            if not header.startswith("data:") or ";" not in header or not payload:
                raise ValueError("图片必须是 data URL 格式")
            mime = header.removeprefix("data:").split(";", 1)[0]
            if mime not in allowed:
                raise ValueError(f"不支持的图片格式 {mime}，只接受 PNG/JPEG/WebP")
            try:
                size = len(base64.b64decode(payload, validate=True))
            except Exception as exc:  # noqa: BLE001
                raise ValueError("图片 base64 编码无效") from exc
            if size > 5 * 1024 * 1024:
                raise ValueError("单张图片不能超过 5MB")
        return value


class ChatConfirmBody(BaseModel):
    """数据管理高危操作的确认：接受执行 / 拒绝取消。"""

    confirm_id: str = Field(min_length=1, max_length=40)
    accepted: bool
