"""Workspace-scoped, integrity-checked archives for completed PDF slices.

Each archive is immutable and addressed by its full SHA-256. A tiny atomic
pointer is written only after extraction and merge validation. The cloud adapter
locks each slice across processes and records known remote task identities.
No API tokens or signed URLs are added to public task metadata. A signed upload
URL is kept separately in a private, expiring transport file for recovery.
Archives may include source copies supplied by the parser.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from uuid import uuid4

from .config import MinerUConfig

_VERSION = "slices-v1"
_MAX_ARCHIVE_BYTES = 500 * 1024 * 1024


def _native(path: Path) -> str:
    """Windows rename/open must also work under long mounted runtime roots."""
    value = str(path.absolute())
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    return "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value


def checkpoint_root() -> Path:
    from MathCraft.services.path_service import get_path_service

    return get_path_service().get_parse_cache_root() / ".mineru-segments"


def job_directory(source: Path, config: MinerUConfig) -> Path:
    digest = hashlib.sha256()
    with source.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    identity = {
        "version": _VERSION,
        "source_sha256": digest.hexdigest(),
        "name": source.name,
        "endpoint": config.api_base_url.rstrip("/"),
        "model": config.model_version,
        "language": config.language,
        "formula": config.enable_formula,
        "table": config.enable_table,
        "ocr": config.is_ocr,
        "pages_per_part": config.max_pages_per_part,
    }
    key = hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
    return checkpoint_root() / key


class SliceCheckpoint:
    def __init__(self, job: Path, start: int, end: int):
        self.directory = job / f"{start}-{end}"
        self.pointer = self.directory / "ready.json"

    def load(self) -> bytes | None:
        try:
            if self.pointer.is_symlink() or self.directory.is_symlink():
                return None
            info = json.loads(self.pointer.read_text(encoding="utf-8"))
            digest = info["sha256"]
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                return None
            archive = Path(_native(self.directory / f"{digest}.zip"))
            if archive.is_symlink() or archive.stat().st_size > _MAX_ARCHIVE_BYTES:
                return None
            data = archive.read_bytes()
            if hashlib.sha256(data).hexdigest() == digest:
                return data
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def save(self, archive: bytes) -> None:
        if len(archive) > _MAX_ARCHIVE_BYTES:
            return
        self.directory.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256(archive).hexdigest()
        self._write(self.directory / f"{digest}.zip", archive)
        self._write(self.pointer, json.dumps({"sha256": digest}).encode())

    def reject(self) -> None:
        """Retain a superseded completion marker; a bad archive must not stay reusable."""
        if self.pointer.exists():
            os.replace(_native(self.pointer), _native(self.pointer.with_name(f"rejected-{uuid4().hex}.json")))

    @staticmethod
    def _write(target: Path, data: bytes) -> None:
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(_native(temporary), _native(target))
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


class RemoteTask:
    """Durable task identity. Only a private transport file may contain a signed URL."""

    def __init__(self, checkpoint: SliceCheckpoint, source: Path):
        self.checkpoint = checkpoint
        self.path = checkpoint.directory / "task.json"
        self.transport = checkpoint.directory / ".transport.json"
        with source.open("rb") as handle:
            self.source_digest = hashlib.file_digest(handle, "sha256").hexdigest()
        self.data = {}
        if self.path.exists():
            from .config import MinerUError
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
                if (self.data.get("schema") != 1
                    or self.data.get("source_digest") != self.source_digest):
                    raise ValueError("identity")
            except (OSError, ValueError, AttributeError) as exc:
                raise MinerUError("云端任务记录损坏或来源身份不符，已保留原记录。",
                                  code="cloud_checkpoint_invalid") from exc

    def save(self, phase: str, **fields) -> None:
        self.checkpoint.directory.mkdir(parents=True, exist_ok=True)
        self.data = {"schema": 1, "request_id": uuid4().hex, "source_digest": self.source_digest,
                     "source_name": self.data.get("source_name", ""), **self.data, **fields,
                     "phase": phase, "updated_at": time.time()}
        SliceCheckpoint._write(self.path, json.dumps(self.data, ensure_ascii=False).encode())

    def remember_upload(self, url: str) -> None:
        self.checkpoint.directory.mkdir(parents=True, exist_ok=True)
        # Kept out of task/progress metadata. POSIX receives owner-only permissions;
        # Windows inherits the configured runtime directory's access control.
        fd, name = tempfile.mkstemp(dir=self.checkpoint.directory, prefix=".transport-")
        temporary = Path(name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"url": url, "expires_at": time.time() + 23 * 3600}, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(_native(temporary), _native(self.transport))
        finally:
            temporary.unlink(missing_ok=True)

    def upload_url(self) -> str:
        from .config import MinerUError
        try:
            value = json.loads(self.transport.read_text(encoding="utf-8"))
            if value["expires_at"] > time.time() and isinstance(value["url"], str):
                return value["url"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        raise MinerUError("已有云端任务尚未上传，上传链接已过期或不可用；未自动重新提交。",
                          code="cloud_upload_expired")
