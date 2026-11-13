"""出题服务：混合检索参考片段 + DeepSeek 流式 JSON + Pydantic 强校验。

- 提示词注入 Schema 与 Few-Shot，输出要求放在 <questions> XML 标签内（近因效应）
- 流式生成、滚动解析：每个完整题目对象立即做 Pydantic 校验，有错立刻阻断
- 校验失败先用 JSON Repair 抢救，再带错误信息重试一次
- original 模式下先统计材料中该题型的原题数量，不足时抛 NeedConfirmError 询问用户
- existing_stems 用于跨请求全局去重：prompt 约束 + 生成后按归一化题干过滤
- progress_cb 用于向调用方上报真实生成进度（百分比 + 阶段文案）
- api_key 为当前用户的 DeepSeek 密钥；retrieve_fn 可注入检索实现（测试用）
- 解题在评审链路的最后一步独立进行（question_review._solve_all），命题侧不产答案
"""
import json
import re
import uuid
from typing import Callable

import json_repair
from pydantic import ValidationError

from app.schemas.question import GenerateParams, Question, QuestionType
from app.services.rag import retrieval, vectorstore
from app.services.rag import llm
from app.services.rag.prompts import QUESTION_SYSTEM, QUESTION_USER_TEMPLATE

ProgressCB = Callable[[int, str], None]
RetrieveFn = Callable[[str], list[dict]]

# 单次模型调用只出 1 道题：十道题一次生成在慢通道上会拖到十分钟以上，
# 拆成单题并发后单次响应可控，也不会因输出被截断而少给题
GEN_BATCH_SIZE = 1
# 并发出题数
GEN_BATCH_WORKERS = 6
# 单题的输出预算（token），含蓝图、评分点与自检。地狱难度带蓝图与自检实测 1100~2200，
# 给到 3000 才不会被 finish_reason=length 截成半截 JSON
GEN_TOKENS_PER_QUESTION = 3000
# 单批固定的 JSON 结构开销
GEN_TOKENS_OVERHEAD = 400

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


class QuestionOutputError(Exception):
    """生成输出不符合 Schema；summary 供重试回喂，raw_excerpt 供日志与排查。"""

    def __init__(self, summary: str, raw_excerpt: str = ""):
        self.summary = summary
        self.raw_excerpt = raw_excerpt
        super().__init__(summary)


_WRAPPER_TAG = re.compile(r"</?\s*questions\s*>")
_CODE_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")
_JSON_DECODER = json.JSONDecoder()


def strip_output_wrapper(text: str) -> str:
    """剥掉 <questions> XML 包裹与 markdown 代码栅栏，只留 JSON 文本。"""
    text = (text or "").strip()
    text = _WRAPPER_TAG.sub("", text)
    text = _CODE_FENCE.sub("", text)
    return text.strip()


def _schema_validate(obj: dict) -> Question:
    """Pydantic 强校验；失败抛出带字段级摘要的 QuestionOutputError。"""
    try:
        return Question.model_validate(obj)
    except ValidationError as exc:
        parts = []
        for err in exc.errors()[:4]:
            loc = ".".join(str(p) for p in err["loc"]) or "root"
            parts.append(f"{loc} {err['msg']}")
        raise QuestionOutputError("；".join(parts)) from exc


class _RollingParser:
    """滚动解析 {"questions": [...]}：流式接收，完整对象逐个提取并立即校验。"""

    def __init__(self) -> None:
        self._buf = ""
        self._pos = 0
        self._array_start: int | None = None
        self._closed = False
        self._extracted = 0

    def feed(self, text: str) -> None:
        self._buf += text

    def extract(self, validate) -> list[Question]:
        """提取新完成的题目对象；校验失败立刻抛出，阻断后续内容。"""
        out: list[Question] = []
        if self._closed:
            return out
        if self._array_start is None:
            match = re.search(r'"questions"\s*:\s*\[', self._buf)
            if not match:
                return out
            self._array_start = match.end()
            self._pos = self._array_start
        while not self._closed:
            while self._pos < len(self._buf) and self._buf[self._pos] in " \t\r\n,":
                self._pos += 1
            if self._pos >= len(self._buf):
                break
            if self._buf[self._pos] == "]":
                self._closed = True
                self._pos += 1
                break
            if self._buf[self._pos] != "{":
                break  # 数组结构异常，交给 finish 的 JSON Repair
            try:
                obj, end = _JSON_DECODER.raw_decode(self._buf, self._pos)
            except json.JSONDecodeError:
                break  # 对象尚未接收完整，等待下一个增量
            self._pos = end
            out.append(validate(obj))
            self._extracted += 1
        return out

    def finish(self, validate) -> list[Question]:
        """流结束后的兜底：剩余未提取内容用 JSON Repair 抢救，抢救出的题同样强校验。"""
        if self._closed:
            return []
        if self._array_start is None:
            data = json_repair.loads(strip_output_wrapper(self._buf))
            items = data.get("questions") if isinstance(data, dict) else data
            out = []
            for item in items or []:
                if isinstance(item, dict):
                    out.append(validate(item))
            self._closed = True
            return out
        seg = self._buf[self._array_start:]
        last = seg.rfind("}")
        if last < 0:
            self._closed = True
            return []
        try:
            fixed = json_repair.loads("[" + seg[: last + 1] + "]")
        except Exception:  # noqa: BLE001
            self._closed = True
            return []
        out = []
        for item in fixed[self._extracted:]:
            if isinstance(item, dict):
                out.append(validate(item))
        self._closed = True
        return out


def _stream_questions(messages: list[dict], budget: int, api_key: str | None) -> list[Question]:
    """流式生成 + 滚动解析：每个完整对象立即校验，有错立刻阻断当前批次。"""
    parser = _RollingParser()
    raw: list[str] = []
    collected: list[Question] = []
    try:
        for delta in llm.chat_stream(messages, api_key=api_key, max_tokens=budget, thinking_off=True):
            raw.append(delta)
            parser.feed(delta)
            collected.extend(parser.extract(_schema_validate))
        collected.extend(parser.finish(_schema_validate))
    except QuestionOutputError as exc:
        exc.raw_excerpt = "".join(raw)[-1500:]
        raise
    if not collected:
        raise QuestionOutputError("未解析出任何题目对象", "".join(raw)[-1500:])
    return collected


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


def _split_counts(total: int, size: int) -> list[int]:
    """把总题数拆成不超过 size 的小批。"""
    out: list[int] = []
    left = total
    while left > 0:
        take = min(size, left)
        out.append(take)
        left -= take
    return out


def _gen_batch(
    tc,
    params: GenerateParams,
    doc_name: str,
    scope: str | None,
    count: int,
    avoid_snapshot: list[str],
    mixed_difficulty: bool,
    api_key: str | None,
    hits: list[dict],
    directive: str,
    hint: str = "",
) -> list[Question]:
    """一次生成 count 道题：流式输出 + 滚动校验，Schema 失败带错误信息重试一次。"""
    type_label = TYPE_LABELS[tc.type]
    extra = f"- 知识点范围：{scope}" if scope else ""
    if hint:
        extra += (
            f"\n- 本题限定考点：{hint}。同一批的其他题已占用别的考点，"
            "不要写成同一类题，也不要只换数字"
        )
    if count >= 5:
        extra += (
            "\n- 数量较多，各题必须覆盖不同的细分考点与题干结构，"
            "禁止同一模板换数字，避免被查重判为重复"
        )
    if mixed_difficulty:
        extra += "\n- 难度分布：约三分之一达到高难度，其余为中等难度"
    if directive:
        extra += "\n" + directive
    if avoid_snapshot:
        extra += (
            "\n- 以下题目已经出过，新题不得与它们重复（考点组合与题干结构都要避开）：\n"
            + "\n".join(f"  {i}. {s[:100]}" for i, s in enumerate(avoid_snapshot, 1))
        )
    user_prompt = QUESTION_USER_TEMPLATE.format(
        context=_build_context(hits),
        type_label=type_label,
        count=count,
        difficulty=params.difficulty.value,
        source_mode=SOURCE_LABELS.get(params.source_mode, params.source_mode),
        score=DEFAULT_SCORES.get(tc.type, 5),
        extra=extra,
    )
    base_messages = [
        {"role": "system", "content": QUESTION_SYSTEM},
        {
            "role": "user",
            "content": user_prompt
            + f"\n\n【重要】本次生成的每一道题 type 字段必须严格为 {tc.type.value}（{type_label}），不得混入其他题型。"
            + f"\n本次请恰好生成 {count} 道。",
        },
    ]
    budget = GEN_TOKENS_OVERHEAD + GEN_TOKENS_PER_QUESTION * count

    last_error: QuestionOutputError | None = None
    last_raw = ""
    questions: list[Question] = []
    for attempt in range(2):
        msgs = base_messages
        if attempt and last_error is not None:
            msgs = base_messages + [
                {"role": "assistant", "content": last_raw[:1200]},
                {"role": "user", "content": (
                    f"上面的输出不符合 Schema：{last_error.summary}。"
                    "请逐字段修正后重新输出，把完整 JSON 放在 <questions></questions> 之间，"
                    "字段名与类型严格与 Schema 一致，公式只用 $...$ 与 $$...$$ 定界。"
                )},
            ]
        try:
            questions = _stream_questions(msgs, budget, api_key)
            break
        except QuestionOutputError as exc:
            last_error = exc
            last_raw = exc.raw_excerpt
            questions = []

    out: list[Question] = []
    for q in questions:
        if q.type != tc.type:
            continue  # 题型不符直接丢弃
        q.id = f"q-{uuid.uuid4().hex[:10]}"
        q.score = DEFAULT_SCORES.get(tc.type, 5)
        q.difficulty = params.difficulty
        q.docName = doc_name
        if tc.type == QuestionType.judge and not q.options:
            from app.schemas.question import OptionItem

            q.options = [OptionItem(label="A", text="正确"), OptionItem(label="B", text="错误")]
            q.answer = "A" if q.answer in ("正确", "对", "T", "true", "√") else "B"
        out.append(q)
    if out:
        return out
    summary = last_error.summary if last_error else f"输出中不含任何 {type_label} 对象"
    raise ValueError(
        f"{type_label}生成输出不符合 Schema（{summary}），已带错误重试仍未通过"
    )


PLAN_PROMPT = """你是高等数学命题组长。根据下面的教学材料与知识点范围，列出 {count} 个互不相同的细分考点，
用于命制 {count} 道{difficulty}难度的{type_label}。
要求：每个考点聚焦不同的概念、方法或题型结构，彼此不重叠，合起来尽量覆盖该范围的不同侧面。

知识点范围：{scope}

教学材料（节选）：
{context}

只输出 JSON：{{"points": ["考点或命题角度", "..."]}}，数组长度恰好 {count}。"""


def _plan_points(
    scope: str | None,
    type_label: str,
    difficulty: str,
    count: int,
    hits: list[dict],
    api_key: str | None,
) -> list[str]:
    """先规划 count 个互不重复的考点。

    单题并发时各批互相看不见，模型极易撞到同一个考点（分段函数连续性），
    撞车后被查重砍掉再重出反而更慢，先分摊考点比事后去重便宜得多。
    """
    if count < 2:
        return []
    context = _build_context(hits)[:1500]
    prompt = PLAN_PROMPT.format(
        count=count, difficulty=difficulty, type_label=type_label,
        scope=scope or "未限定", context=context,
    )
    try:
        data = llm.chat_json(
            [{"role": "user", "content": prompt}],
            api_key=api_key,
            max_tokens=800,
            thinking_off=True,
        )
    except Exception:  # noqa: BLE001
        return []  # 规划失败就按原来的并行出题，不阻断
    points = [str(p).strip() for p in (data.get("points") or []) if str(p).strip()]
    return points[:count]


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
    directive: str = "",
) -> list[Question]:
    """生成单个题型的题目。report(frac, stage) 上报该 agent 的内部完成度（0~1）与阶段文案。

    单次模型调用只生成 GEN_BATCH_SIZE 道，多批并发。一次要十道题的输出量会超过模型
    单次响应能力，慢通道下能拖十分钟以上，因此必须拆批。
    """
    from concurrent.futures import ThreadPoolExecutor

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
    if not hits:
        raise ValueError(f"知识库中没有可参考的内容，请先上传文档（检索「{type_label}」无结果）")

    # 先分摊考点，再并发命题：十道题各自撞同一个考点是去重与重出的主要来源
    if report:
        report(0.06, f"正在规划「{type_label}」的考点分布")
    points = _plan_points(scope, type_label, params.difficulty.value, tc.count, hits, api_key)

    collected: list[Question] = []
    taken = set(avoid_norm)
    errors: list[Exception] = []
    # 生成不足时最多补两轮，每轮按剩余数量重新拆批
    for round_no in range(3):
        need = tc.count - len(collected)
        if need <= 0:
            break
        batch_sizes = _split_counts(need, GEN_BATCH_SIZE)
        if report:
            report(
                max(0.12, len(collected) / tc.count),
                f"「{type_label}」AI 生成中（{len(collected)}/{tc.count} 题）"
                + ("，正在补齐" if round_no else ""),
            )
        snapshot = list(taken)[-12:]
        with ThreadPoolExecutor(max_workers=min(len(batch_sizes), GEN_BATCH_WORKERS),
                                thread_name_prefix="qgen-batch") as pool:
            futures = [
                pool.submit(
                    _gen_batch, tc, params, doc_name, scope, size, snapshot,
                    mixed_difficulty, api_key, hits, directive,
                    # 按已完成题数取考点，补齐轮次接着往后排，避免重复同一考点
                    points[len(collected) + index] if len(collected) + index < len(points) else "",
                )
                for index, size in enumerate(batch_sizes)
            ]
            for future in futures:
                # 单批失败（截断、限流）只丢这一批，剩余数量由下一轮补齐
                try:
                    batch = future.result()
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)
                    continue
                for q in batch:
                    norm = _norm_stem(q.stem)
                    if norm in taken:
                        continue  # 跨批或与历史题目重复，丢弃
                    taken.add(norm)
                    collected.append(q)
                    if report:
                        report(
                            min(0.95, max(0.12, len(collected) / tc.count)),
                            f"「{type_label}」AI 生成中（{len(collected)}/{tc.count} 题）",
                        )

    if len(collected) >= tc.count:
        if report:
            report(1.0, f"「{type_label}」已完成（{tc.count} 题）")
        return collected[: tc.count]
    if not collected and errors:
        raise errors[0]  # 一道都没出：把超时、限流、密钥失效的真实原因带出去
    raise ValueError(
        f"{type_label}生成数量或去重后不达标（要求 {tc.count} 道，实得 {len(collected)} 道），请重试"
    )


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
    directive: str = "",
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
            directive=directive,
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
