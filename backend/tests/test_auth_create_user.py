"""旧创建账号命令必须无副作用拒绝，测试不加载应用或共享 conftest。"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


class RetiredCreateUserCommandTests(unittest.TestCase):
    def test_legacy_creation_refuses_without_loading_app_or_opening_database(self) -> None:
        """完整旧命令也不能触达配置/数据库，且不回显任何参数。"""
        with tempfile.TemporaryDirectory(prefix="mathcraft_retired_cli_") as temporary:
            root = Path(temporary)
            script = root / "create_user.py"
            shutil.copyfile(Path(__file__).resolve().parents[1] / "scripts/create_user.py", script)
            sentinel = root / "forbidden-access"
            guard = '''
import importlib.abc
from pathlib import Path
import runpy
import sys

marker = Path(sys.argv[1])
script = sys.argv[2]
sys.argv = [script, *sys.argv[3:]]

class RejectApplication(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"app", "sqlalchemy", "redis"}:
            marker.write_text("forbidden import", encoding="utf-8")
            raise RuntimeError("application access forbidden")

def reject_database(event, args):
    if event == "sqlite3.connect":
        marker.write_text("forbidden connection", encoding="utf-8")
        raise RuntimeError("database access forbidden")

sys.meta_path.insert(0, RejectApplication())
sys.addaudithook(reject_database)
runpy.run_path(script, run_name="__main__")
'''
            private = ["fake-legacy-account", "Fake-CLI-password-123!", "测试私密姓名",
                       "fake-number-0001", "fake-private@example.invalid"]
            args = ["--account", private[0], "--password", private[1], "--role", "student",
                    "--name", private[2], "--user-no", private[3], "--email", private[4]]
            env = {key: value for key, value in os.environ.items()
                   if not key.startswith(("PYTHON", "DATABASE", "REDIS", "DEV_", "APP_"))}
            env["PYTHONUTF8"] = "1"
            result = subprocess.run(
                [sys.executable, "-c", guard, str(sentinel), str(script), *args],
                cwd=root, env=env, capture_output=True, text=True, encoding="utf-8",
                timeout=10, check=False,
            )
            output = result.stdout + result.stderr
            self.assertFalse(sentinel.exists(), output)
            self.assertEqual(result.returncode, 2, output)
            self.assertIn("公开注册", output)
            self.assertIn("seed.py", output)
            self.assertIn("development", output)
            self.assertIn("dev_accounts_enabled", output)
            self.assertNotIn("Traceback", output)
            for value in private:
                self.assertNotIn(value, output)



    def test_empty_help_and_malformed_arguments_only_show_fixed_guidance(self) -> None:
        """帮助和无效参数也不能触发旧解析器回显。"""
        script = Path(__file__).resolve().parents[1] / "scripts/create_user.py"
        for args in ([], ["--help"], ["--password"], ["--Fake-secret-argument-123!"]):
            with self.subTest(args=args):
                result = subprocess.run(
                    [sys.executable, "-I", "-X", "utf8", str(script), *args],
                    capture_output=True, text=True, encoding="utf-8", timeout=10, check=False,
                )
                self.assertEqual(result.returncode, 2)
                self.assertIn("公开注册", result.stderr)
                self.assertNotIn("Fake-secret-argument-123!", result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
