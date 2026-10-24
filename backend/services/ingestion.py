"""入库编排：解析 → 切片 → 向量化 → 写入 Chroma。"""
import uuid
from pathlib import Path

from services import vectorstore
from services.chunking import chunk_blocks
from services.embeddings import embed_many
from services.parsing.base import get_parser


def ingest_file(kb_id: str, file_path: Path, doc_name: str | None = None) -> dict:
    doc_name = doc_name or file_path.name
    doc_id = uuid.uuid4().hex[:12]

    parser = get_parser(file_path)
    blocks = parser.parse(file_path)
    if not blocks:
        raise ValueError("解析结果为空：文件内容为空或格式异常")

    chunks = chunk_blocks(blocks)
    if not chunks:
        raise ValueError("切片结果为空")

    vectors = embed_many([c.text for c in chunks])
    vectorstore.add_chunks(kb_id, doc_id, doc_name, chunks, vectors)

    return {"doc_id": doc_id, "doc_name": doc_name, "chunks": len(chunks), "blocks": len(blocks)}
