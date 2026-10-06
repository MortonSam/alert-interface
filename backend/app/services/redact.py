"""One redaction for every logged URL, exception message, step outcome and /health value.

Query parameters that carry a credential (token, api_key, apikey, key) and any Authorization header value are replaced
with "***". Apply it at every source (an HTTP client's error) and every sink (a print, a step outcome, /health), so a
vendor URL with a key never reaches a log line or a public response.
"""
from __future__ import annotations

import re
from typing import Any

_QUERY_KEYS = r"(?:token|api_key|apikey|key)"
_QUERY = re.compile(rf"((?:^|[?&\s'\"]){_QUERY_KEYS}=)[^&\s\"'<>)\]]*", re.I)     # a query parameter, or the same shape loose in prose
_HEADER = re.compile(r"(authorization['\"]?\s*[:=]\s*['\"]?)(?:bearer\s+|basic\s+|token\s+)?[^\s,'\"}]+", re.I)
_PARAM_DICT = re.compile(rf"(['\"]{_QUERY_KEYS}['\"]\s*:\s*['\"])[^'\"]*(['\"])", re.I)   # {"token": "..."} in a repr


def redact(value: Any) -> str:
    """The value as text with credentials replaced by ***. Accepts an exception, a URL, a message or anything str() takes."""
    text = str(value) if value is not None else ""
    text = _QUERY.sub(r"\1***", text)
    text = _HEADER.sub(r"\1***", text)
    text = _PARAM_DICT.sub(r"\1***\2", text)
    return text


def redact_deep(value: Any) -> Any:
    """Redact every string inside a nested dict/list/tuple; other values pass through."""
    if isinstance(value, str):
        return redact(value)
    if isinstance(value, dict):
        return {k: redact_deep(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact_deep(v) for v in value]
    return value
