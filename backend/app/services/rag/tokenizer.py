"""中文分词：jieba 预分词供 FTS5 BM25 使用（unicode61 不切分连续中文）。"""
import jieba

_tokenized = False


def _ensure_dict() -> None:
    global _tokenized
    if not _tokenized:
        jieba.initialize()
        _tokenized = True


def tokenize(text: str) -> str:
    """分词并用空格连接，作为 FTS5 tokens 列写入。"""
    _ensure_dict()
    return " ".join(t for t in jieba.cut_for_search(text) if t.strip())


def terms(text: str) -> list[str]:
    """查询侧分词，得到 MATCH 词项列表。"""
    return [t for t in tokenize(text).split() if t]
