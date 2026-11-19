"""Check which retrieved material reaches QA, generation, and planning prompts."""

import pytest

from app.schemas.question import GenerateParams, Question, QuestionType, TypeCount
from app.services.rag import qa, question_gen
from app.services.rag.material_budget import build_material


@pytest.mark.parametrize("entry, limit", [("qa", 4000), ("generation", 4000), ("plan", 1500)])
def test_prompt_prefers_whole_fragments_and_counts_source_labels(monkeypatch, entry, limit):
    label = "【Calculus · Integrals · 第3、8页】\n"
    formula = "$x^2$."
    text = "积" * (limit - len(label) - len(formula)) + formula
    hits = [
        {"doc_name": "Skipped", "text": "oversized " * limit, "chunk_type": "question"},
        {
            "doc_name": "Calculus", "section": "Integrals",
            "source_locations": [{"page": 8}, {"page": 3}, {"page": 8}],
            "text": text,
        },
        {"doc_name": "Skipped after", "text": "oversized " * limit},
    ]
    request = "request " * limit
    messages = []

    def capture(prompt, *_args, **_kwargs):
        messages.extend(prompt)
        return {"related": False, "points": ["first", "second"]}

    if entry == "qa":
        monkeypatch.setattr(qa, "retrieve_for_generation", lambda *_args, **_kwargs: hits)
        monkeypatch.setattr(qa, "chat_json", capture)
        reply = qa.answer_question("bank", "doc", request, [])
        assert "Calculus · Integrals · 第3、8页" in reply
        assert "Skipped" not in reply
        start, end = "【教学材料】\n", "\n\n【问题】"
    elif entry == "generation":
        def stream(prompt, *args, **kwargs):
            capture(prompt, *args, **kwargs)
            return [Question(type=QuestionType.blank, stem="求函数的导数。")]

        monkeypatch.setattr(question_gen, "_stream_questions", stream)
        tc = TypeCount(type=QuestionType.blank, count=1)
        params = GenerateParams(kb_id="bank", doc_id="doc", types=[tc])
        question_gen._gen_batch(tc, params, "Calculus", request, 1, [], False, None, hits, "")
        start, end = "【教学材料（可用于命题的参考内容）】\n", "\n\n【命题要求】"
    else:
        monkeypatch.setattr(question_gen.llm, "chat_json", capture)
        question_gen._plan_points(request, "填空题", "高", 2, hits, None)
        start, end = "教学材料（节选）：\n", "\n\n只输出 JSON"

    prompt = messages[-1]["content"]
    material = prompt.split(start, 1)[1].split(end, 1)[0]
    assert request in prompt
    assert len(material) == limit
    assert material == label + text


def test_oversized_fragments_preserve_formulas_and_prefer_excerpting_non_questions():
    question = {
        "doc_name": "Exam", "chunk_type": "question",
        "text": "求导。\n" + "求" * 4000,
    }
    notes = {
        "doc_name": "Notes", "section": "Derivatives",
        "text": "定义 " * 990 + r"$$\frac{" + "x" * 100 + "}{2}$$",
    }

    material, labels = build_material([question, notes], limit=3000)
    assert material == "【Notes · Derivatives】\n" + ("定义 " * 990).rstrip()
    assert labels == ["Notes · Derivatives"]
    material, labels = build_material([question], limit=3000)
    assert material.endswith("\n求导。")
    assert labels == ["Exam · question"]
