"""题库、成员、文档、检索测试的请求模型。"""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from typing_extensions import NotRequired, TypedDict

from app.models.bank import ChunkSourceLocation


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


class SourceSearchHit(TypedDict):
    """已发布切片的标识和 OCR 来源。"""

    chunk_id: str
    source_locations: list[ChunkSourceLocation] | None


class HybridDenseSearchHit(SourceSearchHit):
    """混合检索中的向量命中。"""

    text: str
    doc_name: str
    chunk_index: int
    distance: float | None


class DenseSearchHit(HybridDenseSearchHit):
    """独立向量检索中的命中。"""

    doc_id: str
    chunk_type: str
    section: str


class SparseSearchHit(SourceSearchHit):
    """独立稀疏检索中的命中。"""

    bm25: float


class ChunkSearchHit(SourceSearchHit):
    """含 SQL 切片正文和文档信息的混合检索命中。"""

    text: str
    chunk_type: str
    section: str
    document_id: str
    doc_name: str


class HybridSparseSearchHit(ChunkSearchHit):
    """混合检索中的稀疏命中。"""

    bm25: float


class FusedSearchHit(ChunkSearchHit):
    """融合后的切片命中。"""

    rrf: float


class RerankedSearchHit(ChunkSearchHit):
    """重排后的切片命中，重排降级时省略得分。"""

    score: NotRequired[float]


class DenseSearchResponse(TypedDict):
    """独立向量检索响应。"""

    mode: Literal["dense"]
    results: list[DenseSearchHit]


class SparseSearchResponse(TypedDict):
    """独立稀疏检索响应。"""

    mode: Literal["sparse"]
    results: list[SparseSearchHit]


class HybridSearchResponse(TypedDict):
    """混合检索和混合重排响应。"""

    hyde: str | None
    dense: list[HybridDenseSearchHit]
    sparse: list[HybridSparseSearchHit]
    fused: list[FusedSearchHit]
    reranked: list[RerankedSearchHit]


SearchResponse = DenseSearchResponse | SparseSearchResponse | HybridSearchResponse


class DocumentRenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
