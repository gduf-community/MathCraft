"""扫描件入库的简化层：OCR 全文 → 提取三级目录 → 按节标题定位正文 → 按章概括 → 简化知识点 Markdown。

流程对齐 experiments/toc_pipeline 验证版本：
前部目录页提取三级目录（只展示一二级）→ 三级知识点作为关键词定位标题下方正文 →
按章整合简化概括（保留核心公式、排除题目）→ 组装带目录的简化文档。
LLM 走 DeepSeek（低推理档位省 token）；调用失败按类型区分：服务类错误抛
SimplifyServiceError 由调用方标记失败，内容类错误由调用方决定回退策略。
"""
import json
import logging
import re
import time
from bisect import bisect_right
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, NamedTuple

import openai
from app.services.rag import llm

logger = logging.getLogger("app.simplify")

# 目录提取只读 OCR 文本开头（首片 15 页，含封面、前言与完整目录页）
TOC_HEAD_CHARS = 24000
# 单节正文截取上限（字符）；单章输入合计上限
SECTION_SLICE_LIMIT = 20000
CHAPTER_INPUT_LIMIT = 90000


class SimplifyServiceError(RuntimeError):
    """LLM 服务不可用（余额不足 / 鉴权失败 / 超时等），调用方应标记失败而非静默降级。"""


def _ws_regex(keyword: str) -> re.Pattern:
    """空白不敏感匹配：OCR 结果中标题常被换行、空格打断。"""
    parts = [re.escape(ch) for ch in keyword if not ch.isspace()]
    return re.compile(r"\s*".join(parts))


def clean_ocr_text(md: str) -> str:
    """清洗 MinerU markdown：表格化的公式碎片还原为纯文本，去图片与杂质。"""
    lines = md.splitlines()
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        if lines[i].lstrip().startswith("|"):
            rows: list[str] = []
            while i < n and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    rows.append(" ".join(c for c in cells if c))
                i += 1
            out.extend(rows)
            continue
        out.append(lines[i])
        i += 1
    text = "\n".join(out)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"<html>.*?</html>", "", text, flags=re.S)
    return re.sub(r"\n{3,}", "\n\n", text)


# ---------------- LLM 调用（低推理档位 + 用量统计） ----------------

_ZERO_USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0}


def _add_usage(a: dict, b: dict | None) -> dict:
    b = b or {}
    return {
        "prompt_tokens": a["prompt_tokens"] + (b.get("prompt_tokens") or 0),
        "completion_tokens": a["completion_tokens"] + (b.get("completion_tokens") or 0),
        "reasoning_tokens": a["reasoning_tokens"] + (b.get("reasoning_tokens") or 0),
    }


def _chat_text(messages: list[dict], max_tokens: int = 8192, max_retries: int = 2,
               json_mode: bool = False, *, api_key: str | None = None) -> tuple[str, dict]:
    """DeepSeek 文本调用：低推理档位、显式 max_tokens/超时；返回 (内容, 用量)。"""
    last: Exception | None = None
    usage = dict(_ZERO_USAGE)
    runtime = llm.resolve_llm_runtime(api_key)
    resolved_key = llm.ResolvedApiKey(runtime)
    for attempt in range(max_retries + 1):
        try:
            kwargs: dict = {"model": runtime.model, "messages": messages,
                            "max_tokens": max_tokens, "timeout": 600.0, "stream": False}
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            try:
                resp = llm.get_client(api_key=resolved_key).chat.completions.create(
                    **kwargs, extra_body={"effort": "low"})
            except openai.BadRequestError as exc:
                if "effort" in str(exc):  # 档位参数不受支持时退回默认档位
                    resp = llm.get_client(api_key=resolved_key).chat.completions.create(**kwargs)
                else:
                    raise
            if resp is None or not getattr(resp, "choices", None):
                last = RuntimeError("DeepSeek 返回空响应")
                time.sleep(8 * (attempt + 1))
                continue
            choice = resp.choices[0]
            content = (choice.message.content or "") if choice.message else ""
            if choice.message and getattr(choice.message, "usage", None) is None:
                pass
            if resp.usage:
                usage = _add_usage(usage, {
                    "prompt_tokens": resp.usage.prompt_tokens,
                    "completion_tokens": resp.usage.completion_tokens,
                    "reasoning_tokens": getattr(
                        resp.usage.completion_tokens_details, "reasoning_tokens", 0) or 0,
                })
            if not content.strip():
                last = RuntimeError("DeepSeek 返回空内容")
                time.sleep(8 * (attempt + 1))
                continue
            return content, usage
        except openai.APIStatusError as exc:
            status = exc.status_code
            if status < 500 and status != 429:
                raise SimplifyServiceError(f"DeepSeek 服务拒绝（HTTP {status}）：{exc}") from exc
            last = exc
        except (openai.APIConnectionError, openai.APITimeoutError) as exc:
            last = exc
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(8 * (attempt + 1))
    raise SimplifyServiceError(f"DeepSeek 调用失败：{last}")


def _chat_json(messages: list[dict], max_tokens: int = 16384,
               *, api_key: str | None = None) -> tuple[dict, dict]:
    msgs = list(messages)
    usage = dict(_ZERO_USAGE)
    for _ in range(2):
        content, u = _chat_text(msgs, max_tokens=max_tokens, json_mode=True, api_key=api_key)
        usage = _add_usage(usage, u)
        try:
            return json.loads(content), usage
        except Exception:  # noqa: BLE001
            msgs = msgs + [
                {"role": "assistant", "content": content},
                {"role": "user", "content": "上面的输出无法解析为 JSON，请严格只输出合法 JSON。"},
            ]
    raise RuntimeError("DeepSeek JSON 解析失败")


# ---------------- 提示词 ----------------

_TOC_PROMPT = (
    "下面是一本教材 OCR 识别结果的开头部分，包含封面、前言与目录页，文本可能有识别噪声。\n"
    "任务一：提取完整的三级目录结构（章、节、知识点）。\n"
    "任务二：基于任务一的结果，生成只含章、节两级标题的简化目录。\n"
    "严格只输出 JSON，结构如下：\n"
    '{"chapters": [{"title": "第1章 函数与极限", '
    '"sections": [{"title": "1.1 映射与函数", "points": ["邻域", "区间与数集"]}]}], '
    '"toc_brief": ["第1章 函数与极限", "  1.1 映射与函数"]}\n'
    "要求：\n"
    "1. title 保留原书编号与名称；points 为三级知识点标题，保持原书措辞与顺序。\n"
    "2. 只依据 OCR 文本提取，不要凭记忆补全；目录页若不完整，提取能看到的最大范围。\n"
)


def _clean_heading(text: str) -> str:
    """去掉标题开头误带的星号、列表符号与多余空白。"""
    text = re.sub(r"^[\s*_\-·]+", "", text or "")
    return re.sub(r"^\*+", "", text).strip()


def _normalize_toc(data) -> dict:
    """防御性归一化：LLM 偶尔返回数组或字段缺失的结构，逐层校验避免崩溃。"""
    chapters = data.get("chapters") if isinstance(data, dict) else None
    if not isinstance(chapters, list):
        return {"chapters": []}
    clean: list[dict] = []
    for c in chapters:
        if not isinstance(c, dict):
            continue
        title = _clean_heading(str(c.get("title") or ""))
        secs: list[dict] = []
        for s in c.get("sections") or []:
            if not isinstance(s, dict):
                continue
            raw_points = s.get("points")
            points = [str(p).strip() for p in raw_points
                      if isinstance(p, str) and p.strip()] if isinstance(raw_points, list) else []
            st = _clean_heading(str(s.get("title") or ""))
            if st:
                secs.append({"title": st, "points": points})
        if title and secs:
            clean.append({"title": title, "sections": secs})
    return {"chapters": clean}


def _parse_toc(toc_md: str, *, api_key: str | None = None) -> tuple[dict, dict]:
    """从 OCR 文本开头提取三级目录；多次为空视为提取失败。"""
    # 模板内含 JSON 花括号示例，不能用 str.format 拼接（KeyError 陷阱）
    prompt = _TOC_PROMPT + "\nOCR 文本如下：\n" + toc_md[:TOC_HEAD_CHARS]
    data: dict = {}
    usage = dict(_ZERO_USAGE)
    for _ in range(3):
        data, u = _chat_json([{"role": "user", "content": prompt}], api_key=api_key)
        usage = _add_usage(usage, u)
        data = _normalize_toc(data)
        chapters = data.get("chapters") or []
        if chapters and any(c.get("sections") for c in chapters):
            return data, usage
    return {}, usage


_CHAPTER_PROMPT = (
    "你是数学教材编辑。下面是《高等数学》教材「{chapter}」"
    "经 OCR 识别的正文（可能含识别噪声），仅作为事实依据。\n"
    "请用自己的话分析、总结并概括，写成本章知识点讲解，严格遵守：\n"
    "1. 禁止照抄原文段落；每个知识点用 2～6 句话概括核心思想，语言精炼，不写废话。\n"
    "2. 每个知识点最多保留 2～4 个最核心公式。公式一律 LaTeX：行内用 $...$；"
    "独立公式单独成段，即 $$ 独占一行、公式内容独占一行、$$ 独占一行。\n"
    "3. 排版契约：节标题用 ###，知识点标题用 ####，标题文字与所给目录一致；"
    "禁止输出一、二级标题；禁止使用 markdown 表格；正文与公式块之间空一行。\n"
    "4. 竖线只能出现在数学定界符内部（如绝对值 $|x|$）；"
    "不写书上的公式编号；不引用图片；不用 \\[ \\] \\( \\) 定界符。\n"
    "5. 严格排除题目类内容：例题、习题、练习、测试、解答一律不写，只写定义、定理、方法与公式。\n"
    "6. 若某知识点在正文中没有对应内容，标题下写（本节未检索到原文片段），不要凭记忆编造。\n\n"
    "目录结构：{toc_json}\n\n"
    "正文：\n{chapter_input}"
)


def _norm_title(text: str) -> str:
    """标题归一化：去空白与装饰符号，用于同名标题判重。"""
    return re.sub(r"[\s*_\-·]+", "", text or "")


def sanitize_chapter(md: str) -> str:
    """对章级 LLM 输出做确定性排版修复：定界符、公式块、表格残留、标题层级。"""
    md = re.sub(r"\\\((.+?)\\\)", r"$\1$", md, flags=re.S)
    md = re.sub(r"\\\[(.+?)\\\]", r"$$\1$$", md, flags=re.S)
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)
    md = clean_ocr_text(md)
    lines = md.splitlines()
    out: list[str] = []
    in_math = False
    last_section = ""
    for ln in lines:
        s = ln.strip()
        if s == "$$":
            if in_math:
                out.append("$$")
                out.append("")
                in_math = False
            else:
                if out and out[-1].strip():
                    out.append("")
                out.append("$$")
                in_math = True
            continue
        if in_math:
            if not s:
                continue
            if re.fullmatch(r"\|[\s:|\-]*\|?", s):
                continue
            out.append(ln)
        else:
            m = re.match(r"^(#{1,6})\s*(.*)$", ln)
            if m:
                level, text_h = len(m.group(1)), m.group(2)
                # 清掉模型误带的列表符号、星号与强调标记，统一编号外观
                text_h = re.sub(r"^[\s*_\-·]+", "", text_h).strip()
                text_h = re.sub(r"^\*+", "", text_h).strip()
                if not text_h:
                    continue
                if level < 3:
                    ln = "### " + text_h
                elif level > 4:
                    ln = "#### " + text_h
                else:
                    ln = "#" * level + " " + text_h
                # 知识点标题与上一级节标题重复时丢弃，避免同名两级标题
                if level >= 4 and last_section and _norm_title(text_h) == last_section:
                    continue
                if level == 3:
                    last_section = _norm_title(text_h)
            out.append(ln)
    if in_math:
        out.append("$$")
    md = re.sub(r"\n{3,}", "\n\n", "\n".join(out))
    return md.strip() + "\n"


# ---------------- 按节标题定位正文 ----------------

_MARKDOWN_HEADING = re.compile(r"^\s*#{1,6}\s*")
_MARKDOWN_HEADING_END = re.compile(r"\s+#+$")
_HEADING_DECORATION = re.compile(r"^(?:\\?[*＊_·]+\s*)+")
_TOC_PAGE_LEADER = re.compile(r"[.．·…⋯。]{2,}\s*\d+\s*$")
_PAGE_FOLIO = re.compile(r"[\s\d.．·…⋯。*_=—–－\-]+")
_OCR_LINE = re.compile(r"[^\n]+")


class _TitleSpan(NamedTuple):
    start: int
    end: int
    markdown: bool
    continued: bool = False


def _heading_key(text: str) -> str:
    return re.sub(r"\s+", "", _HEADING_DECORATION.sub("", text.strip()))


def _find_title_spans(
    corpus: str, keys: set[str],
) -> dict[str, list[_TitleSpan]]:
    """索引整行标题及其相邻行续写形式，保留原文范围。"""
    spans: dict[str, list[_TitleSpan]] = {}
    previous_line: tuple[str, int, bool] | None = None
    for line in _OCR_LINE.finditer(corpus):
        text = line[0].strip()
        if not text:
            continue
        heading = _MARKDOWN_HEADING.match(text)
        title = _MARKDOWN_HEADING_END.sub("", text[heading.end():]) if heading else text
        key = _heading_key(title)
        if key in keys:
            spans.setdefault(key, []).append(_TitleSpan(line.start(), line.end(), bool(heading)))
        if key and previous_line:
            previous_key, previous_start, previous_markdown = previous_line
            combined = previous_key + key
            if combined in keys:
                spans.setdefault(combined, []).append(
                    _TitleSpan(previous_start, line.end(), previous_markdown, continued=True),
                )
        previous_line = (key, line.start(), bool(heading)) if key else None
    return spans


def _has_section_body(
    corpus: str, span: _TitleSpan, end: int,
    section_starts: list[int], chapter_starts: set[int],
) -> bool:
    """检查节标题之后是否有页眉和目录页码之外的内容。"""
    following = bisect_right(section_starts, span.start)
    if following < len(section_starts):
        end = min(end, section_starts[following])
    for line in _OCR_LINE.finditer(corpus, span.end, end):
        text = line[0].strip()
        if (text and line.start() not in chapter_starts and not text.startswith("#")
                and not _TOC_PAGE_LEADER.search(text) and not _PAGE_FOLIO.fullmatch(text)):
            return True
    return False


def _find_chapters(
    corpus: str, chapter_keys: list[str], section_keys: list[list[str]],
    spans: dict[str, list[_TitleSpan]], section_starts: list[int], chapter_starts: set[int],
) -> dict[int, _TitleSpan]:
    """用节标题和其后正文确认章首，允许正文证据跨过同章页眉。"""
    candidates = sorted(
        (span, ci) for ci, key in enumerate(chapter_keys) for span in spans.get(key, [])
    )
    later_body_sections: dict[int, set[str]] = {}
    later_continued_sections: dict[int, set[str]] = {}
    body_end = len(corpus)
    found: dict[int, _TitleSpan] = {}
    for index in reversed(range(len(candidates))):
        chapter, ci = candidates[index]
        anchor_end = len(corpus)
        if index + 1 < len(candidates):
            following, following_ci = candidates[index + 1]
            anchor_end = following.start
            if following_ci != ci:
                body_end = anchor_end
        anchored_sections = [
            (key, section)
            for key in section_keys[ci] for section in spans.get(key, [])
            if chapter.end <= section.start < anchor_end
        ]
        supported_sections = {
            key for key, section in anchored_sections
            if _has_section_body(corpus, section, body_end, section_starts, chapter_starts)
        }
        if not supported_sections:
            continue
        if not chapter.continued:
            # 目录通常会重列多节，页眉续接处至多重列正在阅读的一节。
            repeated_sections = (
                {key for key, _ in anchored_sections} & later_body_sections.get(ci, set())
            )
            if supported_sections & later_continued_sections.get(ci, set()):
                continue
            if repeated_sections and (
                (len(repeated_sections) > 1 and anchored_sections[0][0] in repeated_sections)
                or any(
                    _TOC_PAGE_LEADER.search(line[0])
                    for line in _OCR_LINE.finditer(corpus, chapter.end, anchor_end)
                )
            ):
                continue
        found[ci] = chapter
        later_body_sections.setdefault(ci, set()).update(supported_sections)
        if chapter.continued:
            later_continued_sections.setdefault(ci, set()).update(supported_sections)

    # 正文节标题全部丢失时，仍在已确定的相邻章之间寻找章首，供关键词兜底。
    for ci, key in enumerate(chapter_keys):
        if ci in found:
            continue
        start = max((span.end for index, span in found.items() if index < ci), default=0)
        end = min((span.start for index, span in found.items() if index > ci), default=len(corpus))
        matches = [span for span in spans.get(key, []) if start <= span.start < end]
        if matches:
            found[ci] = next((span for span in matches if span.markdown), matches[0])
    return found


def _keyword_fallback(corpus: str, start: int, end: int,
                      points: list[str], cap: int = 30000) -> list[list[int]]:
    """节标题定位失败时，在章范围内用三级知识点关键词开窗兜底。"""
    merged: list[list[int]] = []
    for point in points:
        positions = [m.start() for m in _ws_regex(point).finditer(corpus, start, end)][:2]
        for pos in positions:
            merged.append([max(start, pos - 1000), min(end, pos + 1800)])
    merged.sort()
    fused: list[list[int]] = []
    for a, b in merged:
        if fused and a <= fused[-1][1] + 150:
            fused[-1][1] = max(fused[-1][1], b)
        else:
            fused.append([a, b])
    total = sum(b - a for a, b in fused)
    while total > cap and len(fused) > 1:
        total -= fused[0][1] - fused[0][0]
        fused.pop(0)
    return fused


def _attach_section_slices(toc: dict, corpus: str) -> None:
    """按节标题定位正文：每节内容 = 标题位置到下一个节/章标题之间（有截取上限）。"""
    chapters = toc.get("chapters") or []
    chapter_keys = [_heading_key(chapter["title"]) for chapter in chapters]
    section_keys = [
        [_heading_key(section["title"]) for section in chapter["sections"]]
        for chapter in chapters
    ]
    all_sections = {key for keys in section_keys for key in keys}
    spans = _find_title_spans(corpus, set(chapter_keys) | all_sections)
    section_starts = sorted({span.start for key in all_sections for span in spans.get(key, [])})
    chapter_starts = {span.start for key in chapter_keys for span in spans.get(key, [])}
    chapter_spans = _find_chapters(
        corpus, chapter_keys, section_keys, spans, section_starts, chapter_starts,
    )
    ordered_chapters = sorted((span, ci) for ci, span in chapter_spans.items())

    for chapter in chapters:
        for section in chapter["sections"]:
            section["_slice"] = None

    for index, (chapter_span, ci) in enumerate(ordered_chapters):
        end = (ordered_chapters[index + 1][0].start
               if index + 1 < len(ordered_chapters) else len(corpus))
        sections = chapters[ci]["sections"]
        located: list[tuple[int, _TitleSpan]] = []
        start = chapter_span.end
        for si, key in enumerate(section_keys[ci]):
            matches = [span for span in spans.get(key, []) if start <= span.start < end]
            if matches:
                span = next(
                    (match for match in matches
                     if _has_section_body(corpus, match, end, section_starts, chapter_starts)),
                    matches[0],
                )
                located.append((si, span))
                start = span.end
            else:
                fused = _keyword_fallback(
                    corpus, chapter_span.end, end, sections[si].get("points") or [],
                )
                sections[si]["_slice"] = fused[0] if fused else None

        for index_in_chapter, (si, span) in enumerate(located):
            next_index = index_in_chapter + 1
            section_end = located[next_index][1].start if next_index < len(located) else end
            if _has_section_body(corpus, span, section_end, section_starts, chapter_starts):
                sections[si]["_slice"] = [
                    span.start, min(section_end, span.start + SECTION_SLICE_LIMIT),
                ]

    # 单章输入合计上限：超限时按节等比例截断
    for chapter in chapters:
        sections = chapter.get("sections") or []
        sized = [(si, s["_slice"]) for si, s in enumerate(sections) if s.get("_slice")]
        total = sum(b - a for _si, (a, b) in sized)
        if total > CHAPTER_INPUT_LIMIT:
            scale = CHAPTER_INPUT_LIMIT / total
            for si, (a, b) in sized:
                keep = max(2000, int((b - a) * scale))
                sections[si]["_slice"] = [a, min(b, a + keep)]


# ---------------- 按章概括 ----------------

# 单次调用的输入上限与节数上限：分批生成，避免输出被 max_tokens 截断而漏掉后半章
SECTION_BATCH = 4
BATCH_INPUT_LIMIT = 64000
# 并发概括的批次数：DeepSeek 侧限流由 _chat_text 的退避重试兜底
LLM_CONCURRENCY = 4


def _plan_batches(chapter: dict) -> list[list[dict]]:
    """把一章的节按输入长度与节数切成若干批，保证每节都被写到。"""
    batches: list[list[dict]] = []
    current: list[dict] = []
    used = 0
    for section in chapter.get("sections") or []:
        sl = section.get("_slice")
        length = (sl[1] - sl[0]) if sl else 800
        if current and (len(current) >= SECTION_BATCH or used + length > BATCH_INPUT_LIMIT):
            batches.append(current)
            current, used = [], 0
        current.append(section)
        used += length
    if current:
        batches.append(current)
    return batches


def _summarize_batch(chapter: dict, sections: list[dict], corpus: str,
                     *, api_key: str | None = None) -> tuple[str, dict]:
    """概括一章中的若干节，输出仅含 ### 节标题与 #### 知识点。"""
    blocks = []
    for section in sections:
        sl = section.get("_slice")
        if not sl:
            blocks.append(f"## 节：{section['title']}（本节未定位到正文）")
        else:
            blocks.append(f"## 节：{section['title']}\n\n{corpus[sl[0]:sl[1]]}")
    batch_input = "\n\n".join(blocks) or "（未检索到正文片段）"
    toc_json = json.dumps(
        {"title": chapter["title"],
         "sections": [{"title": s["title"], "points": s.get("points") or []} for s in sections]},
        ensure_ascii=False)
    prompt = _CHAPTER_PROMPT.format(
        chapter=chapter["title"], toc_json=toc_json, chapter_input=batch_input)
    prompt += ("\n\n注意：本次只写目录中列出的这几节，节标题逐个用 ### 输出，"
               "不要遗漏任何一节，也不要补写其他节。")
    md, usage = _chat_text(
        [{"role": "user", "content": prompt}], max_tokens=8192, api_key=api_key,
    )
    return sanitize_chapter(md), usage


def _similar(a: str, b: str) -> bool:
    """标题相似判定：容忍模型漏字或改写，公共前缀足够长即视为同一节。"""
    if not a or not b:
        return False
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n >= 6


def _assemble_chapter(chapter: dict, batch_mds: list[str]) -> str:
    """拼接各批结果，统一节标题用词，并补齐模型漏掉的节。"""
    parts = [re.sub(r"^(#{3,4}\s+)[*_\-·\s]+", r"\1", md, flags=re.M) for md in batch_mds]
    seen = [m.group(1).strip() for md in parts for m in re.finditer(r"^###\s+(.+)$", md, flags=re.M)]
    for section in chapter.get("sections") or []:
        title = _clean_heading(section.get("title") or "")
        if not title:
            continue
        target = _norm_title(title)
        hit = next((h for h in seen if _norm_title(h) == target), None)
        if hit is None:
            hit = next((h for h in seen if _similar(_norm_title(h), target)), None)
        if hit is not None:
            if hit != title:
                # 正文标题改成目录用词，保证目录与正文逐字一致
                pattern = r"^###\s+" + re.escape(hit) + r"\s*$"
                parts = [re.sub(pattern, lambda _m: "### " + title, md, flags=re.M) for md in parts]
                seen = [title if h == hit else h for h in seen]
            continue
        parts.append(f"### {title}\n\n（本节内容未能生成，请重新解析后查看）")
        seen.append(title)
    return "\n\n".join(p for p in parts if p.strip())


def json_dumps_chapter(chapter: dict) -> str:
    return json.dumps(
        {"title": chapter["title"],
         "sections": [{"title": s["title"], "points": s.get("points") or []}
                      for s in chapter.get("sections") or []]},
        ensure_ascii=False)


def build_simplified_markdown(ocr_markdown: str, source_name: str = "教材",
                              on_progress: Callable[[int, int], None] | None = None,
                              *, api_key: str | None = None) -> tuple[str, dict]:
    """完整简化流程：清洗 → 提目录 → 按节定位 → 按章概括 → 组装。

    返回 (简化文档 Markdown, LLM 用量统计)。目录提取失败或 LLM 服务不可用时抛异常，
    由调用方决定失败或回退策略。on_progress(已完成章数, 总章数) 用于汇报概括进度。
    api_key 为本次操作者的有效凭据，显式传入并发子任务；为空时沿用服务端默认。
    """
    corpus = "\n" + clean_ocr_text(ocr_markdown)
    toc, usage = _parse_toc(corpus[:TOC_HEAD_CHARS], api_key=api_key)
    chapters = toc.get("chapters") or []
    if not chapters:
        raise RuntimeError("目录解析失败：无法定位章节结构")

    _attach_section_slices(toc, corpus)

    # 按批并发概括：每批 4 节，结果按章序拼装，兼顾速度与不截断
    tasks: list[tuple[int, int, dict, list[dict]]] = []
    chapter_totals = [0] * len(chapters)
    for ci, chapter in enumerate(chapters):
        for bi, batch in enumerate(_plan_batches(chapter)):
            tasks.append((ci, bi, chapter, batch))
            chapter_totals[ci] += 1

    chapter_mds: dict[int, list[tuple[int, str]]] = {i: [] for i in range(len(chapters))}
    chapter_done = [0] * len(chapters)
    done_chapters = 0
    with ThreadPoolExecutor(max_workers=LLM_CONCURRENCY) as pool:
        futures = {pool.submit(_summarize_batch, ch, batch, corpus, api_key=api_key): (ci, bi)
                   for ci, bi, ch, batch in tasks}
        for fut in as_completed(futures):
            ci, bi = futures[fut]
            md, u = fut.result()
            chapter_mds[ci].append((bi, md))
            usage = _add_usage(usage, u)
            chapter_done[ci] += 1
            if chapter_done[ci] == chapter_totals[ci]:
                done_chapters += 1
                if on_progress is not None:
                    on_progress(done_chapters, len(chapters))

    # 模型偶发漏写的节：单独重试一次，仍失败才留占位说明
    for ci, chapter in enumerate(chapters):
        written = {_norm_title(m.group(1))
                   for _bi, md in chapter_mds[ci]
                   for m in re.finditer(r"^###\s+(.+)$", md, flags=re.M)}
        for section in chapter.get("sections") or []:
            title = (section.get("title") or "").strip()
            if not title or _norm_title(title) in written:
                continue
            try:
                md, u = _summarize_batch(chapter, [section], corpus, api_key=api_key)
                chapter_mds[ci].append((10**6, md))
                usage = _add_usage(usage, u)
                written.add(_norm_title(title))
                logger.info("补写小节「%s」", title)
            except Exception as exc:  # noqa: BLE001
                logger.warning("补写小节「%s」失败：%s", title, exc)

    chapter_docs = []
    for ci, chapter in enumerate(chapters):
        batch_mds = [md for _bi, md in sorted(chapter_mds[ci], key=lambda x: x[0])]
        chapter_docs.append(f"## {chapter['title']}\n\n{_assemble_chapter(chapter, batch_mds)}")

    lines = [f"# 《{Path(source_name).stem}》知识点简化版", "",
             "> 由 MinerU OCR 与 DeepSeek 自动分析概括生成。"
             "目录仅含一、二级标题，三级知识点作为正文小节，"
             "内容为概括性讲解，保留核心公式，不含例题与习题。", "", "## 目录", ""]
    for c in chapters:
        title = (c.get("title") or "").strip().lstrip("*- ").strip()
        lines.append(f"- **{title}**")
        for s in c.get("sections") or []:
            st = (s.get("title") or "").strip().lstrip("*- ").strip()
            lines.append(f"  - {st}")
    lines.append("")
    lines.append("---")
    for doc in chapter_docs:
        lines.append(doc)
    return "\n".join(lines) + "\n", usage
