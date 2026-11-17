"""Build a deployment ZIP from a pinned Git commit and compiled frontend assets."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
import zipfile


SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-((?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*))?"
    r"(?:\+([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?",
    re.ASCII,
)
REQUIRED = frozenset({
    "backend/app/main.py", "backend/alembic/env.py", "backend/alembic/script.py.mako",
    "backend/alembic.ini", "backend/pyproject.toml", "backend/uv.lock", "backend/README.md",
    "README.md", "openapi.json", "backend/scripts/create_admin.py",
    "backend/app/local_secrets.example.py",
})
OPTIONAL = frozenset({
    "LICENSE", "LICENSE.md", "LICENSE.txt", "NOTICE", "NOTICE.md", "NOTICE.txt",
    "THIRD_PARTY_NOTICES.md", "compose.yaml", "compose.phoenix.yaml",
})
BLOCKED_PARTS = frozenset({
    "data", "cache", "caches", "__pycache__", ".cache", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", ".git", ".venv", "venv", "node_modules", "logs", "uploads", "ocr",
    "avatars", "chroma", "tmp", "temp", "local_secrets.py",
})
BLOCKED_SUFFIXES = frozenset({
    ".db", ".sqlite", ".sqlite3", ".pyc", ".pyo", ".log", ".pem", ".key", ".p12",
    ".pfx", ".db-wal", ".db-shm", ".sqlite-wal", ".sqlite-shm", ".bak",
})

DEPLOY = """# MathCraft 部署包

版本：{version}；Git 提交：{sha}。

本包包含已提交的后端运行源码、Alembic 迁移、依赖锁文件及前端 dist 成品。
不包含 Python 运行时、Python 依赖、Node.js、真实配置、数据库、索引或用户数据。
release.json 列出除自身外的全部文件、字节数与 SHA-256；SHA256SUMS 校验整个 ZIP。
根及后端 README 保留源码说明，其中指向未打包 docs/scripts 的链接或命令不适用本包；
部署时以本文件为准。解压到独立版本目录，升级前备份数据库、文件、索引及加密主密钥。

## 依赖与 Redis

安装符合 backend/pyproject.toml 的 Python（当前至少 3.11）及 uv。
在解压后的顶层目录执行以下 PowerShell 命令；Linux 使用对应 shell 语法：

```powershell
docker compose -f compose.yaml up -d --wait redis
docker compose -f compose.yaml exec redis redis-cli ping
cd backend
uv sync --frozen --no-dev
```

Redis 应返回 PONG；已有 Redis 时直接配置 REDIS_URL，无需 Docker。
compose.yaml 仅负责 Redis，不会启动后端或前端。Phoenix 是可选能力，默认关闭；
需要时另行使用 compose.phoenix.yaml 并安装 `uv sync --frozen --no-dev --extra phoenix`。

## 外置配置与持久数据

由服务管理器注入环境变量，或使用部署目录之外受保护的环境文件并由服务管理器加载。
不要把密钥写入源码、前端静态文件或发布包；应用也支持固定 backend/.env，
如使用此入口，应链接或挂载外置受保护文件，避免每次更新覆盖配置。
至少配置 APP_ENV=production、两个独立且各至少 32 字节的 AUTH_JWT_SECRET 与
AUTH_CODE_SECRET、REDIS_URL、DATABASE_URL、CHROMA_DIR、UPLOAD_DIR、OCR_DIR、AVATAR_DIR。
所有数据目录使用外置可写绝对路径，SQLite 的父目录须预先创建；在 backend/ 下执行命令。
例如 DATABASE_URL=sqlite:///C:/mathcraft-data/mathcraft.db（Linux 为 sqlite:////srv/…）。
UPLOAD_DIR 父目录中的 secret.key 是平台凭据加密主密钥，应与数据库一起备份并跨版本保留。
生产设置 TURNSTILE_ENABLED=true，配置 TURNSTILE_SITE_KEY、TURNSTILE_SECRET_KEY、
TURNSTILE_ALLOWED_HOSTNAMES；CORS_ORIGINS 设置为实际站点的精确 Origin。
关闭 DEV_ACCOUNTS_ENABLED，清空所有 DEV_TEACHER_*、DEV_STUDENT_* 字段。
按需配置 SMTP_*；个人模型凭据由应用设置保存。
Windows 还需将服务进程 TEMP/TMP 指向外置可写临时目录。

## 必需的 local_secrets 模块

所有部署都必须在迁移、管理员初始化和后端启动之前准备 backend/app/local_secrets.py，
后端会无条件导入此模块，即使没有部署默认凭据也不能省略。
真实 local_secrets.py 不打包；包内必须包含已提交的 backend/app/local_secrets.example.py。
样例中的 sk-xxxx 是明显假值，不可作为有效凭据使用。

没有部署默认凭据时，在 backend/ 目录执行以下命令，从样例复制模块并将两项占位值置空；
已有文件或外置挂载时跳过，保留已有配置：

```powershell
if (-not (Test-Path -LiteralPath app/local_secrets.py)) {{
    Copy-Item -LiteralPath app/local_secrets.example.py -Destination app/local_secrets.py
    Set-Content -LiteralPath app/local_secrets.py -Encoding utf8 -Value @(
        'SILICONFLOW_API_KEY = ""'
        'MINERU_DEFAULT_TOKEN = ""'
    )
}}
```

Linux 可复制样例后用编辑器将上述两项改为空字符串。
需要部署默认凭据时，参考样例结构在服务器外置受保护文件中配置，
将其挂载到 backend/app/local_secrets.py，并允许后端服务账号读取；不要覆盖既有真实配置。
该模块不应随版本更新丢失，也不能提交或重新打入发布包。

## 迁移与后端启动

确认外置配置已注入，停止旧服务并完成备份；先在数据副本验证迁移：

```powershell
uv run --frozen --no-dev alembic upgrade head
```

首次部署在迁移成功后，从 backend/ 目录交互创建首个管理员；已有管理员时跳过此步：

```powershell
uv run --frozen --no-dev python scripts/create_admin.py
```

按提示输入登录账号、显示名称及两次初始密码，密码隐藏输入；不要通过命令行传入凭据。
脚本使用相同的外置数据库配置，不覆盖已有账号，不创建默认账号或默认密码。
创建成功后启动后端：

```powershell
uv run --frozen --no-dev uvicorn app.main:app --host 127.0.0.1 `
    --port 8000 --workers 1 --no-proxy-headers
```

后端命令工作目录必须为 backend/。当前链路使用单实例、单 worker，
由服务管理器负责常驻与重启。检查 GET /api/health。
backend/scripts/ 仅包含明确允许的 create_admin.py，不包含其他开发或初始化脚本；
不要执行 README 中未打包的 scripts 命令。已有部署保留账号。

## 前端静态托管与反向代理

将 frontend/dist/ 设置为 Nginx、IIS 或其他静态服务器的站点根目录，
SPA 路由回退至 index.html。必须将 /api 及其子路径、/media 及其子路径代理至
http://127.0.0.1:8000，保留原始路径、查询串和鉴权头，支持 WebSocket 升级及长请求。
API 和媒体路径应先匹配代理，不能落入 SPA 回退。使用 HTTPS，
按上传大小调整代理请求体限额与超时，不通过静态站点暴露 backend/ 或持久数据目录。
前端为 CI 已构建成品，Vite 配置在构建时注入，部署时设置 VITE_* 不会修改这些文件。
上线验证首页及深层路由、/api/health、登录、/media 资源和相关长请求。
"""


def git(repo: Path, *args: str) -> bytes:
    """Read Git objects without exposing command output on failure."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, check=False,
    )
    if result.returncode:
        raise ValueError("Git operation failed: " + args[0])
    return result.stdout


def safe_path(name: str) -> bool:
    """Reject sensitive, runtime and nonportable archive paths before reading files."""
    path = PurePosixPath(name)
    parts = path.parts
    if (not parts or path.is_absolute() or "\\" in name or ":" in name
            or any(part in {".", ".."} for part in name.split("/"))):
        return False
    for part in parts:
        lower = part.lower()
        if (lower in BLOCKED_PARTS or lower.startswith(".env")
                or lower.startswith("local_secrets") and lower != "local_secrets.example.py"
                or lower.endswith(".local") or ".local." in lower
                or lower.startswith(("id_rsa", "id_ed25519"))
                or any(lower.endswith(suffix) for suffix in BLOCKED_SUFFIXES)):
            return False
    return True


def committed_files(repo: Path, sha: str) -> dict[str, bytes]:
    """Collect only whitelisted regular blobs from the verified commit tree."""
    files: dict[str, bytes] = {}
    for record in git(repo, "ls-tree", "-rz", "--full-tree", sha).split(b"\0"):
        if not record:
            continue
        metadata, raw_name = record.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        name = raw_name.decode("utf-8")
        allowed = (name in REQUIRED | OPTIONAL
                   or name.startswith(("backend/app/", "backend/alembic/")))
        if not allowed or not safe_path(name):
            continue
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise ValueError("Non-regular Git entry: " + name)
        files[name] = git(repo, "show", oid)
    missing = REQUIRED - files.keys()
    if missing:
        raise ValueError("Missing committed deployment files: " + ", ".join(sorted(missing)))
    if not any(name.startswith("backend/alembic/versions/") for name in files):
        raise ValueError("Missing committed Alembic revisions")
    return files


def reject_link(path: Path) -> None:
    """Reject symlinks and Windows reparse points, including directory junctions."""
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode)
            or getattr(info, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
        raise ValueError("Symlink/reparse point is forbidden: " + str(path))


def frontend_files(directory: Path) -> dict[str, bytes]:
    """Collect built static assets, rejecting links and local configuration."""
    for parent in (*reversed(directory.parents), directory):
        reject_link(parent)
    if not directory.is_dir() or not (directory / "index.html").is_file():
        raise ValueError("Frontend dist must contain index.html")
    files: dict[str, bytes] = {}
    for base, dirs, names in os.walk(directory, followlinks=False):
        for name in sorted(dirs + names):
            path = Path(base) / name
            reject_link(path)
            relative = path.relative_to(directory).as_posix()
            if not safe_path(relative):
                raise ValueError("Forbidden frontend asset: " + relative)
            if path.is_dir():
                continue
            if not stat.S_ISREG(path.lstat().st_mode):
                raise ValueError("Non-regular frontend asset: " + relative)
            files["frontend/dist/" + relative] = path.read_bytes()
    return files


def build_release(version: str, sha: str, frontend_dir: Path, output_dir: Path) -> Path:
    """Validate inputs and atomically publish a deterministic ZIP and checksum file."""
    if SEMVER.fullmatch(version) is None:
        raise ValueError("--version must be bare SemVer 2.0.0 (no v prefix)")
    if re.fullmatch(r"[0-9a-fA-F]{40}", sha, re.ASCII) is None:
        raise ValueError("--sha must contain exactly 40 hexadecimal characters")
    repo = Path(os.fsdecode(git(Path.cwd(), "rev-parse", "--show-toplevel")).strip())
    head = git(repo, "rev-parse", "HEAD").decode("ascii").strip()
    if head != sha.lower():
        raise ValueError("HEAD does not match --sha")
    frontend_dir = Path(os.path.abspath(frontend_dir))
    output_dir = output_dir.absolute()
    if output_dir.resolve().is_relative_to(frontend_dir.resolve()):
        raise ValueError("Output directory must be outside frontend dist")
    files = committed_files(repo, head)
    files.update(frontend_files(frontend_dir))
    files["DEPLOY.md"] = DEPLOY.format(version=version, sha=head).encode("utf-8")
    manifest = {
        "version": version, "sha": head,
        "files": [
            {"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            for name, data in sorted(files.items())
        ],
    }
    files["release.json"] = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    prefix = "mathcraft-" + version
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / (prefix + ".zip")
    with tempfile.TemporaryDirectory(prefix=".mathcraft-release-", dir=output_dir) as temporary:
        archive = Path(temporary) / destination.name
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for name, data in sorted(files.items()):
                entry = zipfile.ZipInfo(prefix + "/" + name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.create_system = 3
                entry.external_attr = (stat.S_IFREG | 0o644) << 16
                entry.compress_type = zipfile.ZIP_DEFLATED
                bundle.writestr(entry, data)
        with archive.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        sums = Path(temporary) / "SHA256SUMS"
        sums.write_text(f"{digest}  {destination.name}\n", encoding="utf-8", newline="\n")
        os.replace(archive, destination)
        os.replace(sums, output_dir / "SHA256SUMS")
    return destination


def main() -> None:
    """Provide the release builder command line interface."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--frontend-dir", type=Path, default=Path("frontend/dist"))
    parser.add_argument("--output-dir", type=Path, default=Path("release-dist"))
    args = parser.parse_args()
    try:
        archive = build_release(args.version, args.sha, args.frontend_dir, args.output_dir)
    except (ValueError, OSError, UnicodeError) as exc:
        parser.exit(1, f"Release build failed: {exc}\n")
    print(archive)


if __name__ == "__main__":
    main()
