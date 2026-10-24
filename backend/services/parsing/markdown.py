"""Markdown 解析：按标题层级切块，标题作为上下文前缀保留。"""
import re
from pathlib import Path

from services.parsing.base import ParsedBlock

HEADING = re.compile(r"^(#{1,6})\s+(.+)$")


class MarkdownParser:
    def parse(self, file_path: Path) -> list[ParsedBlock]:
        text = file_path.read_text(encoding="utf-8", errors="ignore")
        blocks: list[ParsedBlock] = []
        current_headings: list[str] = []
        buffer: list[str] = []

        def flush():
            content = "\n".join(buffer).strip()
            if content:
                blocks.append(
                    ParsedBlock(text=content, meta={"section": " > ".join(current_headings), "source": file_path.name})
                )
            buffer.clear()

        for line in text.splitlines():
            m = HEADING.match(line.strip())
            if m:
                flush()
                level = len(m.group(1))
                title = m.group(2).strip()
                current_headings = current_headings[: level - 1] + [title]
            else:
                buffer.append(line)
        flush()
        return blocks
