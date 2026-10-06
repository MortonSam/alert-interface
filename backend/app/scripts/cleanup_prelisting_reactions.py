"""Reaction rows dated before a ticker's first stored bar with no move at all are rows nothing priced (SW and TKO's FOMC rows
from before their listings). Dry run by default lists them per ticker; --write deletes them. Rows on a declared
stored-history span and rows with any move are never touched.

    python -m app.scripts.cleanup_prelisting_reactions
    python -m app.scripts.cleanup_prelisting_reactions --write
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.database import ScriptSessionLocal

SELECT_SQL = """
    SELECT hr.id, t.symbol, hr.event_type::text AS event_type, hr.event_date, fb.first_bar
    FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id
    JOIN (SELECT symbol, min(date) AS first_bar FROM price_bars_shadow GROUP BY symbol) fb ON fb.symbol = t.symbol
    WHERE hr.event_date < fb.first_bar AND COALESCE(hr.price_source, '') <> 'stored_history'
      AND hr.pct_change_1d IS NULL AND hr.pct_change_3d IS NULL AND hr.pct_change_5d IS NULL
    ORDER BY t.symbol, hr.event_date"""


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text(SELECT_SQL))).mappings().all()
        by: dict[str, list] = {}
        for r in rows:
            by.setdefault(r["symbol"], []).append(r)
        print(f"{'write' if write else 'dry run'}: {len(rows)} all-null reaction row(s) dated before the first stored bar, {len(by)} ticker(s)")
        for sym, rs in by.items():
            print(f"  {sym}: {len(rs)} {rs[0]['event_type']} row(s) {rs[0]['event_date']}..{rs[-1]['event_date']} (first bar {rs[0]['first_bar']})")
        if not write:
            print("  dry run: nothing changed; rerun with --write")
            return 0
        if rows:
            await s.execute(text("DELETE FROM historical_reactions WHERE id = ANY(:ids)"), {"ids": [r["id"] for r in rows]})
            await s.commit()
        print(f"  deleted {len(rows)} row(s)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
