"""Ingested options chain store.

All chain access goes through this module. Chains are stored in system_metadata
by chain_courier; there is no live yfinance fallback. If no fresh chain exists,
callers get None and surface an absent-data message to the user.
"""
from __future__ import annotations

import json
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.system_metadata import SystemMetadata


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


def is_fresh(chain_last_trade: str | None, max_trading_days: int = 2) -> bool:
    """Return True if chain_last_trade is within max_trading_days of today."""
    if not chain_last_trade:
        return False
    return _trading_days_since(chain_last_trade) <= max_trading_days


async def get_ingested_expirations(db: AsyncSession, sym: str) -> list[str]:
    """Return sorted expiration date strings from ingested chain keys."""
    rows = (await db.execute(
        select(SystemMetadata.key).where(SystemMetadata.key.like(f"chain:{sym}:%"))
    )).scalars().all()
    exps = []
    for key in rows:
        parts = key.split(":")
        if len(parts) == 3:
            exps.append(parts[2])
    return sorted(exps)


async def get_chain(
    db: AsyncSession, sym: str, exp: str,
) -> tuple[dict, str | None] | None:
    """Return (chain_dict, chain_last_trade) or None if not ingested."""
    row = await db.scalar(
        select(SystemMetadata).where(SystemMetadata.key == f"chain:{sym}:{exp}")
    )
    if not row:
        return None
    try:
        chain = json.loads(row.value)
    except (json.JSONDecodeError, TypeError):
        return None
    return chain, chain.get("chain_last_trade")


async def pick_expiration(
    db: AsyncSession, sym: str, min_date: str,
) -> str | None:
    """Return nearest ingested expiration >= min_date, or None."""
    exps = await get_ingested_expirations(db, sym)
    matches = [e for e in exps if e >= min_date]
    return matches[0] if matches else None
