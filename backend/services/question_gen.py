"""出题服务：检索参考片段 + DeepSeek JSON 输出 + Pydantic 校验。

- original 模式下先统计材料中该题型的原题数量，不足时抛 NeedConfirmError 询问用户
- existing_stems 用于跨请求全局去重：prompt 约束 + 生成后按归一化题干过滤
"""
import re
import uuid

from schemas.question import Difficulty, GenerateParams, Question, QuestionType
from services import retrieval
from services.llm import chat_json
from services.prompts import QUESTION_SYSTEM, QUESTION_USER_TEMPLATE
from MathCraft.services.rag.evidence import KnowledgeError
from schemas.question import QuestionSource
from MathCraft.services.llm.config import get_llm_config
from MathCraft.services.llm.context_window import resolve_effective_context_window

TYPE_LABELS: dict[QuestionType, str] = {
    QuestionType.single: "选择题",
    QuestionType.multiple: "多选题",
    QuestionType.judge: "判断题",
    QuestionType.blank: "填空题",
    QuestionType.compute: "计算题",
    QuestionType.essay: "简答题",
}

SOURCE_LABELS = {
    "original": "original（尽量还原材料原题，可微调表述）",
    "variant_data": "variant_data（保留原题结构，替换数值与函数）",
    "variant_context": "variant_context（保留考点，更换实际背景）",
    "new": "new（仅参考材料考点，命制全新题目）",
}

DEFAULT_SCORES: dict[QuestionType, int] = {
    QuestionType.single: 5,
    QuestionType.multiple: 8,
    QuestionType.judge: 3,
    QuestionType.blank: 4,
    QuestionType.compute: 12,
    QuestionType.essay: 10,
}


class NeedConfirmError(Exception):
    """original 模式下材料原题数量不足，需要用户确认。"""

    def __init__(self, type_label: str, available: int, requested: int):
        self.type_label = type_label
        self.available = available
        self.requested = requested
        super().__init__(f"{type_label}原题仅 {available} 道，不足 {requested} 道")


def _section_matches(section: str, qtype: QuestionType) -> bool:
    s = section or ""
    if qtype == QuestionType.single:
        return "单项选择" in s or "单选" in s or ("选择题" in s and "多项" not in s)
    if qtype == QuestionType.multiple:
        return "多项选择" in s or "多选" in s
    if qtype == QuestionType.judge:
        return "判断" in s
    if qtype == QuestionType.blank:
        return "填空" in s
    if qtype == QuestionType.compute:
        return "计算" in s or "证明" in s
    if qtype == QuestionType.essay:
        return "简答" in s or "论述" in s or "解答" in s
    return False


def count_available_originals(kb_id: str, doc_id: str, qtype: QuestionType) -> int | None:
    """完整原题结构和数量未确认；未知不能被当作足够。"""
    _ = (kb_id, doc_id, qtype)
    return None


def _norm_stem(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _build_context(hits: list[dict]) -> str:
    parts = []
    for i, h in enumerate(hits, 1):
        parts.append(f"[证据 {h['evidence_id']} · {h['doc_name']}]\n{h['text']}")
    return "\n\n".join(parts)


async def _gen_for_type(
    tc,
    params: GenerateParams,
    doc_name: str,
    scope: str | None,
    avoid_norm: set[str],
    mixed_difficulty: bool,
    index_version: str,
) -> list[Question]:
    type_label = TYPE_LABELS[tc.type]

    # original 模式：先确认材料原题数量是否足够
    if params.source_mode == "original":
        available = count_available_originals(params.kb_id, params.doc_id, tc.type)
        if available is None:
            raise KnowledgeError("exercise_analysis_unavailable", "原题结构和可用数量尚未确认，不能生成后冒充教材原题。请改选变式或考点参考。")
        if available is not None and available < tc.count:
            raise NeedConfirmError(type_label, available, tc.count)

    # 检索 query：文档主题 + 题型 + 可选知识点范围，参考片段数量随题数放大
    query_parts = [doc_name.rsplit(".", 1)[0]]
    if scope:
        query_parts.append(scope)
    query_parts.append(type_label)
    hits = await retrieval.retrieve(
        params.kb_id,
        query=" ".join(query_parts),
        top_k=max(8, tc.count * 2),
        doc_id=params.doc_id,
        index_version=index_version,
    )
    if not hits:
        raise KnowledgeError("no_match", f"选定文档内没有可参考内容（检索「{type_label}」无结果），未扩大搜索范围。")

    trusted = {hit["evidence_id"]: hit for hit in hits}

    # 模型偶发不守题型或与已有题重复，最多重试 3 轮并逐轮收紧约束
    for _ in range(3):
        extra = f"- 知识点范围：{scope}" if scope else ""
        if mixed_difficulty:
            extra += "\n- 难度分布：约三分之一达到高难度，其余为中等难度"
        if avoid_norm:
            extra += (
                "\n- 以下题目已经出过，新题不得与它们重复（考点组合与题干结构都要避开）：\n"
                + "\n".join(f"  {i}. {s[:100]}" for i, s in enumerate(list(avoid_norm)[-12:], 1))
            )
        user_prompt = QUESTION_USER_TEMPLATE.format(
            context=_build_context(hits),
            type_label=type_label,
            count=tc.count,
            difficulty=params.difficulty.value,
            source_mode=SOURCE_LABELS.get(params.source_mode, params.source_mode),
            score=DEFAULT_SCORES.get(tc.type, 5),
            extra=extra,
        )
        config = get_llm_config()
        window = resolve_effective_context_window(model=config.model, context_window=config.context_window)
        # UTF-8 bytes are a conservative upper bound for the BPE-style token
        # budgets used here; avoid a tokenizer that might download data in tests.
        budget = max(0, window - config.max_tokens - 1024)
        while len((QUESTION_SYSTEM + user_prompt).encode("utf-8")) + 256 > budget:
            if len(hits) <= 1:
                raise KnowledgeError("evidence_budget_exceeded", "完整原文和生成要求超过当前模型上下文预算，请缩小资料范围。")
            hits.pop()
            hits[0]["warnings"].append("模型预算限制减少了完整证据单元数量，未截断入选原文。")
            trusted = {hit["evidence_id"]: hit for hit in hits}
            user_prompt = QUESTION_USER_TEMPLATE.format(
                context=_build_context(hits), type_label=type_label, count=tc.count,
                difficulty=params.difficulty.value, source_mode=SOURCE_LABELS[params.source_mode],
                score=DEFAULT_SCORES.get(tc.type, 5), extra=extra,
            )
        data = await chat_json(
            [
                {"role": "system", "content": QUESTION_SYSTEM},
                {
                    "role": "user",
                    "content": user_prompt
                    + f"\n\n【重要】本次生成的每一道题 type 字段必须严格为 {tc.type.value}（{type_label}），不得混入其他题型。",
                },
            ]
        )
        raw = data if isinstance(data, list) else data.get("questions", [])
        questions: list[Question] = []
        for item in raw:
            ids = item.get("evidence_ids") if isinstance(item, dict) else None
            if (not isinstance(ids, list) or not ids or any(not isinstance(i, str) or i not in trusted for i in ids)):
                raise KnowledgeError("invalid_evidence_reference", "模型返回未知、缺失或越界的证据编号，题目未保存。")
            if item.get("sources") or item.get("relation"):
                raise KnowledgeError("invalid_evidence_reference", "模型只能声明证据编号，不能自行提供来源定位或原题关系。")
            try:
                q = Question.model_validate({k: v for k, v in item.items() if k not in {"sources", "review_status"}})
            except Exception:
                continue
            if q.type != tc.type:
                continue  # 题型不符直接丢弃
            norm = _norm_stem(q.stem)
            if norm in avoid_norm:
                continue  # 与已有题目重复，丢弃
            q.id = f"q-{uuid.uuid4().hex[:10]}"
            q.score = DEFAULT_SCORES.get(tc.type, 5)
            q.difficulty = params.difficulty
            q.docName = doc_name
            relation = "concept_reference" if params.source_mode == "new" else "variant_reference"
            q.sources = [QuestionSource.model_validate({**trusted[i], "relation": relation}) for i in dict.fromkeys(ids)]
            q.review_status = "unreviewed"
            if tc.type == QuestionType.judge and not q.options:
                from schemas.question import OptionItem

                q.options = [OptionItem(label="A", text="正确"), OptionItem(label="B", text="错误")]
                q.answer = "A" if q.answer in ("正确", "对", "T", "true", "√") else "B"
            questions.append(q)
            avoid_norm.add(norm)
        if len(questions) >= tc.count:
            return questions[: tc.count]
    raise ValueError(f"{type_label}生成数量或去重后不达标（要求 {tc.count} 道），请重试")


async def generate_questions(
    params: GenerateParams,
    doc_name: str,
    scope: str | None = None,
    mixed_difficulty: bool = False,
    existing_stems: list[str] | None = None,
    index_version: str | None = None,
) -> list[Question]:
    if index_version is None:
        from services.knowledge import check_document
        index_version = (await check_document(params.kb_id, params.doc_id))["index_version"]
    avoid_norm = {_norm_stem(s) for s in (existing_stems or []) if s}
    out: list[Question] = []
    for tc in params.types:
        fresh = await _gen_for_type(tc, params, doc_name, scope, avoid_norm, mixed_difficulty, index_version)
        out.extend(fresh)
    from services.questions import QuestionStore
    QuestionStore().save_generated(out)
    return out
