"""Build a Trade drafts, kept for the rest of their options day (Sam, 2026-11-02): the same symbol, direction, risk level and
proposed target on the same stored chain (its trading day and the expiration the draft uses) returns the draft already written,
for every visitor, with no model call, no draft slot spent and no AI spend. A new chain (the courier's next session) is a new key.

A served copy keeps what was drafted (strikes, mids, reasoning, its own generated_at) and takes this request's stock price:
the quote fields of its fact block (the stock now, its time, basis and delay) are this request's, never the first visitor's.
Keys live in system_metadata as "draft_cache:{chain day}:{SYMBOL}:{direction}:{risk}:{expiration}:{target}:v{DRAFT_CACHE_VERSION}";
a write drops keys whose chain day is more than KEEP_DAYS old.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import text

from app.services.system_metadata_service import get_value, set_value

PREFIX = "draft_cache"
DRAFT_CACHE_VERSION = 1      # bump when a draft's content or shape changes, so no older draft is served
KEEP_DAYS = 10
QUOTE_FIELDS = {"quote_price": "current_price", "price_as_of": "price_as_of", "quote_basis": "quote_basis",
                "delay_minutes": "delay_minutes"}     # fact block field: the gathered data's field it is taken from


def chain_day(chain_last_trade: str | None) -> str | None:
    """Pure: the chain's trading day (YYYY-MM-DD) from its last-trade stamp, None without one."""
    if not chain_last_trade:
        return None
    day = str(chain_last_trade)[:10]
    try:
        date.fromisoformat(day)
    except ValueError:
        return None
    return day


def key_for(symbol: str, direction: str, aggressiveness: str, chain_last_trade: str | None, expiration: str | None,
            proposed_target: float | None) -> str | None:
    """Pure: the cache key, or None when the draft has no chain day or expiration to pin it to (nothing is cached)."""
    day = chain_day(chain_last_trade)
    if not day or not expiration:
        return None
    target = "none" if proposed_target is None else f"{float(proposed_target):.2f}"
    return f"{PREFIX}:{day}:{symbol.upper()}:{direction}:{aggressiveness}:{expiration}:{target}:v{DRAFT_CACHE_VERSION}"


def restamp(draft: dict, data: dict) -> dict:
    """Pure: a stored draft with this request's quote in its fact block."""
    fact = dict(draft.get("fact_block") or {})
    for field, source in QUOTE_FIELDS.items():
        value = data.get(source)
        fact[field] = round(value, 2) if field == "quote_price" and value is not None else value
    return {**draft, "fact_block": fact}


async def get(db, key: str | None) -> dict | None:
    if not key:
        return None
    raw = await get_value(db, key)
    return json.loads(raw) if raw else None


async def put(db, key: str | None, draft: dict, today: date | None = None) -> None:
    if not key:
        return
    await set_value(db, key, json.dumps(draft, default=str))
    cutoff = ((today or date.today()) - timedelta(days=KEEP_DAYS)).isoformat()
    await db.execute(text("DELETE FROM system_metadata WHERE key LIKE :p AND key < :c"), {"p": f"{PREFIX}:%", "c": f"{PREFIX}:{cutoff}"})
    await db.commit()
