"""Conservative synthetic-test redaction before any export buffer is populated."""

import json
import re
from urllib.parse import unquote

REDACTED = "[REDACTED]"
_SECRET_KEYS = {
    "apikey",
    "api_key",
    "password",
    "passwd",
    "secret",
    "authorization",
    "cookie",
    "set_cookie",
    "access_token",
    "refresh_token",
    "token",
    "bearer",
    "private_key",
    "client_secret",
    "api_token",
}
_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|password|passwd|secret|access[_-]?token|refresh[_-]?token|"
    r"client[_-]?secret|token)\s*([=:])\s*[^\s&;,\"'<>]+"
)


def sensitive_key(key: str) -> bool:
    """Recognize credential fields without hiding numeric token-count metrics."""
    return key.rsplit(".", 1)[-1].lower().replace("-", "_") in _SECRET_KEYS


def clean_text(value: str, limit: int = 4096) -> str:
    """Redact structured credentials and common textual credential forms."""
    text = value[:limit]
    for _ in range(2):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError):
        parsed = None
    if isinstance(parsed, (dict, list)):
        return json.dumps(clean_value(parsed), ensure_ascii=False, separators=(",", ":"))[:limit]
    text = re.sub(
        r"-----BEGIN [^-\n]*PRIVATE KEY-----[\s\S]*?-----END [^-\n]*PRIVATE KEY-----",
        REDACTED,
        text,
    )
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer " + REDACTED, text)
    text = re.sub(r"(?im)\b(?:set-cookie|cookie|authorization)\s*:\s*[^\r\n]+", REDACTED, text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", REDACTED, text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", REDACTED, text)
    return _ASSIGNMENT.sub(lambda match: match[1] + match[2] + REDACTED, text)


def clean_value(value: object, depth: int = 0) -> object:
    """Return a bounded copy; nested unknown objects are excluded rather than repr'd."""
    if depth > 8:
        return "[DEPTH_LIMIT]"
    if isinstance(value, dict):
        route = str(value.get("route", value.get("http.route", value.get("path", ""))))
        excluded = any(
            path in route
            for path in (
                "/api/auth",
                "/api/users/me/model-settings",
                "/api/users/me/password",
            )
        )
        return {
            str(key): REDACTED
            if sensitive_key(str(key))
            or (excluded and str(key) in {"request", "response", "body", "input", "output"})
            else clean_value(item, depth + 1)
            for key, item in list(value.items())[:64]
        }
    if isinstance(value, (list, tuple)):
        return [clean_value(item, depth + 1) for item in value[:64]]
    if isinstance(value, str):
        return clean_text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[UNSUPPORTED_VALUE]"
