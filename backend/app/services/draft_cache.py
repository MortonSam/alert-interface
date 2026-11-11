"""Build a Trade drafts, kept for the rest of their options day (Sam, 2026-11-02): the same symbol, direction, risk level and
proposed target on the same stored chain (its trading day and the expiration the draft uses) returns the draft already written,
for every visitor, with no model call, no draft slot spent and no AI spend. A new chain (the courier's next session) is a new key.

A served copy keeps what was drafted (strikes, mids, reasoning, its own generated_at) and takes this request's stock price:
the quote fields of its fact block (the stock now, its time, basis and delay) are this request's, never the first visitor's.
Keys live in system_metadata as
"draft_cache:{chain day}:{SYMBOL}:{direction}:{risk}:{expiration}:{target}:v{DRAFT_CACHE_VERSION}-{WORDING}"; a write drops keys
whose chain day is more than KEEP_DAYS old.

No visitor is served a draft the model wrote or one in earlier wording (Sam, 2026-11-11). The key ends in the version and in
WORDING, a stamp of the code that writes a draft (WORDING_SOURCES: its sentences, its rules and its fact block), so a draft kept
under an earlier version or by earlier code is never read again and the next request writes it afresh by rules. And a kept draft
whose model_used is not RULES_MODEL is never served, whatever its key.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text

from app.services.system_metadata_service import get_value, set_value

PREFIX = "draft_cache"
DRAFT_CACHE_VERSION = 2      # 2 (2026-11-11): drafts are written by rules; every v1 draft (three in production, one the model's) is ignored
RULES_MODEL = "deterministic"                 # ThesisDraftRead.model_used of a draft written by rules (routers/thesis)
WORDING_SOURCES = ("services/draft_copy.py", "services/draft_rules.py", "routers/thesis.py")     # under app/: what writes a draft
KEEP_DAYS = 10
QUOTE_FIELDS = {"quote_price": "current_price", "price_as_of": "price_as_of", "quote_basis": "quote_basis",
                "delay_minutes": "delay_minutes"}     # fact block field: the gathered data's field it is taken from


def wording_stamp(sources: list[bytes]) -> str:
    """Pure: eight hex characters of the SHA-256 of the sources, in order."""
    h = hashlib.sha256()
    for src in sources:
        h.update(src)
        h.update(b"\0")
    return h.hexdigest()[:8]


def _wording() -> str:
    app_dir = Path(__file__).resolve().parents[1]
    try:
        return wording_stamp([(app_dir / rel).read_bytes() for rel in WORDING_SOURCES])
    except OSError:              # the sources are always in the image; without them the version alone keys the cache
        return "nosource"


WORDING = _wording()


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
    return f"{PREFIX}:{day}:{symbol.upper()}:{direction}:{aggressiveness}:{expiration}:{target}:v{DRAFT_CACHE_VERSION}-{WORDING}"


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
    draft = json.loads(raw) if raw else None
    if draft is not None and draft.get("model_used") != RULES_MODEL:      # never a draft the model wrote
        return None
    return draft


async def put(db, key: str | None, draft: dict, today: date | None = None) -> None:
    if not key:
        return
    await set_value(db, key, json.dumps(draft, default=str))
    cutoff = ((today or date.today()) - timedelta(days=KEEP_DAYS)).isoformat()
    await db.execute(text("DELETE FROM system_metadata WHERE key LIKE :p AND key < :c"), {"p": f"{PREFIX}:%", "c": f"{PREFIX}:{cutoff}"})
    await db.commit()
