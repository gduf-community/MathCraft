"""出题中间件：查重 → 盲评难度与质量 → 缺陷修复 → 生成解析，全部通过后才交给题目预览。

调用顺序固定：
1. 查重：与「题目收藏」「组卷记录」「同题库历史题目」做语义比对，相似度超阈值的丢弃；
2. 盲评：不告知命题时标注的难度，只给题目、知识点范围与目标档。评估模型先独立解题，
   再按六个维度打分并加权；可解性一票否决，高与地狱题要求给出两种解法或数值验证；
   两次评分差超过 0.7 时分派第三位评审仲裁；
3. 反哺：未通过只做一轮最小修补；仍不过就换难度模板重出，不再微调同一题；
4. 解析：通过后另起对话独立解题，写 2~4 句简短解析，覆盖命题阶段自带的答案与解析。

任何一步的服务异常都只降级（保留原题、跳过校验）并写日志，不让整批出题失败。
"""
from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass

import json_repair
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Favorite, Paper, PaperQuestion, Question as QuestionRow
from app.schemas.question import Difficulty, GenerateParams, OptionItem, Question, QuestionType, TypeCount
from app.services.rag import embeddings, llm, question_gen
from app.services.rag.prompts import DRAFT_TRACES, SOLVE_ANSWER_SYSTEM, SOLVE_EXPLAIN_SYSTEM
from app.services import latex_utils
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
# 边界允许 ±0.5 档容差（0.5 分等于半档）
TIER_TOLERANCE = 0.5
# 目标档的参数模板，用于换模板重出时给出明确指令
TIER_PARAMS: dict[Difficulty, str] = {
    Difficulty.low: "步骤 1—2 步、只考 1 个知识点、计算量小、不设陷阱",
    Difficulty.mid: "步骤 2—3 步、综合 2 个知识点、计算量中等、至多 1 个常见易错点",
    Difficulty.high: "步骤 3—5 步、综合 3 个知识点、计算量偏大、至少 1 个真实陷阱",
    Difficulty.hell: "步骤 4 步以上、综合 3 个以上知识点、计算量大、至少 2 个陷阱、解法非常规",
}

EVAL_PROMPT = """你是独立数学审题人。给定一道题、它所属的知识点范围和目标难度档，请先独立解题，再评分。
不要参考任何出题方给出的难度标注，只按题目本身判断。

评分维度，每项 1—5 分（5 分最高）：
- knowledge 知识点匹配：与给定知识点范围的吻合程度
- steps 步骤综合：需要的推理步骤数与综合程度
- abstraction 概念抽象：概念层面的抽象与转化要求
- computation 计算复杂度：计算量与计算技巧
- trap 陷阱非常规：陷阱设置与非标准思路
- unique 可解唯一：可解、答案唯一、无歧义（5 表示完全满足）

加权总分 = 0.20×knowledge + 0.20×steps + 0.20×abstraction + 0.15×computation + 0.15×trap + 0.10×unique
判定档：1—2 低，2—3 中，3—4 高，4—5 地狱。
一票否决：不可解、多解、超纲、题干歧义，此时 passed 必须为 false。
目标档为「高」或「地狱」时，methods 至少给出两种解法或一种数值验证。

只输出 JSON（字段名照抄，不要增删）：
{"independentAnswer": "独立解出的答案",
 "scores": {"knowledge": 1, "steps": 1, "abstraction": 1,
            "computation": 1, "trap": 1, "unique": 1},
 "total": 加权总分（保留一位小数）,
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
缺陷码：__CODES__
首要建议：__SUGGESTION__
目标难度档：__TARGET__（__PARAMS__）

要求：
1 保留题干主体结构与已知条件，只调整必要部分（增删步骤、换数值、去或加陷阱、修正答案）。
2 修改后必须自洽：选项、答案、解析同步更新，答案唯一且可验证。
3 只输出一个 JSON 对象，字段与出题时相同：type、score、difficulty、knowledgePoint、blueprint、
  stem、options、answer、analysis、scoringPoints、selfCheck。不要包在 questions 数组里。

原题：
__QUESTION__
"""

# 评估与解析的并发数
_THINK_WORKERS = 6
_SCORE_KEYS = ("knowledge", "steps", "abstraction", "computation", "trap", "unique")
_SCORE_WEIGHTS = {
    "knowledge": 0.20,
    "steps": 0.20,
    "abstraction": 0.20,
    "computation": 0.15,
    "trap": 0.15,
    "unique": 0.10,
}


@dataclass
class ReviewStats:
    """中间件的处理结果，用于日志与前端提示。"""

    duplicates: int = 0
    repaired: int = 0
    regenerated: int = 0
    solved: int = 0

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


@with_snapshot
def _drop_duplicates(
    questions: list[Question], corpus: list[str]
) -> tuple[list[Question], list[Question]]:
    """语义查重：与语料或批内已保留题目相似度过阈值的丢弃。"""
    if not questions:
        return [], []
    threshold = settings.review_similarity_threshold
    if corpus:
        try:
            corpus_vecs = embeddings.embed_texts(corpus)
        except Exception as exc:  # 向量服务不可用时跳过查重，不阻断出题
            logger.warning("查重跳过（向量服务不可用）：%s", exc)
            corpus_vecs = []
    else:
        corpus_vecs = []
    try:
        fresh_vecs = embeddings.embed_texts([q.stem for q in questions])
    except Exception as exc:
        logger.warning("查重跳过（题目向量化失败）：%s", exc)
        return questions, []

    norm_corpus = {_norm(s) for s in corpus}
    kept: list[Question] = []
    kept_vecs: list[list[float]] = []
    dropped: list[Question] = []
    for question, vec in zip(questions, fresh_vecs):
        if _norm(question.stem) in norm_corpus:
            dropped.append(question)
            continue
        duplicate = any(_cosine(vec, other) >= threshold for other in corpus_vecs)
        if not duplicate:
            duplicate = any(_cosine(vec, other) >= threshold for other in kept_vecs)
        if duplicate:
            dropped.append(question)
        else:
            kept.append(question)
            kept_vecs.append(vec)
    if dropped:
        logger.info("查重丢弃 %d 题（阈值 %.2f）", len(dropped), threshold)
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
    """判定是否落在目标档区间，允许 ±0.5 档容差。"""
    lo, hi = TIER_RANGES[target]
    return lo - TIER_TOLERANCE <= total <= hi + TIER_TOLERANCE


def _strip_json(text: str) -> str:
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _chat_text_with_fallback(
    messages: list[dict], api_key: str | None, max_tokens: int, json_mode: bool = False
) -> str:
    """评估与解析都关掉思考模式，只取结论；接口不认这个参数时由模型层自动退回。"""
    kwargs: dict = {
        "api_key": api_key, "temperature": 0.2, "max_tokens": max_tokens, "thinking_off": True,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    return llm.chat_text(messages, **kwargs)


def _chat_json_low(messages: list[dict], api_key: str | None, max_tokens: int = 4800) -> dict:
    """低温 JSON 调用：先给足预算，被截断再放大一次。

    修补要整题重写 JSON，实测单次输出三千多字；预算给小了会截断成非法 JSON，
    再重来一次等于白等半分钟。
    """
    last: Exception | None = None
    for budget in (max_tokens, int(max_tokens * 1.4)):
        try:
            text = _chat_text_with_fallback(messages, api_key, budget, json_mode=True)
            # 解析前先补反斜杠：模型常把 \neq 写成单斜杠，json 会静默吃掉或直接报非法转义
            payload = latex_utils.escape_bare_commands_in_json(_strip_json(text))
            data = json.loads(payload)
            if isinstance(data, dict):
                return data
            last = ValueError("返回不是 JSON 对象")
        except Exception as exc:  # noqa: BLE001
            # JSON Repair 兜底：截断或非法结构先修复再校验，修复失败才进入下一轮
            try:
                repaired = json_repair.loads(
                    latex_utils.escape_bare_commands_in_json(_strip_json(text))
                )
                if isinstance(repaired, dict) and repaired:
                    return repaired
            except Exception:  # noqa: BLE001
                pass
            last = exc
    raise ValueError(f"JSON 解析失败：{last}")


def _score_int(value) -> int:
    try:
        num = int(round(float(value)))
    except (TypeError, ValueError):
        return 3
    return max(1, min(5, num))


def parse_review(data: dict, target: Difficulty) -> dict:
    """把评估模型的输出收敛成内部结构，加权总分由本地重算，不信任模型算术。"""
    raw_scores = data.get("scores") or {}
    scores = {key: _score_int(raw_scores.get(key)) for key in _SCORE_KEYS}
    total = round(sum(scores[k] * _SCORE_WEIGHTS[k] for k in _SCORE_KEYS), 2)
    tier = tier_of(total)
    defects = [
        code for code in (str(c).strip().upper() for c in (data.get("defectCodes") or []))
        if code and code[0] in "KSCTAO"
    ]
    unique = scores["unique"]
    raw_passed = data.get("passed", True)
    passed_flag = raw_passed is True or str(raw_passed).strip().lower() in ("true", "1", "是", "通过")
    # 可解性一票否决：答案问题、超纲、可解唯一性过低
    veto = unique <= 2 or "O" in defects or ("A" in defects and not passed_flag)
    passed = passed_flag and not veto and in_target(total, target)
    return {
        "scores": scores,
        "total": total,
        "tier": tier.value,
        "defectCodes": defects,
        "suggestion": str(data.get("primarySuggestion") or "").strip(),
        "independentAnswer": str(data.get("independentAnswer") or "").strip(),
        "methods": [str(m).strip() for m in (data.get("methods") or []) if str(m).strip()],
        "veto": veto,
        "passed": passed,
    }


def _judge_once(question: Question, target: Difficulty, scope: str, api_key: str | None) -> dict | None:
    prompt = (
        EVAL_PROMPT.replace("__TARGET__", target.value)
        .replace("__SCOPE__", scope or "未限定")
        .replace("__STEM__", question.stem)
    )
    try:
        data = _chat_json_low([{"role": "user", "content": prompt}], api_key)
        review = parse_review(data, target)
        if target in (Difficulty.high, Difficulty.hell) and len(review["methods"]) < 2:
            logger.info("高难题目评审未给出两种解法，按分数继续判定")
        return review
    except Exception as exc:  # noqa: BLE001
        logger.warning("盲评失败：%s", exc)
        return None


def _merge_reviews(reviews: list[dict]) -> dict:
    """合并多次盲评：总分取均值，任一否决即否决，缺陷码取并集。"""
    valid = [r for r in reviews if r]
    if not valid:
        return {"total": 0.0, "tier": "", "passed": True, "veto": False, "unknown": True,
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
        "independentAnswer": worst.get("independentAnswer", ""),
        "veto": any(r["veto"] for r in valid),
        "passed": all(r["passed"] for r in valid) and not any(r["veto"] for r in valid),
        "unknown": False,
    }


def evaluate(
    question: Question, target: Difficulty, scope: str, api_key: str | None, judges: int = 2
) -> dict:
    """双评 + 仲裁：两次总分差超过 0.7 时请第三位评审裁决。

    修补后的复评只需要确认修补是否到位，用单评即可，省一半调用。
    """
    judges = max(1, judges)
    with ThreadPoolExecutor(max_workers=judges, thread_name_prefix="review-judge") as pool:
        futures = [
            pool.submit(_judge_once, question, target, scope, api_key) for _ in range(judges)
        ]
        first = [f.result() for f in futures]
    valid = [r for r in first if r]
    if len(valid) == 2 and abs(valid[0]["total"] - valid[1]["total"]) > 0.7:
        logger.info("两次盲评差 %.2f，启动仲裁", abs(valid[0]["total"] - valid[1]["total"]))
        arbiter = _judge_once(question, target, scope, api_key)
        if arbiter:
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


# ---------------- 缺陷修复与换模板重出 ----------------


def _repair(
    question: Question, review: dict, target: Difficulty, api_key: str | None
) -> Question | None:
    """按缺陷码做最小修补，保持题型与考点不变。"""
    payload = {
        "type": question.type.value,
        "score": question.score,
        "difficulty": target.value,
        "knowledgePoint": question.knowledgePoint,
        "blueprint": question.blueprint,
        "stem": question.stem,
        "options": [o.model_dump() for o in question.options],
        "answer": question.answer,
        "analysis": question.analysis,
        "scoringPoints": question.scoringPoints,
    }
    prompt = (
        REPAIR_PROMPT.replace("__CODES__", "、".join(review.get("defectCodes") or []) or "未标注")
        .replace("__SUGGESTION__", review.get("suggestion") or "按目标档参数微调")
        .replace("__TARGET__", target.value)
        .replace("__PARAMS__", TIER_PARAMS[target])
        .replace("__QUESTION__", json.dumps(payload, ensure_ascii=False))
    )
    try:
        data = _chat_json_low([{"role": "user", "content": prompt}], api_key)
        item = data.get("question") if isinstance(data.get("question"), dict) else data
        fixed = Question.model_validate(item)
    except Exception as exc:  # noqa: BLE001
        logger.warning("修补失败：%s", exc)
        return None
    fixed.id = question.id
    fixed.type = question.type
    fixed.difficulty = target
    fixed.knowledgePoint = fixed.knowledgePoint or question.knowledgePoint
    if not fixed.options and question.options:
        fixed.options = question.options
    return fixed


def _regen(
    params: GenerateParams,
    qtype: QuestionType,
    count: int,
    doc_name: str,
    avoid: list[str],
    api_key: str | None,
    hyde_text: str | None,
    directive: str = "",
) -> list[Question]:
    """按题型补出 count 道，避免与已保留题目重复。"""
    sub = params.model_copy(update={"types": [TypeCount(type=qtype, count=count)]})
    return question_gen.generate_questions(
        sub,
        doc_name,
        scope=params.scope or None,
        existing_stems=avoid,
        api_key=api_key,
        hyde_text=hyde_text,
        directive=directive,
    )


def _delta(total: float, target: Difficulty) -> float:
    lo, hi = TIER_RANGES[target]
    center = (lo + hi) / 2
    return abs(total - center)


def _normalize_math(text: str) -> str:
    """把 \\(...\\) 与 \\[...\\] 统一成 $...$ / $$...$$，前端只认美元定界符。"""
    text = re.sub(r"\\\((.+?)\\\)", r"$\1$", text, flags=re.S)
    text = re.sub(r"\\\[(.+?)\\\]", r"$$\1$$", text, flags=re.S)
    return text


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

# 需要解题模型产出答案的题型：出题模型只命制题干，答案为空即解题失败
_NEED_ANSWER_TYPES = {QuestionType.single, QuestionType.multiple,
                      QuestionType.judge, QuestionType.blank,
                      QuestionType.compute, QuestionType.essay}


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


def _assign_options(correct_texts: list[str], distractors: list[str]) -> tuple[list, str]:
    """随机分配正确答案到 A/B/C/D 的位置，其余位置放干扰项。

    返回 (选项列表, 正确字母串)。正确项位置每次随机，避免答案总落在同一选项。
    """
    import random

    labels = ["A", "B", "C", "D"]
    positions = sorted(random.sample(range(4), len(correct_texts)))
    options: list = []
    correct_letters: list[str] = []
    ci = 0
    di = 0
    for idx, label in enumerate(labels):
        if ci < len(correct_texts) and idx == positions[ci]:
            options.append(OptionItem(label=label, text=correct_texts[ci]))
            correct_letters.append(label)
            ci += 1
        else:
            options.append(OptionItem(label=label, text=distractors[di]))
            di += 1
    return options, "".join(correct_letters)


# 多选答案在内部用不可见分隔符串联，避免与选项文本里的逗号、分号冲突
_MULTI_SEP = "\u0001"
# 求解要留出完整推理预算，讲解只需要写结论与关键步骤
_SOLVE_ANSWER_TOKENS = 4000
_SOLVE_EXPLAIN_TOKENS = 2400
# 解析里出现草稿痕迹就重写；两次仍不干净则放弃该题
_EXPLAIN_ATTEMPTS = 2
# 解析结论与答案不一致时重新求解的上限；两次仍对不上就放弃该题
_SOLVE_ATTEMPTS = 2


def _ask_answer(question: Question, api_key: str | None) -> tuple[str, str] | None:
    """第一步：独立求解，只拿答案。

    与讲解分开调用是刻意的：一次调用里同时输出答案、干扰项和解析时，
    模型容易在解析里算出 A、把 answer 写成 B，三者互相打架且无人校验。
    先锁定唯一答案，再让讲解围绕它展开，一致性才有保证。
    """
    type_label = _TYPE_CN.get(question.type.value, question.type.value)
    prompt = f"【题干】\n{question.stem}\n\n【题型】{type_label}\n"
    if question.type == QuestionType.multiple:
        prompt += "\n本题为多选题：answer 输出正确选项文本组成的数组，例如 [\"选项一\", \"选项二\"]。"
    elif question.type == QuestionType.single:
        prompt += "\n本题为单选题：answer 填正确选项的文本本身，不要填字母。"
    elif question.type == QuestionType.judge:
        prompt += "\n本题为判断题：answer 只填 正确 或 错误。"
    try:
        data = llm.chat_json(
            [
                {"role": "system", "content": SOLVE_ANSWER_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            api_key=api_key,
            max_tokens=_SOLVE_ANSWER_TOKENS,
            thinking=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("独立求解失败：%s", exc)
        return None
    if not isinstance(data, dict):
        return None
    confidence = str(data.get("confidence") or "mid").strip().lower()
    raw = data.get("answer")
    if isinstance(raw, list):
        items = [str(item).strip() for item in raw if str(item).strip()]
        if not items:
            return None
        return _MULTI_SEP.join(items), confidence
    text = str(raw or "").strip()
    if not text:
        return None
    return text, confidence


def _has_draft_trace(analysis: str) -> bool:
    """解析里出现自我怀疑与重算痕迹，说明模型把草稿写进了成品。"""
    return any(trace in analysis for trace in DRAFT_TRACES)


def _ask_explain(
    question: Question, answer_text: str, api_key: str | None
) -> tuple[str, list[str], str] | None:
    """第二步：以已定答案为准写解析，选择题顺带产出干扰项。

    不需要思考模式：答案已经锁死，这一步只做确定性表述与选错项构造。
    返回 (解析, 干扰项, 解析推导出的结论)，结论供上层与答案交叉核对。
    """
    type_label = _TYPE_CN.get(question.type.value, question.type.value)
    prompt = (
        f"【题干】\n{question.stem}\n\n"
        f"【题型】{type_label}\n\n"
        f"【已确定的标准答案】\n{answer_text}\n"
    )
    is_choice = question.type in (QuestionType.single, QuestionType.multiple)
    if is_choice:
        prompt += "\n请输出 analysis、conclusion 与 distractors，distractors 的数量要使选项总数正好 4 个。"
    else:
        prompt += "\n请只输出 analysis 与 conclusion。"
    explanation = ""
    distractors: list[str] = []
    conclusion = ""
    for _attempt in range(_EXPLAIN_ATTEMPTS):
        try:
            data = llm.chat_json(
                [
                    {"role": "system", "content": SOLVE_EXPLAIN_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                api_key=api_key,
                max_tokens=_SOLVE_EXPLAIN_TOKENS,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("讲解生成失败：%s", exc)
            return None
        if not isinstance(data, dict):
            continue
        analysis = _polish_analysis(str(data.get("analysis") or ""))
        if not analysis:
            continue
        if _has_draft_trace(analysis):
            logger.info("解析含草稿痕迹，重写一次")
            prompt += "\n上次解析里出现了自我怀疑或重算的表述，请只写确定结论。"
            continue
        explanation = analysis
        conclusion = str(data.get("conclusion") or "").strip()
        # 干扰项也要走同一套净化：只清洗正确答案会让选项里一半带 $ 一半裸奔
        distractors = [
            _clean_option_text(str(item))
            for item in (data.get("distractors") or [])
            if str(item).strip()
        ]
        return explanation, distractors, conclusion
    return None


def _answers_agree(conclusion: str, answer_text: str) -> bool:
    """判断解析结论与给定答案是否指向同一结果。

    纯数值必须完全相同：不然 5 与 25 会因包含关系被判成一致，
    第 22 题那种「解析算 5、答案填 17」的错就漏过去了。
    """
    def normalize(text: str) -> str:
        stripped = re.sub(r"\$|\\left|\\right|\\[,;!]|\s+", "", text or "")
        stripped = stripped.replace("{", "").replace("}", "").replace("\\", "")
        return stripped.strip().lower()

    left, right = normalize(conclusion), normalize(answer_text)
    if not left or not right:
        return True  # 没有结论就不拦，避免因模型漏填而误杀
    if left == right:
        return True
    numeric = re.compile(r"-?\d+(?:\.\d+)?")
    if numeric.fullmatch(left) and numeric.fullmatch(right):
        return False
    return left in right or right in left


def _clean_option_text(text: str) -> str:
    """去掉模型偶尔带上的 A. B. 前缀，选项文本只保留内容本身。"""
    cleaned = re.sub(r"^[A-Ha-h][.、．:：）)]\s*", "", text.strip())
    return latex_utils.fix_delimiters(cleaned)


def _prepare_answer(question: Question, answer_raw: str) -> tuple[list[str], str] | None:
    """把求解原文收敛成本平台的答案格式，返回 (正确项文本, 展示用答案文本)。"""
    if question.type == QuestionType.multiple:
        corrects = [
            _clean_option_text(part) for part in answer_raw.split(_MULTI_SEP) if part.strip()
        ]
        corrects = [item for item in corrects if item]
        if not 2 <= len(corrects) <= 3:
            return None
        return corrects, "；".join(corrects)
    if question.type == QuestionType.single:
        correct = _clean_option_text(answer_raw)
        if not correct:
            return None
        return [correct], correct
    if question.type == QuestionType.judge:
        positive = any(word in answer_raw for word in ("正确", "对", "成立", "√", "是"))
        negative = any(word in answer_raw for word in ("错误", "错", "不成立", "×", "否"))
        if positive == negative:
            return None
        return [], "正确" if positive else "错误"
    text = latex_utils.fix_delimiters(_normalize_math(answer_raw))
    if not text:
        return None
    return [], text


def _solve_one(question: Question, api_key: str | None) -> bool:
    """独立解题（思考模式）+ 依答案写解析 + 结论交叉校验。

    先锁定唯一答案，再让解析与干扰项围绕该答案生成。解析完成后比对
    conclusion 与答案：模型第一步算错、解析里又算对的情况（例如行列式题
    答案是 17 而解析推导出 5）在这里被拦下，重新求解一轮；仍不一致就放弃该题，
    宁可少给一道，不让选项与解析互相矛盾的题进题库。
    """
    is_choice = question.type in (QuestionType.single, QuestionType.multiple)
    for attempt in range(_SOLVE_ATTEMPTS):
        solved = _ask_answer(question, api_key)
        if solved is None:
            return False
        answer_raw, confidence = solved
        prepared = _prepare_answer(question, answer_raw)
        if prepared is None:
            continue
        corrects, answer_text = prepared

        explained = _ask_explain(question, answer_text, api_key)
        if explained is None:
            return False
        analysis, distractors, conclusion = explained

        if not _answers_agree(conclusion, answer_text):
            logger.warning(
                "解析结论与答案不一致（第 %d 次）：答案=%r 结论=%r，重新求解",
                attempt + 1, answer_text, conclusion,
            )
            continue

        if is_choice:
            if question.type == QuestionType.single:
                if len(distractors) != 3 or corrects[0] in distractors:
                    return False
            else:
                if not 1 <= len(distractors) <= 2 or len(corrects) + len(distractors) != 4:
                    return False
                if any(item in distractors for item in corrects):
                    return False
            options, letters = _assign_options(corrects, distractors)
            question.options = options
            question.answer = letters
        elif question.type == QuestionType.judge:
            question.answer = "A" if answer_text == "正确" else "B"
        else:
            question.answer = answer_text

        question.analysis = analysis
        if confidence == "low":
            note = str((question.selfCheck or {}).get("note", ""))
            question.selfCheck = {
                **(question.selfCheck or {}),
                "note": (note + "；" if note else "") + "独立解题置信度低，题目可能存在歧义",
            }
        return True
    return False


def _solve_all(questions: list[Question], api_key: str | None, stats: ReviewStats) -> None:
    if not questions:
        return

    def run(q: Question) -> tuple[Question, bool]:
        try:
            ok = _solve_one(q, api_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("解析生成失败：%s", exc)
            ok = False
        if not ok:
            # 修补阶段可能留下命题模型自填的答案、解析与选项，未经独立求解一律作废：
            # 带着未验证的答案入库，正是「选项与解析对不上」的来源。
            q.answer = ""
            q.analysis = ""
            if q.type in (QuestionType.single, QuestionType.multiple):
                q.options = []
        return q, ok

    with ThreadPoolExecutor(max_workers=_THINK_WORKERS, thread_name_prefix="review-solve") as pool:
        for question, ok in pool.map(run, questions):
            if ok:
                stats.solved += 1


def review_questions(
    db: Session,
    user_id: str,
    questions: list[Question],
    params: GenerateParams,
    doc_name: str,
    api_key: str | None,
    hyde_text: str | None = None,
    progress=None,
) -> tuple[list[Question], ReviewStats]:
    """中间件主流程，返回通过校验的题目与统计。

    progress(percent, stage) 用于向出题任务写阶段进度；不传则静默执行。
    """
    stats = ReviewStats()
    if not questions:
        return [], stats

    def report(percent: int, stage: str) -> None:
        if progress:
            progress(percent, stage)

    target = params.difficulty
    scope = params.scope or ""
    corpus = load_corpus(db, user_id, params.kb_id)
    groups: dict[QuestionType, list[Question]] = {}
    for question in questions:
        groups.setdefault(question.type, []).append(question)

    total = len(questions)
    done = 0
    final: list[Question] = []
    requested = {tc.type: tc.count for tc in params.types}
    ordered_types = list(requested) + [t for t in groups if t not in requested]

    for qtype in ordered_types:
        items = groups.get(qtype)
        if not items:
            continue
        target_count = requested.get(qtype, len(items))

        report(78, f"正在排查重复题目（{done + 1}/{total}）")
        kept, dropped = _drop_duplicates(items, corpus)
        stats.duplicates += len(dropped)

        report(82, f"正在盲评题目难度（{done + 1}/{total}）")
        accepted: list[Question] = []
        rejected: list[tuple[Question, dict]] = []
        with ThreadPoolExecutor(max_workers=_THINK_WORKERS, thread_name_prefix="review-eval") as pool:
            reviewed = list(pool.map(lambda q: (q, evaluate(q, target, scope, api_key)), kept))
        for question, review in reviewed:
            _apply_review(question, review)
            if review.get("unknown"):
                # 评审不可用时放行，避免整批出题失败
                accepted.append(question)
            elif review["passed"]:
                accepted.append(question)
            else:
                rejected.append((question, review))

        # 第一轮：按缺陷码做最小修补，不整题重写
        need = target_count - len(accepted)
        if rejected and need > 0:
            report(86, f"难度不符，正在按缺陷修补（{len(rejected)} 题）")
            batch = rejected[:need]
            with ThreadPoolExecutor(max_workers=_THINK_WORKERS, thread_name_prefix="review-fix") as pool:
                fixed = list(pool.map(lambda item: _repair(item[0], item[1], target, api_key), batch))
            still: list[tuple[Question, dict]] = []
            with ThreadPoolExecutor(max_workers=_THINK_WORKERS, thread_name_prefix="review-reeval") as pool:
                reeval = list(pool.map(
                    lambda q: (q, evaluate(q, target, scope, api_key, judges=1)) if q else (None, None),
                    fixed,
                ))
            for question, review in reeval:
                if question is None or review is None:
                    continue
                _apply_review(question, review)
                stats.repaired += 1
                if review.get("unknown") or review["passed"]:
                    accepted.append(question)
                else:
                    still.append((question, review))
            rejected = still + rejected[len(batch):]

        # 换模板重出：轮数由配置控制，默认一轮；再不够就按距离目标档最近的补齐，
        # 避免同一批题反复重出把等待时间拖长
        rounds = max(1, min(2, settings.review_max_regen_rounds))
        for attempt in range(rounds):
            need = target_count - len(accepted)
            if need <= 0:
                break
            report(90, f"修补未通过，换模板重出（{need} 题，第 {attempt + 1} 次）")
            avoid = corpus + [q.stem for q in accepted]
            directive = (
                f"- 这是第 {attempt + 1} 次重出：不要沿用之前的解法路径与结构。"
                f"按目标档重设蓝图：{TIER_PARAMS[target]}。"
            )
            if rejected and rejected[0][1].get("suggestion"):
                directive += f"\n- 评审建议：{rejected[0][1]['suggestion']}"
            try:
                fresh = _regen(params, qtype, need, doc_name, avoid, api_key, hyde_text, directive)
            except Exception as exc:  # noqa: BLE001
                logger.warning("换模板重出失败（%s）：%s", qtype.value, exc)
                break
            fresh, dup = _drop_duplicates(fresh, avoid)
            stats.duplicates += len(dup)
            stats.regenerated += len(fresh)
            if not fresh:
                # 整批被判重，换一轮再来
                continue
            with ThreadPoolExecutor(max_workers=_THINK_WORKERS, thread_name_prefix="review-reeval2") as pool:
                reviewed_fresh = list(pool.map(
                    lambda q: (q, evaluate(q, target, scope, api_key)), fresh
                ))
            for question, review in reviewed_fresh:
                _apply_review(question, review)
                if review.get("unknown") or review["passed"]:
                    accepted.append(question)
                else:
                    rejected.append((question, review))

        # 两轮仍未达标：按距离目标档中心最近的补齐，保证题目数量
        need = target_count - len(accepted)
        if need > 0 and rejected:
            rejected.sort(key=lambda item: _delta(item[0].difficultyScore or 0.0, target))
            accepted.extend(question for question, _review in rejected[:need])

        done += len(items)
        final.extend(accepted[:target_count])

    report(96, f"正在生成解析（共 {len(final)} 题）")
    _solve_all(final, api_key, stats)
    # 解题失败的题目没有答案与解析，不能入库（宁可少给不出半成品）
    unsolved = [q for q in final if q.type in _NEED_ANSWER_TYPES and not q.answer]
    if unsolved:
        logger.warning("解题失败剔除 %d 题（无答案与解析）", len(unsolved))
        dropped_set = {id(q) for q in unsolved}
        final = [q for q in final if id(q) not in dropped_set]

    order = {t: i for i, t in enumerate(ordered_types)}
    final.sort(key=lambda q: order.get(q.type, 99))
    report(98, "题目校验完成")
    return final, stats
