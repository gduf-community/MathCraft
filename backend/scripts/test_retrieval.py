"""检索测试：uv run python scripts/test_retrieval.py "极限" [--kb kb-math]"""
import sys
from argparse import ArgumentParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from riddleme.services.retrieval import retrieve  # noqa: E402


def main():
    ap = ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("--kb", default="kb-math")
    ap.add_argument("--top-k", type=int, default=4)
    args = ap.parse_args()
    hits = retrieve(args.kb, args.query, top_k=args.top_k)
    if not hits:
        print("无结果：该知识库为空或未入库文档")
        return
    print(f"query={args.query!r} 命中 {len(hits)} 条：\n")
    for i, h in enumerate(hits, 1):
        preview = h["text"][:150].replace("\n", " ")
        print(f"{i}. [{h['doc_name']} #{h['chunk_index']}] 距离={h['distance']}")
        print(f"   {preview}...\n")


if __name__ == "__main__":
    main()
