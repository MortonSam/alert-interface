"""Earnings reaction rows labelled beat, miss or meet with no EPS actual (validate outcome_requires_actual) get the label the API
already serves for them, 'unknown': the actual a label rests on is gone, so the label cannot stand. The writer that caused them
(seed_historical_reactions writing a missing actual over a stored one) is fixed by frozen_update_data.

Usage
-----
    python -m app.scripts.clear_outcomes_without_actual            # dry run, read only: lists the rows
    python -m app.scripts.clear_outcomes_without_actual --write    # sets outcome = 'unknown' on exactly those rows
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.database import ScriptSessionLocal

ROWS = text("""SELECT hr.id, t.symbol, hr.event_date, hr.outcome::text AS outcome, hr.eps_estimate FROM historical_reactions hr
    JOIN tickers t ON t.id = hr.ticker_id
    WHERE hr.event_type = 'earnings' AND hr.outcome::text IN ('beat', 'miss', 'meet') AND hr.eps_actual IS NULL ORDER BY 2, 3""")


async def run(write: bool) -> int:
    async with ScriptSessionLocal() as s:
        if not write:
            await s.execute(text("SET TRANSACTION READ ONLY"))
        rows = (await s.execute(ROWS)).all()
        for r in rows:
            print(f"  {r.symbol:6} {r.event_date}  {r.outcome} -> unknown  (estimate {r.eps_estimate}, no actual)")
        print(f"{len(rows)} row(s)")
        if write and rows:
            n = (await s.execute(text("""UPDATE historical_reactions SET outcome = 'unknown' WHERE id = ANY(:ids) AND eps_actual IS NULL
                AND outcome::text IN ('beat', 'miss', 'meet')"""), {"ids": [r.id for r in rows]})).rowcount
            await s.commit()
            print(f"written: {n} row(s) set to unknown")
        else:
            await s.rollback()
            print("dry run: nothing written (add --write)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(asyncio.wait_for(run("--write" in sys.argv), 120)))
