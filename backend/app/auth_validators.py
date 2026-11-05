"""认证登录键的纯校验；供 HTTP 与离线审计共用，不加载配置或凭据。"""
import re
import unicodedata


def normalize_email(value: str) -> str:
    """邮箱仅去边空白、大小写折叠，不合并点号或加号标签。"""
    result = value.strip().lower()
    if len(result) > 128 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", result):
        raise ValueError("请输入有效邮箱")
    domain = result.rsplit("@", 1)[1]
    if not all(domain.split(".")):
        raise ValueError("请输入有效邮箱")
    if any(c.isspace() or unicodedata.category(c) == "Cc" for c in result):
        raise ValueError("邮箱包含无效字符")
    return result


def normalize_user_no(value: str | None) -> str | None:
    """保留前导零及大小写；空白等同移除，不接受控制字符。"""
    result = value.strip() if value else None
    if not result:
        return None
    if len(result) > 32 or any(
        c.isspace() or unicodedata.category(c) == "Cc" for c in result
    ):
        raise ValueError("学工号长度为 1–32 且不能包含空白或控制字符")
    return result
