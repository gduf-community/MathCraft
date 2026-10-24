"""切片策略：练习卷按题号切，通用文档按长度聚合。

题号切片对「导数与微分_50题练习卷」这类文件效果最好：一道题一个 chunk，
检索命中即为完整题目，出题时模型参考的是原题全文而不是半道题。
行级判定：任何一行以「12.」「3、」开头即计入题号；大题标题（一、二、…）
独立起块并作为后续题目的上下文；「参考答案」之后的内容整段聚合，
保证原题模式下答案可被检索到。

每个 chunk 携带元信息（chunk_type / section），供原题数量统计使用。
"""
import re
from dataclasses import dataclass, field

from riddleme.config import settings
from riddleme.services.parsing.base import ParsedBlock

# 匹配 1. 2、3．4， 这类题号行首
QUESTION_NO = re.compile(r"^\s{0,4}\d{1,3}\s*[\.、．]\s*\S")
# 大题标题：一、单项选择题（共 15 题）
SECTION_NO = re.compile(r"^\s{0,4}[一二三四五六七八九十]{1,3}\s*[、.．]\s*\S")
ANSWER_START = re.compile(r"^\s*参考答案")
QUESTION_NO_MIN_HITS = 5


@dataclass
class Chunk:
    text: str
    meta: dict = field(default_factory=dict)


def _looks_like_exam(blocks: list[ParsedBlock]) -> bool:
    hits = sum(1 for b in blocks for line in b.text.splitlines() if QUESTION_NO.match(line))
    return hits >= QUESTION_NO_MIN_HITS


def _split_long(text: str) -> list[str]:
    """超长块滑窗切分，带 overlap。"""
    size, overlap = settings.chunk_size, settings.chunk_overlap
    if len(text) <= size:
        return [text]
    parts = []
    step = size - overlap
    for i in range(0, len(text), step):
        piece = text[i : i + size].strip()
        if len(piece) > overlap // 2:
            parts.append(piece)
        if i + size >= len(text):
            break
    return parts


def _flush(chunks: list[Chunk], buf: list[str], meta: dict) -> None:
    if buf:
        text = "\n".join(buf).strip()
        if text:
            # 过滤答案区溢出产生的无意义碎块
            if len(text) >= 10 or not chunks:
                for piece in _split_long(text):
                    chunks.append(Chunk(text=piece, meta=dict(meta)))
        buf.clear()


def _chunk_exam(blocks: list[ParsedBlock]) -> list[Chunk]:
    lines = [ln.strip() for b in blocks for ln in b.text.splitlines() if ln.strip()]
    chunks: list[Chunk] = []
    cur: list[str] = []
    cur_meta: dict = {"chunk_type": "question", "section": ""}
    in_answer = False
    answer_buf: list[str] = []
    # 当前块以大题标题开头时，第一道题直接并入该块，标题作为上下文
    cur_is_section = False

    for line in lines:
        if ANSWER_START.match(line):
            _flush(chunks, cur, cur_meta)
            cur_is_section = False
            in_answer = True
            answer_buf.append(line)
            continue
        if in_answer:
            answer_buf.append(line)
            if sum(len(x) for x in answer_buf) > settings.chunk_size:
                _flush(chunks, answer_buf, {"chunk_type": "answer", "section": "参考答案"})
            continue
        if QUESTION_NO.match(line):
            if not cur_is_section:
                _flush(chunks, cur, cur_meta)
                cur_meta = {"chunk_type": "question", "section": cur_meta.get("section", "")}
            cur_is_section = False
        elif SECTION_NO.match(line):
            _flush(chunks, cur, cur_meta)
            cur_meta = {"chunk_type": "question", "section": line}
            cur_is_section = True
        cur.append(line)

    _flush(chunks, cur, cur_meta)
    _flush(chunks, answer_buf, {"chunk_type": "answer", "section": "参考答案"})
    return chunks


def _chunk_generic(blocks: list[ParsedBlock]) -> list[Chunk]:
    """通用模式：块按顺序聚合到 chunk_size，保留元信息前缀。"""
    chunks: list[Chunk] = []
    buffer: list[str] = []
    length = 0
    cur_meta: dict = {"chunk_type": "general", "section": ""}
    for b in blocks:
        prefix = ""
        section = b.meta.get("section")
        page = b.meta.get("page")
        if section:
            prefix = f"[{section}] "
            cur_meta = {"chunk_type": "general", "section": section}
        elif page:
            prefix = f"[第{page}页] "
        text = prefix + b.text
        if length + len(text) > settings.chunk_size and buffer:
            chunks.append(Chunk(text="\n".join(buffer).strip(), meta=dict(cur_meta)))
            tail = buffer[-1][-settings.chunk_overlap :] if settings.chunk_overlap else ""
            buffer = [tail] if tail else []
            length = len(tail)
        buffer.append(text)
        length += len(text)
    if buffer:
        chunks.append(Chunk(text="\n".join(buffer).strip(), meta=dict(cur_meta)))
    return [c for c in chunks if c.text]


def chunk_blocks(blocks: list[ParsedBlock]) -> list[Chunk]:
    if not blocks:
        return []
    if _looks_like_exam(blocks):
        return _chunk_exam(blocks)
    return _chunk_generic(blocks)
