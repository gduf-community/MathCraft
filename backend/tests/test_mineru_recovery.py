"""Cloud adapter behavior against a fake transport; no real accounts or endpoints."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
import io
import json
from pathlib import Path
import threading

import httpx
import pytest

from MathCraft.services.parsing.engines.mineru import checkpoints, cloud
from MathCraft.services.parsing.engines.mineru.config import MinerUConfig, MinerUError


def write_pdf(path: Path, pages=1):
    import pymupdf

    doc = pymupdf.open()
    for index in range(pages):
        doc.new_page().insert_text(
            (72, 120), f"Complete reference on source page {index + 1}. FINAL"
        )
    doc.save(path)
    doc.close()
    return path


def archive(*, image=False, invalid_page=False):
    import zipfile

    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as target:
        target.writestr("result/full.md", "完整参考材料 FINAL_CONDITION")
        target.writestr(
            "result/full_content_list.json",
            json.dumps(
                [
                    {
                        "type": "text",
                        "text": "complete source",
                        "page_idx": 5 if invalid_page else 0,
                    },
                    *(
                        [{"type": "image", "page_idx": 0, "img_path": "images/missing.png"}]
                        if image
                        else []
                    ),
                ]
            ),
        )
    return result.getvalue()


class FakeCloud:
    base = "https://fake-mineru.test"

    def __init__(self):
        self.submits = self.uploads = self.polls = self.downloads = 0
        self.state = "done"
        self.body = archive()
        self.submit_timeout = False
        self.upload_timeout = False
        self.query_failures = []
        self.first_submit_gate = None
        self.names = {}
        self.retry_after = "0"
        self.submit_limits = 0
        self.owners = {}
        self.enforce_owner = False
        self.upload_url = None
        self.invalid_query = False

    def handle(self, request):
        path = request.url.path
        if request.method == "POST":
            self.submits += 1
            if self.submit_limits:
                self.submit_limits -= 1
                return httpx.Response(429, headers={"Retry-After": "0"})
            if self.first_submit_gate:
                self.first_submit_gate.set()
                threading.Event().wait(0.2)
            if self.submit_timeout:
                raise httpx.ReadTimeout("fake ambiguous submission", request=request)
            batch = f"batch-{self.submits}"
            self.names[batch] = json.loads(request.content)["files"][0]["name"]
            self.owners[batch] = request.headers.get("authorization")
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "batch_id": batch,
                        "file_urls": [
                            self.upload_url
                            if self.upload_url is not None
                            else f"{self.base}/upload/{batch}?signature=fake-signed-url"
                        ],
                    },
                },
            )
        if request.method == "PUT":
            self.uploads += 1
            assert "authorization" not in request.headers
            assert "content-type" not in request.headers
            if self.upload_timeout:
                self.upload_timeout = False
                raise httpx.ReadTimeout("fake response lost after acceptance", request=request)
            return httpx.Response(200)
        if "extract-results" in path:
            self.polls += 1
            if self.invalid_query:
                return httpx.Response(200, json={"code": 0, "data": "invalid task record"})
            if self.query_failures:
                status = self.query_failures.pop(0)
                return httpx.Response(status, headers={"Retry-After": self.retry_after})
            batch = path.rsplit("/", 1)[-1]
            if self.enforce_owner and request.headers.get("authorization") != self.owners[batch]:
                return httpx.Response(403)
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "extract_result": [
                            {
                                "file_name": self.names[batch],
                                "state": self.state,
                                "full_zip_url": f"{self.base}/result/{batch}.zip?signature=fake-download-url",
                            }
                        ]
                    },
                },
            )
        self.downloads += 1
        return httpx.Response(200, content=self.body)


@pytest.fixture
def fake_cloud(tmp_path, monkeypatch):
    fake = FakeCloud()
    original = httpx.Client
    transport = httpx.MockTransport(fake.handle)
    monkeypatch.setattr(checkpoints, "checkpoint_root", lambda: tmp_path / "jobs")
    class FakeClient(original):
        def __init__(self, *args, **kwargs):
            kwargs.setdefault("transport", transport)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(cloud.httpx, "Client", FakeClient)

    def put(url, **kwargs):
        with original(transport=transport) as client:
            return client.put(url, **kwargs)

    @contextmanager
    def stream(method, url, **kwargs):
        with original(transport=transport) as client:
            with client.stream(method, url, **kwargs) as response:
                yield response

    monkeypatch.setattr(cloud.httpx, "put", put)
    monkeypatch.setattr(cloud.httpx, "stream", stream)
    # No real-time backoff in automated tests; cancellation still uses the real boundary.
    monkeypatch.setattr(cloud, "_wait", lambda _: cloud._check_cancel())
    return fake


def config(**overrides):
    return MinerUConfig(
        mode="cloud",
        api_base_url=FakeCloud.base,
        api_token="fake-test-token-not-for-storage",
        **overrides,
    )


def parse(source, output, **kwargs):
    return cloud.parse_cloud(source, output, config(), poll_interval=0, timeout=0, **kwargs)


def test_wait_budget_resume_queries_existing_task_without_reupload(tmp_path, fake_cloud):
    source = write_pdf(tmp_path / "source.pdf")
    fake_cloud.state = "pending"
    with pytest.raises(MinerUError) as error:
        parse(source, tmp_path / "first")
    assert error.value.code == "cloud_wait_budget_exceeded"
    journal = json.loads(next((tmp_path / "jobs").rglob("task.json")).read_text(encoding="utf-8"))
    assert journal["batch_id"] == "batch-1"
    assert journal["remote_state"] == "pending"
    assert "fake-test-token" not in json.dumps(journal)
    assert "signature=" not in json.dumps(journal)
    fake_cloud.state = "done"
    result = parse(source, tmp_path / "after-restart")
    assert "FINAL_CONDITION" in (result / "result/full.md").read_text(encoding="utf-8")
    assert (fake_cloud.submits, fake_cloud.uploads) == (1, 1)
    assert list((tmp_path / "jobs").rglob("ready.json"))


def test_submission_unknown_does_not_blindly_resubmit(tmp_path, fake_cloud):
    source = write_pdf(tmp_path / "source.pdf")
    fake_cloud.submit_timeout = True
    for _ in range(2):
        with pytest.raises(MinerUError) as error:
            parse(source, tmp_path / "output")
        assert error.value.code == "cloud_submission_unknown"
    assert fake_cloud.submits == 1
    assert fake_cloud.uploads == 0


def test_lost_upload_response_checks_remote_before_repeating_put(tmp_path, fake_cloud):
    source = write_pdf(tmp_path / "source.pdf")
    fake_cloud.upload_timeout = True
    with pytest.raises(MinerUError) as error:
        parse(source, tmp_path / "output")
    assert error.value.code == "cloud_upload_interrupted"
    parse(source, tmp_path / "recovered")
    assert (fake_cloud.submits, fake_cloud.uploads) == (1, 1)


def test_waiting_file_does_not_prove_an_ambiguous_upload_was_not_received(tmp_path, fake_cloud):
    source = write_pdf(tmp_path / "source.pdf")
    fake_cloud.upload_timeout = True
    with pytest.raises(MinerUError):
        parse(source, tmp_path / "output")
    fake_cloud.state = "waiting-file"
    with pytest.raises(MinerUError) as error:
        parse(source, tmp_path / "retry")
    assert error.value.code == "cloud_upload_unknown"
    assert (fake_cloud.submits, fake_cloud.uploads) == (1, 1)


def test_retry_after_longer_than_local_budget_is_not_ignored(tmp_path, fake_cloud):
    source = write_pdf(tmp_path / "source.pdf")
    fake_cloud.query_failures = [429]
    fake_cloud.retry_after = "120"
    with pytest.raises(MinerUError) as error:
        parse(source, tmp_path / "output")
    assert error.value.code == "cloud_rate_limited"
    assert fake_cloud.polls == 1
    fake_cloud.retry_after = "0"
    parse(source, tmp_path / "recovered")
    assert fake_cloud.submits == 1


def test_query_limits_and_server_failures_are_bounded_and_recoverable(tmp_path, fake_cloud):
    source = write_pdf(tmp_path / "source.pdf")
    fake_cloud.query_failures = [429, 503, 502]
    with pytest.raises(MinerUError) as error:
        parse(source, tmp_path / "output")
    assert error.value.code == "cloud_api_failed"
    assert fake_cloud.polls == 3
    parse(source, tmp_path / "recovered")
    assert fake_cloud.submits == 1


@pytest.mark.parametrize("failure", ["zip", "page", "image", "path"])
def test_invalid_results_are_not_completed_and_can_be_downloaded_again(
    tmp_path, fake_cloud, failure
):
    import zipfile

    source = write_pdf(tmp_path / "source.pdf")
    if failure == "zip":
        fake_cloud.body = b"not a zip"
    elif failure == "page":
        fake_cloud.body = archive(invalid_page=True)
    elif failure == "image":
        fake_cloud.body = archive(image=True)
    else:
        body = io.BytesIO()
        with zipfile.ZipFile(body, "w") as target:
            target.writestr("../outside.txt", "escape")
        fake_cloud.body = body.getvalue()
    with pytest.raises(MinerUError) as error:
        parse(source, tmp_path / "output")
    assert error.value.code == "cloud_result_invalid"
    assert not list((tmp_path / "jobs").rglob("ready.json"))
    fake_cloud.body = archive()
    parse(source, tmp_path / "recovered")
    assert fake_cloud.submits == 1
    assert not (tmp_path / "outside.txt").exists()


def test_cancel_preserves_task_and_only_explicit_retry_continues(tmp_path, fake_cloud):
    from MathCraft.knowledge.indexing_run import IndexingCancelled, IndexingRun, request_cancel

    source = write_pdf(tmp_path / "source.pdf")
    fake_cloud.state = "pending"
    kb = tmp_path / "kb"
    with pytest.raises(IndexingCancelled):
        with IndexingRun(kb, [str(source)], task_id="cancel-test"):
            parse(
                source,
                tmp_path / "output",
                on_progress=lambda message: (
                    request_cancel(kb, "cancel-test") if "pending" in message else None
                ),
            )
    journal = json.loads(next((tmp_path / "jobs").rglob("task.json")).read_text(encoding="utf-8"))
    assert journal["phase"] == "cancelled"
    assert journal["batch_id"] == "batch-1"
    assert not list((tmp_path / "jobs").rglob("ready.json"))
    fake_cloud.state = "done"
    with IndexingRun(kb, [str(source)], task_id="explicit-retry"):
        parse(source, tmp_path / "recovered")
    assert (fake_cloud.submits, fake_cloud.uploads) == (1, 1)


def test_duplicate_concurrent_requests_share_the_completed_checkpoint(tmp_path, fake_cloud):
    source = write_pdf(tmp_path / "source.pdf")
    fake_cloud.first_submit_gate = threading.Event()
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(parse, source, tmp_path / "a")
        assert fake_cloud.first_submit_gate.wait(5)
        second = pool.submit(parse, source, tmp_path / "b")
        assert first.result(15).is_dir()
        assert second.result(15).is_dir()
    assert (fake_cloud.submits, fake_cloud.uploads) == (1, 1)


def test_completed_slices_restore_original_page_indices(tmp_path, fake_cloud):
    source = write_pdf(tmp_path / "different-three-pages.pdf", 3)
    cfg = config(max_pages_per_part=1)
    result = cloud.parse_cloud(source, tmp_path / "output", cfg, poll_interval=0, timeout=0)
    blocks = json.loads(
        (result / "different-three-pages_content_list.json").read_text(encoding="utf-8")
    )
    assert [block["page_idx"] for block in blocks] == [0, 1, 2]
    assert fake_cloud.submits == 3
    cloud.parse_cloud(source, tmp_path / "recovered", cfg, poll_interval=0, timeout=0)
    assert fake_cloud.submits == 3


def test_completed_archive_reuse_does_not_require_a_token(tmp_path, fake_cloud, monkeypatch):
    source = write_pdf(tmp_path / "source.pdf")
    parse(source, tmp_path / "first")
    without_token = replace(config(), api_token="")
    output = cloud.parse_cloud(source, tmp_path / "from-archive", without_token)
    assert (output / "result/full.md").is_file()
    assert (fake_cloud.submits, fake_cloud.uploads, fake_cloud.polls, fake_cloud.downloads) == (
        1,
        1,
        1,
        1,
    )
    # A normal ParseService cache miss can reconstruct IR locally from the same archive.
    from MathCraft.services.parsing.engines.mineru.engine import MinerUParser
    from MathCraft.services.parsing.service import ParseService

    monkeypatch.setattr(MinerUParser, "resolve_config", lambda _: without_token)
    parsed = ParseService(tmp_path / "new-ir-cache").parse(source, engine="mineru")
    assert "FINAL_CONDITION" in parsed.markdown
    assert fake_cloud.submits == 1


def test_large_pdf_is_split_by_byte_budget_as_well_as_pages(tmp_path, fake_cloud, monkeypatch):
    from pypdf import PdfReader, PdfWriter

    source = write_pdf(tmp_path / "three-pages.pdf", 3)
    writer = PdfWriter()
    writer.add_page(PdfReader(source).pages[0])
    one = io.BytesIO()
    writer.write(one)
    writer.close()
    monkeypatch.setattr(cloud, "_MAX_UPLOAD_BYTES", len(one.getvalue()) + 10)
    parse(source, tmp_path / "bounded-output")
    assert fake_cloud.submits == 3


def test_nested_images_keep_distinct_paths_after_merging(tmp_path, fake_cloud):
    from PIL import Image
    import zipfile

    image = io.BytesIO()
    Image.new("RGB", (32, 24), "white").save(image, format="PNG")
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as target:
        target.writestr("result/full.md", "![figure](images/nested/same.png)")
        target.writestr("result/images/nested/same.png", image.getvalue())
        target.writestr(
            "result/full_content_list.json",
            json.dumps([{"type": "image", "page_idx": 0, "img_path": "images/nested/same.png"}]),
        )
    fake_cloud.body = data.getvalue()
    source = write_pdf(tmp_path / "figures.pdf", 2)
    output = cloud.parse_cloud(source, tmp_path / "output", config(max_pages_per_part=1))
    assert (output / "images/part01/nested/same.png").is_file()
    assert (output / "images/part02/nested/same.png").is_file()
    blocks = json.loads((output / "figures_content_list.json").read_text(encoding="utf-8"))
    assert [block["page_idx"] for block in blocks] == [0, 1]
    assert [block["img_path"] for block in blocks] == [
        "images/part01/nested/same.png",
        "images/part02/nested/same.png",
    ]
    from MathCraft.services.parsing.cache import load_ir
    from MathCraft.services.parsing.types import ParsedDocument
    from MathCraft.services.rag.visual_assets import collect_visual_assets
    from MathCraft.services.rag.visual_coverage import record_coverage
    from MathCraft.services.rag.pipelines.llamaindex.document_loader import LlamaIndexDocumentLoader

    markdown, blocks, asset_dir = load_ir(output)
    parsed = ParsedDocument(
        markdown,
        blocks=blocks,
        asset_dir=asset_dir,
        workdir=output,
        parser_signature="controlled",
        engine="mineru",
    )
    kb = tmp_path / "kb"
    (kb / "raw").mkdir(parents=True)
    managed_source = kb / "raw" / source.name
    managed_source.write_bytes(source.read_bytes())
    candidates = collect_visual_assets(parsed, managed_source, kb)
    assert [candidate.record["page_index"] for candidate in candidates] == [0, 1]
    assert len({candidate.record["asset_id"] for candidate in candidates}) == 2
    images = LlamaIndexDocumentLoader()._collect_asset_images(asset_dir, origin=managed_source)
    assert len(images) == 2
    record_coverage(parsed, managed_source, kb, candidates)
    coverage = json.loads(
        next((kb / "visual_assets" / "coverage").glob("*.json")).read_text(encoding="utf-8")
    )
    assert coverage["validated_count"] == 2
    assert not any(
        issue["reason"] == "referenced_image_not_retained" for issue in coverage["issues"]
    )


def test_missing_credentials_do_not_submit_an_unfinished_task(tmp_path, fake_cloud):
    source = write_pdf(tmp_path / "source.pdf")
    with pytest.raises(MinerUError) as error:
        cloud.parse_cloud(source, tmp_path / "output", replace(config(), api_token=""))
    assert error.value.code == "cloud_credentials_missing"
    assert fake_cloud.submits == 0


def test_key_rotation_keeps_queries_bound_to_the_submission_credential(tmp_path, fake_cloud):
    source = write_pdf(tmp_path / "source.pdf")
    fake_cloud.submit_limits = 1
    fake_cloud.enforce_owner = True
    cfg = replace(config(), api_token=["fake-first-key", "fake-second-key"])
    cloud.parse_cloud(source, tmp_path / "output", cfg)
    assert fake_cloud.submits == 2
    assert fake_cloud.owners["batch-2"] == "Bearer fake-second-key"
    journal = json.loads(next((tmp_path / "jobs").rglob("task.json")).read_text(encoding="utf-8"))
    assert "fake-first-key" not in json.dumps(journal)
    assert "fake-second-key" not in json.dumps(journal)


def test_invalid_upload_url_keeps_known_identity_without_resubmitting(tmp_path, fake_cloud):
    source = write_pdf(tmp_path / "source.pdf")
    fake_cloud.upload_url = "http://[invalid"
    with pytest.raises(MinerUError) as error:
        parse(source, tmp_path / "first")
    assert error.value.code == "cloud_result_invalid"
    journal = json.loads(next((tmp_path / "jobs").rglob("task.json")).read_text(encoding="utf-8"))
    assert journal["batch_id"] == "batch-1"
    assert fake_cloud.upload_url not in json.dumps(journal)
    fake_cloud.state = "waiting-file"
    with pytest.raises(MinerUError) as error:
        parse(source, tmp_path / "second")
    assert error.value.code == "cloud_upload_expired"
    assert (fake_cloud.submits, fake_cloud.uploads) == (1, 0)


def test_malformed_status_retains_task_and_can_be_retried(tmp_path, fake_cloud):
    source = write_pdf(tmp_path / "source.pdf")
    fake_cloud.invalid_query = True
    with pytest.raises(MinerUError) as error:
        parse(source, tmp_path / "first")
    assert error.value.code == "cloud_result_invalid"
    fake_cloud.invalid_query = False
    parse(source, tmp_path / "second")
    assert (fake_cloud.submits, fake_cloud.uploads) == (1, 1)


def test_task_identity_survives_a_real_interpreter_restart(tmp_path, fake_cloud):
    """A loopback fake stays alive while two independent Python processes run."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import os
    import subprocess
    import sys

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self):
            content = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            response = fake_cloud.handle(
                httpx.Request(
                    self.command,
                    fake_cloud.base + self.path,
                    headers=dict(self.headers),
                    content=content,
                )
            )
            self.send_response(response.status_code)
            self.send_header("Content-Length", str(len(response.content)))
            for key, value in response.headers.items():
                if key.lower() != "content-length":
                    self.send_header(key, value)
            self.end_headers()
            self.wfile.write(response.content)

        do_GET = do_POST = do_PUT = reply

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    fake_cloud.base = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    source = write_pdf(tmp_path / "restart.pdf")
    env = {
        **os.environ,
        "MATHCRAFT_HOME": str(tmp_path / "child-home"),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
    }
    script = """
import sys
from pathlib import Path
from MathCraft.services.parsing.engines.mineru.cloud import parse_cloud
from MathCraft.services.parsing.engines.mineru.config import MinerUConfig, MinerUError
try:
    parse_cloud(Path(sys.argv[1]),Path(sys.argv[2]),MinerUConfig(mode='cloud',
        api_base_url=sys.argv[3],api_token='fake-only'),timeout=0,poll_interval=0)
    print('completed')
except MinerUError as exc:
    print(exc.code)
    sys.exit(42)
"""
    try:
        fake_cloud.state = "pending"
        first = subprocess.run(
            [sys.executable, "-c", script, str(source), str(tmp_path / "first"), fake_cloud.base],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert first.returncode == 42, first.stderr
        assert "cloud_wait_budget_exceeded" in first.stdout
        fake_cloud.state = "done"
        second = subprocess.run(
            [sys.executable, "-c", script, str(source), str(tmp_path / "second"), fake_cloud.base],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert second.returncode == 0, second.stderr
        assert (fake_cloud.submits, fake_cloud.uploads) == (1, 1)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(5)
