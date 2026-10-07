"""Old symbols resolve to the ticker's current one. Read from ticker_aliases, cached briefly per process."""
from __future__ import annotations

import time

from sqlalchemy import text

CACHE_SECONDS = 300
_cache: dict[str, str] = {}
_loaded_at: float | None = None     # None: never loaded (or reset), so the next call reads the table whatever the clock says


async def alias_map(session, now: float | None = None) -> dict[str, str]:
    """The old-to-current symbol map, read from ticker_aliases on the first call and again once CACHE_SECONDS have passed.
    The first load never depends on the clock's value: time.monotonic() counts from boot, and comparing it with a zero
    sentinel skipped every load in a process younger than CACHE_SECONDS (a freshly booted host resolved no alias for five minutes)."""
    global _cache, _loaded_at
    now = now if now is not None else time.monotonic()
    if _loaded_at is None or now - _loaded_at > CACHE_SECONDS:
        rows = (await session.execute(text("SELECT old_symbol, symbol FROM ticker_aliases"))).all()
        _cache = {o.upper(): n.upper() for o, n in rows}
        _loaded_at = now
    return _cache


def reset_cache() -> None:
    global _loaded_at
    _loaded_at = None


async def resolve_symbol(session, symbol: str) -> str:
    """The current symbol for `symbol`, following aliases; the input when none applies."""
    aliases = await alias_map(session)
    seen, cur = set(), symbol.upper()
    while cur in aliases and cur not in seen:
        seen.add(cur)
        cur = aliases[cur]
    return cur


def redirect_path(path: str, aliases: dict[str, str]) -> str | None:
    """The path with any segment that is an old symbol replaced by the current one; None when nothing changes."""
    parts = path.split("/")
    out = [aliases.get(p.upper(), p) if p.upper() in aliases else p for p in parts]
    return "/".join(out) if out != parts else None
