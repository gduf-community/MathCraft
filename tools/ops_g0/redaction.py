"""Conservative synthetic-test redaction before any export buffer is populated."""

from collections.abc import Iterable
import json
import re
from urllib.parse import unquote, urlsplit

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
_FIELD_PATTERN = "|".join(re.escape(key).replace("_", r"[_-]?") for key in sorted(_SECRET_KEYS))
_ASSIGNMENT = re.compile(
    r"""(?i)(["']?(?:""" + _FIELD_PATTERN + r""")["']?)\s*([=:])\s*"""
    r"""(?:"(?:\\.|[^"\\])*(?:"|$)|'(?:\\.|[^'\\])*(?:'|$)|[^\s&;,"'<>]+)"""
)
_ROUTE_KEYS = {"route", "http.route", "path", "url.path", "http.target", "url.full", "http.url"}
_SENSITIVE_PATHS = ("/api/auth", "/api/users/me/model-settings", "/api/users/me/password")


def has_sensitive_route(fields: Iterable[tuple[str, object]]) -> bool:
    """Recognize sensitive paths in both route fields and full URL attributes."""
    for key, value in fields:
        if key.lower() not in _ROUTE_KEYS or not isinstance(value, str):
            continue
        for _ in range(2):
            value = unquote(value)
        try:
            path = urlsplit(value).path
        except ValueError:
            # A malformed URL cannot establish that its body is safe to retain.
            return True
        if any(sensitive in path for sensitive in _SENSITIVE_PATHS):
            return True
    return False


def is_body_key(key: str) -> bool:
    """Share body-field recognition across JSON and OTLP representations."""
    key = key.lower()
    return key in {"request", "response", "body", "input", "output"} or key.startswith(
        (
            "input.",
            "output.",
            "llm.input_",
            "llm.output_",
            "http.request.body",
            "http.response.body",
            "request.body",
            "response.body",
        )
    )


def sensitive_key(key: str) -> bool:
    """Recognize credential fields without hiding numeric token-count metrics."""
    return key.rsplit(".", 1)[-1].lower().replace("-", "_") in _SECRET_KEYS


def clean_text(
    value: str, limit: int = 4096, *, exclude_body: bool = False, depth: int = 0
) -> str:
    """Redact structured credentials and common textual credential forms."""
    if depth > 8:
        return "[DEPTH_LIMIT]"
    text = value[:limit]
    for _ in range(2):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    try:
        parsed = json.loads(text)
    except (ValueError, TypeError, RecursionError):
        # OTel may already have truncated an attribute. Partial structured content
        # (including escaped nested JSON) cannot be safely parsed field by field.
        if text.lstrip().startswith(("{", "[", '"')) or r"\"" in text:
            return REDACTED
        parsed = None
    if isinstance(parsed, (dict, list)):
        return json.dumps(
            clean_value(parsed, depth + 1, exclude_body=exclude_body),
            ensure_ascii=False,
            separators=(",", ":"),
        )[:limit]
    if isinstance(parsed, str) and parsed != text:
        return clean_text(parsed, limit, exclude_body=exclude_body, depth=depth + 1)
    text = re.sub(
        r"-----BEGIN [^-\n]*PRIVATE KEY-----[\s\S]*?(?:-----END [^-\n]*PRIVATE KEY-----|$)",
        REDACTED,
        text,
    )
    text = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer " + REDACTED, text)
    text = re.sub(r"(?im)\b(?:set-cookie|cookie|authorization)\s*:\s*[^\r\n]+", REDACTED, text)
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}", REDACTED, text)
    text = re.sub(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b", REDACTED, text)
    return _ASSIGNMENT.sub(lambda match: match[1] + match[2] + REDACTED, text)


def clean_value(value: object, depth: int = 0, *, exclude_body: bool = False) -> object:
    """Return a bounded copy; nested unknown objects are excluded rather than repr'd."""
    if depth > 8:
        return "[DEPTH_LIMIT]"
    if isinstance(value, dict):
        excluded = exclude_body or has_sensitive_route((str(key), item) for key, item in value.items())
        return {
            str(key): REDACTED
            if sensitive_key(str(key))
            or (excluded and is_body_key(str(key)))
            else clean_value(item, depth + 1, exclude_body=excluded)
            for key, item in list(value.items())[:64]
        }
    if isinstance(value, (list, tuple)):
        return [clean_value(item, depth + 1, exclude_body=exclude_body) for item in value[:64]]
    if isinstance(value, str):
        return clean_text(value, exclude_body=exclude_body, depth=depth)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return "[UNSUPPORTED_VALUE]"
