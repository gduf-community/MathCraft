"""纯文本解析：按空行分段；超长段落再按行拆开，避免产生超过切片长度的块。"""
from pathlib import Path

from app.services.parsing.base import ParsedBlock

MAX_PARA_CHARS = 1000


class TxtParser:
    def parse(self, file_path: Path) -> list[ParsedBlock]:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        blocks: list[ParsedBlock] = []
        for para in text.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            if len(para) <= MAX_PARA_CHARS:
                blocks.append(ParsedBlock(text=para, meta={"source": file_path.name}))
            else:
                for line in para.splitlines():
                    line = line.strip()
                    if line:
                        blocks.append(ParsedBlock(text=line, meta={"source": file_path.name}))
        return blocks
