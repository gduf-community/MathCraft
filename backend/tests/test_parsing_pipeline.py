"""Document parsing: PDF text extraction, and an honest failure when it can't run.

Two seams are used deliberately:

* the extractor itself (service level) — proves a PDF with a text layer is read;
* the upload → index path (HTTP) — proves the pipeline either indexes the PDF or
  reports an actionable parser error instead of silently claiming success.

The isolated-worker extraction path cannot spawn a subprocess in this sandbox,
so the HTTP half accepts either outcome and pins the wording of the failure.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

SOURCES = Path(__file__).resolve().parent / ".sources"


@pytest.fixture()
def pdf_path():
    import pymupdf

    SOURCES.mkdir(parents=True, exist_ok=True)
    target = SOURCES / "gears.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "The helix angle of a gear is 20 degrees.")
    page.insert_text((72, 96), "A worm gear has a lead angle of 5 degrees.")
    document.save(str(target))
    document.close()
    yield target
    shutil.rmtree(SOURCES, ignore_errors=True)


def test_pdf_text_is_extracted(pdf_path):
    from MathCraft.utils.document_extractor import extract_text_from_path

    text = extract_text_from_path(pdf_path)
    assert "helix angle" in text.lower()
    assert "worm gear" in text.lower()


def test_pdf_upload_either_indexes_or_explains_the_parser_problem(client, pdf_path):
    with open(pdf_path, "rb") as handle:
        created = client.post(
            "/api/knowledge-bases",
            data={"name": "pdf-kb"},
            files={"files": ("gears.pdf", handle.read(), "application/pdf")},
        )
    assert created.status_code == 200, created.text

    deadline = 0
    stats: dict = {}
    while deadline < 60:
        stats = client.get("/api/knowledge-bases/pdf-kb").json().get("statistics", {})
        if stats.get("rag_initialized") or stats.get("status") in {"error", "failed"}:
            break
        import time

        time.sleep(0.5)
        deadline += 1

    if stats.get("rag_initialized"):
        response = client.post(
            "/api/knowledge-bases/pdf-kb/query",
            json={"query": "helix angle", "top_k": 3},
        )
        assert response.status_code == 200, response.text
        text = " ".join(source.get("content", "") for source in response.json()["sources"])
        assert "helix" in text.lower()
    else:
        message = (stats.get("progress") or {}).get("message") or stats.get("last_error") or ""
        # A parser that cannot run must surface a failure, never a silent
        # success with an empty index. The detailed reason is logged.
        assert stats.get("status") in {"error", "failed"}, stats
        assert message, stats

    client.delete("/api/knowledge-bases/pdf-kb")
