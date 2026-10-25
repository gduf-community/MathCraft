from __future__ import annotations

import io
from pathlib import Path

import pytest


def _write_scanned_pdf(path: Path) -> Path:
    import pymupdf
    from PIL import Image

    document = pymupdf.open()
    page = document.new_page()
    image = Image.new("RGB", (32, 32), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    page.insert_image(page.rect, stream=buffer.getvalue())
    document.save(str(path))
    document.close()
    return path


class _CloudMinerUProbe:
    name = "mineru"
    needs_local_models = False

    def __init__(self, calls: list[object]) -> None:
        self.calls = calls

    def resolve_config(self):
        from math_q_agent.services.parsing.engines.mineru.config import MinerUConfig

        return MinerUConfig(mode="cloud", api_token="test-token", is_ocr=False)

    def supported_formats(self):
        return frozenset({".pdf"})

    def signature(self, config):
        from math_q_agent.services.parsing.signature import ParserSignature

        return ParserSignature.build(
            "mineru", "test", {"mode": config.mode, "is_ocr": config.is_ocr}
        )

    def is_ready(self, _config):
        from math_q_agent.services.parsing.base import ReadinessReport

        return ReadinessReport(ready=True)

    def parse(self, source_path, workdir, *, config, on_output=None):
        self.calls.append(config)
        Path(workdir, f"{Path(source_path).stem}.md").write_text(
            "OCR text from MinerU cloud", encoding="utf-8"
        )


def test_scanned_pdf_requires_mineru_cloud_ocr(client, tmp_path):
    from math_q_agent.services.parsing.service import ParseService
    from math_q_agent.services.parsing.types import ParserError

    scanned_pdf = _write_scanned_pdf(tmp_path / "scanned.pdf")

    with pytest.raises(ParserError, match="MinerU 云端 OCR.*无法启动 OCR 模式"):
        ParseService(cache_root=tmp_path / "cache").parse(scanned_pdf)


def test_scanned_pdf_forces_cloud_mineru_ocr(client, tmp_path, monkeypatch):
    import math_q_agent.services.parsing.service as parsing_service

    calls: list[object] = []
    parser_names: list[str] = []
    probe = _CloudMinerUProbe(calls)

    def get_parser(name):
        parser_names.append(name)
        return probe

    monkeypatch.setattr(parsing_service, "get_parser", get_parser)

    scanned_pdf = _write_scanned_pdf(tmp_path / "scanned.pdf")
    parsed = parsing_service.ParseService(cache_root=tmp_path / "cache").parse(scanned_pdf)

    assert parsed.engine == "mineru"
    assert parsed.markdown == "OCR text from MinerU cloud"
    assert len(calls) == 1
    assert parser_names == ["mineru"]
    assert calls[0].mode == "cloud"
    assert calls[0].is_ocr is True


def test_loader_preserves_scanned_pdf_cloud_error(client, tmp_path):
    from math_q_agent.services.parsing.types import ParserError
    from math_q_agent.services.rag.pipelines.llamaindex.document_loader import (
        LlamaIndexDocumentLoader,
    )

    class FailingParseService:
        def parse(self, *_args, **_kwargs):
            raise ParserError(
                "扫描型 PDF 未配置 MinerU 云端 OCR",
                code="scanned_pdf_mineru_cloud_not_configured",
            )

    loader = LlamaIndexDocumentLoader()
    with pytest.raises(ParserError, match="未配置 MinerU 云端 OCR"):
        loader._parse_document(tmp_path / "scanned.pdf", FailingParseService())
