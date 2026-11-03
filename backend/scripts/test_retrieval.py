"""混合检索命令行测试：HyDE + 稠密 + 稀疏 + RRF + 重排。

用法：
  uv run python scripts/test_retrieval.py "隐函数求导" --bank bank_xxx [--doc doc_xxx] [--top-k 6]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.rag import retrieval


def main() -> None:
    p = argparse.ArgumentParser(description="混合检索测试")
    p.add_argument("query", help="检索词")
    p.add_argument("--bank", required=True, help="题库 id")
    p.add_argument("--doc", default=None, help="文档 id（可选）")
    p.add_argument("--top-k", type=int, default=6)
    p.add_argument("--no-rerank", action="store_true", help="只看融合结果，不重排")
    args = p.parse_args()

    result = retrieval.hybrid_retrieve(
        args.bank,
        args.query,
        document_id=args.doc,
        rerank_top_k=None if args.no_rerank else args.top_k,
    )

    print(f"=== HyDE ===\n{(result['hyde'] or '(未生成)')[:200]}\n")
    print(f"=== 稠密 top{len(result['dense'])} ===")
    for h in result["dense"][: args.top_k]:
        print(f"  [{h.get('doc_name')}] {h['text'][:60]}...")
    print(f"\n=== 稀疏 top{len(result['sparse'])} ===")
    for h in result["sparse"][: args.top_k]:
        print(f"  bm25={h.get('bm25', 0):.2f} {h.get('text', '')[:60]}...")
    print(f"\n=== RRF 融合 top{len(result['fused'])} ===")
    for h in result["fused"][: args.top_k]:
        print(f"  rrf={h.get('rrf', 0):.4f} {h.get('text', '')[:60]}...")
    print(f"\n=== 重排最终 top{len(result['reranked'])} ===")
    for h in result["reranked"]:
        print(f"  score={h.get('score', 0):.4f} [{h.get('doc_name')}] {h['text'][:60]}...")


if __name__ == "__main__":
    main()
