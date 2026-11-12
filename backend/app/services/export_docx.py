"""题目集合导出为 Word 文档：按题型分组，题号全卷连续，公式转 OMML。

- 分组只保留题型名称与题目序号，不含难度、分值等信息
- 答案与解析可选，位置支持每题下方或文末集中
- 排版规则：全文宋体；仅大标题加粗；题型标题四号加粗；正文小四不加粗
- LaTeX 公式经 MathML 转 OMML 内嵌；拆段前先把跨行展示公式压平成单行，
  避免 $$...$$ 被换行切碎后降级成原文；转换失败降级为原样文本
"""
import io
import re
import urllib.parse

import latex2mathml.converter
import mathml2omml
from docx import Document
from docx.document import Document as DocumentType
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.styles.style import ParagraphStyle

from app.schemas.question import Question

MATH_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
WORD_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SONG = "宋体"
BODY_PT = 12    # 小四
HEADING_PT = 14 # 四号
TITLE_PT = 16   # 大标题三号
_CN_NUMS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十"]

TYPE_CN = {"single": "选择题", "multiple": "多选题", "judge": "判断题",
           "blank": "填空题", "compute": "计算题", "essay": "简答题"}

_MATH_TOKEN = re.compile(r"\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$")
_DISPLAY_BLOCK = re.compile(r"\$\$\s*([\s\S]+?)\s*\$\$")


def flatten_display_math(text: str) -> str:
    """把跨行的 $$...$$ 压成单行：公式内部换行替换为空格，保持定界符成对。

    解析文本常见「$$\\n公式多行排布\\n$$」的写法；按换行拆段前必须先压平，
    否则拆段后每行只剩半个定界符，公式会整体降级成原文。
    """
    def _flatten(match: re.Match) -> str:
        inner = re.sub(r"\s*\n\s*", " ", match.group(1)).strip()
        return f"$${inner}$$"
    return _DISPLAY_BLOCK.sub(_flatten, text)


def _latex_to_omml(latex: str):
    """LaTeX → MathML → OMML；任一步失败返回 None，由调用方降级为文本。"""
    try:
        mathml = latex2mathml.converter.convert(latex)
        omml = mathml2omml.convert(mathml)
        if not omml or "oMath" not in omml:
            return None
        inner = omml.strip()
        if inner.startswith("<m:oMath>") and "xmlns:m" not in inner:
            inner = inner.replace("<m:oMath>", f'<m:oMath xmlns:m="{MATH_NS}">', 1)
        return parse_xml(inner)
    except Exception:  # noqa: BLE001  个别复杂环境不支持时直接给文本
        return None


def _styled_run(paragraph, text: str, size_pt: int, bold: bool):
    """写入宋体 run；同时设置 eastAsia 字体，保证中文不是默认 Calibri。"""
    run = paragraph.add_run(text)
    run.font.name = SONG
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), SONG)
    return run


def _append_with_math(paragraph, text: str, size_pt: int = BODY_PT, bold: bool = False) -> None:
    """把混合文本写进段落；公式段插入 OMML，失败时保留原始定界文本。"""
    pos = 0
    for match in _MATH_TOKEN.finditer(text):
        if match.start() > pos:
            _styled_run(paragraph, text[pos: match.start()], size_pt, bold)
        display = match.group(1) is not None
        latex = (match.group(1) if display else match.group(2) or "").strip()
        omml = _latex_to_omml(latex)
        if omml is None:
            _styled_run(paragraph, f"$${latex}$$" if display else f"${latex}$", size_pt, bold)
        else:
            paragraph._p.append(omml)
        pos = match.end()
    if pos < len(text):
        _styled_run(paragraph, text[pos:], size_pt, bold)


def _add_body_text(doc: DocumentType, text: str, indent_first: str = "",
                   size_pt: int = BODY_PT, bold: bool = False) -> None:
    """按换行拆段写入；首段可带前缀（题号、答案标记）。调用前先压平跨行公式。"""
    lines = (text or "").split("\n")
    for index, line in enumerate(lines):
        paragraph = doc.add_paragraph()
        if index == 0 and indent_first:
            _styled_run(paragraph, indent_first, size_pt, bold)
        if line.strip():
            _append_with_math(paragraph, line, size_pt, bold)


def _add_section_title(doc: DocumentType, text: str) -> None:
    """题型标题与文末节标题：四号加粗。"""
    paragraph = doc.add_paragraph()
    _styled_run(paragraph, text, HEADING_PT, True)
    paragraph.paragraph_format.space_before = 8
    paragraph.paragraph_format.space_after = 4


def build_export_docx(
    title: str,
    type_order: list[str],
    questions: list[Question],
    include_answer: bool,
    include_analysis: bool,
    placement: str,
) -> bytes:
    """生成 Word 字节流。questions 为已通过 Pydantic 校验的 Question 对象列表。"""
    groups: dict[str, list[Question]] = {t: [] for t in type_order}
    for question in questions:
        if question.type.value in groups:
            groups[question.type.value].append(question)
    ordered = [t for t in type_order if groups.get(t)]

    doc = Document()
    # 全文默认宋体小四：显式 run 之外（如空段）也保持一致
    normal = doc.styles["Normal"]
    assert isinstance(normal, ParagraphStyle)
    normal.font.name = SONG
    normal.font.size = Pt(BODY_PT)
    normal.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), SONG)

    heading = doc.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _styled_run(heading, title, TITLE_PT, True)

    answer_lines: list[tuple[int, str]] = []
    analysis_lines: list[tuple[int, str]] = []

    number = 0
    for group_index, qtype in enumerate(ordered, 1):
        _add_section_title(doc, f"{_CN_NUMS[group_index - 1]}、{TYPE_CN.get(qtype, qtype)}")
        for question in groups[qtype]:
            number += 1
            _add_body_text(doc, flatten_display_math(question.stem), indent_first=f"{number}. ")
            for option in question.options:
                _add_body_text(doc, flatten_display_math(f"{option.label}. {option.text}"))
            if placement == "inline":
                if include_answer:
                    _add_body_text(doc, flatten_display_math(question.answer), indent_first="答案：")
                if include_analysis:
                    _add_body_text(doc, flatten_display_math(question.analysis), indent_first="解析：")
            else:
                if include_answer:
                    answer_lines.append((number, question.answer))
                if include_analysis:
                    analysis_lines.append((number, question.analysis))

    if placement == "end":
        if include_answer:
            _add_section_title(doc, "参考答案")
            for no, answer in answer_lines:
                _add_body_text(doc, flatten_display_math(answer), indent_first=f"{no}. ")
        if include_analysis:
            _add_section_title(doc, "解析")
            for no, analysis in analysis_lines:
                _add_body_text(doc, flatten_display_math(analysis), indent_first=f"{no}. ")

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()


def docx_filename(name: str) -> str:
    """Content-Disposition 用的 RFC 5987 文件名。"""
    safe = (name or "试卷").strip() or "试卷"
    return f"attachment; filename*=UTF-8''{urllib.parse.quote(safe + '.docx')}"
