"""已停用的旧账号创建入口，不解析参数或加载应用配置。

真实用户由管理员通过管理面板开通账号；首个管理员使用 create_admin.py。
开发联调仅使用显式 seed.py，且要求 development 与 dev_accounts_enabled 双门禁。
禁止向本命令传递密码；本兼容入口始终拒绝且不会回显参数。
"""
import sys


def main() -> int:
    """拒绝旧创建旁路，返回固定非零退出码且不连接数据库。"""
    print(
        "旧账号创建命令已停用；请联系管理员开通账号；首个管理员使用 create_admin.py。"
        "开发账号仅通过 seed.py 显式初始化，要求 "
        "app_env=development 且 dev_accounts_enabled=true。"
        "请勿在命令行传递密码。",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
