"""认证密钥 CLI 的无副作用边界；只用假密钥，不加载应用或共享夹具。"""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import importlib.util
from io import StringIO
from pathlib import Path
from types import ModuleType
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/generate_auth_secrets.py"


def load_script() -> ModuleType:
    """从文件加载独立命令，不把后端应用加入导入路径。"""
    spec = importlib.util.spec_from_file_location("generate_auth_secrets", SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("无法加载密钥生成脚本")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GenerateAuthSecretsTests(unittest.TestCase):
    def test_import_does_not_generate_or_print_keys(self) -> None:
        """导入不能轮换密钥或泄露终端输出。"""
        output = StringIO()
        with patch("secrets.token_urlsafe") as generate, redirect_stdout(output):
            load_script()
        generate.assert_not_called()
        self.assertEqual(output.getvalue(), "")

    def test_help_does_not_generate_keys(self) -> None:
        """查看用法不生成配置。"""
        module = load_script()
        with patch("secrets.token_urlsafe") as generate, redirect_stdout(StringIO()):
            with self.assertRaises(SystemExit) as result:
                module.main(["--help"])
        self.assertEqual(result.exception.code, 0)
        generate.assert_not_called()

    def test_generation_uses_independent_entropy_and_leaves_configuration_untouched(self) -> None:
        """运行时禁止文件访问，且只输出假密钥，确认两种用途独立生成。"""
        module = load_script()
        output = StringIO()
        fake_jwt = "fake-jwt-secret-not-for-production"
        fake_code = "fake-code-secret-not-for-production"
        with (
            patch("secrets.token_urlsafe", side_effect=[fake_jwt, fake_code]) as generate,
            patch("builtins.open", side_effect=AssertionError("命令不应读写配置")),
            patch("io.open", side_effect=AssertionError("命令不应读写配置")),
            redirect_stdout(output),
        ):
            self.assertEqual(module.main([]), 0)
        self.assertEqual(generate.call_args_list, [unittest.mock.call(48), unittest.mock.call(48)])
        lines = output.getvalue().splitlines()
        self.assertIn(f"AUTH_JWT_SECRET={fake_jwt}", lines)
        self.assertIn(f"AUTH_CODE_SECRET={fake_code}", lines)
        self.assertIn("backend/.env", output.getvalue())
        self.assertIn("手工保存", output.getvalue())
        self.assertIn("刷新会话", output.getvalue())

    def test_invalid_arguments_do_not_generate_keys(self) -> None:
        """参数错误不能悄悄生成另一组密钥。"""
        module = load_script()
        with patch("secrets.token_urlsafe") as generate, redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as result:
                module.main(["--write"])
        self.assertEqual(result.exception.code, 2)
        generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
