"""In-process options chain cache.

Keyed by (symbol_upper, expiration_str).  A fresh yfinance fetch is issued only
when the entry is absent or older than CHAIN_TTL_SECONDS.  All callers within
the TTL window receive the *same* dict and the same ``fetched_at`` timestamp so
API responses reflect when the data was actually retrieved, not when the request
was served.
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.services.yfinance_client import YFinanceClient

CHAIN_TTL_SECONDS = 45


@dataclass
class ChainEntry:
    chain: dict
    fetched_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))


_cache: dict[tuple[str, str], ChainEntry] = {}
_lock = threading.Lock()


async def fetch_chain(
    symbol: str,
    expiration: str,
    loop: asyncio.AbstractEventLoop | None = None,
) -> ChainEntry:
    """Return a ChainEntry for (symbol, expiration), using the cache when fresh."""
    key = (symbol.upper(), expiration)
    now = datetime.now(tz=timezone.utc)

    with _lock:
        entry = _cache.get(key)
        if entry is not None and (now - entry.fetched_at).total_seconds() < CHAIN_TTL_SECONDS:
            return entry  # cache hit — return early, still holding lock briefly

    # Cache miss or stale — fetch outside the lock so other (symbol, exp) pairs
    # aren't serialised behind this potentially slow yfinance call.
    if loop is None:
        loop = asyncio.get_event_loop()

    chain = await loop.run_in_executor(
        None, YFinanceClient.get_option_chain, symbol.upper(), expiration
    )
    new_entry = ChainEntry(chain=chain, fetched_at=datetime.now(tz=timezone.utc))

    with _lock:
        # Another coroutine may have fetched while we were out; keep the newer one.
        existing = _cache.get(key)
        if existing is None or new_entry.fetched_at >= existing.fetched_at:
            _cache[key] = new_entry
            return new_entry
        return existing
