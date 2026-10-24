"""出题测试：uv run python scripts/test_generate.py [--kb kb-math]"""
import sys
from argparse import ArgumentParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from schemas.question import Difficulty, GenerateParams, QuestionType, TypeCount  # noqa: E402
from services.question_gen import generate_questions  # noqa: E402
from services.vectorstore import list_documents  # noqa: E402


def main():
    ap = ArgumentParser()
    ap.add_argument("--kb", default="kb-math")
    ap.add_argument("--doc", default="", help="doc_id，留空取第一个文档")
    ap.add_argument("--types", default="single:2,compute:1", help="题型:数量，逗号分隔")
    args = ap.parse_args()

    docs = list_documents(args.kb)
    if not docs:
        sys.exit("知识库为空，请先运行 scripts/upload.py 入库")
    doc = docs[0] if not args.doc else next((d for d in docs if d["doc_id"] == args.doc), None)
    if not doc:
        sys.exit(f"doc_id 不存在，可用：{[d['doc_id'] for d in docs]}")

    types = [TypeCount(type=QuestionType(t.split(":")[0]), count=int(t.split(":")[1])) for t in args.types.split(",")]
    params = GenerateParams(kb_id=args.kb, doc_id=doc["doc_id"], types=types, difficulty=Difficulty("中"))
    print(f"文档：{doc['doc_name']}  题型：{[(t.type.value, t.count) for t in types]}\n")

    questions = generate_questions(params, doc["doc_name"])
    print(f"共生成 {len(questions)} 道：\n")
    for q in questions:
        print(f"[{q.id}] {q.type.value} {q.score}分 难度:{q.difficulty.value} 考点:{q.knowledgePoint}")
        print(f"  题干: {q.stem[:120]}")
        for o in q.options:
            print(f"    {o.label}. {o.text[:80]}")
        print(f"  答案: {q.answer[:80]}")
        print(f"  解析: {q.analysis[:150]}...\n")


if __name__ == "__main__":
    main()
