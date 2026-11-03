"""题库、成员、文档、检索测试的请求模型。"""
from pydantic import BaseModel, Field


class BankCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class BankUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    admin_level: str | None = Field(default=None, pattern="^(normal|super)$")


class BankJoinBody(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class MemberRoleBody(BaseModel):
    role: str = Field(pattern="^(admin|member)$")


class TransferBody(BaseModel):
    target_user_id: str = Field(min_length=1, max_length=40)


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    top_k: int = Field(default=6, ge=1, le=50)
    document_id: str | None = None
    mode: str = Field(default="hybrid_rerank", pattern="^(dense|sparse|hybrid|hybrid_rerank)$")


class DocumentRenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
