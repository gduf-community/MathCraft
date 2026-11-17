"""Exercise release packaging against disposable Git repositories and static assets."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile


SCRIPT = Path(__file__).with_name("build-release.py").resolve()
SPEC = importlib.util.spec_from_file_location("build_release", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
EMPTY_CONFIG_TEMPLATE = 'SILICONFLOW_API_KEY = ""\nMINERU_DEFAULT_TOKEN = ""\n'


class ReleaseTests(unittest.TestCase):
    """Use the same isolated repository fixture for all packaging scenarios."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="mathcraft-release-test-")
        self.addCleanup(self.clean_temporary)
        self.repo = Path(self.temporary.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Release Test")
        self.git("config", "user.email", "release@example.invalid")
        self.git("config", "core.autocrlf", "false")
        for name in BUILDER.REQUIRED:
            self.write(name, "committed: " + name + "\n")
        self.write("backend/scripts/create_admin.py", '"""Fake admin entrypoint."""\n')
        self.write("backend/scripts/init_auth_secrets.py", "# fake development helper\n")
        self.write("backend/alembic/versions/initial.py", "# migration fixture\n")
        self.write("backend/app/local_secrets.example.py", EMPTY_CONFIG_TEMPLATE)
        self.write("backend/app/services/prompts.json", '{"prompt": "测试"}\n')
        self.write("compose.yaml", "services: {}\n")
        self.write("compose.phoenix.yaml", "services: {}\n")
        self.write("LICENSE", "license fixture\n")
        self.write("THIRD_PARTY_NOTICES.md", "third party fixture\n")
        self.commit()
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.write("frontend/dist/index.html", "<html>fixture</html>\n")
        self.write("frontend/dist/assets/app.js", "console.log('fixture');\n")
        self.write("frontend/dist/assets/app.css", "body { margin: 0; }\n")

    def clean_temporary(self) -> None:
        """Allow Windows a bounded interval to release completed child-process handles."""
        for attempt in range(10):
            try:
                self.temporary.cleanup()
                return
            except PermissionError:
                if attempt == 9:
                    raise
                time.sleep(0.1)

    def git(self, *args: str) -> str:
        """Run fixture-only Git operations with no machine identity dependency."""
        return subprocess.run(
            ["git", "-C", str(self.repo), *args], check=True, capture_output=True,
        ).stdout.decode("utf-8")

    def write(self, name: str, data: str) -> Path:
        """Create a fixture file, including any required parent directories."""
        path = self.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(data, encoding="utf-8", newline="\n")
        return path

    def commit(self) -> None:
        """Commit the fixture's explicit staged and untracked test files."""
        self.git("add", "--all")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "test: fixture")

    def run_builder(self, *extra: str) -> subprocess.CompletedProcess[str]:
        """Run the real CLI with its default directory parameters."""
        return subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "--version", "1.2.3-rc.1+build.007",
             "--sha", self.sha, *extra],
            cwd=self.repo, capture_output=True, text=True, encoding="utf-8",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )

    def archive(self) -> Path:
        """Return the default fixture release archive path."""
        return self.repo / "release-dist/mathcraft-1.2.3-rc.1+build.007.zip"

    def assert_failed(self, result: subprocess.CompletedProcess[str], message: str) -> None:
        """Check validation fails before publishing an output directory."""
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(message, result.stderr)
        self.assertFalse((self.repo / "release-dist").exists())

    def test_manifest_contents_checksums_and_reproducibility(self) -> None:
        """A complete package records byte-accurate provenance and stable output."""
        result = self.run_builder()
        self.assertEqual(result.returncode, 0, result.stderr)
        original = self.archive().read_bytes()
        with zipfile.ZipFile(self.archive()) as bundle:
            prefix = "mathcraft-1.2.3-rc.1+build.007/"
            self.assertTrue(all(name.startswith(prefix) for name in bundle.namelist()))
            manifest = json.loads(bundle.read(prefix + "release.json"))
            self.assertEqual(manifest["version"], "1.2.3-rc.1+build.007")
            self.assertEqual(manifest["sha"], self.sha)
            paths = {entry["path"] for entry in manifest["files"]}
            self.assertEqual(paths, {name.removeprefix(prefix) for name in bundle.namelist()}
                             - {"release.json"})
            self.assertTrue(BUILDER.REQUIRED <= paths)
            self.assertIn("backend/scripts/create_admin.py", BUILDER.REQUIRED)
            self.assertIn("backend/app/local_secrets.example.py", BUILDER.REQUIRED)
            self.assertEqual(bundle.read(prefix + "backend/app/local_secrets.example.py"),
                             EMPTY_CONFIG_TEMPLATE.encode("utf-8"))
            template_module = ast.parse(
                bundle.read(prefix + "backend/app/local_secrets.example.py").decode("utf-8"),
            )
            self.assertEqual(len(template_module.body), 2)
            template_values = {
                target.id: ast.literal_eval(statement.value)
                for statement in template_module.body if isinstance(statement, ast.Assign)
                for target in statement.targets if isinstance(target, ast.Name)
            }
            self.assertEqual(template_values,
                             {"SILICONFLOW_API_KEY": "", "MINERU_DEFAULT_TOKEN": ""})
            self.assertNotIn("backend/app/local_secrets.py", paths)
            self.assertEqual({name for name in paths if name.startswith("backend/scripts/")},
                             {"backend/scripts/create_admin.py"})
            self.assertEqual(bundle.read(prefix + "backend/scripts/create_admin.py"),
                             b'"""Fake admin entrypoint."""\n')
            self.assertTrue({"DEPLOY.md", "compose.yaml", "compose.phoenix.yaml", "LICENSE",
                             "THIRD_PARTY_NOTICES.md", "frontend/dist/index.html",
                             "frontend/dist/assets/app.js", "frontend/dist/assets/app.css",
                             "backend/app/local_secrets.example.py",
                             "backend/app/services/prompts.json"} <= paths)
            for entry in manifest["files"]:
                data = bundle.read(prefix + entry["path"])
                self.assertEqual(entry["size"], len(data))
                self.assertEqual(entry["sha256"], hashlib.sha256(data).hexdigest())
            deploy = bundle.read(prefix + "DEPLOY.md").decode("utf-8")
            for expected in ("uv sync --frozen --no-dev", "alembic upgrade head", "Redis",
                             "app.main:app", "/api", "/media", "外置", "Python 运行时",
                             "uv run --frozen --no-dev python scripts/create_admin.py",
                             "已有管理员时跳过", "密码隐藏输入",
                             "backend/scripts/ 仅包含明确允许的 create_admin.py"):
                self.assertIn(expected, deploy)
            self.assertNotIn("包中不包含 backend/scripts", deploy)
            self.assertLess(deploy.index("alembic upgrade head"),
                            deploy.index("python scripts/create_admin.py"))
            self.assertLess(deploy.index("python scripts/create_admin.py"),
                            deploy.index("uvicorn app.main:app"))
            self.assertIn("所有部署都必须", deploy)
            self.assertIn("即使没有部署默认凭据也不能省略", deploy)
            self.assertIn("已有文件或外置挂载时跳过", deploy)
            self.assertIn("服务器外置受保护文件", deploy)
            self.assertIn("sk-xxxx 是明显假值", deploy)
            prepare_module = "Copy-Item -LiteralPath app/local_secrets.example.py"
            self.assertIn(prepare_module + " -Destination app/local_secrets.py", deploy)
            self.assertIn("if (-not (Test-Path -LiteralPath app/local_secrets.py)) {", deploy)
            self.assertIn("Set-Content -LiteralPath app/local_secrets.py", deploy)
            for setting in ("SILICONFLOW_API_KEY", "MINERU_DEFAULT_TOKEN"):
                self.assertIn(f"'{setting} = \"\"'", deploy)
            self.assertLess(deploy.index(prepare_module), deploy.index("alembic upgrade head"))
        checksum = (self.repo / "release-dist/SHA256SUMS").read_text(encoding="utf-8")
        self.assertEqual(checksum, hashlib.sha256(original).hexdigest()
                         + "  " + self.archive().name + "\n")
        self.assertEqual(self.run_builder().returncode, 0)
        self.assertEqual(original, self.archive().read_bytes())
        self.assertEqual(sorted(path.name for path in self.archive().parent.iterdir()),
                         ["SHA256SUMS", self.archive().name])

    def test_committed_sources_ignore_worktree_and_index(self) -> None:
        """Even staged edits and deleted workspace files cannot change source blobs."""
        self.write("backend/app/main.py", "staged replacement\n")
        self.git("add", "backend/app/main.py")
        self.write("backend/app/main.py", "workspace replacement\n")
        self.write("backend/scripts/create_admin.py", "staged admin replacement\n")
        self.git("add", "backend/scripts/create_admin.py")
        self.write("backend/scripts/create_admin.py", "workspace admin replacement\n")
        self.write("backend/app/local_secrets.example.py", "# staged template replacement\n")
        self.git("add", "backend/app/local_secrets.example.py")
        self.write("backend/app/local_secrets.example.py", "# workspace template replacement\n")
        (self.repo / "backend/uv.lock").unlink()
        self.write("backend/app/untracked.py", "untracked\n")
        result = self.run_builder()
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.archive()) as bundle:
            prefix = "mathcraft-1.2.3-rc.1+build.007/"
            self.assertEqual(bundle.read(prefix + "backend/app/main.py"),
                             b"committed: backend/app/main.py\n")
            self.assertEqual(bundle.read(prefix + "backend/scripts/create_admin.py"),
                             b'"""Fake admin entrypoint."""\n')
            self.assertEqual(bundle.read(prefix + "backend/app/local_secrets.example.py"),
                             EMPTY_CONFIG_TEMPLATE.encode("utf-8"))
            self.assertIn(prefix + "backend/uv.lock", bundle.namelist())
            self.assertNotIn(prefix + "backend/app/untracked.py", bundle.namelist())

    def test_tracked_and_untracked_sensitive_files_are_excluded(self) -> None:
        """Sensitive names are excluded before blob reads, even when committed."""
        forbidden = [
            "backend/app/local_secrets.py",
            "backend/app/.env", "backend/app/nested/.env.production",
            "backend/app/nested/local_secrets.backup.py", "backend/app/config.local.json",
            "backend/app/data/store.json", "backend/app/__pycache__/main.pyc",
            "backend/app/store.db", "backend/app/store.sqlite3", "backend/app/secret.key",
            "backend/alembic/.env", "backend/alembic/cache/state.json",
            "backend/alembic/store.db-wal", "backend/.env", "backend/.env.example",
            "backend/scripts/extra.py", "frontend/src/main.tsx", "unlisted.yaml",
        ]
        for name in forbidden:
            self.write(name, "FAKE_SENSITIVE_FIXTURE\n")
        self.commit()
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.write("backend/app/untracked-secret.py", "FAKE_UNTRACKED\n")
        self.write("backend/app/local_secrets.py", "FAKE_WORKSPACE_ONLY\n")
        result = self.run_builder()
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(self.archive()) as bundle:
            for name in bundle.namelist():
                data = bundle.read(name)
                self.assertNotIn(b"FAKE_SENSITIVE_FIXTURE", data)
                self.assertNotIn(b"FAKE_UNTRACKED", data)
                self.assertNotIn(b"FAKE_WORKSPACE_ONLY", data)
        # Also prove the collector never asks Git for a sensitive blob's contents.
        original_git = BUILDER.git
        secret_oid = self.git("rev-parse", self.sha + ":backend/app/local_secrets.py").strip()
        with patch.object(BUILDER, "git", wraps=original_git) as read_git:
            BUILDER.committed_files(self.repo, self.sha)
        self.assertNotIn((self.repo, "show", secret_oid),
                         [call.args for call in read_git.call_args_list])
        self.assertFalse(BUILDER.safe_path("backend/app/LOCAL_SECRETS.PY"))

    def test_missing_dist_or_entrypoint_fails(self) -> None:
        """Neither absent output nor an incomplete build is releasable."""
        self.assert_failed(self.run_builder("--frontend-dir", "absent"), "Release build failed")
        (self.repo / "frontend/dist/index.html").unlink()
        self.assert_failed(self.run_builder(), "index.html")

    def test_sha_mismatch_and_malformed_sha_fail(self) -> None:
        """Require a full commit identity matching HEAD, before writing artifacts."""
        self.assert_failed(self.run_builder("--sha", "0" * 40), "HEAD does not match")
        for sha in (self.sha[:12], "g" * 40, "HEAD"):
            with self.subTest(sha=sha):
                self.assert_failed(self.run_builder("--sha", sha), "40 hexadecimal")

    def test_semver_accepted_and_rejected(self) -> None:
        """Cover SemVer numeric identifiers, ASCII grammar and full-string matching."""
        valid = ["0.0.0", "1.2.3", "10.20.30", "1.0.0-0", "1.0.0-alpha.1",
                 "1.0.0-01alpha", "1.0.0--", "1.0.0+001", "1.2.3-rc.1+build.007"]
        invalid = ["v1.2.3", "1.2", "1.2.3.4", "01.2.3", "1.02.3", "1.2.03",
                   "1.2.3-01", "1.2.3-alpha.01", "1.2.3-", "1.2.3+", "1.2.3-a..b",
                   "1.2.3+a..b", "1.2.3+build+more", "1.2.3_a", "1.2.3-测试",
                   "１.2.3", "1.2.3\n", " 1.2.3", "1.2.3/../../escape"]
        for version in valid:
            with self.subTest(version=version):
                self.assertIsNotNone(BUILDER.SEMVER.fullmatch(version))
        for version in invalid:
            with self.subTest(version=version):
                self.assert_failed(self.run_builder("--version", version), "bare SemVer")

    def test_frontend_local_config_fails(self) -> None:
        """Local configuration inside dist cannot silently leak into a release."""
        for name in (".env", ".env.production", "settings.local.json", "local_secrets.py",
                     "data/store.json", "cache/state.json", "private.pem"):
            with self.subTest(name=name):
                path = self.write("frontend/dist/" + name, "FAKE_ONLY\n")
                self.assert_failed(self.run_builder(), "Forbidden frontend asset")
                path.unlink()
                if "/" in name:
                    path.parent.rmdir()

    def test_git_symlink_is_rejected_without_windows_symlink_privileges(self) -> None:
        """Git symlink modes are validated even on Windows without native symlinks."""
        oid = subprocess.run(
            ["git", "-C", str(self.repo), "hash-object", "-w", "--stdin"],
            input=b"../../outside.py", capture_output=True, check=True,
        ).stdout.decode().strip()
        self.git("update-index", "--add", "--cacheinfo", "120000", oid,
                 "backend/app/link.py")
        self.git("-c", "commit.gpgsign=false", "commit", "-qm", "test: symlink")
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.assert_failed(self.run_builder(), "Non-regular Git entry")

    def test_frontend_symlink_is_rejected(self) -> None:
        """Reject internal and escaping file, directory and dist-root symlinks."""
        target = self.write("outside.txt", "FAKE_OUTSIDE\n")
        link = self.repo / "frontend/dist/link.txt"
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("Native symlinks require Windows Developer Mode or privileges")
        self.assert_failed(self.run_builder(), "Symlink/reparse")
        link.unlink()
        link.symlink_to(self.repo / "frontend/dist/index.html")
        self.assert_failed(self.run_builder(), "Symlink/reparse")
        link.unlink()
        link.symlink_to(self.repo, target_is_directory=True)
        self.assert_failed(self.run_builder(), "Symlink/reparse")
        link.unlink()
        root_link = self.repo / "linked-dist"
        root_link.symlink_to(self.repo / "frontend/dist", target_is_directory=True)
        self.assert_failed(self.run_builder("--frontend-dir", str(root_link)), "Symlink/reparse")

    def test_output_cannot_contaminate_frontend(self) -> None:
        """Avoid collecting previous artifacts as static frontend files."""
        self.assert_failed(self.run_builder("--output-dir", "frontend/dist/release"),
                           "outside frontend dist")

    @unittest.skipUnless(sys.platform == "win32", "Windows junction test")
    def test_frontend_windows_junction_is_rejected(self) -> None:
        """Exercise real Windows directory reparse points without symlink privileges."""
        target = self.repo / "outside-assets"
        target.mkdir()
        link = self.repo / "frontend/dist/linked-assets"
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, "Cannot create fixture directory junction")
        try:
            self.assert_failed(self.run_builder(), "Symlink/reparse")
        finally:
            link.rmdir()

    def test_missing_committed_backend_file_fails(self) -> None:
        """A working-tree replacement cannot conceal an incomplete Git commit."""
        self.git("rm", "-q", "backend/uv.lock")
        self.commit()
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.write("backend/uv.lock", "untracked lock\n")
        self.assert_failed(self.run_builder(), "Missing committed deployment files")

    def test_missing_committed_admin_cannot_be_replaced_by_worktree_or_index(self) -> None:
        """First-deployment support must exist in HEAD, not just in a local checkout."""
        self.assert_required_committed("backend/scripts/create_admin.py")

    def test_missing_committed_secrets_example_cannot_be_replaced_locally(self) -> None:
        """Every deployment needs a committed template, even without default credentials."""
        self.assert_required_committed("backend/app/local_secrets.example.py")

    def assert_required_committed(self, name: str) -> None:
        """Reject missing required blobs despite untracked or staged local replacements."""
        self.git("rm", "-q", name)
        self.commit()
        self.sha = self.git("rev-parse", "HEAD").strip()
        self.write(name, "# fake untracked replacement\n")
        self.assert_failed(self.run_builder(),
                           "Missing committed deployment files: " + name)
        self.git("add", name)
        self.assert_failed(self.run_builder(),
                           "Missing committed deployment files: " + name)


if __name__ == "__main__":
    unittest.main()
