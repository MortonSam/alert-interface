"""Read helper for iv_history. The only way ATM implied volatility reaches a response.

Rows from the ticker's serving chain source are served (services/options_source): the courier's (iv_source = 'courier')
or, with OPTIONS_PRIMARY_SOURCE=intrinio, the solver's rows from Intrinio's chain (iv_source = 'intrinio_mid'). When the
ticker's options are hidden (no fresh chain passing the parity check), no IV is served and the reason says why. Rows are dated by their chain, so an unrefreshed chain leaves the window empty and the
reason names the chain's age in sessions.

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
    WHERE symbol = :s AND iv_source = :src AND date >= :cutoff
    ORDER BY date DESC
""")
_LAST_GOOD_SQL = sa.text("""
    SELECT date, atm_iv FROM iv_history
    WHERE symbol = :s AND iv_source = :src AND atm_iv IS NOT NULL
    ORDER BY date DESC LIMIT 1
""")


async def stale_chain_line(db: AsyncSession, symbol: str, today: date) -> str | None:
    """"options chain is N sessions old" when the newest stored chain fails chain_store's freshness rule; None otherwise."""
    from app.config import settings
    from app.services import chain_store
    chain_date = await chain_store.get_latest_chain_date(db, symbol, source=settings.options_primary_source)   # the primary's own age
    if not chain_date or chain_store.is_fresh(chain_date, today=today):
        return None
    try:
        return f"options chain is {chain_store.trading_days_since(chain_date, today)} sessions old"
    except ValueError:
        return None


def pick_servable(rows: list, today: date) -> tuple[object | None, object | None]:
    """Pure: (row with the newest non-null atm_iv inside the window, newest row in the window)."""
    cutoff = today - timedelta(days=IV_WINDOW_DAYS)
    in_window = [r for r in rows if r.date >= cutoff]
    newest = in_window[0] if in_window else None
    served = next((r for r in in_window if r.atm_iv is not None), None)
    return served, newest


async def get_servable_iv(db: AsyncSession, symbol: str, today: date | None = None) -> IVState:
    today = today or date.today()
    from app.services.options_source import IV_SOURCE, resolve
    serving = await resolve(db, symbol)
    if serving.source is None and serving.hidden_by_check:
        from app.services.options_source import PAUSED_NOTE
        return IVState(None, None, PAUSED_NOTE)
    from app.config import settings
    src = IV_SOURCE[serving.source or settings.options_primary_source]     # no chain at all: the primary's rows, under the window rule
    rows = (await db.execute(_WINDOW_SQL, {"s": symbol, "src": src, "cutoff": today - timedelta(days=IV_WINDOW_DAYS)})).all()
    served, newest = pick_servable(rows, today)
    if served is not None:
        return IVState(float(served.atm_iv), served.date.isoformat(), None)
    reason = f"No ATM implied volatility in the last {IV_WINDOW_DAYS} days"
    chain_age = await stale_chain_line(db, symbol, today)
    if chain_age:
        reason += f" ({chain_age})"
    if newest is not None:
        reason += f" (the {newest.date.isoformat()} snapshot recorded none"
        reason += f": {newest.atm_iv_reason})" if newest.atm_iv_reason else ")"
    last_good = (await db.execute(_LAST_GOOD_SQL, {"s": symbol, "src": src})).first()
    if last_good is not None:
        reason += f"; last: {float(last_good.atm_iv) * 100:.1f}% on {last_good.date.isoformat()}"
    return IVState(None, None, reason)
