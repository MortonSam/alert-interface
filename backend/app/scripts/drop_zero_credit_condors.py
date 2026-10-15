"""Shadow iron condors stored with no credit (validate credit_shadow_integrity: credit <= 0 or a missing strike) are removed: a
condor that collects nothing is not a position, and the writer now refuses one under MIN_CONDOR_CREDIT (auto_pick). Unsettled
rows only; a settled row is listed and left for review.

Usage
-----
    python -m app.scripts.drop_zero_credit_condors            # dry run, read only: lists the rows
    python -m app.scripts.drop_zero_credit_condors --write    # deletes exactly the unsettled ones listed
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.database import ScriptSessionLocal

ROWS = text("""SELECT id, symbol, event_date, eval_date, credit_received, max_loss, settled_at FROM credit_shadow_picks
    WHERE credit_received IS NULL OR credit_received <= 0 OR short_put_strike IS NULL OR short_call_strike IS NULL
       OR long_put_strike IS NULL OR long_call_strike IS NULL ORDER BY event_date, eval_date""")


async def run(write: bool) -> int:
    async with ScriptSessionLocal() as s:
        if not write:
            await s.execute(text("SET TRANSACTION READ ONLY"))
        rows = (await s.execute(ROWS)).all()
        for r in rows:
            state = "settled, left for review" if r.settled_at else "unsettled, removed"
            print(f"  {r.symbol:6} report {r.event_date} decided {r.eval_date}  credit {r.credit_received}  max loss {r.max_loss}  ({state})")
        drop = [r.id for r in rows if r.settled_at is None]
        print(f"{len(rows)} row(s), {len(drop)} to remove")
        if write and drop:
            n = (await s.execute(text("DELETE FROM credit_shadow_picks WHERE id = ANY(:ids) AND settled_at IS NULL AND (credit_received IS NULL OR credit_received <= 0 "
                                      "OR short_put_strike IS NULL OR short_call_strike IS NULL OR long_put_strike IS NULL OR long_call_strike IS NULL)"),
                                 {"ids": drop})).rowcount
            await s.commit()
            print(f"written: {n} row(s) removed")
        else:
            await s.rollback()
            print("dry run: nothing written (add --write)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(asyncio.wait_for(run("--write" in sys.argv), 120)))
