"""In-process quote cache.

Keyed by symbol (uppercase).  Stores {price, change, change_pct} dicts with
a 60-second TTL so the home grid doesn't hammer Finnhub on every page view.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

QUOTE_TTL_SECONDS = 60

_cache: dict[str, tuple[dict, datetime]] = {}
_lock = threading.Lock()


def get(symbol: str) -> dict | None:
    """Return cached quote dict or None if missing/expired."""
    key = symbol.upper()
    now = datetime.now(tz=timezone.utc)
    with _lock:
        entry = _cache.get(key)
        if entry is None:
            return None
        data, fetched_at = entry
        if (now - fetched_at).total_seconds() >= QUOTE_TTL_SECONDS:
            return None
        return data


def set(symbol: str, data: dict) -> None:
    """Store a quote dict with the current timestamp."""
    key = symbol.upper()
    now = datetime.now(tz=timezone.utc)
    with _lock:
        _cache[key] = (data, now)
