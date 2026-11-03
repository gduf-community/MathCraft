"""批卷：客观题规则判分，主观题调用 DeepSeek。"""
import json
import re

from app.errors import AppError
from app.models import PaperQuestion
from app.services.rag.llm import chat_json

CHOICE_TYPES = {"single", "multiple", "judge"}
SUBJECTIVE_TYPES = {"blank", "compute", "essay"}

GRADE_SYSTEM = """你是一名严谨的高等数学阅卷老师。根据题目、参考答案和评分标准，为学生答案打分。
只输出 JSON：{"score": 整数, "comment": "简短评语"}。
分数必须在 0 到满分之间，按步骤给分；答案完全正确给满分，空白给 0 分。"""

GRADE_USER = """【题目】
{stem}

【参考答案】
{answer}

【满分】
{score}

【学生答案】
{response}

请给出得分与简短评语。"""


def _correct_letters(answer: str) -> list[str]:
    return sorted(re.findall(r"[A-Z]", answer.upper()))


def _picked(choices: list[str]) -> list[str]:
    return sorted({c.upper() for c in choices if c})


def grade_objective(pq: PaperQuestion, choices: list[str]) -> tuple[int, bool]:
    correct = _correct_letters(pq.answer)
    picked = _picked(choices)
    if pq.type == "multiple":
        is_correct = bool(correct) and picked == correct
    else:
        is_correct = len(correct) == 1 and picked == correct
    return (pq.score if is_correct else 0), is_correct


def grade_subjective(pq: PaperQuestion, text: str, api_key: str | None) -> tuple[int, bool, str]:
    text = (text or "").strip()
    if not text:
        return 0, False, "空白答案"
    if not api_key:
        raise AppError(
            "DEEPSEEK_KEY_MISSING",
            "主观题批卷需要 DeepSeek API Key，请到个人中心 → 模型配置中填写",
            status_code=400,
        )
    try:
        data = chat_json(
            [
                {"role": "system", "content": GRADE_SYSTEM},
                {
                    "role": "user",
                    "content": GRADE_USER.format(
                        stem=pq.stem, answer=pq.answer, score=pq.score, response=text
                    ),
                },
            ],
            api_key=api_key,
        )
        score = int(data.get("score", 0))
        score = max(0, min(pq.score, score))
        comment = str(data.get("comment", ""))[:500]
        return score, score >= pq.score, comment
    except AppError:
        raise
    except Exception:
        # 模型异常时按参考答案包含关系兜底，避免整份试卷提交失败
        norm = lambda s: re.sub(r"\s+", "", (s or "").lower())  # noqa: E731
        if norm(pq.answer) and norm(pq.answer) in norm(text):
            return pq.score, True, "模型不可用，按参考答案匹配给分"
        return 0, False, "模型不可用，未匹配参考答案"


def answer_needs_llm(pq: PaperQuestion, text: str) -> bool:
    return pq.type in SUBJECTIVE_TYPES and bool((text or "").strip())


def serialize_choices(choices: list[str]) -> str | None:
    return json.dumps(choices, ensure_ascii=False) if choices else None
