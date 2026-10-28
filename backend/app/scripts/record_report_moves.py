"""Nightly, after tonight's chains: each upcoming confirmed report's report move (services/report_move) is kept under its chain
date in the report's history, so a term-method move over STEADY_RATIO times the typical move can be checked against the previous
chain date's (report_move.report_move_view). Reports within REPORT_MOVE_DAYS days, the nightly's report-move window.

Usage: python -m app.scripts.record_report_moves
"""
from __future__ import annotations

import asyncio
import sys
from collections import Counter
from datetime import date, timedelta

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.step_outcomes import record_step_fields
from app.services.write_failures import WriteFailures

STEP = "Report move history"
WRITES = WriteFailures(STEP)
REPORT_MOVE_DAYS = 45


async def run(today: date | None = None) -> int:
    from app.services.earnings_calendar import level_of
    from app.services.implied_move import implied_move_allowed
    from app.services.report_move import record_history, report_move
    today = today or date.today()
    states: Counter = Counter()
    recorded = 0
    async with ScriptSessionLocal() as db:
        rows = (await db.execute(text("""
            SELECT DISTINCT ON (t.symbol) t.symbol, e.event_date, e.is_confirmed, e.unresolved_since FROM events e
            JOIN tickers t ON t.id = e.ticker_id
            WHERE e.event_type = 'earnings' AND t.is_active AND e.event_date >= :today AND e.event_date <= :cutoff
            ORDER BY t.symbol, e.event_date"""), {"today": today, "cutoff": today + timedelta(days=REPORT_MOVE_DAYS)})).all()
        for r in rows:
            if not implied_move_allowed(level_of(r.is_confirmed, r.unresolved_since)):
                continue
            async with WRITES.own(db, r.symbol) as done:             # each report's history stands alone
                rm = await report_move(db, r.symbol, r.event_date, today)
                n = await record_history(db, r.symbol, rm)
            if done.ok:
                states[rm.state] += 1
                recorded += n
    print(f"[report-move-history] {recorded} recorded; states {dict(states)}")
    await record_step_fields(STEP, {"recorded": recorded, "states": dict(states)})
    return await WRITES.finish()


if __name__ == "__main__":
    sys.exit(asyncio.run(asyncio.wait_for(run(), 1200)))
