"""Remove a stored earnings event that was never an earnings report (Tesla's deliveries release of 2026-10-02, ARES's quarter-end
date of 2026-09-30). Dry run by default: prints the event, any reaction row on its date, and what reads it; --write deletes the
event. It refuses when a reaction row or an EPS actual stands on the date (that is evidence of a real report).

Usage: python -m app.scripts.remove_false_report --symbol=TSLA --date=2026-10-02 --why="Q3 deliveries release, not earnings" [--write]
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date

from sqlalchemy import text

from app.database import ScriptSessionLocal


def _arg(argv: list[str], name: str) -> str | None:
    return next((a.split("=", 1)[1] for a in argv if a.startswith(f"--{name}=")), None)


async def run(argv: list[str]) -> int:
    sym, day, why, write = (_arg(argv, "symbol") or "").upper(), _arg(argv, "date"), _arg(argv, "why"), "--write" in argv
    if not sym or not day or not why:
        print(__doc__); return 2
    d = date.fromisoformat(day)
    async with ScriptSessionLocal() as s:
        ev = (await s.execute(text("""SELECT e.id, e.event_date, e.source::text, e.is_confirmed, e.confirmation_note, e.eps_actual, e.created_at
            FROM events e JOIN tickers t ON t.id = e.ticker_id WHERE t.symbol = :s AND e.event_type = 'earnings' AND e.event_date = :d"""),
            {"s": sym, "d": d})).all()
        rx = (await s.execute(text("""SELECT h.event_date, h.pct_change_1d FROM historical_reactions h JOIN tickers t ON t.id = h.ticker_id
            WHERE t.symbol = :s AND h.event_type = 'earnings' AND abs(h.event_date - :d) <= 1"""), {"s": sym, "d": d})).all()
        latest = (await s.execute(text("""SELECT max(x) FROM (SELECT e.event_date x FROM events e JOIN tickers t ON t.id = e.ticker_id
            WHERE t.symbol = :s AND e.event_type = 'earnings' AND e.event_date <= CURRENT_DATE AND (e.is_confirmed OR e.eps_actual IS NOT NULL) AND e.event_date <> :d
            UNION ALL SELECT h.event_date FROM historical_reactions h JOIN tickers t ON t.id = h.ticker_id WHERE t.symbol = :s AND h.event_type = 'earnings') q"""),
            {"s": sym, "d": d})).scalar()
        print(f"{sym} {d}: {why}")
        if not ev:
            print("  no earnings event on that date: nothing to remove"); return 1
        for e in ev:
            print(f"  event {e.id}: source {e.source}, confirmed {e.is_confirmed}, eps_actual {e.eps_actual}, created {e.created_at:%Y-%m-%d %H:%M} UTC")
            print(f"    note: {e.confirmation_note}")
        print(f"  reaction rows within a day: {[(str(r[0]), float(r[1]) if r[1] is not None else None) for r in rx] or 'none'}")
        print(f"  the latest report after removal: {latest}")
        if rx or any(e.eps_actual is not None for e in ev):
            print("REFUSED: a reaction row or an EPS actual stands on this date"); return 1
        if not write:
            print("dry run: nothing written (add --write)"); return 0
        await s.execute(text("DELETE FROM events WHERE id = ANY(:ids)"), {"ids": [e.id for e in ev]})
        await s.commit()
        print(f"deleted {len(ev)} event(s)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
