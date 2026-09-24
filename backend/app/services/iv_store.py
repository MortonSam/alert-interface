"""Read helper for iv_history. The only way ATM implied volatility reaches a response.

get_servable_iv(db, symbol) -> IVState(value, as_of, reason)

The newest row within IV_WINDOW_DAYS whose atm_iv is not null is served, dated
by its own row. A null row never hides an older value. When nothing in the
window has a value, `reason` says so, names why the newest snapshot recorded
none (iv_history.atm_iv_reason) and the last good value and date, so the row
and the read state the same sentence.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

IV_WINDOW_DAYS = 3


@dataclass(frozen=True)
class IVState:
    value: float | None      # 0-1 decimal, None unless served
    as_of: str | None        # ISO date of the row served
    reason: str | None       # plain language when value is None


_WINDOW_SQL = sa.text("""
    SELECT date, atm_iv, atm_iv_reason FROM iv_history
    WHERE symbol = :s AND date >= :cutoff
    ORDER BY date DESC
""")
_LAST_GOOD_SQL = sa.text("""
    SELECT date, atm_iv FROM iv_history
    WHERE symbol = :s AND atm_iv IS NOT NULL
    ORDER BY date DESC LIMIT 1
""")


def pick_servable(rows: list, today: date) -> tuple[object | None, object | None]:
    """Pure: (row with the newest non-null atm_iv inside the window, newest row in the window)."""
    cutoff = today - timedelta(days=IV_WINDOW_DAYS)
    in_window = [r for r in rows if r.date >= cutoff]
    newest = in_window[0] if in_window else None
    served = next((r for r in in_window if r.atm_iv is not None), None)
    return served, newest


async def get_servable_iv(db: AsyncSession, symbol: str, today: date | None = None) -> IVState:
    today = today or date.today()
    rows = (await db.execute(_WINDOW_SQL, {"s": symbol, "cutoff": today - timedelta(days=IV_WINDOW_DAYS)})).all()
    served, newest = pick_servable(rows, today)
    if served is not None:
        return IVState(float(served.atm_iv), served.date.isoformat(), None)
    reason = f"No ATM implied volatility in the last {IV_WINDOW_DAYS} days"
    if newest is not None:
        reason += f" (the {newest.date.isoformat()} snapshot recorded none"
        reason += f": {newest.atm_iv_reason})" if newest.atm_iv_reason else ")"
    last_good = (await db.execute(_LAST_GOOD_SQL, {"s": symbol})).first()
    if last_good is not None:
        reason += f"; last: {float(last_good.atm_iv) * 100:.1f}% on {last_good.date.isoformat()}"
    return IVState(None, None, reason)
