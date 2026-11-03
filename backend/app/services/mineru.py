"""MinerU OCR 客户端（v4 API）：扫描版 PDF 上传 → 轮询 → 下载 zip → 取 full.md。

限制：文件 ≤ 200 MB，页数 ≤ 200 页（上传前由调用方校验）。
Token 优先取用户配置，默认用 local_secrets 中的系统 Token。
"""
import io
import time
import zipfile
from pathlib import Path

import httpx
import pymupdf as fitz

from app.config import settings

BASE_URL = "https://mineru.net/api/v4"
MODEL_VERSION = "vlm"
MAX_FILE_MB = 200
MAX_PAGES = 200
POLL_INTERVAL = 5
POLL_TIMEOUT = 600  # 10 分钟


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


def extract_pdf(token: str, file_path: Path, result_dir: Path) -> tuple[str, Path]:
    """完整 OCR 流程：申请上传 URL → PUT 文件 → 轮询 → 下载解压 → 读 full.md。

    返回 (markdown 文本, 结果目录)。
    """
    if file_path.stat().st_size > MAX_FILE_MB * 1024 * 1024:
        raise MinerUError(f"文件超过 {MAX_FILE_MB} MB 上限")
    with fitz.open(file_path) as doc:
        if doc.page_count > MAX_PAGES:
            raise MinerUError(f"PDF 超过 {MAX_PAGES} 页上限（当前 {doc.page_count} 页）")

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
