"""Close expired alert picks by fetching their official close price.

Usage:
    python -m app.scripts.close_alert_picks
    python -m app.scripts.close_alert_picks --backfill
    make close-picks
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.alert_pick import AlertPick
from app.services.pnl_math import compute_option_pnl_at_expiry
from app.services.yfinance_client import YFinanceClient


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


async def _close_picks() -> int:
    today_str = date.today().isoformat()
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AlertPick).where(
                AlertPick.status == "open",
                AlertPick.expiration < today_str,
            )
        )).scalars().all()

        if not rows:
            print("[close-picks] No expired open picks to close.")
            return 0

        closed = 0
        for pick in rows:
            close_price = YFinanceClient.get_close_on_date(pick.symbol, pick.expiration)
            if close_price is None:
                print(f"[close-picks] {pick.symbol} exp={pick.expiration}: no close found, skipping")
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


async def _backfill() -> int:
    """Backfill option P&L for closed picks that are missing it."""
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(
            select(AlertPick).where(
                AlertPick.status == "closed",
                AlertPick.option_pnl_dollars.is_(None),
            )
        )).scalars().all()

        if not rows:
            print("[backfill] No closed picks need option P&L backfill.")
            return 0

        filled = 0
        for pick in rows:
            if pick.close_price is None:
                print(f"[backfill] {pick.symbol}: no close_price stored, skipping")
                continue
            _store_option_pnl(pick, float(pick.close_price))
            if pick.option_pnl_dollars is not None:
                filled += 1
                print(f"[backfill] {pick.symbol}: option_pnl=${pick.option_pnl_dollars} ({pick.option_pnl_pct}%)")
            else:
                print(f"[backfill] {pick.symbol}: no strike/cost data, skipping")

        await session.commit()
        print(f"[backfill] Done. Filled {filled}/{len(rows)} picks.")
        return 0


def main() -> int:
    if "--backfill" in sys.argv:
        return asyncio.run(_backfill())
    return asyncio.run(_close_picks())


if __name__ == "__main__":
    sys.exit(main())
