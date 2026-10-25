"""对话状态机联测：模拟对话直到出题。uv run python scripts/test_chat.py --kb <知识库>"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import urllib.request  # noqa: E402
from argparse import ArgumentParser  # noqa: E402

BASE = "http://localhost:8000"


def post(path: str, payload: dict) -> dict:
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    ap = ArgumentParser()
    ap.add_argument("--kb", required=True)
    args = ap.parse_args()
    print("== health ==")
    with urllib.request.urlopen(BASE + "/api/health", timeout=60) as r:
        print(json.dumps(json.loads(r.read().decode("utf-8")), ensure_ascii=False))

    kb_list = json.loads(urllib.request.urlopen(BASE + "/api/knowledge-bases", timeout=30).read().decode("utf-8"))
    if not any(item.get("id") == args.kb for item in kb_list):
        raise SystemExit(f"知识库不存在或不可见：{args.kb}")
    files = json.loads(urllib.request.urlopen(BASE + f"/api/knowledge-bases/{args.kb}/files", timeout=30).read().decode("utf-8"))["files"]
    docs = [file for file in files if file.get("type") == "file"]
    doc_id = docs[0]["name"] if docs else ""
    print(f"doc_id={doc_id}\n")

    state: dict = {}
    history: list[dict] = []
    turns = [
        "帮我生成5道选择题",
        "就考导数定义和求导法则那部分，改数据的题，难度整体中等就行",
    ]
    questions: list[dict] = []
    for i, msg in enumerate(turns, 1):
        print(f"== 第{i}轮 用户：{msg}")
        result = post("/api/chat", {"kb_id": args.kb, "doc_id": doc_id, "message": msg, "history": history, "slot_state": state})
        print(f"助手：{result['reply']}")
        print(f"槽位：{json.dumps(result['slot_state'], ensure_ascii=False)}\n")
        history.append({"role": "user", "text": msg})
        history.append({"role": "assistant", "text": result["reply"]})
        state = result["slot_state"]
        questions = result["questions"]
        if result["done"]:
            for q in questions:
                print(f"[{q['id']}] {q['type']} 考点:{q['knowledgePoint']}")
                print(f"  {q['stem'][:100]}")
            break


if __name__ == "__main__":
    main()
