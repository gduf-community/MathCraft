"""显式补齐 backend/.env 中的认证密钥，不打印密钥、不加载应用。

用法：在 backend 目录执行 python scripts/init_auth_secrets.py。
文件缺失时使用同目录 .env.example；已有非空密钥永不自动覆盖或轮换。
"""
from __future__ import annotations

import io
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile

from dotenv.parser import parse_stream

BACKEND_DIR = Path(__file__).resolve().parent.parent
SECRET_KEYS = ("AUTH_JWT_SECRET", "AUTH_CODE_SECRET")
_EMPTY_BINDING = re.compile(
    r"(?P<prefix>\s*(?:export[ \t]+)?(?:'[^'\r\n]+'|[^=\s#]+)[ \t]*)"
    r"(?P<equals>=[ \t]*)?(?P<quotes>''|\"\")?"
    r"(?P<suffix>[ \t]*(?:#[^\r\n]*)?(?:\r\n|\n|\r)?\Z)"
)


class InitializationError(ValueError):
    """只携带由脚本定义、可安全输出的固定错误提示。"""


def _prepare_content(content: str) -> tuple[str, int]:
    """先验证完整配置，再补齐两项；保留其他绑定的原文。"""
    bom = "\ufeff" if content.startswith("\ufeff") else ""
    body = content.removeprefix("\ufeff")
    bindings = list(parse_stream(io.StringIO(body)))
    existing: dict[str, str | None] = {}
    for binding in bindings:
        if binding.error:
            raise InitializationError("dotenv 语法错误，未修改配置。")
        key = binding.key.upper() if binding.key else ""
        if key not in SECRET_KEYS:
            continue
        if key in existing:
            raise InitializationError("认证密钥配置项重复，未修改配置。")
        value = binding.value
        if value and ("${" in value or len(value.encode("utf-8")) < 32):
            raise InitializationError("已有认证密钥无效或包含变量插值，未修改配置。")
        existing[key] = value
    if existing.get(SECRET_KEYS[0]) and existing.get(SECRET_KEYS[0]) == existing.get(
        SECRET_KEYS[1]
    ):
        raise InitializationError("两项认证密钥必须不同，未修改配置。")

    generated = {key: secrets.token_urlsafe(48) for key in SECRET_KEYS if not existing.get(key)}
    values = {key: generated.get(key) or existing[key] for key in SECRET_KEYS}
    if values[SECRET_KEYS[0]] == values[SECRET_KEYS[1]]:
        raise InitializationError("密钥生成冲突，未修改配置，请重试。")
    chunks = []
    for binding in bindings:
        original = binding.original.string
        key = binding.key.upper() if binding.key else ""
        if key in generated:
            match = _EMPTY_BINDING.fullmatch(original)
            if match is None:
                raise InitializationError("空认证密钥的格式不受支持，未修改配置。")
            suffix = match["suffix"]
            if suffix.startswith("#"):
                suffix = " " + suffix
            quote = match["quotes"][0] if match["quotes"] else ""
            original = (match["prefix"] + (match["equals"] or "=")
                        + quote + generated[key] + quote + suffix)
        chunks.append(original)
    updated = "".join(chunks)
    newline_match = re.search(r"\r\n|\n|\r", body)
    newline = newline_match[0] if newline_match else "\n"
    for key in SECRET_KEYS:
        if key not in existing:
            if updated and not updated.endswith(("\r", "\n")):
                updated += newline
            updated += f"{key}={generated[key]}{newline}"
    return bom + updated, len(generated)


def _write_configuration(path: Path, original: bytes | None, updated: bytes) -> None:
    """写入同目录临时文件，失败时保留原文件并清理临时内容。"""
    descriptor, name = tempfile.mkstemp(prefix=".env.init-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        if path.is_symlink():
            raise InitializationError("不支持 .env 符号链接，未修改配置。")
        if original is None:
            if path.exists():
                raise InitializationError("配置文件已由其他进程创建，请重试。")
        else:
            if path.read_bytes() != original:
                raise InitializationError("配置文件已被其他进程修改，请重试。")
            # Windows 的只读位会阻止失败后的临时文件清理；替换只读目标本身会失败。
            if os.name != "nt":
                temporary.chmod(stat.S_IMODE(path.stat().st_mode))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def initialize_auth_secrets(backend_dir: Path) -> int:
    """在指定后端目录补齐密钥，返回生成数量；只访问本地配置文件。"""
    path = backend_dir / ".env"
    lock = backend_dir / ".env.init.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        raise InitializationError("初始化锁已存在；确认没有初始化进程后再移除锁重试。") from None
    try:
        os.close(descriptor)
        if path.is_symlink():
            raise InitializationError("不支持 .env 符号链接，未修改配置。")
        original = path.read_bytes() if path.exists() else None
        source = original if original is not None else (backend_dir / ".env.example").read_bytes()
        updated, count = _prepare_content(source.decode("utf-8"))
        encoded = updated.encode("utf-8")
        if original != encoded:
            _write_configuration(path, original, encoded)
        return count
    finally:
        lock.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    """只接受帮助参数，输出固定脱敏结果；不接收命令行凭据。"""
    args = sys.argv[1:] if argv is None else argv
    if args in (["--help"], ["-h"]):
        print(__doc__)
        return 0
    if args:
        print("此命令不接受配置参数；请直接执行初始化。", file=sys.stderr)
        return 2
    try:
        count = initialize_auth_secrets(BACKEND_DIR)
    except UnicodeError:
        print("配置文件不是有效 UTF-8，未修改配置。", file=sys.stderr)
        return 2
    except InitializationError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError:
        print("配置文件读写失败；请检查文件、目录权限和磁盘空间。", file=sys.stderr)
        return 2
    if count:
        print("认证密钥初始化完成，已写入 backend/.env；已有配置已保留。")
    else:
        print("认证密钥已配置，未修改已有配置。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
