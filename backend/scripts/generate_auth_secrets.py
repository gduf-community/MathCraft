"""生成供操作者手工填入 backend/.env 的认证密钥，不加载应用或读写配置。"""
from __future__ import annotations

import argparse
from collections.abc import Sequence
import secrets


def main(argv: Sequence[str] | None = None) -> int:
    """显式执行时生成两个独立的 48 随机字节密钥并提示保存位置。"""
    parser = argparse.ArgumentParser(
        description="生成生产认证密钥；仅使用 Python 标准库，不读取或修改 .env。",
        epilog="SMTP 和 Turnstile 凭据请向对应服务商获取，本脚本不生成第三方凭据。",
    )
    parser.parse_args(argv)
    # 先生成完整密钥对，再输出，避免生成异常时展示半份配置。
    jwt_secret = secrets.token_urlsafe(48)
    code_secret = secrets.token_urlsafe(48)
    print("请将下面两行分别填入 backend/.env 的同名配置项：")
    print()
    print(f"AUTH_JWT_SECRET={jwt_secret}")
    print(f"AUTH_CODE_SECRET={code_secret}")
    print()
    print("本脚本未读取、创建或修改 .env，请手工保存；已有配置文件请勿整份覆盖。")
    print("生产同时设置 APP_ENV=production、DEV_ACCOUNTS_ENABLED=false，清空开发账号字段。")
    print("SMTP/Turnstile、域名与其他必填配置见 README.md 的生产配置说明。")
    print("请在受控终端运行，不将输出提交到 Git、共享日志或聊天。")
    print("同一部署的所有实例使用同一组密钥，不要在每次启动时重新生成。")
    print("轮换 JWT 密钥会使旧访问令牌失效；轮换验证码密钥会使旧邮件码失效。")
    print("轮换不等同于撤销数据库刷新会话；相关会话按既有撤销流程处理。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
