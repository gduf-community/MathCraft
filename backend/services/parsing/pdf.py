"""PDF 解析：PyMuPDF 提取文字层；无可提取文本时走 OCR 引擎。"""
from pathlib import Path

import fitz

from services.parsing.base import OCREngine, ParsedBlock

# 每页平均可提取字符低于该阈值即判定为扫描版
MIN_CHARS_PER_PAGE = 20


class PdfParser:
    def __init__(self, ocr_engine: OCREngine) -> None:
        self.ocr_engine = ocr_engine

    def parse(self, file_path: Path) -> list[ParsedBlock]:
        with fitz.open(file_path) as doc:
            pages = [page.get_text("text").strip() for page in doc]
        total = sum(len(t) for t in pages)
        if pages and total / len(pages) < MIN_CHARS_PER_PAGE:
            # 扫描版：交给 OCR 引擎（当前为占位，会抛出明确异常）
            pages = self.ocr_engine.recognize(file_path)
        return [
            ParsedBlock(text=text, meta={"page": i + 1, "source": file_path.name})
            for i, text in enumerate(pages)
            if text
        ]
