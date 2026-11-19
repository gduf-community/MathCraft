"""用离线 SQL 快照与 MinerU 缓存对照同一本教材的稀疏检索。"""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DOCUMENT_ID = "doc_f91f3f2413507515"
DATA = BACKEND / "data"


@dataclass(frozen=True)
class Query:
    """查询与需要在同一命中块正文中出现的证据。"""

    text: str
    criterion: str
    patterns: tuple[str, ...]


QUERIES = (
    Query(
        "确界原理 非空数集有上界",
        "正文给出非空数集有上界时存在上确界的命题。",
        (r"非空.{0,24}上界.{0,28}上确界",),
    ),
    Query(
        "单调有界定理 数列",
        "正文给出有界单调数列存在极限或收敛的结论。",
        (r"(?:有界.{0,8}单调|单调.{0,12}有界)数列.{0,16}(?:极限|收敛)",),
    ),
    Query(
        "柯西收敛准则 数列 充要条件",
        "正文同时给出数列收敛的充要性与两项差小于任意正数的条件。",
        (r"收敛的充要条件", r"a_?\{?n\}?[-−]a_?\{?m\}?.{0,18}<\\varepsilon"),
    ),
    Query(
        "拉格朗日中值定理 闭区间连续 开区间可导",
        "正文同时给出闭区间连续、开区间可导及斜率差商。",
        (r"闭区间.{0,24}连续", r"开区间.{0,24}可导", r"f\(b\)[-−]f\(a\)"),
    ),
    Query(
        "牛顿莱布尼茨公式 原函数 定积分",
        "同一块给出原函数条件与端点原函数值之差。",
        (r"原函数", r"F\(b\)[-−]F\(a\)"),
    ),
    Query(
        "正整数集 有下界无上界 例题",
        "例题含正整数集有下界无上界及用任意 M 构造更大整数的证明。",
        (r"正整数", r"下界.{0,12}无上界", r"\[M\]\+1"),
    ),
    Query(
        r"习题 3.1 按定义证明极限 \frac{6x+5}{x}",
        "习题正文含按定义证明极限的题干及分式 (6x+5)/x。",
        (r"按定义证明下列极限", r"\\frac\{6x\+5\}\{x\}"),
    ),
    Query(
        "黎曼函数 可积 定积分等于零 例题",
        "例题给出黎曼函数的积分结论及按既约真分数定义函数的内容。",
        (r"黎曼函数", r"积分等于[0零]", r"既约真分数"),
    ),
    Query(
        "有端分划 稠密 有理数",
        "正文说明两分划之间存在有理数或有理数对应的有端分划。",
        (r"有端分划.{0,28}稠密", r"存在.{0,18}(?:\\in\\(?:mathbf|mathbb)\{Q\}|有理数)"),
    ),
)


@dataclass(frozen=True)
class Chunk:
    """用于检索与复核的原始切片或解析块。"""

    id: str
    text: str
    tokens: str
    meta: dict[str, object]


def load_baseline(snapshot: Path, document_id: str) -> tuple[str, int, list[Chunk]]:
    """只读查询独立 SQLite 快照中的 ready 文档切片。"""
    if not snapshot.is_file():
        raise ValueError(f"找不到离线快照：{snapshot}")
    snapshot = snapshot.resolve()
    if snapshot.name.lower() == "mathcraft.db" or any(
        snapshot.with_name(snapshot.name + suffix).exists()
        for suffix in ("-wal", "-journal", "-shm")
    ):
        raise ValueError("请提供独立、已合并日志的离线快照，并使用不同于 mathcraft.db 的文件名。")
    with closing(sqlite3.connect(snapshot.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        document = db.execute(
            """SELECT name, page_count, chunk_count
               FROM documents WHERE id = ? AND status = 'ready'""",
            (document_id,),
        ).fetchone()
        if document is None:
            raise ValueError(f"快照没有该 ready 文档：{document_id}")
        name, pages, expected_chunks = document
        rows = db.execute(
            """SELECT c.id, c.text, c.tokens, c.chunk_index, c.section, c.chunk_type
               FROM document_chunks c
               JOIN documents d ON d.id = c.document_id AND d.bank_id = c.bank_id
               WHERE d.id = ? ORDER BY c.chunk_index, c.id""",
            (document_id,),
        ).fetchall()
    if not pages or not rows or len(rows) != expected_chunks:
        raise ValueError("快照中的页数、切片数量或文档状态不完整。")
    return name, pages, [
        Chunk(chunk_id, body, tokens, {"chunk_index": index, "section": section, "type": kind})
        for chunk_id, body, tokens, index, section, kind in rows
    ]


def evidence(text: str, query: Query) -> list[str]:
    """对同一块正文检查所有证据条件，并返回匹配附近的短摘录。"""
    body = re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))
    excerpts = []
    for pattern in query.patterns:
        match = re.search(pattern, body)
        if match is None:
            return []
        excerpts.append(body[max(0, match.start() - 20):match.end() + 20])
    return excerpts


def evaluate(
    chunks: list[Chunk], match_expressions: list[str], top_k: int
) -> dict[str, object]:
    """在单个内存 FTS5 语料上执行查询，返回排序和逐条证据。"""
    normalized_hits: list[int | None] = []
    results = []
    with closing(sqlite3.connect(":memory:")) as db:
        db.execute("CREATE VIRTUAL TABLE chunks USING fts5(tokens, tokenize='unicode61')")
        db.executemany(
            "INSERT INTO chunks(rowid, tokens) VALUES (?, ?)",
            ((index, chunk.tokens) for index, chunk in enumerate(chunks, 1)),
        )
        for query, match in zip(QUERIES, match_expressions, strict=True):
            ranked = db.execute(
                """SELECT rowid, -bm25(chunks) AS score FROM chunks WHERE chunks MATCH ?
                   ORDER BY score DESC, rowid LIMIT ?""",
                (match, top_k),
            )
            hits = []
            first_rank = None
            for rank, (rowid, score) in enumerate(ranked, 1):
                chunk = chunks[rowid - 1]
                excerpts = evidence(chunk.text, query)
                hits.append({
                    "rank": rank,
                    "id": chunk.id,
                    "bm25": score,
                    "meta": chunk.meta,
                    "chars": len(chunk.text),
                    "excerpt": " ".join(chunk.text.split())[:160],
                    "evidence": excerpts,
                })
                if excerpts and first_rank is None:
                    first_rank = rank
            normalized_hits.append(first_rank)
            results.append({"first_evidence_rank": first_rank, "hits": hits})
    cutoffs = sorted({1, top_k, *(k for k in (3, 5) if k <= top_k)})
    return {
        "chunk_count": len(chunks),
        "text_chars": sum(len(chunk.text) for chunk in chunks),
        "matching_queries": {
            f"Hit@{k}": sum(rank is not None and rank <= k for rank in normalized_hits)
            for k in cutoffs
        },
        "results": results,
    }


def main() -> None:
    """运行对照并将 JSON 报告写入标准输出。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, required=True, help="独立 SQLite 离线快照")
    parser.add_argument("--result-dir", type=Path, default=DATA / "ocr" / DOCUMENT_ID)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--baseline-only", action="store_true", help="仅运行简化稿基线")
    args = parser.parse_args()
    if args.top_k < 1:
        parser.error("--top-k 必须是正整数")

    sys.path.insert(0, str(BACKEND))
    from app.services.rag.tokenizer import terms, tokenize

    try:
        name, pages, baseline = load_baseline(args.snapshot, DOCUMENT_ID)
        expressions = [
            " OR ".join('"' + term.replace('"', '""') + '"' for term in terms(query.text))
            for query in QUERIES
        ]
        report = {
            "document_id": DOCUMENT_ID,
            "document_name": name,
            "page_count": pages,
            "top_k": args.top_k,
            "sqlite_version": sqlite3.sqlite_version,
            "snapshot": args.snapshot.name,
            "queries": [
                {"query": query.text, "criterion": query.criterion, "patterns": query.patterns}
                for query in QUERIES
            ],
            "simplified": evaluate(baseline, expressions, args.top_k),
        }
        if not args.baseline_only:
            from app.services.parsing.ocr_textbook import parse_ocr_textbook

            markdown_bytes = (args.result_dir / "full.md").read_bytes()
            blocks = parse_ocr_textbook(markdown_bytes.decode("utf-8-sig"), args.result_dir, pages)
            if not blocks:
                raise ValueError("OCR 教材解析未返回任何检索块。")
            original = [
                Chunk(f"ocr-{index}", block.text, tokenize(block.text), block.meta)
                for index, block in enumerate(blocks)
            ]
            report["ocr_markdown_sha256"] = hashlib.sha256(markdown_bytes).hexdigest()
            report["original"] = evaluate(original, expressions, args.top_k)
    except ModuleNotFoundError as exc:
        if exc.name != "app.services.parsing.ocr_textbook":
            raise
        parser.error("当前工作树缺少 app.services.parsing.ocr_textbook。")
    except (OSError, RuntimeError, ValueError, sqlite3.Error) as exc:
        parser.error(str(exc))
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
