"""Close expired alert picks by fetching their official close price.

A pick is never marked closed without its close. A v2 pick settles on exit_date at that session's close: the
stock close for exit_date must exist (the nightly runs at 06:00Z, before exit_date's session, so the first
run on exit_date waits) and the chain the spread is marked on must be dated on or after exit_date (an
earlier chain is the day-before mark). Otherwise the pick stays open with the reason, recorded in the step
outcome, and is retried next run; expiration is the hard stop, and even that needs a valid close.

Usage:
    python -m app.scripts.close_alert_picks
    python -m app.scripts.close_alert_picks --backfill
    python -m app.scripts.close_alert_picks --reopen-null-close   # a pick marked closed without a close goes back to open
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
from app.models.credit_shadow_pick import CreditShadowPick
from app.models.iv_history import COURIER_SOURCE, IVHistory
from app.models.shadow_pick import ShadowPick
from app.services import chain_store
from app.services.pnl_math import compute_option_pnl_at_expiry, pnl_percent
from app.services.step_outcomes import record_step_fields
from app.services.yfinance_client import YFinanceClient

logger = logging.getLogger(__name__)

STEP_LABEL = "Close expired alert picks"


def _chain_date(chain_last_trade) -> date | None:
    """The date of a chain's last trade, from the ISO string or datetime the chain store keeps."""
    if chain_last_trade is None:
        return None
    if isinstance(chain_last_trade, datetime):
        return chain_last_trade.date()
    if isinstance(chain_last_trade, date):
        return chain_last_trade
    try:
        return date.fromisoformat(str(chain_last_trade)[:10])
    except ValueError:
        return None


def settle_decision(exit_date: date, expiration: str | None, today: date, spread_mid: float | None, mark_note: str | None,
                    chain_last_trade, close_price) -> tuple[str, str]:
    """What the closer does with a v2 pick due for exit: ('close', ''), ('hard_stop', why) or ('wait', why).

    'close' needs a valid stock close for exit_date and a spread mark on a chain dated on or after exit_date.
    'hard_stop' is expiration passed with no usable exit mark: the caller closes at the expiration close, and only
    with a valid one. Anything else waits, with the reason, and is retried next run."""
    chain_date = _chain_date(chain_last_trade)
    if not _is_valid_price(close_price):
        why = f"no stock close for {exit_date.isoformat()} yet"
    elif spread_mid is None:
        why = mark_note or "no spread mark"
    elif chain_date is None or chain_date < exit_date:
        why = f"chain dated {chain_date.isoformat() if chain_date else 'unknown'}, the exit mark needs {exit_date.isoformat()} or later"
    else:
        return "close", ""
    if expiration and expiration < today.isoformat():
        return "hard_stop", why
    return "wait", why


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


def _leg_mid(row: dict) -> float:
    """Compute a mid price for a single option leg.

    A worthless leg (bid=0, ask=0) returns 0.0 -- that is a real market
    value, not missing data.  Returns None only when the strike row is
    absent from the chain (handled by the caller).
    """
    bid = row.get("bid") or 0.0
    ask = row.get("ask") or 0.0
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    if bid == 0 and ask > 0:
        return ask / 2.0
    # Both zero (or negative): the leg is worthless.
    return 0.0


def _find_leg(side: list[dict], strike: float) -> dict | None:
    """Find the chain row matching *strike*, or None if absent."""
    for row in side:
        if row.get("strike") == strike:
            return row
    return None


async def _compute_spread_mid(
    session, pick: AlertPick,
) -> tuple[float | None, str | None]:
    """Return (spread_mid, mark_note) from the chain store for a v2 pick.

    spread_mid is the net debit value of the bull call spread at current marks.
    A spread_mid of 0.0 is valid (worthless spread, -100% P&L).
    Returns (None, note) only when the chain or strike rows are absent.
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
    leg1_row = _find_leg(side, strike)
    if leg1_row is None:
        return None, f"strike {strike} not in chain"
    mid1 = _leg_mid(leg1_row)

    spread_strike = float(pick.suggested_spread_strike) if pick.suggested_spread_strike else None
    if spread_strike is not None:
        leg2_row = _find_leg(side, spread_strike)
        if leg2_row is None:
            return None, f"spread strike {spread_strike} not in chain"
        mid2 = _leg_mid(leg2_row)
        return round(mid1 - mid2, 4), None

    return round(mid1, 4), None


def _compute_stock_move(pick: AlertPick, close_price: float) -> Decimal | None:
    """Return stock move percentage from entry to close."""
    entry = float(pick.entry_price) if pick.entry_price else None
    if entry is None or entry <= 0:
        return None
    return Decimal(str(round((close_price - entry) / entry * 100, 4)))


async def _close_v2_picks() -> tuple[list[str], list[str]]:
    """Close v2 picks that have reached their exit_date at exit_date's close (see settle_decision).

    Returns (closed, waiting) labels for the step outcome."""
    today = date.today()
    closed_labels: list[str] = []
    waiting: list[str] = []
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AlertPick).where(
                AlertPick.status == "open",
                AlertPick.exit_date.is_not(None),
                AlertPick.exit_date <= today,
            )
        )).scalars().all()

        if not rows:
            print("[close-v2] No v2 picks due for exit.")
            return closed_labels, waiting

        for pick in rows:
            days_late = (today - pick.exit_date).days
            if days_late > 1:
                logger.warning("[close-v2] %s exit_date=%s is %d day(s) late", pick.symbol, pick.exit_date, days_late)

            spread_mid, mark_note = await _compute_spread_mid(session, pick)
            chain_last_trade = None
            result = await chain_store.get_chain(session, pick.symbol, pick.expiration) if pick.expiration else None
            if result is not None:
                chain_last_trade = result[1]
            close_price = YFinanceClient.get_close_on_date(pick.symbol, pick.exit_date.isoformat())
            action, why = settle_decision(pick.exit_date, pick.expiration, today, spread_mid, mark_note, chain_last_trade, close_price)

            if action == "close":
                cost = float(pick.cost_to_enter) if pick.cost_to_enter else None
                if cost and cost > 0:
                    pnl_d = round((spread_mid - cost) * 100, 2)
                    pnl_p = pnl_percent(spread_mid - cost, cost)
                    pick.option_pnl_dollars = Decimal(str(pnl_d))
                    pick.option_pnl_pct = Decimal(str(pnl_p))
                pick.close_price = close_price
                pick.stock_move_5d = _compute_stock_move(pick, float(close_price))
                pick.status = "closed"
                pick.closed_at = datetime.now(timezone.utc)
                late = f" (marked {days_late} day(s) late)" if days_late > 0 else ""
                pnl_msg = f" option_pnl=${pick.option_pnl_dollars}" if pick.option_pnl_dollars is not None else ""
                move_msg = f" stock_move={pick.stock_move_5d}%" if pick.stock_move_5d is not None else ""
                print(f"[close-v2] {pick.symbol} exit={pick.exit_date}: spread_mid=${spread_mid} close=${close_price}{pnl_msg}{move_msg}{late}")
                closed_labels.append(f"{pick.symbol}@{pick.exit_date.isoformat()}")
            elif action == "hard_stop":
                exp_close = YFinanceClient.get_close_on_date(pick.symbol, pick.expiration)
                if _is_valid_price(exp_close):
                    pick.close_price = exp_close
                    pick.stock_move_5d = _compute_stock_move(pick, float(exp_close))
                    _store_option_pnl(pick, float(exp_close))
                    pick.status = "closed"
                    pick.closed_at = datetime.now(timezone.utc)
                    logger.warning("[close-v2] %s: %s; closed at expiration hard stop", pick.symbol, why)
                    print(f"[close-v2] {pick.symbol}: {why}; closed at expiration {pick.expiration} hard stop ${exp_close}")
                    closed_labels.append(f"{pick.symbol}@{pick.expiration} (hard stop)")
                else:
                    reason = f"{why}; no valid close at expiration {pick.expiration} either"
                    print(f"[close-v2] {pick.symbol} exit={pick.exit_date}: {reason}, stays open, will retry next run")
                    waiting.append(f"{pick.symbol}@{pick.exit_date.isoformat()}: {reason}")
            else:
                print(f"[close-v2] {pick.symbol} exit={pick.exit_date}: {why}, stays open, will retry next run")
                waiting.append(f"{pick.symbol}@{pick.exit_date.isoformat()}: {why}")

        await session.commit()
        print(f"[close-v2] Done. Closed {len(closed_labels)}/{len(rows)} v2 picks; {len(waiting)} waiting.")
    return closed_labels, waiting


async def _reopen_null_close() -> int:
    """A pick marked closed without a close (the bug this module's docstring describes) goes back to open, so the
    closer settles it at its real exit close on the next run."""
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AlertPick).where(AlertPick.status == "closed", AlertPick.close_price.is_(None))
        )).scalars().all()
        for pick in rows:
            pick.status = "open"
            pick.closed_at = None
            pick.option_pnl_dollars = None
            pick.option_pnl_pct = None
            pick.stock_move_5d = None
            print(f"[reopen] {pick.symbol} exit={pick.exit_date} expiration={pick.expiration}: reopened, closed with no close")
        await session.commit()
        print(f"[reopen] Done. Reopened {len(rows)} pick(s).")
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
            IVHistory.iv_source == COURIER_SOURCE,
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


async def _settle_credit_shadows() -> int:
    """Settle credit shadow picks that have reached exit_date."""
    today = date.today()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(CreditShadowPick).where(
                CreditShadowPick.settled_at.is_(None),
                CreditShadowPick.exit_date <= today,
            )
        )).scalars().all()

        if not rows:
            print("[credit-shadow-settle] No credit shadow picks to settle.")
            return 0

        settled = 0
        for csp in rows:
            # Get chain at exit for the 4 legs
            result = await chain_store.get_chain(session, csp.symbol, csp.expiration)
            if result is None:
                print(f"[credit-shadow-settle] {csp.symbol}: no chain for {csp.expiration}, skipping")
                continue
            chain_data, _ = result
            puts = chain_data.get("puts", [])
            calls = chain_data.get("calls", [])

            sp_row = _find_leg(puts, float(csp.short_put_strike))
            lp_row = _find_leg(puts, float(csp.long_put_strike))
            sc_row = _find_leg(calls, float(csp.short_call_strike))
            lc_row = _find_leg(calls, float(csp.long_call_strike))

            if any(r is None for r in [sp_row, lp_row, sc_row, lc_row]):
                print(f"[credit-shadow-settle] {csp.symbol}: missing leg in chain, skipping")
                continue

            sp_mid = _leg_mid(sp_row)
            lp_mid = _leg_mid(lp_row)
            sc_mid = _leg_mid(sc_row)
            lc_mid = _leg_mid(lc_row)

            close_value = (sp_mid + sc_mid) - (lp_mid + lc_mid)
            credit = float(csp.credit_received)
            max_loss_val = float(csp.max_loss)

            pnl_dollars = round((credit - close_value) * 100, 2)
            pnl_pct = pnl_percent(pnl_dollars, max_loss_val * 100) or 0.0  # percent of max loss

            csp.close_value = Decimal(str(round(close_value, 4)))
            csp.pnl_dollars = Decimal(str(pnl_dollars))
            csp.pnl_pct = Decimal(str(pnl_pct))

            # Stock move
            close_price = YFinanceClient.get_close_on_date(
                csp.symbol, csp.exit_date.isoformat(),
            )
            if _is_valid_price(close_price):
                spot = float(csp.spot)
                if spot > 0:
                    csp.stock_move_5d = Decimal(str(round(
                        (float(close_price) - spot) / spot * 100, 4
                    )))

            csp.settled_at = datetime.now(timezone.utc)
            settled += 1
            win = "WIN" if pnl_dollars > 0 else "LOSS"
            print(f"[credit-shadow-settle] {csp.symbol} event={csp.event_date}: "
                  f"pnl=${pnl_dollars:+.2f} ({pnl_pct:+.2%}) {win}")

        await session.commit()
        print(f"[credit-shadow-settle] Done. Settled {settled}/{len(rows)}.")
    return 0


async def _main() -> int:
    """Single event loop for all close operations."""
    await _settle_shadow_picks()
    await _settle_credit_shadows()
    closed, waiting = await _close_v2_picks()
    await _close_picks()
    await record_step_fields(STEP_LABEL, {"closed": closed, "waiting": waiting})
    return 0


def main() -> int:
    if "--backfill" in sys.argv:
        return asyncio.run(_backfill())
    if "--reopen-null-close" in sys.argv:
        return asyncio.run(_reopen_null_close())
    return asyncio.run(_main())


if __name__ == "__main__":
    sys.exit(main())
