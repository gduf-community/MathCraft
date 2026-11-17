"""题库、成员、文档、检索测试的请求模型。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class BankCreatorResponse(BaseModel):
    """题库创建者的列表展示信息。"""

    id: str
    display_name: str


class BankResponse(BaseModel):
    """现有题库列表契约；删除中仅所有者可见并允许继续 DELETE。"""

    id: str
    name: str
    code: str
    creator: BankCreatorResponse | None
    member_count: int
    capacity: int
    status: Literal["active", "deleting"]
    stage: str | None
    error_message: str | None
    source: Literal["owned", "joined"]
    quitted: bool
    my_role: str | None
    can_upload_document: bool
    can_download_document: bool
    can_delete_document: bool
    can_manage_members: bool
    can_edit_bank: bool
    can_transfer_bank: bool
    can_delete_bank: bool


class DocumentResponse(BaseModel):
    """文档列表及删除恢复占位记录；不向客户端暴露本地文件路径。"""

    id: str
    bank_id: str
    name: str
    format: str
    size_bytes: int
    page_count: int | None
    is_scanned: bool
    status: Literal[
        "uploaded", "parsing", "ocr", "chunking", "embedding", "ready", "failed", "deleting",
    ]
    stage: str | None
    progress: int
    chunk_count: int
    ocr_status: str | None
    error_message: str | None
    created_at: datetime


class BankCreateBody(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class BankUpdateBody(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)


class BankJoinBody(BaseModel):
    code: str = Field(min_length=1, max_length=32)


class MemberAddBody(BaseModel):
    account: str = Field(min_length=1, max_length=64)
    role: str = Field(default="readonly", pattern="^(editor|readonly)$")


class MemberRoleBody(BaseModel):
    role: str = Field(pattern="^(editor|readonly)$")


class TransferBody(BaseModel):
    target_user_id: str = Field(min_length=1, max_length=40)


class SearchBody(BaseModel):
    query: str = Field(min_length=1, max_length=512)
    top_k: int = Field(default=6, ge=1, le=50)
    document_id: str | None = None
    mode: str = Field(
        default="hybrid_rerank",
        pattern="^(dense|sparse|hybrid|hybrid_rerank)$",
        description="仅检索 ready 文档；hybrid 融合向量与稀疏结果，hybrid_rerank 额外调用重排",
    )


class DocumentRenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
