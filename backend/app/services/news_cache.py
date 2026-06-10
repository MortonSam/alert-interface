"""In-process company-news cache.

Keyed by symbol (uppercase).  Stores serialised NewsRead dicts with a
10-minute TTL so the ticker page doesn't hammer Finnhub on every view.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

NEWS_TTL_SECONDS = 600  # 10 minutes

_cache: dict[str, tuple[dict, datetime]] = {}
_lock = threading.Lock()


def get(symbol: str) -> dict | None:
    """Return cached news dict or None if missing/expired."""
    key = symbol.upper()
    now = datetime.now(tz=timezone.utc)
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        data, fetched_at = entry
        if (now - fetched_at).total_seconds() >= NEWS_TTL_SECONDS:
            return None
        return data


def set(symbol: str, data: dict) -> None:
    """Store a news dict with the current timestamp."""
    key = symbol.upper()
    now = datetime.now(tz=timezone.utc)
    with _lock:
        _cache[key] = (data, now)
