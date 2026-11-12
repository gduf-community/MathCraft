"""MinerU OCR 客户端（v4 API）：扫描版 PDF 上传 → 轮询 → 下载 zip → 取 full.md。

限制：文件 ≤ 200 MB，页数 ≤ 200 页（上传前由调用方校验）。
Token 优先取用户配置，默认用 local_secrets 中的系统 Token。
"""
import io
import logging
import math
import re
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

import httpx
import pymupdf as fitz


BASE_URL = "https://mineru.net/api/v4"
MODEL_VERSION = "vlm"
MAX_FILE_MB = 200
MAX_PAGES = 200
POLL_INTERVAL = 5
POLL_TIMEOUT = 600  # 单次轮询上限 10 分钟
# 分片策略：首片固定 15 页用于提取目录，其余按需均分；总片数控制在 20 以内
TOC_PAGES = 15
MAX_PARTS = 16
logger = logging.getLogger("app.mineru")


class MinerUError(RuntimeError):
    """OCR 错误；只允许受限诊断字段进入日志、状态和通知。"""

    def __init__(self, message: str, *, operation: str = "request",
                 provider_code: object = None, http_status: int | None = None,
                 part_index: int | None = None, reason: str = "response") -> None:
        super().__init__(message)
        self.operation = operation if operation in _OPERATIONS else "request"
        self.provider_code = _safe_code(provider_code)
        self.http_status = http_status if type(http_status) is int else None
        self.part_index = part_index if type(part_index) is int and part_index >= 0 else None
        self.reason = reason if reason in _REASONS else "response"

    def diagnostic(self) -> str:
        """返回可公开的诊断，不使用供应商错误原文。"""
        fields = [_OPERATIONS[self.operation], _REASONS[self.reason]]
        if self.part_index is not None:
            fields.append(f"分片 part_{self.part_index:02d}")
        if self.http_status is not None:
            fields.append(f"HTTP {self.http_status}")
        if self.provider_code is not None:
            fields.append(f"业务码 {self.provider_code}")
            if self.provider_code in _CODE_REASONS:
                fields.append(_CODE_REASONS[self.provider_code])
        return "OCR 解析失败：" + "；".join(fields)


_OPERATIONS = {
    "request": "MinerU 请求", "submit": "申请上传链接", "upload": "上传文件",
    "poll": "查询任务", "parse": "云端解析", "download": "下载解析结果",
    "result": "读取解析结果", "probe": "连接测试",
}
_REASONS = {
    "response": "服务返回异常", "business": "服务拒绝请求", "task": "任务失败",
    "protocol": "响应格式异常", "timeout": "服务超时", "connection": "网络连接失败",
    "missing": "结果文件缺失",
    "task_retry": "云端返回解析失败，建议稍后重试",
    "credential": "Token 格式错误",
}
_CODE_REASONS = {
    "A0202": "Token 错误", "A0211": "Token 已过期",
    "-60003": "文件读取失败", "-60004": "空文件",
    "-60005": "文件大小超限", "-60006": "文件页数超限",
    "-60007": "模型服务暂时不可用", "-60008": "文件读取超时",
    "-60009": "任务提交队列已满", "-60010": "解析失败",
    "-60011": "获取有效文件失败", "-60012": "找不到任务",
    "-60013": "无权访问该任务", "-60018": "每日解析任务数量已达上限",
}


def _safe_code(value: object) -> str | None:
    """仅接收 API 定义的短错误码，拒绝任意供应商文本。"""
    if type(value) is int:
        value = str(value)
    if isinstance(value, str) and re.fullmatch(r"(?:A[0-9]{4}|-?[0-9]{1,6})", value):
        return value
    return None


@contextmanager
def _at_stage(operation: str, part_index: int | None = None) -> Iterator[None]:
    """为网络异常添加本地阶段与片号，保留异常链而不回显 URL。"""
    try:
        yield
    except MinerUError as exc:
        if exc.part_index is None:
            exc.part_index = part_index
        raise
    except httpx.HTTPError as exc:
        status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
        reason = "response"
        if isinstance(exc, httpx.TimeoutException):
            reason = "timeout"
        elif isinstance(exc, httpx.RequestError):
            reason = "connection"
        raise MinerUError("MinerU 网络请求失败", operation=operation, http_status=status,
                          part_index=part_index, reason=reason) from exc


def detect_scanned_pdf(file_path: Path) -> tuple[bool, int]:
    """判定 PDF 是否为扫描件（无可提取文本层）。返回 (is_scanned, page_count)。"""
    with fitz.open(file_path) as doc:
        pages = [page.get_text("text").strip() for page in doc]
    page_count = len(pages)
    if page_count == 0:
        return False, 0
    total_chars = sum(len(t) for t in pages)
    # 全文可提取字符过少，或平均每页低于 30 字符 → 扫描版
    is_scanned = total_chars < 50 or total_chars / page_count < 30
    return is_scanned, page_count


def ping_token(token: str) -> tuple[bool, str]:
    """只读验证连接及鉴权；找不到探测任务不代表文件解析成功。"""
    try:
        with _at_stage("probe"):
            resp = httpx.get(
                f"{BASE_URL}/extract-results/batch/00000000-0000-0000-0000-000000000000",
                headers=_authorization(token, "probe"), timeout=30.0,
            )
            _check_code(resp, operation="probe", allow_missing_task=True)
        return True, "MinerU 连接及鉴权通过；未验证实际解析，仍受额度、文件和任务结果影响"
    except MinerUError as exc:
        return False, exc.diagnostic()


def _check_code(resp: httpx.Response, *, operation: str = "request",
                allow_missing_task: bool = False) -> dict:
    """校验 HTTP 与业务状态，拒绝缺失状态及非对象响应。"""
    try:
        body = resp.json()
    except ValueError:
        body = None
    if not resp.is_success:
        code = body.get("code") if isinstance(body, dict) else None
        raise MinerUError("MinerU HTTP 请求失败", operation=operation,
                          http_status=resp.status_code, provider_code=code)
    if not isinstance(body, dict):
        raise MinerUError("MinerU 响应不是对象", operation=operation, reason="protocol",
                          http_status=resp.status_code)
    code = body.get("code")
    if allow_missing_task and resp.status_code == 200 and _safe_code(code) == "-60012":
        return {}
    if type(code) is not int or code != 0:
        raise MinerUError("MinerU 业务请求失败", operation=operation,
                          provider_code=code, reason="business", http_status=resp.status_code)
    data = body.get("data")
    if not isinstance(data, dict):
        raise MinerUError("MinerU 缺少数据对象", operation=operation, reason="protocol",
                          http_status=resp.status_code)
    return data


def _authorization(token: str, operation: str = "submit") -> dict[str, str]:
    """在构造请求头前拒绝非 ASCII、空白及控制字符，避免异常泄漏凭据。"""
    if not re.fullmatch(r"[\x21-\x7e]+", token):
        raise MinerUError("MinerU Token 格式错误", operation=operation, reason="credential")
    return {"Authorization": f"Bearer {token}"}


def _batch_request(client: httpx.Client, headers: dict[str, str], *,
                   files: list[dict] | None = None, batch_id: str = "") -> dict:
    """提交或查询批次，并记录异常发生的安全阶段。"""
    operation = "submit" if files is not None else "poll"
    with _at_stage(operation):
        if files is not None:
            response = client.post(f"{BASE_URL}/file-urls/batch", headers=headers, json={
                "enable_formula": True, "enable_table": True, "language": "ch",
                "model_version": MODEL_VERSION, "files": files,
            })
        else:
            response = client.get(f"{BASE_URL}/extract-results/batch/{batch_id}",
                                  headers=headers)
        data = _check_code(response, operation=operation)
        if files is not None:
            batch = data.get("batch_id")
            urls = data.get("file_urls")
            valid = (
                isinstance(batch, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", batch)
                and isinstance(urls, list) and len(urls) == len(files)
                and all(isinstance(url, str) and url.startswith(("https://", "http://"))
                        for url in urls)
            )
        else:
            results = data.get("extract_result", [])
            valid = isinstance(results, list) and all(isinstance(item, dict) for item in results)
        if not valid:
            raise MinerUError("MinerU 批次字段异常", operation=operation, reason="protocol",
                              http_status=response.status_code)
        return data


def _task_failure(item: dict, part_index: int | None = None) -> MinerUError:
    """任务 err_msg 仅识别已知码，不保存供应商自由文本。"""
    code = _safe_code(item.get("err_code"))
    if code is None:
        # 部分响应只在 err_msg 中给出错误码，白名单以外的正文一律丢弃。
        for known in _CODE_REASONS:
            if re.search(r"(?<![\w-])" + re.escape(known) + r"(?!\w)",
                         str(item.get("err_msg", ""))):
                code = known
                break
    reason = "task"
    if item.get("err_msg") == "parsing failed, please try again later":
        reason = "task_retry"
    return MinerUError("MinerU 云端解析失败", operation="parse", provider_code=code,
                       part_index=part_index, reason=reason)


def _record_batch(result_dir: Path, batch_id: str) -> None:
    """保留最近批次编号供失败后只读核查，不保存上传地址或凭据。"""
    if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", batch_id):
        try:
            result_dir.mkdir(parents=True, exist_ok=True)
            (result_dir / "last_batch_id.txt").write_text(batch_id, encoding="utf-8")
        except OSError as exc:
            # 辅助诊断文件被锁定或只读时，不阻断实际上传与解析。
            logger.warning("MinerU diagnostic persistence failure type=%s "
                           "code=OCR_BATCH_RECORD_UNAVAILABLE", type(exc).__name__)


def extract_pdf(token: str, file_path: Path, result_dir: Path,
                on_progress: Callable[[int, int], None] | None = None) -> tuple[str, Path]:
    """完整 OCR 流程：申请上传 URL → PUT 文件 → 轮询 → 下载解压 → 读 full.md。

    返回 (markdown 文本, 结果目录)。超过 MAX_PAGES 的 PDF 自动切分批量识别后合并。
    on_progress(已完成片数, 总片数) 用于向上层汇报切分识别进度。
    """
    if file_path.stat().st_size > MAX_FILE_MB * 1024 * 1024:
        raise MinerUError(f"文件超过 {MAX_FILE_MB} MB 上限")
    with fitz.open(file_path) as doc:
        if doc.page_count > MAX_PAGES:
            return _extract_pdf_in_parts(token, file_path, result_dir, on_progress)

    headers = _authorization(token)
    with httpx.Client(timeout=120.0) as client:
        # 1. 申请上传链接
        data = _batch_request(client, headers,
                              files=[{"name": file_path.name, "is_ocr": True}])
        batch_id = data.get("batch_id")
        upload_url = (data.get("file_urls") or [None])[0]
        if not batch_id or not upload_url:
            raise MinerUError("MinerU 缺少上传链接", operation="submit", reason="protocol")
        _record_batch(result_dir, batch_id)

        # 2. PUT 上传文件（预签名 URL，不带鉴权头）
        _upload_part(client, upload_url, file_path)

        # 3. 轮询批次结果
        deadline = time.monotonic() + POLL_TIMEOUT
        result = None
        while time.monotonic() < deadline:
            data = _batch_request(client, headers, batch_id=batch_id)
            results = data.get("extract_result") or []
            if results:
                state = results[0].get("state")
                if state == "done":
                    result = results[0]
                    break
                if state == "failed":
                    raise _task_failure(results[0])
            time.sleep(POLL_INTERVAL)
        if result is None:
            raise MinerUError("MinerU 任务超时", operation="poll", reason="timeout")

        zip_url = result.get("full_zip_url")
        if not isinstance(zip_url, str) or not zip_url:
            raise MinerUError("MinerU 未返回结果链接", operation="download", reason="protocol")

        # 4. 下载 zip 并解压
        markdown = _download_part_md(client, zip_url, result_dir)

    md_path = result_dir / "full.md"
    if not md_path.exists():
        # 兼容压缩包内带子目录的情况
        candidates = list(result_dir.rglob("full.md"))
        if not candidates:
            raise MinerUError("OCR 结果中未找到 full.md")
        md_path = candidates[0]
    return markdown, md_path.parent


def _plan_parts(page_count: int) -> list[tuple[int, int]]:
    """分片计划：首片固定前 15 页（用于目录提取），其余按页均分，总片数不超过 MAX_PARTS。

    返回左闭右开区间列表，区间按页码顺序排列。
    """
    if page_count <= MAX_PAGES:
        return [(0, page_count)]
    first_end = min(TOC_PAGES, page_count)
    rest = page_count - first_end
    size = max(30, math.ceil(rest / (MAX_PARTS - 1)))
    plan = [(0, first_end)]
    start = first_end
    while start < page_count:
        plan.append((start, min(start + size, page_count)))
        start += size
    return plan


def _split_pdf(file_path: Path, result_dir: Path,
               plan: list[tuple[int, int]]) -> list[Path]:
    """按分片计划切分 PDF，返回分片文件路径列表（顺序与计划一致）。"""
    parts_dir = result_dir / "parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    with fitz.open(file_path) as doc:
        for idx, (start, end) in enumerate(plan):
            part = fitz.open()
            part.insert_pdf(doc, from_page=start, to_page=end - 1)
            part_path = parts_dir / f"part_{idx:02d}.pdf"
            part.save(str(part_path))
            part.close()
            parts.append(part_path)
    return parts


def _download_part_md(client: httpx.Client, zip_url: str, target_dir: Path,
                      part_index: int | None = None) -> str:
    """下载单个分片的结果压缩包，解压后返回其 full.md 文本（网络抖动重试三次）。"""
    resp = None
    for attempt in range(3):
        try:
            resp = client.get(zip_url)
            resp.raise_for_status()
            break
        except httpx.HTTPError:
            if attempt == 2:
                with _at_stage("download", part_index):
                    raise
            time.sleep(5 * (attempt + 1))
    target_dir.mkdir(parents=True, exist_ok=True)
    assert resp is not None  # 三次均失败时已在上方抛出；成功分支一定持有响应。
    try:
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            zf.extractall(target_dir)
    except zipfile.BadZipFile as exc:
        raise MinerUError("MinerU 结果不是 ZIP", operation="download",
                          part_index=part_index, reason="protocol") from exc
    md_path = target_dir / "full.md"
    if not md_path.exists():
        candidates = list(target_dir.rglob("full.md"))
        if not candidates:
            raise MinerUError("MinerU 结果缺少 full.md", operation="result",
                              part_index=part_index, reason="missing")
        md_path = candidates[0]
    return md_path.read_text(encoding="utf-8", errors="ignore")


def _upload_part(client: httpx.Client, url: str, part: Path,
                 part_index: int | None = None) -> None:
    """预签名地址 PUT 上传；存储侧 5xx 视为可重试。"""
    last: Exception | None = None
    for attempt in range(3):
        try:
            with open(part, "rb") as f:
                put = client.put(url, content=f.read())
            if put.status_code < 300:
                return
            last = MinerUError("MinerU 上传失败", operation="upload",
                               part_index=part_index, http_status=put.status_code)
            if put.status_code < 500:
                break
        except httpx.HTTPError as exc:
            last = exc
        time.sleep(5 * (attempt + 1))
    with _at_stage("upload", part_index):
        raise last or MinerUError("MinerU 上传失败", operation="upload")


def _extract_pdf_in_parts(token: str, file_path: Path, result_dir: Path,
                          on_progress: Callable[[int, int], None] | None = None
                          ) -> tuple[str, Path]:
    """超过 MAX_PAGES 的扫描件：首片 15 页 + 其余分片，同一批次提交并行识别，按序合并。"""
    with fitz.open(file_path) as doc:
        page_count = doc.page_count
    plan = _plan_parts(page_count)
    parts = _split_pdf(file_path, result_dir, plan)
    total = len(parts)

    # 断点复用：已完成分片的结果直接读盘，重试不重复消耗 MinerU 额度
    merged: dict[int, str] = {}
    for idx in range(total):
        cached = result_dir / f"part_{idx:02d}" / "full.md"
        if cached.exists():
            merged[idx] = cached.read_text(encoding="utf-8", errors="ignore")
    if on_progress:
        on_progress(len(merged), total)

    pending = [idx for idx in range(total) if idx not in merged]
    if pending:
        names = {parts[idx].name: idx for idx in pending}
        headers = _authorization(token)
        with httpx.Client(timeout=180.0) as client:
            data = _batch_request(client, headers,
                                  files=[{"name": name, "is_ocr": True} for name in names])
            batch_id = data.get("batch_id")
            urls = data.get("file_urls") or []
            if not batch_id or len(urls) != len(pending):
                raise MinerUError("MinerU 缺少上传链接", operation="submit", reason="protocol")
            _record_batch(result_dir, batch_id)
            for idx, url in zip(pending, urls):
                _upload_part(client, url, parts[idx], idx)

            deadline = time.monotonic() + min(3600, max(POLL_TIMEOUT, 240 * len(pending)))
            while time.monotonic() < deadline and len(merged) < total:
                data = _batch_request(client, headers, batch_id=batch_id)
                for item in data.get("extract_result") or []:
                    name = item.get("file_name") or ""
                    idx = names.get(name)
                    if idx is None or idx in merged:
                        continue
                    if item.get("state") == "done":
                        zip_url = item.get("full_zip_url")
                        if not isinstance(zip_url, str) or not zip_url:
                            raise MinerUError("MinerU 缺少结果链接", operation="download",
                                              part_index=idx, reason="protocol")
                        merged[idx] = _download_part_md(
                            client, zip_url, result_dir / f"part_{idx:02d}", idx
                        )
                        if on_progress:
                            on_progress(len(merged), total)
                    elif item.get("state") == "failed":
                        raise _task_failure(item, idx)
                time.sleep(POLL_INTERVAL)
            if len(merged) < total:
                raise MinerUError("MinerU 分片识别超时", operation="poll", reason="timeout")

    merged_md = "\n\n".join(merged[i] for i in range(total))
    md_path = result_dir / "full.md"
    md_path.write_text(merged_md, encoding="utf-8")
    return merged_md, result_dir
