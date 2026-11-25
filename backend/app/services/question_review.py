"""独立求解、定向修补与成品验收。补题由调用方统一调度。"""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypedDict

from sqlalchemy.exc import InvalidRequestError
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Favorite, Paper, PaperQuestion, Question as QuestionRow
from app.schemas.question import Difficulty, GenerateParams, OptionItem, Question, QuestionType
from app.services import phoenix_tracing as trace
from app.services.generation_cancellation import (
    GenerationCanceled,
    cancellation_kwargs,
    check_cancellation,
    run_checked,
)
from app.services.rag import embeddings, llm
from app.services.rag.prompts import DRAFT_TRACES, SOLVE_ANSWER_SYSTEM, SOLVE_EXPLAIN_SYSTEM
from app.services import latex_utils
from app.services.question_symbolic import SymbolicResult, solve_symbolic, verify_symbolic
from app.services.rag_runtime import with_snapshot
from app.services.phoenix_tracing import TracingThreadPoolExecutor as ThreadPoolExecutor

logger = logging.getLogger("app.review")

# 加权总分到档位的映射：1—2 低，2—3 中，3—4 高，4—5 地狱
TIER_RANGES: dict[Difficulty, tuple[float, float]] = {
    Difficulty.low: (1.0, 2.0),
    Difficulty.mid: (2.0, 3.0),
    Difficulty.high: (3.0, 4.0),
    Difficulty.hell: (4.0, 5.0),
}
# 定向修补的目标档参数
TIER_PARAMS: dict[Difficulty, str] = {
    Difficulty.low: "步骤 1—2 步、只考 1 个知识点、计算量小、不设陷阱",
    Difficulty.mid: "步骤 2—3 步、综合 2 个知识点、计算量中等、至多 1 个常见易错点",
    Difficulty.high: "步骤 3—5 步、综合 3 个知识点、计算量偏大、至少 1 个真实陷阱",
    Difficulty.hell: "步骤 4 步以上、综合 3 个以上知识点、计算量大、至少 2 个陷阱、解法非常规",
}

EVAL_PROMPT = """你是独立数学审题人。给定一道题、它所属的知识点范围和目标难度档，请先独立解题，再评分。
不要参考任何出题方给出的难度标注，只按题目本身判断。

难度维度按指定范围内的最短合理解法评分，每项 1—5 分（5 分最高）：
- steps 步骤综合：需要的推理步骤数与综合程度
- abstraction 概念抽象：概念层面的抽象与转化要求
- computation 计算复杂度：计算量与计算技巧
- trap 陷阱非常规：陷阱设置与非标准思路

质量维度，每项 1—5 分（5 分最高）：
- knowledge 知识点匹配：与给定知识点范围的吻合程度
- unique 可解唯一：可解、答案唯一、无歧义（5 表示完全满足）

难度总分 = (20×steps + 20×abstraction + 15×computation + 15×trap) / 70。
knowledge 和 unique 用于质量审核。
判定档：[1, 2) 低，[2, 3) 中，[3, 4) 高，[4, 5] 地狱。
一票否决：不可解、答案不确定、超纲、题干歧义，此时 passed 必须为 false。
methods 写出关键解法。目标档为「高」或「地狱」时，提供两种解法或一种数值验证。

只输出 JSON，包含以下评分字段：
{"independentAnswer": "独立解出的答案",
 "scores": {"knowledge": 1, "steps": 1, "abstraction": 1,
            "computation": 1, "trap": 1, "unique": 1},
 "total": 难度总分（保留两位小数）,
 "tier": "低|中|高|地狱",
 "defectCodes": ["K|S|C|T|A|O"],
 "primarySuggestion": "参数级修改建议",
 "methods": ["解法或验证一", "解法或验证二"],
 "passed": true}

缺陷码：K 知识错配、S 步骤不足或过多、C 计算量不符、T 陷阱不符、A 答案有问题、O 超纲。
不要只写「太难」或「太简单」，必须给参数级建议，例如「减少一个综合知识点，步骤从 5 降到 3，去掉一个陷阱」。
目标难度档：__TARGET__
知识点范围：__SCOPE__
题目：
__STEM__
"""

REPAIR_PROMPT = """下面这道题没有通过难度与质量审查。请只做最小修补，不要整题重写，保持题型与考点不变。
拦截依据：__EVIDENCE__
知识点范围：__SCOPE__
原题限制：__ORIGINAL__
目标难度档：__TARGET__（__PARAMS__）

要求：
1 保留题干主体结构与已知条件，只调整必要部分（增删步骤、换数值、去或加陷阱、修正答案）。
2 修补后选项、答案、解析必须自洽。若仅解析方法越界，保留题面与答案，改用范围内的方法。
3 只输出一个 JSON 对象，字段与出题时相同：type、score、difficulty、knowledgePoint、blueprint、
  stem、options、answer、analysis、scoringPoints、selfCheck。不要包在 questions 数组里。

原题：
__QUESTION__
"""

EXPLANATION_REPAIR_PROMPT = """下面这道题没有通过解析验收。请只改写解析，逐字保留题干、选项和答案。
使用指定范围内的定理和方法，使推导成立且结论与成品答案一致。选择题需说明各项正误。
只输出一个 JSON 对象，唯一字段为 analysis，值为完整解析字符串。
指定范围：__SCOPE__
拦截依据：__EVIDENCE__
原题：
__QUESTION__
"""

JOINT_PROMPT = """
以上是完整题面，下面还给出成品选项、答案、解析与独立求解证据。逐项核验成品，
不能仅根据独立解题结果判断成品合格。输出的 JSON 须额外包含以下布尔字段：
- stemValid：题面完整、条件相容、问题明确。没有具体数学命题或必需数据时不能通过。
  判断题的命题可以为假，要求证明的命题若为假则题干有缺陷。
- scopeValid：实际考点和成品解析使用的方法均在指定范围。
- optionsValid：逐项核验定义域、真假、正确项数量与答案标签。单选恰好一项正确，
  多选至少两项正确。无定义的选项不能当作普通错误干扰项。非客观题无选项时填 true。
- answerValid：成品答案回应所有小问且与独立求解相符，包括判断题正误与选项标签。
- analysisValid：成品推导和结论成立，证明完成题目要求，选择题说明各项正误，
  判断为错须给反例或反证。
额外输出 evidence 字符串。通过时简述支持验收的关键依据，失败时给出具体反例、
缺失条件、越界定理或不成立的步骤。仅解析越界时说明可用的范围内方法。
另输出 explanationScopeOnly 布尔字段。仅当题目本身可用指定范围内的方法作答，
而成品解析的方法超出范围时填 true，否则填 false。
另输出 verifiable 布尔字段。证据不足时 verifiable 为 false。
任一字段无法验证或不成立时，passed 必须为 false。五项均通过时 passed 为 true，
难度只用评分表达，按成品的最短合理解法评分。
"""

_JOINT_FIELDS = {
    "stemValid": "题面缺陷",
    "scopeValid": "超出范围",
    "optionsValid": "选项不合格",
    "answerValid": "答案不成立",
    "analysisValid": "解析不成立",
}


class SolveStatus(StrEnum):
    """独立求解的结构化结论。"""

    SOLVED = "solved"
    INSUFFICIENT = "insufficient_conditions"
    FALSE_PROPOSITION = "false_proposition"
    CONTRADICTION = "contradictory_conditions"
    UNVERIFIABLE = "unverifiable"


_SOLVE_REASONS = {
    SolveStatus.INSUFFICIENT: "题设不足",
    SolveStatus.FALSE_PROPOSITION: "命题为假",
    SolveStatus.CONTRADICTION: "条件矛盾",
    SolveStatus.UNVERIFIABLE: "无法验证",
}

_STRUCTURED_SOLVE_PROMPT = """
本次必须额外输出 status 和 evidence。status 取 solved、insufficient_conditions、
false_proposition、contradictory_conditions 或 unverifiable。solved 表示正常作答，
evidence 给出关键依据或验算。其他状态的 answer 留空，evidence 给出缺失条件、
反例、矛盾条件或无法验证的原因。不能猜测题意或擅自补足题设。
判断题命题为假且可以反驳时为 solved，answer 填错误并在 evidence 中给出反例。
要求证明的命题被反例推翻时填 false_proposition。
"""


@dataclass(frozen=True)
class _SolveResult:
    status: SolveStatus
    evidence: str = ""
    answer: str = ""
    confidence: str = "mid"
    symbolic: SymbolicResult | None = None


@dataclass(frozen=True)
class _Finding:
    reason: str
    evidence: str = ""
    explanation_only: bool = False
    completion_answer: _SolveResult | None = None


@dataclass(frozen=True)
class _CandidateResult:
    question: Question | None = None
    reason: str = ""
    repaired: bool = False


class _QuestionTraceFields(TypedDict):
    candidate_id: str | None
    kind: str
    difficulty: str
    revision: int


def _trace_fields(question: Question, revision: int) -> _QuestionTraceFields:
    return {
        "candidate_id": question.id or None,
        "kind": question.type.value,
        "difficulty": question.difficulty.value,
        "revision": revision,
    }


# 评估与解析的并发数
_THINK_WORKERS = 6
_SCORE_KEYS = ("knowledge", "steps", "abstraction", "computation", "trap", "unique")
_DIFFICULTY_WEIGHTS = {"steps": 20, "abstraction": 20, "computation": 15, "trap": 15}


@dataclass
class ReviewStats:
    """中间件的处理结果，用于日志与前端提示。"""

    duplicates: int = 0
    repaired: int = 0
    regenerated: int = 0
    solved: int = 0
    rejections: dict[tuple[QuestionType, Difficulty], Counter[str]] = field(default_factory=dict)

    def summary(self) -> str:
        parts = []
        if self.duplicates:
            parts.append(f"去除重复 {self.duplicates} 题")
        if self.repaired:
            parts.append(f"修补 {self.repaired} 题")
        if self.regenerated:
            parts.append(f"重出 {self.regenerated} 题")
        if self.solved:
            parts.append(f"补解析 {self.solved} 题")
        return "，".join(parts)


def _norm(text: str) -> str:
    """题干归一化：去空白与常见标点，只用于完全相同判定。"""
    return re.sub(r"[\s，。、；：？！（）()\[\]【】,.;:?\"'“”‘’]+", "", text or "")


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def load_corpus(db: Session, user_id: str, bank_id: str) -> list[str]:
    """汇总当前账号的收藏、组卷记录及同题库个人历史题目，按时间倒序各取上限。"""
    limit = max(50, settings.review_corpus_limit)
    stems: list[str] = []

    fav = (
        db.query(QuestionRow.stem)
        .join(Favorite, Favorite.question_id == QuestionRow.id)
        .filter(Favorite.user_id == user_id)
        .order_by(Favorite.created_at.desc())
        .limit(limit)
        .all()
    )
    stems.extend(row[0] for row in fav)

    paper = (
        db.query(PaperQuestion.stem)
        .join(Paper, Paper.id == PaperQuestion.paper_id)
        .filter(Paper.owner_id == user_id)
        .order_by(Paper.created_at.desc())
        .limit(limit)
        .all()
    )
    stems.extend(row[0] for row in paper)

    history = (
        db.query(QuestionRow.stem)
        .filter(QuestionRow.bank_id == bank_id, QuestionRow.created_by == user_id)
        .order_by(QuestionRow.created_at.desc())
        .limit(limit)
        .all()
    )
    stems.extend(row[0] for row in history)

    seen: set[str] = set()
    out: list[str] = []
    for stem in stems:
        key = _norm(stem)
        if len(key) < 8 or key in seen:
            continue
        seen.add(key)
        out.append(stem)
    return out[: limit * 2]


class _DuplicateCheckError(ValueError):
    """缺少完成语义查重所需的有效向量。"""


@with_snapshot
def _drop_duplicates(
    questions: list[Question], corpus: list[str],
    cancel_check: Callable[[], None] | None = None,
) -> tuple[list[Question], list[Question]]:
    """与语料或批内已保留题目相似度过阈值的候选题判重。"""
    check_cancellation(cancel_check)
    norm_corpus = {_norm(stem) for stem in corpus}
    pending = [q for q in questions if _norm(q.stem) not in norm_corpus]
    dropped = [q for q in questions if _norm(q.stem) in norm_corpus]
    if not pending:
        return [], dropped
    if not corpus and len(pending) == 1:
        return pending, dropped
    stems = [q.stem for q in pending]
    try:
        if cancel_check is None:
            vectors = embeddings.embed_texts(corpus + stems)
        else:
            vectors = []
            for texts in (corpus, stems):
                for batch in embeddings.text_batches(texts):
                    vectors.extend(run_checked(cancel_check, embeddings.embed_texts, batch))
    except GenerationCanceled:
        raise
    except Exception as exc:
        raise _DuplicateCheckError("题目向量化失败") from exc
    if (len(vectors) != len(corpus) + len(pending)
            or any(len(vec) != len(vectors[0]) or not any(vec)
                   or not all(math.isfinite(x) for x in vec) for vec in vectors)):
        raise _DuplicateCheckError("题目向量不完整")
    threshold = settings.review_similarity_threshold
    seen = vectors[:len(corpus)]
    kept: list[Question] = []
    for question, vec in zip(pending, vectors[len(corpus):]):
        key = _norm(question.stem)
        if key in norm_corpus or any(_cosine(vec, other) >= threshold for other in seen):
            dropped.append(question)
        else:
            kept.append(question)
            norm_corpus.add(key)
            seen.append(vec)
    return kept, dropped


# ---------------- 盲评 ----------------


def tier_of(total: float) -> Difficulty:
    """加权总分映射到档位，4 分及以上算地狱。"""
    if total < TIER_RANGES[Difficulty.mid][0]:
        return Difficulty.low
    if total < TIER_RANGES[Difficulty.high][0]:
        return Difficulty.mid
    if total < TIER_RANGES[Difficulty.hell][0]:
        return Difficulty.high
    return Difficulty.hell


def in_target(total: float, target: Difficulty) -> bool:
    """判断评分是否落在唯一的目标档。"""
    return 1.0 <= total <= 5.0 and tier_of(total) == target


def _strip_json(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _chat_text_with_fallback(
    messages: list[dict], api_key: str | None, max_tokens: int, json_mode: bool = False,
    cancel_check: Callable[[], None] | None = None,
) -> str:
    """评估与解析都关掉思考模式，只取结论；接口不认这个参数时由模型层自动退回。"""
    kwargs: dict = {
        "api_key": api_key, "temperature": 0.2, "max_tokens": max_tokens, "thinking_off": True,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    return llm.chat_text(messages, **kwargs, **cancellation_kwargs(cancel_check))


def _chat_json_low(
    messages: list[dict], api_key: str | None, max_tokens: int = 4800,
    cancel_check: Callable[[], None] | None = None,
) -> dict:
    """请求严格 JSON 对象，失败由当前验收环节处理。"""
    text = run_checked(
        cancel_check, _chat_text_with_fallback, messages, api_key, max_tokens, json_mode=True,
        **cancellation_kwargs(cancel_check),
    )
    data = json.loads(latex_utils.escape_bare_commands_in_json(_strip_json(text)))
    if not isinstance(data, dict):
        raise ValueError("返回不是 JSON 对象")
    return data


def _trace_model_failure(exc: Exception) -> None:
    if isinstance(exc, ValueError) or (
        isinstance(exc, llm.LLMError) and str(exc) == llm._INVALID_JSON
    ):
        trace.record_question_failure("invalid_output")
    else:
        code = llm.model_error_trace_code(llm.friendly_error(exc))
        trace.record_question_failure(code if code != "other" else "model_error")


def parse_review(data: dict, target: Difficulty) -> dict:
    """验证盲评契约，重算难度分和档位，并检查质量否决。"""
    scores = data.get("scores")
    passed_flag = data.get("passed")
    if (
        not isinstance(scores, dict)
        or any(type(scores.get(key)) is not int or not 1 <= scores[key] <= 5
               for key in _SCORE_KEYS)
        or type(passed_flag) is not bool
    ):
        raise ValueError("缺少有效评分或判定")
    weighted = sum(scores[key] * weight for key, weight in _DIFFICULTY_WEIGHTS.items())
    total = round(weighted / sum(_DIFFICULTY_WEIGHTS.values()), 2)
    codes = data.get("defectCodes", [])
    methods = data.get("methods", [])
    if not isinstance(codes, list) or not isinstance(methods, list):
        raise ValueError("盲评字段格式无效")
    defects = [code for code in codes if isinstance(code, str) and code in tuple("KSCTAO")]
    veto = scores["unique"] <= 2 or "O" in defects or "A" in defects
    return {
        "scores": scores,
        "total": total,
        "tier": tier_of(total).value,
        "defectCodes": defects,
        "suggestion": str(data.get("primarySuggestion") or "").strip(),
        "methods": [m.strip() for m in methods if isinstance(m, str) and m.strip()],
        "veto": veto,
        "passed": passed_flag and not veto and in_target(total, target),
        "qualityPassed": passed_flag and not veto,
    }


def _judge_once(
    question: Question, target: Difficulty, scope: str, api_key: str | None,
    cancel_check: Callable[[], None] | None = None,
    *, independent: _SolveResult | None = None,
) -> dict | None:
    prompt = (
        EVAL_PROMPT.replace("__TARGET__", target.value)
        .replace("__SCOPE__", scope or "未限定")
        .replace("__STEM__", question.stem)
    )
    if independent is not None:
        prompt += "\n" + JOINT_PROMPT + json.dumps({
            **question.model_dump(include={"type", "stem", "options", "answer", "analysis"}),
            "independentAnswer": independent.answer.replace(_MULTI_SEP, "；"),
            "independentEvidence": independent.evidence,
        }, ensure_ascii=False)
    try:
        data = _chat_json_low(
            [{"role": "user", "content": prompt}], api_key,
            **cancellation_kwargs(cancel_check),
        )
        review = parse_review(data, target)
        if independent is not None:
            evidence = data.get("evidence")
            if (type(data.get("verifiable")) is not bool
                    or any(type(data.get(key)) is not bool for key in _JOINT_FIELDS)):
                trace.record_question_failure("invalid_output")
                return None
            if not data["verifiable"]:
                trace.record_question_failure("unverifiable_output")
                return None
            if not isinstance(evidence, str) or not evidence.strip():
                trace.record_question_failure("missing_evidence")
                return None
            finding = next(
                (_Finding(reason, evidence) for key, reason in _JOINT_FIELDS.items()
                 if data[key] is False),
                None,
            )
            other_fields_valid = all(data[key] for key in ("stemValid", "optionsValid", "answerValid"))
            if other_fields_valid and not data["scopeValid"]:
                explanation_scope_only = data.get("explanationScopeOnly")
                if type(explanation_scope_only) is not bool:
                    trace.record_question_failure("invalid_output")
                    return None
                if explanation_scope_only:
                    finding = _Finding("解析方法超出范围", evidence, explanation_only=True)
            elif other_fields_valid and data["scopeValid"] and not data["analysisValid"]:
                finding = _Finding("解析不成立", evidence, explanation_only=True)
            if finding is None and (not review["qualityPassed"] or not review["methods"]):
                trace.record_question_failure("unverifiable_output")
                return None
            review["finding"] = finding
            review["evidence"] = evidence
        return review
    except GenerationCanceled:
        raise
    except Exception as exc:  # noqa: BLE001
        _trace_model_failure(exc)
        logger.warning("盲评失败：%s", type(exc).__name__)
        return None


def _merge_reviews(reviews: list[dict]) -> dict:
    """合并多次盲评：总分取均值，任一否决即否决，缺陷码取并集。"""
    valid = [r for r in reviews if r]
    if not valid:
        return {"total": 0.0, "tier": "", "passed": False, "veto": False, "unknown": True,
                "scores": {}, "defectCodes": [], "suggestion": "", "methods": []}
    total = round(sum(r["total"] for r in valid) / len(valid), 2)
    scores = {
        key: round(sum(r["scores"][key] for r in valid) / len(valid), 2) for key in _SCORE_KEYS
    }
    defects: list[str] = []
    for r in valid:
        for code in r["defectCodes"]:
            if code not in defects:
                defects.append(code)
    worst = min(valid, key=lambda r: r["total"])
    return {
        "total": total,
        "tier": tier_of(total).value,
        "scores": scores,
        "defectCodes": defects,
        "suggestion": worst.get("suggestion", ""),
        "methods": max((r["methods"] for r in valid), key=len),
        "evidence": worst.get("evidence", ""),
        "veto": any(r["veto"] for r in valid),
        "passed": all(r["passed"] for r in valid) and not any(r["veto"] for r in valid),
        "unknown": False,
    }


def evaluate(
    question: Question, target: Difficulty, scope: str, api_key: str | None, judges: int = 2,
    cancel_check: Callable[[], None] | None = None,
    *, independent: _SolveResult | None = None,
) -> dict:
    """双评 + 仲裁：两次总分差超过 0.7 时请第三位评审裁决。

    修补后的复评只需要确认修补是否到位，用单评即可，省一半调用。
    """
    check_cancellation(cancel_check)
    cancel_kwargs = cancellation_kwargs(cancel_check)
    judge_kwargs = {"independent": independent} if independent is not None else {}
    judges = max(1, judges)
    with ThreadPoolExecutor(max_workers=judges, thread_name_prefix="review-judge") as pool:
        futures = [
            pool.submit(
                run_checked, cancel_check, _judge_once,
                question, target, scope, api_key, **cancel_kwargs, **judge_kwargs,
            ) for _ in range(judges)
        ]
        first = [f.result() for f in futures]
    check_cancellation(cancel_check)
    valid = [r for r in first if r]
    findings = [review for review in valid if review.get("finding") is not None]
    if findings:
        return next(
            (review for review in findings if not review["finding"].explanation_only), findings[0],
        )
    if len(valid) != judges:
        return _merge_reviews([])
    if (len(valid) == 2 and all(r["qualityPassed"] for r in valid)
            and abs(valid[0]["total"] - valid[1]["total"]) > 0.7):
        logger.info("两次盲评差 %.2f，启动仲裁", abs(valid[0]["total"] - valid[1]["total"]))
        arbiter = run_checked(
            cancel_check, _judge_once, question, target, scope, api_key, **cancel_kwargs, **judge_kwargs,
        )
        if arbiter is None:
            return _merge_reviews([])
        if arbiter.get("finding") is not None:
            return arbiter
        merged = _merge_reviews([arbiter])
        merged["arbitrated"] = True
        return merged
    merged = _merge_reviews(valid)
    merged["arbitrated"] = False
    if len(valid) == 2:
        merged["passed"] = merged["passed"] and in_target(merged["total"], target) and not merged["veto"]
    return merged


def _apply_review(question: Question, review: dict) -> None:
    question.difficultyScore = float(review.get("total") or 0.0)
    question.difficultyReview = {
        key: review.get(key)
        for key in ("total", "tier", "scores", "defectCodes", "suggestion",
                    "veto", "passed", "arbitrated", "unknown")
    }
    question.difficultyReview["methodCount"] = len(review.get("methods") or [])


def _repair(
    question: Question, finding: _Finding, target: Difficulty, api_key: str | None,
    cancel_check: Callable[[], None] | None = None,
    *, scope: str = "", original: bool = False,
) -> Question | None:
    """依据具体缺陷修订一次，保留候选身份与交付档位。"""
    if finding.completion_answer is not None:
        fixed = question.model_copy(deep=True)
        if _solve_one(
            fixed, api_key, independent=finding.completion_answer, scope=scope,
            targeted_reason=finding.evidence, **cancellation_kwargs(cancel_check),
        ):
            return fixed
        return None
    payload = question.model_dump(exclude={"difficultyReview", "difficultyScore"})
    restriction = (
        "原题模式须逐字保留题干及成品已有的选项，只可修正答案、解析及评分点。"
        if original else "保留题型与核心考点，只修正必要内容。"
    )
    template = EXPLANATION_REPAIR_PROMPT if finding.explanation_only else REPAIR_PROMPT
    prompt = (
        template.replace("__TARGET__", target.value)
        .replace("__PARAMS__", TIER_PARAMS[target])
        .replace("__ORIGINAL__", restriction)
        .replace("__SCOPE__", scope or "未限定")
        .replace("__EVIDENCE__", f"{finding.reason}：{finding.evidence}")
        .replace("__QUESTION__", json.dumps(payload, ensure_ascii=False))
    )
    try:
        data = _chat_json_low(
            [{"role": "user", "content": prompt}], api_key,
            **cancellation_kwargs(cancel_check),
        )
        if finding.explanation_only:
            if any(
                key != "analysis" and key in data and data[key] != value
                for key, value in payload.items()
            ):
                trace.record_question_failure("protected_fields_changed")
                return None
            raw = data.get("analysis")
            analysis = _polish_analysis(raw) if isinstance(raw, str) else None
            if not analysis or _has_draft_trace(analysis):
                trace.record_question_failure("invalid_output")
                return None
            return question.model_copy(update={"analysis": analysis})
        fixed = Question.model_validate(data)
    except GenerationCanceled:
        raise
    except (ValueError, llm.LLMError) as exc:
        _trace_model_failure(exc)
        logger.warning("修补失败：%s", type(exc).__name__)
        return None
    if fixed.type != question.type:
        trace.record_question_failure("protected_fields_changed")
        return None
    return fixed.model_copy(update={
        "id": question.id, "difficulty": target, "score": question.score,
        "docName": question.docName, "starred": question.starred,
    })


def _normalize_math(text: str) -> str:
    """题干、选项、答案与解析共用公式机械修复。"""
    return latex_utils.fix_delimiters(text)


def _normalize_answer(question: Question, raw: str) -> str:
    """把模型答案收敛到本平台的存储格式。"""
    text = (raw or "").strip().strip("：:").strip()
    if question.type in (QuestionType.single, QuestionType.multiple):
        labels = {o.label.upper() for o in question.options}
        picked = sorted({ch for ch in re.findall(r"[A-Z]", text.upper()) if ch in labels})
        if picked:
            return "".join(picked)
        return question.answer
    if question.type == QuestionType.judge:
        positive = any(word in text for word in ("正确", "对", "成立", "√", "是"))
        negative = any(word in text for word in ("错误", "错", "不成立", "×", "否"))
        if positive and not negative:
            return "正确"
        if negative and not positive:
            return "错误"
        return question.answer
    return text or question.answer


_TYPE_CN = {"single": "单选题", "multiple": "多选题", "judge": "判断题",
            "blank": "填空题", "compute": "计算题", "essay": "简答题"}

def _latex_issue(text: str) -> str | None:
    """题干与解析共用的 LaTeX 定界校验（统一实现见 latex_utils）。"""
    return latex_utils.latex_issue(text)


def _polish_analysis(text: str) -> str | None:
    """解析规范化：收敛空行、套用与题干相同的 LaTeX 定界校验与机械修复。"""
    cleaned = re.sub(r"\n{3,}", "\n\n", (text or "").strip())
    if not cleaned:
        return None
    cleaned = latex_utils.fix_delimiters(cleaned)
    if latex_utils.latex_issue(cleaned):
        return None
    return cleaned


def _assign_options(
    correct_texts: list[str], distractors: list[str],
) -> tuple[list[OptionItem], str]:
    """随机排列四个已验证的选项，正确答案与标签同时产生。"""
    import random

    entries = [(text, True) for text in correct_texts] + [
        (text, False) for text in distractors
    ]
    random.shuffle(entries)
    options = [
        OptionItem(label=label, text=text)
        for label, (text, _correct) in zip("ABCD", entries)
    ]
    answer = "".join(
        label for label, (_text, correct) in zip("ABCD", entries) if correct
    )
    return options, answer


_MULTI_SEP = "\u0001"
_SOLVE_ANSWER_TOKENS = 4000
_SOLVE_EXPLAIN_TOKENS = 2400
_SOLVE_ATTEMPTS = 2
_EXPLAIN_ATTEMPTS = 2


def _clean_option_text(text: str) -> str:
    """清除选项标签并统一公式定界，后续仍须校验非空与公式合法性。"""
    return latex_utils.fix_delimiters(re.sub(r"^[A-Ha-h][.、．:：）)]\s*", "", text.strip()))


def _option_key(text: str) -> str:
    """选项唯一性忽略空白、公式定界及展示用伸缩括号指令。"""
    return re.sub(r"[\s$]+|\\(?:left|right)(?![A-Za-z])", "", text)


def _prepare_answer(question: Question, answer_raw: str) -> tuple[list[str], str] | None:
    """验证答案文本，返回正确项列表与传给讲解阶段的答案。"""
    if question.type in (QuestionType.single, QuestionType.multiple):
        corrects = [_clean_option_text(part) for part in answer_raw.split(_MULTI_SEP)]
        expected = len(corrects) == 1 if question.type == QuestionType.single else (
            2 <= len(corrects) <= 3
        )
        keys = [_option_key(item) for item in corrects]
        if (not expected or any(not key for key in keys)
                or len(set(keys)) != len(keys)
                or any(_polish_analysis(item) is None for item in corrects)):
            return None
        return corrects, "；".join(corrects)
    if question.type == QuestionType.judge:
        raw = answer_raw.strip().lower()
        if raw in ("正确", "对", "t", "true", "√"):
            return [], "正确"
        if raw in ("错误", "错", "f", "false", "×"):
            return [], "错误"
        return None
    answer = _polish_analysis(answer_raw)
    return ([], answer) if answer else None


def _ask_answer(
    question: Question, api_key: str | None,
    cancel_check: Callable[[], None] | None = None,
    *, structured: bool = False,
) -> _SolveResult:
    """独立求解并验证答案协议，失败重试；每次调用前后检查取消。"""
    prompt = (
        f"【题干】\n{question.stem}\n\n"
        f"【题型】{_TYPE_CN.get(question.type.value, question.type.value)}\n"
    )
    if question.type == QuestionType.multiple:
        prompt += (
            "多选题固定四个选项：answer 必须为 2~3 个互异正确项文本的数组，"
            "保留 1~2 个干扰项位置。不要输出选项字母。"
        )
    elif question.type == QuestionType.single:
        prompt += "单选题 answer 为唯一正确选项文本的字符串，不要输出字母或数组。"
    elif question.type == QuestionType.judge:
        prompt += "判断题 answer 只填 正确 或 错误。"
    if structured and question.options:
        prompt += "\n【固定选项】" + json.dumps(
            [option.model_dump() for option in question.options], ensure_ascii=False,
        )
        prompt += "\n选择题只从给定选项中选取，按题型返回对应的选项文本。"
    system = SOLVE_ANSWER_SYSTEM + (_STRUCTURED_SOLVE_PROMPT if structured else "")
    for attempt in range(_SOLVE_ATTEMPTS):
        check_cancellation(cancel_check)
        retry = "\n上次答案不合格，请重新求解并遵守字段类型与题型约束。" if attempt else ""
        try:
            data = run_checked(
                cancel_check, llm.chat_json,
                [{"role": "system", "content": system},
                 {"role": "user", "content": prompt + retry}],
                api_key=api_key, max_tokens=_SOLVE_ANSWER_TOKENS, thinking=True,
                **cancellation_kwargs(cancel_check),
            )
        except GenerationCanceled:
            raise
        except Exception as exc:
            _trace_model_failure(exc)
            logger.warning("独立求解失败：%s", type(exc).__name__)
            continue
        if not isinstance(data, dict):
            trace.record_question_failure("invalid_output")
            continue
        evidence = ""
        if structured:
            raw_evidence = data.get("evidence")
            try:
                status = SolveStatus(data.get("status"))
            except (ValueError, TypeError):
                trace.record_question_failure("invalid_output")
                continue
            if not isinstance(raw_evidence, str) or not raw_evidence.strip():
                trace.record_question_failure("missing_evidence")
                continue
            evidence = raw_evidence.strip()
            if status != SolveStatus.SOLVED:
                return _SolveResult(status, evidence)
        confidence = data.get("confidence", "mid")
        if not isinstance(confidence, str) or confidence not in ("high", "mid", "low"):
            trace.record_question_failure("invalid_output")
            continue
        raw = data.get("answer")
        if question.type == QuestionType.multiple:
            if (not isinstance(raw, list) or not 2 <= len(raw) <= 3
                    or any(not isinstance(item, str) or _MULTI_SEP in item for item in raw)):
                trace.record_question_failure("invalid_output")
                continue
            answer = _MULTI_SEP.join(raw)
        elif isinstance(raw, str) and _MULTI_SEP not in raw:
            answer = raw
        else:
            trace.record_question_failure("invalid_output")
            continue
        if _prepare_answer(question, answer) is not None:
            return _SolveResult(SolveStatus.SOLVED, evidence, answer, confidence)
        trace.record_question_failure("invalid_output")
    return _SolveResult(SolveStatus.UNVERIFIABLE)


def _has_draft_trace(analysis: str) -> bool:
    """拦截解析中的自我纠错与草稿独白。"""
    return any(trace in analysis.lower() for trace in DRAFT_TRACES)


def _ask_explain(
    question: Question, answer_text: str, api_key: str | None,
    cancel_check: Callable[[], None] | None = None,
    correct_texts: list[str] | None = None,
    *, scope: str = "", fixed_options: bool = False, targeted_reason: str = "",
) -> tuple[str, list[str], str] | None:
    """核验候选答案后写成品解析与干扰项，格式错误或草稿泄漏时重试。"""
    prompt = (
        f"【题干】\n{question.stem}\n\n"
        f"【题型】{_TYPE_CN.get(question.type.value, question.type.value)}\n\n"
        f"【待核验的候选答案】\n{answer_text}\n"
    )
    choice = question.type in (QuestionType.single, QuestionType.multiple)
    if scope:
        prompt += f"\n【指定范围】{scope}。只使用范围内的定理和方法。"
    system = SOLVE_EXPLAIN_SYSTEM
    if fixed_options:
        system += "\n本题选项已固定，逐项说明其正误，只输出 analysis 和 conclusion。"
        prompt += "\n【固定选项】" + json.dumps(
            [option.model_dump() for option in question.options], ensure_ascii=False,
        )
    if choice and not fixed_options:
        prompt += "输出 analysis、conclusion 与 distractors，正确项与干扰项合计恰好四项。"
        if question.type == QuestionType.multiple:
            prompt += "多选有 2~3 个正确项，配 1~2 个互异干扰项；conclusion 按候选项顺序用；连接。"
    else:
        prompt += "输出 analysis 与 conclusion。"
    if targeted_reason:
        prompt += (
            f"\n【定向修订】{targeted_reason}。保留已确认的答案及现有选项，"
            "重新写出完整解析，并在 conclusion 原样填写待核验的候选答案。"
        )
    for attempt in range(1 if targeted_reason else _EXPLAIN_ATTEMPTS):
        check_cancellation(cancel_check)
        retry = (
            "\n上次讲解不合格：请检查字段类型、公式、四项唯一性和草稿痕迹，"
            "只输出成立的推导与真实结论。"
        ) if attempt else ""
        try:
            data = run_checked(
                cancel_check, llm.chat_json,
                [{"role": "system", "content": system},
                 {"role": "user", "content": prompt + retry}],
                api_key=api_key, max_tokens=_SOLVE_EXPLAIN_TOKENS,
                **cancellation_kwargs(cancel_check),
            )
        except GenerationCanceled:
            raise
        except Exception as exc:
            _trace_model_failure(exc)
            logger.warning("讲解生成失败：%s", type(exc).__name__)
            continue
        if not isinstance(data, dict):
            trace.record_question_failure("invalid_output")
            continue
        raw_analysis, raw_conclusion = data.get("analysis"), data.get("conclusion", "")
        if not isinstance(raw_analysis, str) or not isinstance(raw_conclusion, str):
            trace.record_question_failure("invalid_output")
            continue
        analysis = _polish_analysis(raw_analysis)
        conclusion = raw_conclusion.strip()
        if not analysis or _has_draft_trace(analysis):
            trace.record_question_failure(
                "empty_explanation" if not raw_analysis.strip() else
                "explanation_formula" if not analysis else "explanation_draft"
            )
            continue
        if targeted_reason and not conclusion:
            trace.record_question_failure("missing_conclusion")
            continue
        distractors: list[str] = []
        if choice and not fixed_options:
            raw_distractors = data.get("distractors")
            if (not isinstance(raw_distractors, list)
                    or any(not isinstance(item, str) for item in raw_distractors)):
                trace.record_question_failure("invalid_distractors")
                continue
            distractors = [_clean_option_text(item) for item in raw_distractors]
            if any(_polish_analysis(item) is None for item in distractors):
                trace.record_question_failure("invalid_distractors")
                continue
            corrects = correct_texts or [answer_text]
            keys = [_option_key(item) for item in corrects + distractors]
            if len(keys) != 4 or any(not key for key in keys) or len(set(keys)) != 4:
                trace.record_question_failure("invalid_distractors")
                continue
        return analysis, distractors, conclusion
    return None


def _answers_agree(conclusion: str, answer_text: str, *, exact: bool = False) -> bool:
    """比较规范化结论，定向修订要求与已确认的答案一致。"""
    if exact:
        left, right = (
            re.sub(r"\s+", " ", latex_utils.fix_delimiters(text)).strip()
            for text in (conclusion, answer_text)
        )
        return bool(left) and left == right

    def normalize(text: str) -> str:
        stripped = re.sub(r"\$|\\(?:left|right)(?![A-Za-z])|\\[,;!]|\s+", "", text or "")
        stripped = stripped.replace("{", "").replace("}", "").replace("\\", "")
        return stripped.strip().lower()

    left, right = normalize(conclusion), normalize(answer_text)
    if not left or not right:
        return True
    if left == right:
        return True
    numeric = re.compile(r"-?\d+(?:\.\d+)?")
    if numeric.fullmatch(left) and numeric.fullmatch(right):
        return False
    return left in right or right in left


def _solve_one(
    question: Question, api_key: str | None,
    cancel_check: Callable[[], None] | None = None,
    *, independent: _SolveResult | None = None, scope: str = "", targeted_reason: str = "",
) -> bool:
    """两步解题并核对结论，整题验证和取消检查通过后才回写。"""
    check_cancellation(cancel_check)
    fixed_options = (
        independent is not None and bool(question.options)
        and question.type in (QuestionType.single, QuestionType.multiple)
    )
    attempts = 1 if independent is not None else _SOLVE_ATTEMPTS
    for _attempt in range(attempts):
        solved = independent or _ask_answer(question, api_key, **cancellation_kwargs(cancel_check))
        if solved.status != SolveStatus.SOLVED:
            return False
        prepared = _prepare_answer(question, solved.answer)
        if prepared is None:
            continue
        corrects, answer_text = prepared
        if fixed_options and not (
            {_option_key(text) for text in corrects}
            <= {_option_key(option.text) for option in question.options}
        ):
            trace.record_question_failure("independent_options_mismatch")
            return False
        explained = _ask_explain(
            question, answer_text, api_key, correct_texts=corrects,
            scope=scope, fixed_options=fixed_options,
            **({"targeted_reason": targeted_reason} if targeted_reason else {}),
            **cancellation_kwargs(cancel_check),
        )
        if explained is None:
            return False
        analysis, distractors, conclusion = explained
        agreement = None
        if solved.symbolic is not None and conclusion and not corrects[1:]:
            agreement = verify_symbolic(solved.symbolic, conclusion, (), cancel_check).answer_matches
        if agreement is False or (
            agreement is None and not _answers_agree(
                conclusion, answer_text, exact=bool(targeted_reason),
            )
        ):
            trace.record_question_failure("answer_conflict")
            logger.warning("解析结论与候选答案不一致，重新独立求解")
            continue
        options = list(question.options)
        if fixed_options:
            correct_keys = {_option_key(text) for text in corrects}
            selected = [item.label for item in options if _option_key(item.text) in correct_keys]
            if len(selected) != len(correct_keys):
                trace.record_question_failure("answer_conflict")
                return False
            answer = "".join(sorted(selected))
        elif question.type in (QuestionType.single, QuestionType.multiple):
            options, answer = _assign_options(corrects, distractors)
        elif question.type == QuestionType.judge:
            answer = "A" if answer_text == "正确" else "B"
            if independent is None or not options:
                options = [OptionItem(label="A", text="正确"), OptionItem(label="B", text="错误")]
        else:
            answer = answer_text
        self_check = dict(question.selfCheck)
        if solved.confidence == "low":
            note = str(self_check.get("note") or "")
            self_check["note"] = (
                (note + "；" if note else "") + "独立解题置信度低，题目可能存在歧义"
            )
        candidate = Question.model_validate({
            **question.model_dump(), "answer": answer, "analysis": analysis,
            "options": options, "selfCheck": self_check,
        })
        check_cancellation(cancel_check)
        question.answer = candidate.answer
        question.analysis = candidate.analysis
        question.options = candidate.options
        question.selfCheck = candidate.selfCheck
        return True
    return False



def _solve_all(
    questions: list[Question], api_key: str | None, stats: ReviewStats,
    cancel_check: Callable[[], None] | None = None,
) -> set[int]:
    """等待全部求解线程退出后统一更新，并返回独立求解成功的对象身份。"""
    check_cancellation(cancel_check)
    if not questions:
        return set()

    def run(q: Question) -> tuple[Question, Question, bool]:
        candidate = q.model_copy(deep=True)
        try:
            return q, candidate, run_checked(
                cancel_check, _solve_one, candidate, api_key,
                **cancellation_kwargs(cancel_check),
            )
        except GenerationCanceled:
            raise
        except Exception as exc:
            logger.warning("解析生成失败：%s", exc)
            check_cancellation(cancel_check)
            return q, candidate, False

    with ThreadPoolExecutor(max_workers=_THINK_WORKERS, thread_name_prefix="review-solve") as pool:
        results = list(pool.map(run, questions))
    check_cancellation(cancel_check)
    solved: set[int] = set()
    for original, candidate, ok in results:
        if ok:
            original.answer = candidate.answer
            original.analysis = candidate.analysis
            original.options = candidate.options
            original.selfCheck = candidate.selfCheck
            stats.solved += 1
            solved.add(id(original))
    return solved


_COMPLETION_REASONS = {
    "answer_conflict": ("补全结论与答案冲突", "修正解析结论，使其与已确认的答案一致"),
    "empty_explanation": ("解析为空", "补齐解析和必要步骤"),
    "explanation_formula": ("解析公式格式错误", "修复解析中的公式定界与转义"),
    "explanation_draft": ("解析含草稿", "删去草稿与反复试算，给出完整推导"),
    "missing_conclusion": ("解析补全失败", "给出明确的解析结论"),
    "invalid_distractors": ("选项不合格", "保留正确项，并生成数量正确且互不等价的干扰项"),
}


def _symbolic_solve(
    question: Question, fields: _QuestionTraceFields, cancel_check: Callable[[], None] | None,
) -> tuple[_SolveResult | None, _Finding | None]:
    with trace.question_stage("symbolic_solve", **fields) as stage:
        symbolic = solve_symbolic(question.stem, question.type.value, cancel_check)
        if symbolic.status != "solved":
            stage.decision("skipped", f"symbolic_{symbolic.status}")
            return None, None
        options = tuple(option.text for option in question.options)
        if options and question.type in (QuestionType.single, QuestionType.multiple):
            verification = verify_symbolic(symbolic, symbolic.answer, options, cancel_check)
            correct = verification.true_option_indices
            if correct is None:
                stage.decision("skipped", f"symbolic_{verification.status}")
                return None, None
            valid_count = (
                len(correct) == 1 if question.type == QuestionType.single else
                2 <= len(correct) <= 3 and len(correct) < len(options)
            )
            if not valid_count:
                stage.decision("rejected", "invalid_options")
                return None, _Finding(
                    "选项不合格", f"符号验算得到 {len(correct)} 个正确项，与该题型要求不符。",
                )
            answer = _MULTI_SEP.join(options[index] for index in correct)
        elif question.type == QuestionType.multiple:
            stage.decision("skipped", "symbolic_unsupported")
            return None, None
        else:
            answer = symbolic.answer
        stage.decision("passed")
        return _SolveResult(SolveStatus.SOLVED, "由 SymPy 独立验算。", answer, "high", symbolic), None


def _check_candidate(
    question: Question, scope: str, api_key: str | None,
    cancel_check: Callable[[], None] | None, *, repaired: bool,
) -> _Finding | None:
    """独立求解完整题面，再验收实际交付字段与难度。"""
    fields = _trace_fields(question, int(repaired))
    with trace.question_stage("independent_solve", **fields) as stage:
        if not question.stem.strip() or _latex_issue(question.stem):
            stage.decision("rejected", "题面缺陷")
            return _Finding("题面缺陷", "题干为空或数学公式定界有误")
        independent, symbolic_finding = _symbolic_solve(question, fields, cancel_check)
        if symbolic_finding is not None:
            stage.decision("rejected", symbolic_finding.reason)
            return symbolic_finding
        if independent is None:
            independent = _ask_answer(
                question, api_key, structured=True, **cancellation_kwargs(cancel_check),
            )
        if independent.status != SolveStatus.SOLVED:
            stage.decision("rejected", independent.status.value)
            reason = _SOLVE_REASONS[independent.status]
            evidence = independent.evidence if independent.status != SolveStatus.UNVERIFIABLE else ""
            return _Finding(reason, evidence)
        stage.decision("passed")
    if not question.answer.strip():
        with trace.question_stage("solution_completion", **fields) as stage:
            if not _solve_one(
                question, api_key, independent=independent, scope=scope,
                **cancellation_kwargs(cancel_check),
            ):
                code = stage.failure_reason()
                if code == "independent_options_mismatch":
                    stage.decision("rejected", code)
                    return _Finding("选项不合格")
                reason, instruction = _COMPLETION_REASONS.get(
                    code or "", (
                        "解析补全失败",
                        "核对返回字段、公式定界和解析结论，重新完成解析",
                    ),
                )
                if code and code.startswith("model_"):
                    instruction = "上一轮模型调用失败，重新完成解析并核对输出字段"
                stage.decision("rejected", code or reason)
                return _Finding(
                    reason, instruction, explanation_only=True, completion_answer=independent,
                )
            stage.decision("passed")
    with trace.question_stage("final_acceptance", **fields) as stage:
        finding = _accept_candidate(question, independent, scope, api_key, cancel_check,
                                    repaired=repaired)
        if finding is None:
            stage.decision("passed")
        else:
            stage.decision("rejected", finding.reason)
        return finding


def _check_symbolic_answer(
    question: Question, symbolic: SymbolicResult, cancel_check: Callable[[], None] | None,
) -> _Finding | None:
    options = tuple(option.text for option in question.options)
    choice = question.type in (QuestionType.single, QuestionType.multiple)
    verification = verify_symbolic(
        symbolic, symbolic.answer if choice else question.answer, options, cancel_check,
    )
    if choice:
        indices = verification.true_option_indices
        if indices is None:
            trace.record_question_failure(f"symbolic_{verification.status}")
            return None
        valid_count = (
            len(indices) == 1 if question.type == QuestionType.single
            else 2 <= len(indices) <= 3 and len(indices) < len(options)
        )
        if not valid_count:
            return _Finding("选项不合格", "符号验算发现实际正确选项数不符合题型。")
        selected = {question.options[index].label for index in indices}
        if selected != set(question.answer):
            return _Finding("答案不成立", "成品所选标签与符号验算结果不一致。")
    elif verification.answer_matches is False:
        return _Finding("答案不成立", f"符号验算得到 {symbolic.answer}，与成品答案不一致。")
    elif verification.answer_matches is None:
        trace.record_question_failure(f"symbolic_{verification.status}")
    return None


def _accept_candidate(
    question: Question, independent: _SolveResult, scope: str, api_key: str | None,
    cancel_check: Callable[[], None] | None, *, repaired: bool,
) -> _Finding | None:
    """验收成品的答案、解析、选项和难度。"""
    if not question.answer.strip() or _latex_issue(question.answer):
        return _Finding("答案不成立", "成品答案为空或数学公式定界有误")
    if independent.symbolic is not None:
        finding = _check_symbolic_answer(question, independent.symbolic, cancel_check)
        if finding is not None:
            return finding
    if question.type in (QuestionType.single, QuestionType.multiple, QuestionType.judge):
        labels = {item.label for item in question.options}
        answer = set(question.answer)
        min_correct = 2 if question.type == QuestionType.multiple else 1
        option_keys = {_option_key(item.text) for item in question.options}
        if (
                len(labels) != len(question.options)
                or any(not re.fullmatch("[A-H]", label) for label in labels)
                or len(option_keys) != len(labels) or "" in option_keys
                or any(_latex_issue(item.text) for item in question.options)
                or not answer <= labels or len(answer) != len(question.answer)
                or len(answer) < min_correct
                or (question.type == QuestionType.multiple and len(answer) == len(labels))
                or (question.type != QuestionType.multiple and len(answer) != 1)
                or (question.type == QuestionType.judge and labels != {"A", "B"})
                or len(labels) < 2):
            return _Finding("选项不合格", "成品选项或正确项标签、内容、数量不符合题型")
        prepared = _prepare_answer(question, independent.answer)
        if prepared is None:
            return _Finding("无法验证")
        correct_texts, answer_text = prepared
        expected = correct_texts if question.type != QuestionType.judge else [answer_text]
        selected = [item.text for item in question.options if item.label in answer]
        if {_option_key(text) for text in selected} != {_option_key(text) for text in expected}:
            return _Finding(
                "答案不成立",
                f"成品答案 {question.answer} 对应「{'；'.join(selected)}」，"
                f"独立求解得到「{'；'.join(expected)}」。{independent.evidence}",
            )
    elif question.options:
        return _Finding("选项不合格", "该题型不应附带选项")
    if not _polish_analysis(question.analysis) or _has_draft_trace(question.analysis):
        return _Finding(
            "解析不成立", "成品解析为空、公式定界有误或含推导草稿", explanation_only=True,
        )
    review = evaluate(
        question, question.difficulty, scope, api_key, judges=1 if repaired else 2,
        independent=independent, **cancellation_kwargs(cancel_check),
    )
    if review.get("finding") is not None:
        return review["finding"]
    if review.get("unknown") is not False:
        return _Finding("无法验证")
    total = review["total"]
    if review["passed"] is not True or not in_target(total, question.difficulty):
        evidence = (
            f"成品评定为{tier_of(total).value}档（{total} 分），"
            f"目标为{question.difficulty.value}档。"
            f"{review.get('suggestion') or review.get('evidence', '')}"
        )
        return _Finding("难度不符", evidence)
    _apply_review(question, review)
    return None


def _review_candidate(
    question: Question, params: GenerateParams, api_key: str | None,
    cancel_check: Callable[[], None] | None,
) -> _CandidateResult:
    """候选及其唯一一次修订共用验收链。"""
    candidate = question.model_copy(deep=True)
    scope = params.scope
    original = params.source_mode == "original"
    if (original and question.type in (QuestionType.single, QuestionType.multiple)
            and not question.options):
        return _CandidateResult(reason="原题选项缺失")
    try:
        finding = _check_candidate(candidate, scope, api_key, cancel_check, repaired=False)
        if finding is None:
            return _CandidateResult(candidate)
        fields = _trace_fields(candidate, 1)
        if original and finding.reason in {"题设不足", "命题为假", "条件矛盾", "题面缺陷", "难度不符"}:
            trace.question_decision("repair", "skipped", finding.reason, **fields)
            return _CandidateResult(reason=finding.reason)
        if not finding.evidence:
            trace.question_decision("repair", "skipped", finding.reason, **fields)
            return _CandidateResult(reason=finding.reason)
        repair_mode = "explanation_only" if finding.explanation_only else "full"
        with trace.question_stage("repair", repair_mode=repair_mode, **fields) as stage:
            fixed = _repair(
                candidate, finding, question.difficulty, api_key, scope=scope, original=original,
                **cancellation_kwargs(cancel_check),
            )
            if fixed is None:
                stage.decision("rejected", stage.failure_reason() or finding.reason)
                return _CandidateResult(reason=finding.reason)
            if original and (fixed.stem != question.stem or fixed.options != candidate.options):
                trace.record_question_failure("protected_fields_changed")
                stage.decision("rejected", "原题被改动")
                return _CandidateResult(reason="原题被改动")
            stage.decision("passed", finding.reason)
        with trace.question_stage("re_review", **fields) as stage:
            finding = _check_candidate(fixed, scope, api_key, cancel_check, repaired=True)
            if finding is not None:
                stage.decision("rejected", finding.reason)
                return _CandidateResult(reason=finding.reason, repaired=True)
            stage.decision("passed")
            return _CandidateResult(fixed, repaired=True)
    except GenerationCanceled:
        raise
    except Exception as exc:
        check_cancellation(cancel_check)
        logger.warning("候选题校验失败：%s", type(exc).__name__)
        return _CandidateResult(reason="无法验证")


def review_questions(
    db: Session,
    user_id: str,
    questions: list[Question],
    params: GenerateParams,
    doc_name: str,
    api_key: str | None,
    hyde_text: str | None = None,
    progress=None,
    cancel_check: Callable[[], None] | None = None,
    *,
    deduplicate: bool = True,
) -> tuple[list[Question], ReviewStats]:
    """审核本批候选题，由调用方根据实际通过结果安排补题。

    启用内置查重时，语料在短读事务中读取。共享交付可关闭内置查重。
    候选复制后独立验收，取消和拒绝均不会修改调用方传入的题目。
    """
    check_cancellation(cancel_check)
    stats = ReviewStats()
    eligible = {(item.type, item.difficulty or params.difficulty) for item in params.types}
    questions = [q for q in questions if (q.type, q.difficulty) in eligible]
    if not questions:
        return [], stats
    def report(percent: int, stage: str) -> None:
        check_cancellation(cancel_check)
        if progress:
            progress(percent, stage)
        check_cancellation(cancel_check)

    def reject(
        question: Question, reason: str, *, stage: str, revision: int = 0,
        failure_code: str | None = None,
    ) -> None:
        stats.rejections.setdefault((question.type, question.difficulty), Counter())[reason] += 1
        if reason == "重复题目":
            stats.duplicates += 1
        with trace.question_stage(stage, **_trace_fields(question, revision)) as observation:
            if failure_code is not None:
                trace.record_question_failure(failure_code)
            observation.decision("rejected", reason)

    pending = questions
    corpus: list[str] = []
    if deduplicate:
        if db.in_transaction() or db.new or db.dirty or db.deleted:
            raise InvalidRequestError(
                "review_questions requires a clean Session without an active transaction"
            )
        with db.begin():
            corpus = load_corpus(db, user_id, params.kb_id)
        corpus_by_norm: dict[str, str] = {}
        for stem in corpus + params.existing_stems:
            if key := _norm(stem):
                corpus_by_norm.setdefault(key, stem)
        corpus = list(corpus_by_norm.values())
        report(78, "正在排查重复题目")
        pending = []
        for question in questions:
            if _norm(question.stem) in corpus_by_norm:
                reject(question, "重复题目", stage="corpus_dedup")
            else:
                pending.append(question)

    report(82, "正在独立求解与验收候选题")
    with ThreadPoolExecutor(max_workers=_THINK_WORKERS, thread_name_prefix="review-candidate") as pool:
        results = list(pool.map(
            lambda question: _review_candidate(question, params, api_key, cancel_check), pending,
        ))
    check_cancellation(cancel_check)
    accepted: list[Question] = []
    repaired_candidates: set[int] = set()
    for question, result in zip(pending, results, strict=True):
        stats.repaired += int(result.repaired)
        if result.question is None:
            reject(question, result.reason, stage="candidate_review", revision=int(result.repaired))
        else:
            accepted.append(result.question)
            if deduplicate and result.repaired:
                repaired_candidates.add(id(result.question))

    if not deduplicate:
        stats.solved = len(accepted)
        report(100, "题目校验完成")
        return accepted, stats

    report(96, "正在对成品查重")
    try:
        final, duplicates = _drop_duplicates(accepted, corpus, **cancellation_kwargs(cancel_check))
    except _DuplicateCheckError as exc:
        logger.warning("成品查重失败：%s", exc)
        final, duplicates = [], []
        for question in accepted:
            reject(
                question, "无法验证", stage="finished_dedup",
                revision=int(id(question) in repaired_candidates), failure_code="duplicate_check_failed",
            )
    for question in duplicates:
        reject(question, "重复题目", stage="finished_dedup",
               revision=int(id(question) in repaired_candidates))
    stats.solved = len(final)
    report(100, "题目校验完成")
    return final, stats
