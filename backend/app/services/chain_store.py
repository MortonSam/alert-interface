"""Ingested options chain store.

All chain access goes through this module. Chains are stored in system_metadata; there is no live
yfinance fallback. If no fresh chain exists, callers get None and surface an absent-data message to
the user.

Two sources, told apart by key prefix and by the chain's own chain_source field:
  courier   chain:{SYM}:{EXP}            written by the residential courier through /admin/ingest-options-chains.
            Every reader reads this one. A chain stored before the field existed is a courier chain.
  intrinio  intrinio_chain:{SYM}:{EXP}   written nightly by scripts/shadow_option_chains.py from Intrinio's
            EOD chain, by security record. Read only by validate's chain_shadow check. Nothing switches
            until the shadow week's retirement criteria pass.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_metadata import SystemMetadata
from app.services.system_metadata_service import set_value

COURIER = "courier"
INTRINIO = "intrinio"
SOURCES = (COURIER, INTRINIO)
_PREFIX = {COURIER: "chain", INTRINIO: "intrinio_chain"}


def chain_key(sym: str, exp: str, source: str = COURIER) -> str:
    return f"{_PREFIX[source]}:{sym}:{exp}"


def chain_source(chain: dict | None) -> str:
    """The source a stored chain names; one stored before the field existed is the courier's."""
    return (chain or {}).get("chain_source") or COURIER


def build_courier_chain(calls: list[dict], puts: list[dict], expiration: str, chain_last_trade: str | None,
                        underlying_price: float | None) -> dict:
    """The dict the ingest endpoint stores for a courier chain (before float sanitising)."""
    return {"calls": calls, "puts": puts, "expiration": expiration, "chain_last_trade": chain_last_trade,
            "underlying_price": underlying_price, "chain_source": COURIER}


async def put_chain(db: AsyncSession, sym: str, exp: str, chain: dict, source: str) -> str:
    """Store a chain under its source's key. The chain must name the same source."""
    if chain.get("chain_source") != source:
        raise ValueError(f"chain_source {chain.get('chain_source')!r} does not match the key's source {source!r}")
    key = chain_key(sym, exp, source)
    await set_value(db, key, json.dumps(chain))
    return key


async def delete_expired(db: AsyncSession, source: str, before: date) -> list[str]:
    """Remove a source's chains whose expiration is before `before`. Returns the keys removed."""
    rows = (await db.execute(select(SystemMetadata.key).where(SystemMetadata.key.like(f"{_PREFIX[source]}:%")))).scalars().all()
    expired = [k for k in rows if len(k.split(":")) == 3 and k.split(":")[2] < before.isoformat()]
    if expired:
        await db.execute(delete(SystemMetadata).where(SystemMetadata.key.in_(expired)))
    return sorted(expired)


def _trading_days_since(trade_date_str: str) -> int:
    """Count trading days (Mon-Fri) between trade_date and today, inclusive of today."""
    trade_date = date.fromisoformat(trade_date_str)
    today = date.today()
    count = 0
    d = trade_date
    while d < today:
        d += timedelta(days=1)
        if d.weekday() < 5:
            count += 1
    return count


CHAIN_FRESH_TRADING_DAYS = 2   # a chain older than this many trading days is not used


def is_fresh(chain_last_trade: str | None, max_trading_days: int = CHAIN_FRESH_TRADING_DAYS) -> bool:
    """Return True if chain_last_trade is within max_trading_days of today."""
    if not chain_last_trade:
        return False
    return _trading_days_since(chain_last_trade) <= max_trading_days


async def get_ingested_expirations(db: AsyncSession, sym: str, source: str = COURIER) -> list[str]:
    """Return sorted expiration date strings from a source's chain keys (the courier's by default)."""
    rows = (await db.execute(
        select(SystemMetadata.key).where(SystemMetadata.key.like(f"{_PREFIX[source]}:{sym}:%"))
    )).scalars().all()
    exps = []
    for key in rows:
        parts = key.split(":")
        if len(parts) == 3:
            exps.append(parts[2])
    return sorted(exps)


async def get_chain(
    db: AsyncSession, sym: str, exp: str, source: str = COURIER,
) -> tuple[dict, str | None] | None:
    """Return (chain_dict, chain_last_trade) or None if not ingested. Readers take the courier's (the default)."""
    row = await db.scalar(
        select(SystemMetadata).where(SystemMetadata.key == chain_key(sym, exp, source))
    )
    if not row:
        return None
    try:
        chain = json.loads(row.value)
    except (json.JSONDecodeError, TypeError):
        return None
    return chain, chain.get("chain_last_trade")


async def get_latest_chain_date(db: AsyncSession, sym: str) -> str | None:
    """Return the chain_last_trade date for any chain of this symbol, or None.

    All expirations for a symbol share the same chain_last_trade (ingested
    in the same courier batch), so we just grab the first one.
    """
    row = await db.scalar(
        select(SystemMetadata)
        .where(SystemMetadata.key.like(f"chain:{sym}:%"))
        .limit(1)
    )
    if not row:
        return None
    try:
        chain = json.loads(row.value)
        clt = chain.get("chain_last_trade")
        return clt[:10] if clt else None  # "YYYY-MM-DD" or full ISO → just date part
    except (json.JSONDecodeError, TypeError):
        return None


async def pick_expiration(
    db: AsyncSession, sym: str, min_date: str,
) -> str | None:
    """Return nearest ingested expiration >= min_date, or None."""
    exps = await get_ingested_expirations(db, sym)
    matches = [e for e in exps if e >= min_date]
    return matches[0] if matches else None
