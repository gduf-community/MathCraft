"""对话状态机联测：模拟三轮对话直到出题。uv run python scripts/test_chat.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import urllib.request  # noqa: E402

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
    print("== health ==")
    with urllib.request.urlopen(BASE + "/api/health", timeout=60) as r:
        print(json.dumps(json.loads(r.read().decode("utf-8")), ensure_ascii=False))

    docs = json.loads(urllib.request.urlopen(BASE + "/api/kb/documents?kb_id=kb-math", timeout=30).read().decode("utf-8"))
    doc_id = docs[0]["doc_id"] if docs else ""
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
        result = post("/api/chat", {"kb_id": "kb-math", "doc_id": doc_id, "message": msg, "history": history, "slot_state": state})
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
