"""MinerU OCR 客户端（v4 API）：扫描版 PDF 上传 → 轮询 → 下载 zip → 取 full.md。

限制：文件 ≤ 200 MB，页数 ≤ 200 页（上传前由调用方校验）。
Token 优先取用户配置，默认用 local_secrets 中的系统 Token。
"""
import io
import math
import time
import zipfile
from pathlib import Path
from typing import Callable

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


class MinerUError(RuntimeError):
    pass


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
    """验证 Token：请求一个必然不存在的批次，401 视为 Token 无效，其余视为有效。"""
    try:
        resp = httpx.get(
            f"{BASE_URL}/extract-results/batch/ping-connection-nonexistent",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )
        if resp.status_code == 401:
            return False, "Token 无效或已过期（401）"
        return True, "Token 有效"
    except Exception as exc:
        return False, f"网络错误：{exc}"


def _check_code(resp: httpx.Response) -> dict:
    resp.raise_for_status()
    body = resp.json()
    if body.get("code") != 0:
        raise MinerUError(f"MinerU 接口错误 code={body.get('code')}: {body.get('msg', '未知错误')}")
    return body.get("data", {})


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

    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(timeout=120.0) as client:
        # 1. 申请上传链接
        data = _check_code(
            client.post(
                f"{BASE_URL}/file-urls/batch",
                headers=headers,
                json={
                    "enable_formula": True,
                    "enable_table": True,
                    "language": "ch",
                    "model_version": MODEL_VERSION,
                    "files": [{"name": file_path.name, "is_ocr": True}],
                },
            )
        )
        batch_id = data.get("batch_id")
        upload_url = (data.get("file_urls") or [None])[0]
        if not batch_id or not upload_url:
            raise MinerUError(f"MinerU 返回缺少 batch_id / file_urls：{data}")

        # 2. PUT 上传文件（预签名 URL，不带鉴权头）
        with open(file_path, "rb") as f:
            put = client.put(upload_url, content=f.read())
        if put.status_code >= 300:
            raise MinerUError(f"文件上传失败 HTTP {put.status_code}")

        # 3. 轮询批次结果
        deadline = time.monotonic() + POLL_TIMEOUT
        result = None
        while time.monotonic() < deadline:
            data = _check_code(client.get(f"{BASE_URL}/extract-results/batch/{batch_id}", headers=headers))
            results = data.get("extract_result") or []
            if results:
                state = results[0].get("state")
                if state == "done":
                    result = results[0]
                    break
                if state == "failed":
                    raise MinerUError(f"MinerU 解析失败：{results[0].get('err_msg', '未知错误')}")
            time.sleep(POLL_INTERVAL)
        if result is None:
            raise MinerUError("MinerU 任务超时（10 分钟）")

        zip_url = result.get("full_zip_url")
        if not zip_url:
            raise MinerUError(f"MinerU 未返回 full_zip_url：{result}")

        # 4. 下载 zip 并解压
        zip_resp = client.get(zip_url)
        zip_resp.raise_for_status()
        result_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(zip_resp.content)) as zf:
            zf.extractall(result_dir)

    md_path = result_dir / "full.md"
    if not md_path.exists():
        # 兼容压缩包内带子目录的情况
        candidates = list(result_dir.rglob("full.md"))
        if not candidates:
            raise MinerUError("OCR 结果中未找到 full.md")
        md_path = candidates[0]
    return md_path.read_text(encoding="utf-8", errors="ignore"), md_path.parent


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


def _download_part_md(client: httpx.Client, zip_url: str, target_dir: Path) -> str:
    """下载单个分片的结果压缩包，解压后返回其 full.md 文本（网络抖动重试三次）。"""
    resp = None
    for attempt in range(3):
        try:
            resp = client.get(zip_url)
            resp.raise_for_status()
            break
        except httpx.HTTPError:
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))
    target_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(target_dir)
    md_path = target_dir / "full.md"
    if not md_path.exists():
        candidates = list(target_dir.rglob("full.md"))
        if not candidates:
            raise MinerUError(f"{target_dir.name} 的 OCR 结果缺少 full.md")
        md_path = candidates[0]
    return md_path.read_text(encoding="utf-8", errors="ignore")


def _upload_part(client: httpx.Client, url: str, part: Path) -> None:
    """预签名地址 PUT 上传；存储侧 5xx 视为可重试。"""
    last: Exception | None = None
    for attempt in range(3):
        try:
            with open(part, "rb") as f:
                put = client.put(url, content=f.read())
            if put.status_code < 300:
                return
            last = MinerUError(f"{part.name} 上传失败 HTTP {put.status_code}")
            if put.status_code < 500:
                break
        except httpx.HTTPError as exc:
            last = exc
        time.sleep(5 * (attempt + 1))
    raise last or MinerUError(f"{part.name} 上传失败")


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
        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(timeout=180.0) as client:
            data = _check_code(
                client.post(
                    f"{BASE_URL}/file-urls/batch",
                    headers=headers,
                    json={
                        "enable_formula": True,
                        "enable_table": True,
                        "language": "ch",
                        "model_version": MODEL_VERSION,
                        "files": [{"name": name, "is_ocr": True} for name in names],
                    },
                )
            )
            batch_id = data.get("batch_id")
            urls = data.get("file_urls") or []
            if not batch_id or len(urls) != len(pending):
                raise MinerUError(f"MinerU 返回缺少 batch_id / file_urls：{data}")
            for idx, url in zip(pending, urls):
                _upload_part(client, url, parts[idx])

            deadline = time.monotonic() + min(3600, max(POLL_TIMEOUT, 240 * len(pending)))
            while time.monotonic() < deadline and len(merged) < total:
                data = _check_code(
                    client.get(f"{BASE_URL}/extract-results/batch/{batch_id}", headers=headers)
                )
                for item in data.get("extract_result") or []:
                    name = item.get("file_name") or ""
                    idx = names.get(name)
                    if idx is None or idx in merged:
                        continue
                    if item.get("state") == "done":
                        merged[idx] = _download_part_md(
                            client, item.get("full_zip_url"), result_dir / f"part_{idx:02d}"
                        )
                        if on_progress:
                            on_progress(len(merged), total)
                    elif item.get("state") == "failed":
                        raise MinerUError(f"{name} 解析失败：{item.get('err_msg', '未知错误')}")
                time.sleep(POLL_INTERVAL)
            if len(merged) < total:
                raise MinerUError(f"MinerU 分片识别超时（{total} 片只完成 {len(merged)} 片）")

    merged_md = "\n\n".join(merged[i] for i in range(total))
    md_path = result_dir / "full.md"
    md_path.write_text(merged_md, encoding="utf-8")
    return merged_md, result_dir
