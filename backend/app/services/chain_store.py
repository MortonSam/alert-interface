"""Ingested options chain store.

All chain access goes through this module. Chains are stored in system_metadata; there is no live
yfinance fallback. If no fresh chain exists, callers get None and surface an absent-data message to
the user.

Two sources, told apart by key prefix and by the chain's own chain_source field:
  courier   chain:{SYM}:{EXP}            written by the residential courier through /admin/ingest-options-chains.
            Every reader reads this one. A chain stored before the field existed is a courier chain.
  intrinio  intrinio_chain:{SYM}:{EXP}   written nightly by scripts/shadow_option_chains.py from Intrinio's
            EOD chain, by security record.
Readers that name no source get the ticker's serving source (services/options_source.resolve): the primary source set by
OPTIONS_PRIMARY_SOURCE (courier by default), its chain fresh and through the put-call parity check, else the fallback, else
nothing (the pages hide the figures with the reason). Writers and the shadow comparison always name their source.
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
                        underlying_price: float | None, chain_captured_at: str | None = None) -> dict:
    """The dict the ingest endpoint stores for a courier chain (before float sanitising). chain_captured_at is the
    courier's capture time on the New York clock; a chain without one was captured before the field existed."""
    return {"calls": calls, "puts": puts, "expiration": expiration, "chain_last_trade": chain_last_trade,
            "underlying_price": underlying_price, "chain_source": COURIER, "chain_captured_at": chain_captured_at}


async def put_chain(db: AsyncSession, sym: str, exp: str, chain: dict, source: str) -> str:
    """Store a chain under its source's key. The chain must name the same source."""
    if chain.get("chain_source") != source:
        raise ValueError(f"chain_source {chain.get('chain_source')!r} does not match the key's source {source!r}")
    key = chain_key(sym, exp, source)
    await set_value(db, key, json.dumps(chain))
    from app.services.options_source import forget
    forget(sym)
    return key


async def delete_expired(db: AsyncSession, source: str, before: date) -> list[str]:
    """Remove a source's chains whose expiration is before `before`. Returns the keys removed."""
    rows = (await db.execute(select(SystemMetadata.key).where(SystemMetadata.key.like(f"{_PREFIX[source]}:%")))).scalars().all()
    expired = [k for k in rows if len(k.split(":")) == 3 and k.split(":")[2] < before.isoformat()]
    if expired:
        await db.execute(delete(SystemMetadata).where(SystemMetadata.key.in_(expired)))
    return sorted(expired)


def trading_days_since(trade_date_str: str, today: date | None = None) -> int:
    """Sessions after trade_date through today, inclusive of today, on the NYSE calendar (services/trading_calendar):
    weekends and exchange holidays do not count."""
    from app.services.trading_calendar import is_trading_day, sessions_after
    trade_date = date.fromisoformat(str(trade_date_str)[:10])
    today = today or date.today()
    if today <= trade_date:
        return 0
    return sessions_after(trade_date, today) + (1 if is_trading_day(today) else 0)


CHAIN_FRESH_TRADING_DAYS = 2   # a chain older than this many trading days is not used


def is_fresh(chain_last_trade: str | None, max_trading_days: int = CHAIN_FRESH_TRADING_DAYS, today: date | None = None) -> bool:
    """Return True if chain_last_trade is within max_trading_days of today (or of `today` when given)."""
    if not chain_last_trade:
        return False
    return trading_days_since(chain_last_trade, today) <= max_trading_days


async def _serving(db: AsyncSession, sym: str) -> str | None:
    from app.services.options_source import resolve
    return (await resolve(db, sym)).source


async def get_ingested_expirations(db: AsyncSession, sym: str, source: str | None = None) -> list[str]:
    """Return sorted expiration date strings from a source's chain keys (the ticker's serving source when none is named; none when
    the ticker's options are hidden)."""
    if source is None:
        source = await _serving(db, sym)
        if source is None:
            return []
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
    db: AsyncSession, sym: str, exp: str, source: str | None = None,
) -> tuple[dict, str | None] | None:
    """Return (chain_dict, chain_last_trade) or None if not ingested. With no source named, the ticker's serving source; None when
    its options are hidden (missing, stale or failing the parity check with no passing fallback)."""
    if source is None:
        source = await _serving(db, sym)
        if source is None:
            return None
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


async def get_latest_chain_date(db: AsyncSession, sym: str, source: str | None = None) -> str | None:
    """Return the chain_last_trade date for any chain of this symbol from a source (the serving source when none is named), or None.

    Expirations a night's run skipped keep their older chain_last_trade, so the newest date across them is the chain's date.
    """
    if source is None:
        source = await _serving(db, sym)
        if source is None:
            return None
    from sqlalchemy import text as _text
    rows = (await db.execute(_text("SELECT value::json->>'chain_last_trade' FROM system_metadata WHERE key LIKE :p"),
                             {"p": f"{_PREFIX[source]}:{sym}:%"})).scalars().all()
    dates = [d[:10] for d in rows if d]
    return max(dates) if dates else None     # the newest batch: an expiration a night's run skipped keeps its older date


async def pick_expiration(
    db: AsyncSession, sym: str, min_date: str, source: str | None = None,
) -> str | None:
    """Return nearest ingested expiration >= min_date from the serving source (or the named one), or None.

    When min_date is the ticker's earnings date, the expiry must capture the report (chain_shadow.counts_for_report): one
    on the report day counts only for a before-open report, so an after-close or unknown-timing report takes a later one.
    The Intrinio step stores the expiry on an after-close report day as the pre-earnings leg; it is never the move's."""
    from app.services.chain_shadow import counts_for_report
    exps = await get_ingested_expirations(db, sym, source=source)
    timing = await report_timing_on(db, sym, min_date)
    if timing is not _NO_REPORT:
        matches = [e for e in exps if counts_for_report(e, min_date, timing)]
    else:
        matches = [e for e in exps if e >= min_date]
    return matches[0] if matches else None


_NO_REPORT = object()


async def report_timing_on(db: AsyncSession, sym: str, day: str):
    """The report timing of the ticker's earnings event on `day` (None when unknown), or _NO_REPORT when none is on that day."""
    from sqlalchemy import text as _text
    try:
        d = date.fromisoformat(str(day)[:10])
    except ValueError:
        return _NO_REPORT
    rows = (await db.execute(_text("""SELECT e.report_timing::text FROM events e JOIN tickers t ON t.id = e.ticker_id
        WHERE t.symbol = :s AND e.event_type = 'earnings' AND e.event_date = :d"""), {"s": sym, "d": d})).scalars().all()
    if not rows:
        return _NO_REPORT
    return "bmo" if all(r == "bmo" for r in rows) else next((r for r in rows if r and r != "bmo"), None)
