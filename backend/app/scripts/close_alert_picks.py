"""Close expired alert picks by fetching their official close price.

Usage:
    python -m app.scripts.close_alert_picks
    python -m app.scripts.close_alert_picks --backfill
    make close-picks
"""
from __future__ import annotations

import asyncio
import logging
import math
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, text

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.alert_pick import AlertPick
from app.models.iv_history import IVHistory
from app.models.shadow_pick import ShadowPick
from app.services import chain_store
from app.services.pnl_math import compute_option_pnl_at_expiry
from app.services.yfinance_client import YFinanceClient

logger = logging.getLogger(__name__)


def _is_valid_price(price) -> bool:
    """Return True if price is a usable finite number."""
    if price is None:
        return False
    try:
        f = float(price)
    except (TypeError, ValueError):
        return False
    return not math.isnan(f) and not math.isinf(f) and f > 0


def _store_option_pnl(pick: AlertPick, close_price: float) -> None:
    """Compute and store option P&L on a pick if it has strike/cost data."""
    if pick.suggested_strike and pick.cost_to_enter and float(pick.cost_to_enter) > 0:
        pnl_d, pnl_p = compute_option_pnl_at_expiry(
            close=close_price,
            strike=float(pick.suggested_strike),
            spread_strike=float(pick.suggested_spread_strike) if pick.suggested_spread_strike else None,
            cost=float(pick.cost_to_enter),
            direction=pick.picked_direction,
        )
        pick.option_pnl_dollars = pnl_d
        pick.option_pnl_pct = pnl_p


def _mid_or_last(bid, ask, last) -> float | None:
    """Compute mid from bid/ask, falling back to lastPrice."""
    if bid and ask and bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    return last if last and last > 0 else None


async def _compute_spread_mid(
    session, pick: AlertPick,
) -> tuple[float | None, str | None]:
    """Return (spread_mid, mark_note) from the chain store for a v2 pick.

    spread_mid is the net debit value of the bull call spread at current marks.
    Returns (None, note) if the chain or strikes are unavailable.
    """
    if not pick.expiration or not pick.suggested_strike:
        return None, "no expiration or strike"

    result = await chain_store.get_chain(session, pick.symbol, pick.expiration)
    if result is None:
        return None, f"no chain for {pick.expiration}"

    chain_data, chain_last_trade = result
    side_key = "calls" if pick.picked_direction == "bullish" else "puts"
    side = chain_data.get(side_key, [])

    strike = float(pick.suggested_strike)
    mid1 = None
    for row in side:
        if row.get("strike") == strike:
            mid1 = _mid_or_last(row.get("bid"), row.get("ask"), row.get("lastPrice"))
            break

    if mid1 is None:
        return None, f"strike {strike} not in chain"

    spread_strike = float(pick.suggested_spread_strike) if pick.suggested_spread_strike else None
    if spread_strike is not None:
        mid2 = None
        for row in side:
            if row.get("strike") == spread_strike:
                mid2 = _mid_or_last(row.get("bid"), row.get("ask"), row.get("lastPrice"))
                break
        if mid2 is not None:
            return round(mid1 - mid2, 4), None
        return None, f"spread strike {spread_strike} not in chain"

    return round(mid1, 4), None


def _compute_stock_move(pick: AlertPick, close_price: float) -> Decimal | None:
    """Return stock move percentage from entry to close."""
    entry = float(pick.entry_price) if pick.entry_price else None
    if entry is None or entry <= 0:
        return None
    return Decimal(str(round((close_price - entry) / entry * 100, 4)))


async def _close_v2_picks() -> int:
    """Close v2 picks that have reached their exit_date.

    V2 picks close on exit_date using the chain-store spread mid,
    not at expiration. stock_move_5d is persisted alongside option P&L.
    Expiration remains a hard stop if exit_date close was missed.
    """
    today = date.today()
    async with AsyncSessionLocal() as session:
        # v2 picks due for exit: exit_date is set and <= today
        rows = (await session.execute(
            select(AlertPick).where(
                AlertPick.status == "open",
                AlertPick.exit_date.is_not(None),
                AlertPick.exit_date <= today,
            )
        )).scalars().all()

        if not rows:
            print("[close-v2] No v2 picks due for exit.")
            return 0

        closed = 0
        for pick in rows:
            # Warn if we are late (more than 1 day past exit_date)
            days_late = (today - pick.exit_date).days
            if days_late > 1:
                logger.warning(
                    "[close-v2] %s exit_date=%s is %d day(s) late",
                    pick.symbol, pick.exit_date, days_late,
                )

            # Try chain-store spread mid first
            spread_mid, mark_note = await _compute_spread_mid(session, pick)

            if spread_mid is not None and spread_mid > 0:
                # Compute option P&L from spread mid
                cost = float(pick.cost_to_enter) if pick.cost_to_enter else None
                if cost and cost > 0:
                    pnl_d = round((spread_mid - cost) * 100, 2)
                    pnl_p = round((spread_mid - cost) / cost, 4)
                    pick.option_pnl_dollars = Decimal(str(pnl_d))
                    pick.option_pnl_pct = Decimal(str(pnl_p))

                # Get stock close price for stock_move_5d
                close_price = YFinanceClient.get_close_on_date(
                    pick.symbol, pick.exit_date.isoformat(),
                )
                if _is_valid_price(close_price):
                    pick.close_price = close_price
                    pick.stock_move_5d = _compute_stock_move(pick, float(close_price))
                else:
                    # Use entry as fallback for close_price column
                    pick.close_price = pick.entry_price

                close_note = ""
                if days_late > 0:
                    close_note = f" (marked {days_late} day(s) late)"

                pick.status = "closed"
                pick.closed_at = datetime.now(timezone.utc)
                closed += 1
                pnl_msg = f" option_pnl=${pick.option_pnl_dollars}" if pick.option_pnl_dollars is not None else ""
                move_msg = f" stock_move={pick.stock_move_5d}%" if pick.stock_move_5d is not None else ""
                print(f"[close-v2] {pick.symbol} exit={pick.exit_date}: "
                      f"spread_mid=${spread_mid}{pnl_msg}{move_msg}{close_note}")
            else:
                # No chain available -- check if expiration is a hard stop
                exp_str = pick.expiration or ""
                if exp_str < today.isoformat():
                    # Hard stop: fall back to yfinance close at expiration
                    close_price = YFinanceClient.get_close_on_date(pick.symbol, exp_str)
                    if _is_valid_price(close_price):
                        pick.close_price = close_price
                        pick.stock_move_5d = _compute_stock_move(pick, float(close_price))
                        _store_option_pnl(pick, float(close_price))
                        pick.status = "closed"
                        pick.closed_at = datetime.now(timezone.utc)
                        closed += 1
                        logger.warning(
                            "[close-v2] %s: no chain at exit_date, closed at expiration hard stop",
                            pick.symbol,
                        )
                        print(f"[close-v2] {pick.symbol}: closed at expiration hard stop ${close_price}")
                    else:
                        print(f"[close-v2] {pick.symbol}: no chain and no valid expiration close, leaving open")
                else:
                    print(f"[close-v2] {pick.symbol} exit={pick.exit_date}: "
                          f"{mark_note}, will retry next run")

        await session.commit()
        print(f"[close-v2] Done. Closed {closed}/{len(rows)} v2 picks.")
    return 0


async def _close_picks() -> int:
    """Close non-v2 picks (those without exit_date) at expiration."""
    today_str = date.today().isoformat()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AlertPick).where(
                AlertPick.status == "open",
                AlertPick.exit_date.is_(None),
                AlertPick.expiration < today_str,
            )
        )).scalars().all()

        if not rows:
            print("[close-picks] No expired open picks to close.")
            return 0

        closed = 0
        for pick in rows:
            close_price = YFinanceClient.get_close_on_date(pick.symbol, pick.expiration)
            if not _is_valid_price(close_price):
                print(f"[close-picks] {pick.symbol} exp={pick.expiration}: no valid close, leaving open for retry")
                continue

            pick.status = "closed"
            pick.closed_at = datetime.now(timezone.utc)
            pick.close_price = close_price
            _store_option_pnl(pick, float(close_price))
            closed += 1
            pnl_msg = f" option_pnl=${pick.option_pnl_dollars}" if pick.option_pnl_dollars is not None else ""
            print(f"[close-picks] {pick.symbol} exp={pick.expiration}: closed at ${close_price}{pnl_msg}")

        await session.commit()
        print(f"[close-picks] Done. Closed {closed}/{len(rows)} expired picks.")
        return 0


async def _resolve_close_from_iv_history(
    session, symbol: str, expiration: str,
) -> float | None:
    """Look up close price from iv_history, rolling back if expiration was non-trading."""
    exp_date = date.fromisoformat(expiration)
    row = (await session.execute(
        select(IVHistory.current_price)
        .where(
            IVHistory.symbol == symbol,
            IVHistory.date <= exp_date,
            IVHistory.current_price.is_not(None),
        )
        .order_by(IVHistory.date.desc())
        .limit(1)
    )).scalar()
    if _is_valid_price(row):
        return round(float(row), 4)
    return None


async def _backfill() -> int:
    """Backfill option P&L for closed picks with missing or NaN values."""
    async with AsyncSessionLocal() as session:
        # Catch both NULL and NaN rows
        rows = (await session.execute(
            select(AlertPick).where(
                AlertPick.status == "closed",
            ).where(
                AlertPick.option_pnl_dollars.is_(None)
                | (text("alert_picks.option_pnl_dollars = 'NaN'::numeric"))
            )
        )).scalars().all()

        if not rows:
            print("[backfill] No closed picks need option P&L backfill.")
            return 0

        filled = 0
        for pick in rows:
            close_price = pick.close_price

            # Resolve close_price if missing or NaN
            if not _is_valid_price(close_price):
                if not pick.expiration:
                    print(f"[backfill] {pick.symbol}: no close_price and no expiration, skipping")
                    continue

                # Try yfinance first (authoritative)
                yf_price = YFinanceClient.get_close_on_date(pick.symbol, pick.expiration)
                if _is_valid_price(yf_price):
                    pick.close_price = yf_price
                    close_price = yf_price
                    print(f"[backfill] {pick.symbol}: resolved close=${yf_price} from yfinance")
                else:
                    # Fall back to iv_history
                    ih_price = await _resolve_close_from_iv_history(session, pick.symbol, pick.expiration)
                    if ih_price is None:
                        print(f"[backfill] {pick.symbol}: no valid close from yfinance or iv_history for {pick.expiration}, skipping")
                        continue
                    pick.close_price = ih_price
                    close_price = ih_price
                    print(f"[backfill] {pick.symbol}: resolved close=${ih_price} from iv_history (yfinance unavailable)")

            # Clear any NaN P&L before recomputing
            pick.option_pnl_dollars = None
            pick.option_pnl_pct = None

            _store_option_pnl(pick, float(close_price))
            if pick.option_pnl_dollars is not None:
                filled += 1
                print(f"[backfill] {pick.symbol}: option_pnl=${pick.option_pnl_dollars} ({pick.option_pnl_pct}%)")
            else:
                print(f"[backfill] {pick.symbol}: no strike/cost data, skipping")

        await session.commit()
        print(f"[backfill] Done. Filled {filled}/{len(rows)} picks.")
        return 0


async def _settle_shadow_picks() -> int:
    """Fill actual_5d on shadow_picks once 5 trading days have passed."""
    today = date.today()
    # 5 trading days ~ 7 calendar days; settle anything with event_date <= today - 8
    cutoff = today - timedelta(days=8)

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(ShadowPick).where(
                ShadowPick.actual_5d.is_(None),
                ShadowPick.event_date <= cutoff,
            )
        )).scalars().all()

        if not rows:
            print("[shadow-settle] No shadow picks to settle.")
            return 0

        settled = 0
        for sp in rows:
            # Get the 5-day move: compare close on event_date to close 5 trading days later
            close_before = YFinanceClient.get_close_on_date(sp.symbol, sp.event_date.isoformat())
            # Approximate 5 trading days after event: +7 calendar days
            settle_date = sp.event_date + timedelta(days=7)
            close_after = YFinanceClient.get_close_on_date(sp.symbol, settle_date.isoformat())

            if not _is_valid_price(close_before) or not _is_valid_price(close_after):
                continue

            cb = float(close_before)
            ca = float(close_after)
            pct_5d = round((ca - cb) / cb * 100, 4)
            sp.actual_5d = pct_5d
            sp.settled_at = datetime.now(timezone.utc)
            settled += 1
            hit = "HIT" if pct_5d > 0 else "MISS"
            print(f"[shadow-settle] {sp.symbol} event={sp.event_date}: "
                  f"actual_5d={pct_5d:+.2f}% prob={sp.probability} "
                  f"would_pick={sp.would_pick} {hit}")

        await session.commit()
        print(f"[shadow-settle] Done. Settled {settled}/{len(rows)}.")
    return 0


def main() -> int:
    if "--backfill" in sys.argv:
        return asyncio.run(_backfill())
    # Always run shadow settlement alongside normal close
    asyncio.run(_settle_shadow_picks())
    asyncio.run(_close_v2_picks())
    return asyncio.run(_close_picks())


if __name__ == "__main__":
    sys.exit(main())
