"""出题服务：混合检索参考片段 + DeepSeek JSON 输出 + Pydantic 校验。

- original 模式下先统计材料中该题型的原题数量，不足时抛 NeedConfirmError 询问用户
- existing_stems 用于跨请求全局去重：prompt 约束 + 生成后按归一化题干过滤
- progress_cb 用于向调用方上报真实生成进度（百分比 + 阶段文案）
- api_key 为当前用户的 DeepSeek 密钥；retrieve_fn 可注入检索实现（测试用）
"""
import re
import uuid
from typing import Callable

from app.config import settings
from app.schemas.question import Difficulty, GenerateParams, Question, QuestionType
from app.services.rag import retrieval, vectorstore
from app.services.rag.llm import chat_json
from app.services.rag.prompts import QUESTION_SYSTEM, QUESTION_USER_TEMPLATE

ProgressCB = Callable[[int, str], None]
RetrieveFn = Callable[[str], list[dict]]

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


def count_available_originals(bank_id: str, doc_id: str, qtype: QuestionType) -> int | None:
    """统计材料中该题型的原题数量；材料没有题号结构时返回 None（跳过检查）。"""
    chunks = vectorstore.count_question_chunks(bank_id, doc_id)
    if not chunks:
        return None
    matched = [c for c in chunks if c["section"] and _section_matches(c["section"], qtype)]
    if not matched:
        # 有题号结构但没找到该题型的大题标题
        return 0
    return len(matched)


def _norm_stem(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _build_context(hits: list[dict]) -> str:
    parts = []
    for i, h in enumerate(hits, 1):
        label = h.get("section") or h.get("chunk_type") or ""
        prefix = f" · {label}" if label else ""
        parts.append(f"[片段{i}{prefix}]\n{h['text']}")
    return "\n\n".join(parts)


def _gen_for_type(
    tc,
    params: GenerateParams,
    doc_name: str,
    scope: str | None,
    avoid_norm: set[str],
    mixed_difficulty: bool,
    api_key: str | None,
    hyde_text: str | None,
    retrieve_fn: RetrieveFn | None = None,
    report: Callable[[float, str], None] | None = None,
) -> list[Question]:
    """生成单个题型的题目。report(frac, stage) 上报该 agent 的内部完成度（0~1）与阶段文案。"""
    type_label = TYPE_LABELS[tc.type]

    # original 模式：先确认材料原题数量是否足够
    if params.source_mode == "original":
        available = count_available_originals(params.kb_id, params.doc_id, tc.type)
        if available is not None and available < tc.count:
            raise NeedConfirmError(type_label, available, tc.count)

    # 检索 query：文档主题 + 题型 + 可选知识点范围，参考片段数量随题数放大
    query_parts = [doc_name.rsplit(".", 1)[0]]
    if scope:
        query_parts.append(scope)
    query_parts.append(type_label)
    if report:
        report(0.02, f"正在检索「{type_label}」相关材料")
    retrieve = retrieve_fn or (
        lambda q: retrieval.retrieve_for_generation(params.kb_id, q, params.doc_id or None, hyde_text)
    )
    hits = retrieve(" ".join(query_parts))
    if report:
        report(0.12, f"「{type_label}」检索完成，AI 生成中")
    if not hits:
        raise ValueError(f"知识库中没有可参考的内容，请先上传文档（检索「{type_label}」无结果）")

    # 模型偶发不守题型或与已有题重复，最多重试 3 轮并逐轮收紧约束
    for attempt in range(3):
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
        data = chat_json(
            [
                {"role": "system", "content": QUESTION_SYSTEM},
                {
                    "role": "user",
                    "content": user_prompt
                    + f"\n\n【重要】本次生成的每一道题 type 字段必须严格为 {tc.type.value}（{type_label}），不得混入其他题型。",
                },
            ],
            api_key=api_key,
        )
        if report:
            report(0.82, f"「{type_label}」AI 已返回，正在校验格式")
        raw = data.get("questions", data if isinstance(data, list) else [])
        questions: list[Question] = []
        for item in raw:
            try:
                q = Question.model_validate(item)
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
            if tc.type == QuestionType.judge and not q.options:
                from app.schemas.question import OptionItem

                q.options = [OptionItem(label="A", text="正确"), OptionItem(label="B", text="错误")]
                q.answer = "A" if q.answer in ("正确", "对", "T", "true", "√") else "B"
            questions.append(q)
            avoid_norm.add(norm)
        if len(questions) >= tc.count:
            if report:
                report(1.0, f"「{type_label}」已完成（{tc.count} 题）")
            return questions[: tc.count]
        if report:
            report(0.35 + 0.15 * attempt, f"「{type_label}」第 {attempt + 1} 轮不达标，正在重试")
    raise ValueError(f"{type_label}生成数量或去重后不达标（要求 {tc.count} 道），请重试")


def generate_questions(
    params: GenerateParams,
    doc_name: str,
    scope: str | None = None,
    mixed_difficulty: bool = False,
    existing_stems: list[str] | None = None,
    progress_cb: ProgressCB | None = None,
    api_key: str | None = None,
    hyde_text: str | None = None,
    retrieve_fn: RetrieveFn | None = None,
) -> list[Question]:
    """按题型并行出题：每个题型一个独立 agent（线程），全部完成后汇总呈现。

    - 进度 = 各 agent 内部完成度（0~1）按题数加权的均值，映射到 5~95%
    - 去重集合每个 agent 独立副本：不同题型的题干天然不同，无需共享可变状态
    - 任一 agent 失败（原题不足 / 检索为空 / 模型超时）整体抛出该异常
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    avoid_base = {_norm_stem(s) for s in (existing_stems or []) if s}
    weights = [max(1, tc.count) for tc in params.types]
    total_weight = sum(weights)
    fracs = [0.0] * len(params.types)
    stages = ["准备中"] * len(params.types)
    lock = threading.Lock()

    def make_report(idx: int) -> Callable[[float, str], None]:
        def report(frac: float, stage: str) -> None:
            with lock:
                fracs[idx] = max(fracs[idx], min(1.0, max(0.0, frac)))
                stages[idx] = stage
                if progress_cb:
                    weighted = sum(w * f for w, f in zip(weights, fracs)) / total_weight
                    overall = 5 + int(90 * weighted)
                    bottleneck = min(range(len(fracs)), key=lambda i: fracs[i])
                    progress_cb(min(overall, 95), stages[bottleneck])

        return report

    def run_one(idx: int, tc) -> None:
        fresh = _gen_for_type(
            tc,
            params,
            doc_name,
            scope,
            set(avoid_base),
            mixed_difficulty,
            api_key,
            hyde_text,
            retrieve_fn=retrieve_fn,
            report=make_report(idx),
        )
        results[idx] = fresh

    results: list[list[Question] | None] = [None] * len(params.types)
    workers = max(1, min(len(params.types), 6))
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="qgen-agent") as pool:
            futures = [pool.submit(run_one, idx, tc) for idx, tc in enumerate(params.types)]
            for future in futures:
                future.result()
    else:
        run_one(0, params.types[0])

    out: list[Question] = []
    for fresh in results:
        if fresh:
            out.extend(fresh)
    if progress_cb:
        progress_cb(96, f"正在校验题目格式与去重（共 {len(out)}/{sum(weights)} 题）")
    return out
