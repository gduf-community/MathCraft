"""通过真实 PDF 与 HTTP 假传输验证 MinerU 分片缓存、错误字段和脱敏出口。"""

import io
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pymupdf
import pytest
from fastapi.testclient import TestClient
from redis import Redis
from sqlalchemy.orm import Session

from app.models import Document
from app.services import cache, mineru
from app.services.rag import vectorstore
from conftest import create_bank


_HTTP_CLIENT = httpx.Client
_FAKE_TOKEN = "fake-mineru-cache-token-only"
_FAKE_BASE_URL = "https://mineru.example.test/api/v4"
_FAKE_PRIVATE_URL = "https://private.example.test/fake-document?signature=fake-signature"
_FAKE_PROVIDER_TEXT = f"Bearer {_FAKE_TOKEN} {_FAKE_PRIVATE_URL} fake-private-response"


def _make_pdf(page_count: int) -> bytes:
    """生成真实空白 PDF，保留扫描检测、页数计算和切分逻辑。"""
    with pymupdf.open() as pdf:
        for _ in range(page_count):
            pdf.new_page()
        return pdf.tobytes()


def _cache_parts(result_dir: Path, count: int) -> list[str]:
    """在临时目录写入已经成功的分片缓存。"""
    contents: list[str] = []
    for index in range(count):
        target = result_dir / f"part_{index:02d}" / "full.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        text = f"# Cached part {index:02d}\n\nFake cached OCR content."
        target.write_text(text, encoding="utf-8")
        contents.append(text)
    return contents


def _result_markdown(index: int) -> str:
    return f"# Downloaded part {index:02d}\n\nFake newly parsed OCR content."


def _assert_batch_record(result_dir: Path) -> None:
    """仅持久化批次编号，不能写入供应商响应、上传 URL 或凭据。"""
    record = result_dir / "last_batch_id.txt"
    assert record.is_file()
    content = record.read_text(encoding="utf-8")
    assert content == "fake-cache-batch"
    for private in (_FAKE_TOKEN, "https://", "file_urls", "Authorization"):
        assert private not in content


@dataclass
class _MineruServer:
    """假供应商只模拟 HTTP，不替换真实 OCR 服务和错误分类逻辑。"""

    fail_parse: bool = True
    archive_prefix: str = ""
    requests: list[httpx.Request] = field(default_factory=list)
    submitted: list[str] = field(default_factory=list)
    uploads: list[tuple[str, int]] = field(default_factory=list)
    downloaded: list[int] = field(default_factory=list)
    poll_count: int = 0

    def respond(self, request: httpx.Request) -> httpx.Response:
        """模拟申请上传、真实 PDF 上传、轮询失败或成功及 ZIP 下载。"""
        self.requests.append(request)
        if request.method == "POST" and str(request.url) == f"{_FAKE_BASE_URL}/file-urls/batch":
            assert request.headers["Authorization"] == f"Bearer {_FAKE_TOKEN}"
            payload = json.loads(request.content)
            self.submitted = [item["name"] for item in payload["files"]]
            assert all(item["is_ocr"] is True for item in payload["files"])
            return httpx.Response(200, json={"code": 0, "data": {
                "batch_id": "fake-cache-batch",
                "file_urls": [f"https://upload.example.test/{name}" for name in self.submitted],
            }})
        if request.method == "PUT" and request.url.host == "upload.example.test":
            assert "Authorization" not in request.headers
            with pymupdf.open(stream=request.content, filetype="pdf") as pdf:
                self.uploads.append((Path(request.url.path).name, pdf.page_count))
            return httpx.Response(200)
        if request.method == "GET" and str(request.url) == (
            f"{_FAKE_BASE_URL}/extract-results/batch/fake-cache-batch"
        ):
            self.poll_count += 1
            if self.fail_parse:
                items = [{
                    "file_name": self.submitted[0], "state": "failed",
                    "err_code": -60007, "err_msg": _FAKE_PROVIDER_TEXT,
                }]
            else:
                # 供应商逆序返回，合并结果仍应按 PDF 原始页序排列。
                items = [{
                    "file_name": name, "state": "done",
                    "full_zip_url": f"https://download.example.test/{Path(name).stem}.zip",
                } for name in reversed(self.submitted)]
            return httpx.Response(200, json={"code": 0, "data": {"extract_result": items}})
        if request.method == "GET" and request.url.host == "download.example.test":
            stem = Path(request.url.path).stem
            index = 0 if stem == "fake-scan" else int(stem.removeprefix("part_"))
            self.downloaded.append(index)
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as result:
                result.writestr(f"{self.archive_prefix}full.md", _result_markdown(index))
            return httpx.Response(200, content=archive.getvalue())
        pytest.fail(f"意外的假服务请求：{request.method} {request.url.host} {request.url.path}")


@pytest.fixture
def mineru_server(monkeypatch: pytest.MonkeyPatch) -> _MineruServer:
    """所有 HTTP 经过 MockTransport；配置与凭据全部使用明确假值。"""
    server = _MineruServer()
    transport = httpx.MockTransport(server.respond)

    def make_client(**kwargs: object) -> httpx.Client:
        return _HTTP_CLIENT(transport=transport, **kwargs)

    monkeypatch.setattr(httpx, "Client", make_client)
    monkeypatch.setattr(mineru, "BASE_URL", _FAKE_BASE_URL)
    monkeypatch.setattr(mineru, "POLL_INTERVAL", 0)
    return server


@pytest.mark.parametrize("page_count,total_parts", [(201, 8), (322, 12)])
def test_extract_pdf_cached_parts_preserve_failed_part_identity(
    tmp_path: Path, mineru_server: _MineruServer, page_count: int, total_parts: int,
) -> None:
    """复用四个成功缓存后，首个待解析分片的错误仍应指向 part_04。"""
    source = tmp_path / "fake-scan.pdf"
    source.write_bytes(_make_pdf(page_count))
    result_dir = tmp_path / "ocr"
    cached = _cache_parts(result_dir, 4)
    progress: list[tuple[int, int]] = []

    with pytest.raises(mineru.MinerUError) as error:
        mineru.extract_pdf(
            _FAKE_TOKEN, source, result_dir, lambda done, total: progress.append((done, total)),
        )

    assert mineru_server.submitted == [f"part_{index:02d}.pdf" for index in range(4, total_parts)]
    assert [name for name, _ in mineru_server.uploads] == mineru_server.submitted
    assert mineru_server.poll_count == 1
    assert mineru_server.downloaded == []
    assert progress == [(4, total_parts)]
    failure = error.value
    assert failure.operation == "parse"
    assert failure.part_index == 4
    assert failure.provider_code == "-60007"
    diagnostic = failure.diagnostic()
    assert "part_04" in diagnostic
    assert "-60007" in diagnostic
    for private in (_FAKE_TOKEN, _FAKE_PRIVATE_URL, "Bearer", "fake-private-response"):
        assert private not in diagnostic + str(failure)
    assert not (result_dir / "full.md").exists()
    _assert_batch_record(result_dir)
    for index, content in enumerate(cached):
        assert (result_dir / f"part_{index:02d}" / "full.md").read_text("utf-8") == content


@pytest.mark.parametrize("page_count,total_parts", [(201, 8), (322, 12)])
def test_extract_pdf_merges_cached_and_downloaded_parts_in_page_order(
    tmp_path: Path, mineru_server: _MineruServer, page_count: int, total_parts: int,
) -> None:
    """只上传缺失分片，逆序返回的 ZIP 与缓存按原页序合并，再次调用完全复用缓存。"""
    source = tmp_path / "fake-scan.pdf"
    source.write_bytes(_make_pdf(page_count))
    result_dir = tmp_path / "ocr"
    cached = _cache_parts(result_dir, 4)
    mineru_server.fail_parse = False
    progress: list[tuple[int, int]] = []

    markdown, returned_dir = mineru.extract_pdf(
        _FAKE_TOKEN, source, result_dir, lambda done, total: progress.append((done, total)),
    )

    expected = "\n\n".join(cached + [_result_markdown(i) for i in range(4, total_parts)])
    assert returned_dir == result_dir
    assert markdown == expected
    assert (result_dir / "full.md").read_text("utf-8") == expected
    _assert_batch_record(result_dir)
    assert mineru_server.submitted == [f"part_{index:02d}.pdf" for index in range(4, total_parts)]
    assert [name for name, _ in mineru_server.uploads] == mineru_server.submitted
    expected_uploaded_pages = [30, 30, 30, 6] if page_count == 201 else [30] * 7 + [7]
    assert [pages for _, pages in mineru_server.uploads] == expected_uploaded_pages
    assert mineru_server.downloaded == list(reversed(range(4, total_parts)))
    assert mineru_server.poll_count == 1
    assert progress == [(done, total_parts) for done in range(4, total_parts + 1)]
    for index, content in enumerate(cached):
        assert (result_dir / f"part_{index:02d}" / "full.md").read_text("utf-8") == content

    requests_before_retry = len(mineru_server.requests)
    assert mineru.extract_pdf(_FAKE_TOKEN, source, result_dir) == (expected, result_dir)
    assert len(mineru_server.requests) == requests_before_retry
    _assert_batch_record(result_dir)


def test_extract_pdf_single_page_uploads_and_downloads_nested_zip(
    tmp_path: Path, mineru_server: _MineruServer,
) -> None:
    """单文件走真实上传与共享 ZIP 下载逻辑，正确返回压缩包内子目录的 Markdown。"""
    source = tmp_path / "fake-scan.pdf"
    source.write_bytes(_make_pdf(1))
    result_dir = tmp_path / "ocr"
    mineru_server.fail_parse = False
    mineru_server.archive_prefix = "fake-result/"

    markdown, returned_dir = mineru.extract_pdf(_FAKE_TOKEN, source, result_dir)

    assert markdown == _result_markdown(0)
    assert returned_dir == result_dir / "fake-result"
    assert (returned_dir / "full.md").read_text(encoding="utf-8") == markdown
    assert mineru_server.submitted == ["fake-scan.pdf"]
    assert mineru_server.uploads == [("fake-scan.pdf", 1)]
    assert mineru_server.downloaded == [0]
    assert mineru_server.poll_count == 1
    assert [request.method for request in mineru_server.requests] == ["POST", "PUT", "GET", "GET"]
    for request in mineru_server.requests:
        if request.url.host == "mineru.example.test":
            assert request.headers["Authorization"] == f"Bearer {_FAKE_TOKEN}"
        else:
            assert "Authorization" not in request.headers
    _assert_batch_record(result_dir)


@pytest.mark.parametrize(
    "status_code,code,expected_provider_code",
    [(403, "A0211", "A0211"), (200, -60018, "-60018")],
    ids=["http-403-expired-token", "http-200-daily-quota"],
)
def test_check_code_preserves_http_and_provider_status(
    status_code: int, code: int | str, expected_provider_code: str,
) -> None:
    """HTTP 状态与供应商业务码同时保留，诊断不能丢失任一维度。"""
    response = httpx.Response(
        status_code, json={"code": code, "msg": _FAKE_PROVIDER_TEXT},
        request=httpx.Request("GET", _FAKE_PRIVATE_URL),
    )

    with pytest.raises(mineru.MinerUError) as error:
        mineru._check_code(response, operation="poll")

    failure = error.value
    assert failure.operation == "poll"
    assert failure.http_status == status_code
    assert failure.provider_code == expected_provider_code
    diagnostic = failure.diagnostic()
    assert f"HTTP {status_code}" in diagnostic
    assert expected_provider_code in diagnostic
    for private in (_FAKE_TOKEN, _FAKE_PRIVATE_URL, "Bearer", "fake-private-response"):
        assert private not in diagnostic + str(failure)


@pytest.mark.parametrize("page_count", [1, 201])
def test_locked_batch_record_does_not_block_ocr(
    tmp_path: Path, mineru_server: _MineruServer, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture, page_count: int,
) -> None:
    """辅助诊断文件只读或被锁定时，单文件及分片仍应上传、解析并保存正文。"""
    source = tmp_path / "fake-scan.pdf"
    source.write_bytes(_make_pdf(page_count))
    result_dir = tmp_path / "ocr"
    mineru_server.fail_parse = False
    original_write = Path.write_text

    def write(path: Path, text: str, *, encoding: str | None = None) -> int:
        if path.name == "last_batch_id.txt":
            raise PermissionError(_FAKE_PROVIDER_TEXT)
        return original_write(path, text, encoding=encoding)

    monkeypatch.setattr(Path, "write_text", write)
    markdown, returned_dir = mineru.extract_pdf(_FAKE_TOKEN, source, result_dir)

    assert markdown
    assert returned_dir == result_dir
    assert (result_dir / "full.md").read_text("utf-8") == markdown
    assert mineru_server.uploads
    assert mineru_server.downloaded
    assert "OCR_BATCH_RECORD_UNAVAILABLE" in caplog.text
    for private in (_FAKE_TOKEN, _FAKE_PRIVATE_URL, "Bearer", "fake-private-response"):
        assert private not in caplog.text


@pytest.mark.parametrize(
    "message,expected_reason",
    [
        pytest.param("parsing failed, please try again later", "task_retry", id="exact-message"),
        pytest.param(
            f"parsing failed, please try again later {_FAKE_PROVIDER_TEXT}",
            "task", id="message-with-private-suffix",
        ),
    ],
)
def test_task_failure_retry_message_is_exact_and_does_not_invent_code(
    message: str, expected_reason: str,
) -> None:
    """仅精确已知消息给出安全重试建议；无业务码时不猜码、不回显供应商原文。"""
    failure = mineru._task_failure({"state": "failed", "err_msg": message}, part_index=4)

    assert failure.operation == "parse"
    assert failure.part_index == 4
    assert failure.reason == expected_reason
    assert failure.provider_code is None
    assert failure.http_status is None
    diagnostic = failure.diagnostic()
    assert "part_04" in diagnostic
    if expected_reason == "task_retry":
        assert "稍后重试" in diagnostic
    assert "业务码" not in diagnostic
    for private in (
        "parsing failed", _FAKE_TOKEN, _FAKE_PRIVATE_URL, "Bearer", "fake-private-response",
    ):
        assert private not in diagnostic + str(failure)


def test_document_ingestion_preserves_mineru_error_fields_without_private_text(
    client: TestClient, teacher: dict[str, str], db: Session,
    monkeypatch: pytest.MonkeyPatch, mineru_server: _MineruServer,
    isolated_redis: Redis, caplog: pytest.LogCaptureFixture,
) -> None:
    """真实上传、切分、HTTP 失败和入库流程保留阶段片号业务码，所有出口均脱敏。"""
    monkeypatch.setattr(vectorstore, "delete_document_chunks", lambda *args, **kwargs: None)
    saved = client.put(
        "/api/users/me/model-settings", headers=teacher, json={"mineru_token": _FAKE_TOKEN},
    )
    assert saved.status_code == 200
    bank = create_bank(client, teacher)
    uploaded = client.post(
        f"/api/banks/{bank['id']}/documents", headers=teacher,
        files={"file": ("fake-scan.pdf", _make_pdf(201), "application/pdf")},
    )
    assert uploaded.status_code == 202
    document_id = uploaded.json()["document_id"]
    response = client.get(f"/api/banks/{bank['id']}/documents/{document_id}", headers=teacher)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "failed"
    assert payload["ocr_status"] == "failed"
    assert mineru_server.poll_count == 1
    doc = db.get(Document, document_id)
    assert doc is not None
    assert doc.ocr_error
    for diagnostic in (payload["error_message"], doc.ocr_error):
        assert "part_00" in diagnostic
        assert "-60007" in diagnostic
        assert "云端解析" in diagnostic
    notices = client.get("/api/notifications", headers=teacher)
    assert notices.status_code == 200
    assert notices.json()["items"]
    cached = isolated_redis.hgetall(cache.PREFIX_INGEST_TASK.format(document_id=document_id))
    assert cached
    exposed = response.text + doc.ocr_error + notices.text + json.dumps(cached) + caplog.text
    for private in (_FAKE_TOKEN, _FAKE_PRIVATE_URL, "Bearer", "fake-private-response"):
        assert private not in exposed
    assert "code=OCR_RESPONSE" in caplog.text
