"""Nightly: choose the home page's featured example by rule and store it in system_metadata (services/briefing_build.FEATURED_KEY).

The rule: the active index member with the nearest confirmed earnings date that has at least FEATURED_MIN_QUARTERS stored
quarters with a 1-day move, ties broken by market cap (largest first). No ticker qualifying stores an empty pick with the
rule, and the home block renders nothing.

    python -m app.scripts.pick_featured_example
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date

from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.ticker import Ticker
from app.services.briefing_build import FEATURED_KEY
from app.services.next_earnings import batch_next_earnings
from app.services.price_history_exclusion import EXCLUDED_SYMBOLS_SQL
from app.services.step_outcomes import record_step_fields
from app.services.system_metadata_service import set_value

STEP_LABEL = "Featured example"
FEATURED_MIN_QUARTERS = 20
RULE = (f"the active S&P 500 member with the nearest company-confirmed earnings date and at least {FEATURED_MIN_QUARTERS} stored quarters "
        "with a 1-day move; ties go to the larger market cap")


def choose_featured(candidates: list[dict]) -> dict | None:
    """Pure: candidates are {symbol, earnings_date, confirmation, quarters, market_cap}; the pick or None."""
    ok = [c for c in candidates if c.get("earnings_date") and c.get("confirmation") == "confirmed" and (c.get("quarters") or 0) >= FEATURED_MIN_QUARTERS]
    if not ok:
        return None
    return min(ok, key=lambda c: (c["earnings_date"], -(c.get("market_cap") or 0), c["symbol"]))


async def run(today: date | None = None) -> int:
    today = today or date.today()
    async with ScriptSessionLocal() as s:
        tickers = (await s.execute(select(Ticker.id, Ticker.symbol, Ticker.market_cap).where(Ticker.is_active, Ticker.index_member))).all()
        quarters = dict((await s.execute(text(
            "SELECT hr.ticker_id, count(*) FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id "
            "WHERE hr.event_type = 'earnings' AND hr.pct_change_1d IS NOT NULL AND t.symbol NOT IN " + EXCLUDED_SYMBOLS_SQL + " GROUP BY hr.ticker_id"))).all())
        nxt = await batch_next_earnings(s, [t.id for t in tickers], today)
        candidates = [{"symbol": t.symbol, "earnings_date": nxt[t.id].date, "confirmation": nxt[t.id].confirmation, "quarters": quarters.get(t.id, 0),
                       "market_cap": t.market_cap} for t in tickers if t.id in nxt]
        pick = choose_featured(candidates)
        value = {"symbol": pick["symbol"] if pick else None, "earnings_date": pick["earnings_date"].isoformat() if pick else None,
                 "quarters": pick["quarters"] if pick else None, "market_cap": pick["market_cap"] if pick else None,
                 "picked_on": today.isoformat(), "rule": RULE, "candidates_confirmed": sum(1 for c in candidates if c["confirmation"] == "confirmed")}
        await set_value(s, FEATURED_KEY, json.dumps(value))
        await s.commit()
    print(f"{STEP_LABEL}: {value}")
    await record_step_fields(STEP_LABEL, {**value, "error": None})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
