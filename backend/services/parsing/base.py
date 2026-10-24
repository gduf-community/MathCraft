"""文档解析抽象层。

统一产出 ParsedBlock 列表（文本 + 元信息），上游切片与入库只面对这一层。
新增格式时实现 Parser 协议并在 get_parser 中注册即可。

OCR 接口：扫描版 PDF 走 OCREngine 协议，当前为占位实现，
后续接入 PaddleOCR / MinerU 时替换 ocr_engine 默认实例即可。
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


@dataclass
class ParsedBlock:
    """解析后的最小文本单元（一页、一个段落组或一个表格行）。"""

    text: str
    meta: dict = field(default_factory=dict)


class OCREngine(Protocol):
    """OCR 引擎协议。输入 PDF 路径，返回逐页文本。"""

    def recognize(self, pdf_path: Path) -> list[str]: ...


class OCRNotConfigured(OCREngine):
    """占位实现：明确报错，提示接入真实 OCR 引擎。"""

    def recognize(self, pdf_path: Path) -> list[str]:
        raise NotImplementedError(
            "该 PDF 疑似扫描版（无可提取文本层）。OCR 引擎尚未接入，"
            "请实现 app/services/parsing/base.py 中的 OCREngine 协议"
            "（推荐 PaddleOCR 或 MinerU），并在 ocr_engine 中替换。"
        )


# 全局 OCR 引擎实例，接入真实引擎时替换这一行
ocr_engine: OCREngine = OCRNotConfigured()


class Parser(Protocol):
    def parse(self, file_path: Path) -> list[ParsedBlock]: ...


PARSERS: dict[str, str] = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".xlsx": "excel",
    ".xls": "excel",
    ".md": "markdown",
    ".markdown": "markdown",
}


def get_parser(file_path: Path) -> Parser:
    """按扩展名返回对应解析器；.xls 老格式由 openpyxl 不支持，提示转换。"""
    suffix = file_path.suffix.lower()
    if suffix == ".xls":
        raise ValueError("暂不支持老版 .xls，请另存为 .xlsx 后上传")
    if suffix not in PARSERS:
        raise ValueError(f"不支持的文件格式：{suffix}，目前支持 {sorted(set(PARSERS))}")
    if suffix == ".pdf":
        from services.parsing import pdf as pdf_parser

        return pdf_parser.PdfParser(ocr_engine=ocr_engine)
    if suffix == ".docx":
        from services.parsing import docx as docx_parser

        return docx_parser.DocxParser()
    if suffix in (".xlsx",):
        from services.parsing import excel as excel_parser

        return excel_parser.ExcelParser()
    from services.parsing import markdown as md_parser

    return md_parser.MarkdownParser()
