from dataclasses import replace
import io
import json
from pathlib import Path

import pytest

from MathCraft.services.parsing.base import ReadinessReport
from MathCraft.services.parsing.engines.mineru.config import MinerUConfig
from MathCraft.services.parsing.service import ParseService
from MathCraft.services.parsing.signature import ParserSignature
from MathCraft.services.parsing.types import ParserError


def pdf(path, *, scanned=False, mixed=False):
    import pymupdf
    from PIL import Image

    doc = pymupdf.open()
    image = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(image, format="PNG")
    for index in range(3 if mixed else 1):
        page = doc.new_page()
        if scanned and (not mixed or index == 1):
            page.insert_image(page.rect, stream=image.getvalue())
            if mixed:
                page.insert_text((40, 25), "Chapter heading only")
        else:
            page.insert_text(
                (60, 160), "Other document: complete ordinary body text and final condition."
            )
    doc.save(path)
    doc.close()
    return path


class Probe:
    name = "mineru"
    config = MinerUConfig(mode="cloud", api_token="fake-test-only")

    def __init__(self, text="Complete reference text.", blocks=None):
        self.text, self.blocks, self.calls = text, blocks, 0

    def resolve_config(self):
        return self.config

    def supported_formats(self):
        return frozenset({".pdf", ".txt", ".md"})

    def signature(self, config):
        return ParserSignature.build(self.name, "controlled", {"ocr": config.is_ocr})

    def is_ready(self, config):
        if not config.api_keys:
            raise AssertionError("缓存命中不应检查外发凭据")
        return ReadinessReport(ready=True)

    def parse(self, source, workdir, *, config, on_output=None):
        self.calls += 1
        Path(workdir, "full.md").write_text(self.text, encoding="utf-8")
        if self.blocks is not None:
            Path(workdir, "full_content_list.json").write_text(
                json.dumps(self.blocks), encoding="utf-8"
            )


def test_compatible_cache_can_be_read_without_cloud_token(tmp_path, monkeypatch):
    import MathCraft.services.parsing.service as service

    probe = Probe(blocks=[{"type": "text", "text": "complete", "page_idx": 0}])
    monkeypatch.setattr(service, "get_parser", lambda _: probe)
    source = pdf(tmp_path / "scan.pdf", scanned=True)
    parsed = ParseService(tmp_path / "cache").parse(source)
    probe.config = replace(probe.config, api_token="")
    cached = ParseService(tmp_path / "cache").parse(source)
    assert cached.markdown == parsed.markdown
    assert cached.quality["status"] == "passed"
    assert probe.calls == 1


def test_unrelated_mixed_document_checks_all_pages(tmp_path, monkeypatch):
    import MathCraft.services.parsing.service as service

    probe = Probe(blocks=[{"type": "text", "text": f"page {i}", "page_idx": i} for i in range(3)])
    monkeypatch.setattr(service, "get_parser", lambda _: probe)
    result = ParseService(tmp_path / "cache").parse(
        pdf(tmp_path / "unrelated.pdf", scanned=True, mixed=True)
    )
    assert result.engine == "mineru"
    assert result.quality["page_count"] == 3
    assert [page["page_index"] for page in result.quality["pages"]] == [0, 1, 2]
    assert result.quality["pages"][1]["needs_ocr"] is True
    assert result.quality["pages"][0]["needs_ocr"] is False


@pytest.mark.parametrize(
    "text,blocks,reason",
    [
        ("a\ufffdb", [{"page_idx": 0}], "replacement_character"),
        ("formula-not-decoded", [{"page_idx": 0}], "unresolved_formula"),
        ("![missing](images/x.png)", [{"page_idx": 0}], "image_missing"),
        ("body", [{"page_idx": 5}], "invalid_page"),
    ],
)
def test_invalid_output_never_gets_a_completed_cache(tmp_path, monkeypatch, text, blocks, reason):
    import MathCraft.services.parsing.service as service

    probe = Probe(text, blocks)
    monkeypatch.setattr(service, "get_parser", lambda _: probe)
    cache = tmp_path / "cache"
    with pytest.raises(ParserError) as error:
        ParseService(cache).parse(pdf(tmp_path / "source.pdf", scanned=True))
    assert error.value.code == "parse_quality_failed"
    assert not list(cache.rglob("manifest.json"))
    reports = [json.loads(p.read_text(encoding="utf-8")) for p in cache.rglob("quality.json")]
    assert any(reason in [issue["code"] for issue in report["issues"]] for report in reports)


def test_cached_assets_are_checked_again(tmp_path, monkeypatch):
    import MathCraft.services.parsing.service as service

    probe = Probe(blocks=[{"page_idx": 0, "text": "body"}])
    monkeypatch.setattr(service, "get_parser", lambda _: probe)
    source = pdf(tmp_path / "scan.pdf", scanned=True)
    parsed = ParseService(tmp_path / "cache").parse(source)
    (parsed.workdir / "full.md").write_text("![figure](images/removed.png)", encoding="utf-8")
    probe.config = replace(probe.config, api_token="")
    with pytest.raises(ParserError) as error:
        ParseService(tmp_path / "cache").parse(source)
    assert error.value.code == "parse_quality_failed"
    assert probe.calls == 1
    from MathCraft.services.parsing import cache

    assert cache.is_ready(parsed.workdir) is False


def test_legacy_cache_is_revalidated_without_changing_original_artifacts(tmp_path, monkeypatch):
    import MathCraft.services.parsing.service as service
    from MathCraft.services.parsing import cache

    probe = Probe()
    probe.config = replace(probe.config, api_token="")
    monkeypatch.setattr(service, "get_parser", lambda _: probe)
    source = pdf(tmp_path / "scan.pdf", scanned=True)
    legacy_sig = probe.signature(replace(probe.config, is_ocr=True)).legacy_hash()
    old = cache.reserve(tmp_path / "cache", cache.source_hash_from_path(source), legacy_sig)
    (old / "full.md").write_text("Legacy source body", encoding="utf-8")
    (old / "full_content_list.json").write_text(
        '[{"page_idx":0,"text":"Legacy source body"}]', encoding="utf-8"
    )
    cache.write_manifest(old, {"signature": legacy_sig})
    before = {p.name: p.read_bytes() for p in old.iterdir()}
    parsed = ParseService(tmp_path / "cache").parse(source)
    assert parsed.markdown == "Legacy source body"
    assert parsed.quality["status"] == "passed"
    assert parsed.parser_signature != legacy_sig
    assert probe.calls == 0
    assert before == {p.name: p.read_bytes() for p in old.iterdir()}


def test_plain_text_keeps_literal_characters_and_no_pdf_page_requirement(tmp_path, monkeypatch):
    import MathCraft.services.parsing.service as service

    source = tmp_path / "different.txt"
    source.write_text("Literal \ufffd in a text lesson.\nFINAL_CONDITION", encoding="utf-8")
    probe = Probe(source.read_text(encoding="utf-8"))
    monkeypatch.setattr(service, "get_parser", lambda _: probe)
    parsed = ParseService(tmp_path / "cache").parse(source)
    assert parsed.markdown == source.read_text(encoding="utf-8")
    assert parsed.quality["status"] == "warning"
    assert parsed.quality["page_count"] is None


def test_good_native_pdf_stays_on_explicit_text_parser(tmp_path, monkeypatch):
    import MathCraft.services.parsing.service as service

    probe = Probe()
    requested = []
    monkeypatch.setattr(service, "get_parser", lambda name: requested.append(name) or probe)
    result = ParseService(tmp_path / "cache").parse(
        pdf(tmp_path / "other-not-a-textbook.pdf"), engine="text_only"
    )
    assert requested == ["text_only"]
    assert result.quality["status"] == "passed"


def test_readable_image_keeps_asset_identity_without_claiming_model_review(tmp_path, monkeypatch):
    import MathCraft.services.parsing.service as service
    from PIL import Image

    class ImageProbe(Probe):
        def parse(self, source, workdir, **kwargs):
            super().parse(source, workdir, **kwargs)
            images = Path(workdir) / "images"
            images.mkdir()
            Image.new("RGB", (32, 24), "white").save(images / "figure.png")

    probe = ImageProbe(
        "![figure](images/figure.png)",
        [{"page_idx": 0, "type": "image", "img_path": "images/figure.png"}],
    )
    monkeypatch.setattr(service, "get_parser", lambda _: probe)
    result = ParseService(tmp_path / "cache").parse(pdf(tmp_path / "image.pdf", scanned=True))
    assert result.quality["status"] == "warning"
    assert result.quality["assets"][0]["width"] == 32
    assert result.quality["assets"][0]["height"] == 24
    assert len(result.quality["assets"][0]["sha256"]) == 64
    assert "images_not_model_verified" in [issue["code"] for issue in result.quality["issues"]]


def test_sample_tool_is_offline_and_does_not_change_source(tmp_path):
    import hashlib
    import importlib.util
    from pypdf import PdfReader

    module_path = Path(__file__).resolve().parents[2] / "tools/prepare_knowledge_samples.py"
    spec = importlib.util.spec_from_file_location("sample_tool", module_path)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    source = pdf(tmp_path / "arbitrary-three-pages.pdf", mixed=True)
    original = source.read_bytes()
    manifest = tmp_path / "fixture.json"
    manifest.write_text(
        json.dumps(
            {
                "source_sha256": hashlib.sha256(original).hexdigest(),
                "source_page_count": 3,
                "samples": [
                    {"source_page": 3, "checks": ["last page"]},
                    {"source_page": 1, "checks": ["first page"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    result = tool.prepare(source, tmp_path / "samples", manifest)
    assert [sample["source_page_index"] for sample in result["samples"]] == [2, 0]
    assert len(PdfReader(tmp_path / "samples/fixed-ten-pages.pdf").pages) == 2
    assert result["review_status"] == "pending_manual_review"
    assert source.read_bytes() == original
    wrong = tmp_path / "wrong.pdf"
    wrong.write_bytes(b"another document")
    with pytest.raises(ValueError, match="摘要"):
        tool.prepare(wrong, tmp_path / "wrong-samples", manifest)
    assert not (tmp_path / "wrong-samples").exists()
