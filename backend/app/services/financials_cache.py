"""In-process financials cache.

Keyed by symbol (uppercase).  Stores curated metric dicts with a 60-minute
TTL so we don't re-fetch Finnhub /stock/metric on every research-note
generation within the same hour.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

FINANCIALS_TTL_SECONDS = 3600  # 60 minutes

_cache: dict[str, tuple[dict, datetime]] = {}
_lock = threading.Lock()


def get(symbol: str) -> dict | None:
    """Return cached financials dict or None if missing/expired."""
    key = symbol.upper()
    now = datetime.now(tz=timezone.utc)
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        data, fetched_at = entry
        if (now - fetched_at).total_seconds() >= FINANCIALS_TTL_SECONDS:
            return None
        return data


def set(symbol: str, data: dict) -> None:
    """Store a financials dict with the current timestamp."""
    key = symbol.upper()
    now = datetime.now(tz=timezone.utc)
    with _lock:
        _cache[key] = (data, now)
