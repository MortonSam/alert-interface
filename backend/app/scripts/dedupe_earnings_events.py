"""Two earnings event rows for one ticker and date are one report stored twice. Dry run by default; --write keeps the
oldest row, carries any field it lacks over from the duplicates (EPS, timing, confirmation), repoints every event_id
reference to it, deletes the rest, and creates the unique index that stops it recurring (uq_events_earnings_ticker_date).

    python -m app.scripts.dedupe_earnings_events
    python -m app.scripts.dedupe_earnings_events --write
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.database import ScriptSessionLocal

INDEX_SQL = "CREATE UNIQUE INDEX IF NOT EXISTS uq_events_earnings_ticker_date ON events (ticker_id, event_date) WHERE event_type = 'earnings'"
MERGE_FIELDS = ("eps_actual", "eps_estimate", "eps_source", "eps_fetched_at", "confirmation_note", "report_timing", "report_timing_source")


def dedupe_plan(rows: list[dict]) -> list[dict]:
    """Pure: rows are {id, ticker_id, symbol, event_date, created_at, ...MERGE_FIELDS}; one plan per duplicated (ticker, date):
    {keep, drop: [...], fill: {field: value}} where fill is what the kept row takes from the dropped ones."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["ticker_id"], r["event_date"]), []).append(r)
    plans = []
    for (tid, d), members in sorted(groups.items(), key=lambda kv: (str(kv[1][0]["symbol"]), kv[0][1])):
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda r: (r["created_at"], str(r["id"])))
        keep, drop = members[0], members[1:]
        fill = {}
        for f in MERGE_FIELDS:
            if keep.get(f) in (None, "unknown"):
                val = next((m.get(f) for m in drop if m.get(f) not in (None, "unknown")), None)
                if val is not None:
                    fill[f] = val
        plans.append({"symbol": keep["symbol"], "event_date": d, "keep": keep["id"], "drop": [m["id"] for m in drop], "fill": fill})
    return plans


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT e.id, e.ticker_id, t.symbol, e.event_date, e.created_at, e.eps_actual, e.eps_estimate, e.eps_source, e.eps_fetched_at,
                   e.confirmation_note, e.report_timing, e.report_timing_source
            FROM events e JOIN tickers t ON t.id = e.ticker_id
            WHERE e.event_type = 'earnings' AND (e.ticker_id, e.event_date) IN (
                SELECT ticker_id, event_date FROM events WHERE event_type = 'earnings' GROUP BY ticker_id, event_date HAVING count(*) > 1)"""))).mappings().all()
        plans = dedupe_plan([dict(r) for r in rows])
        refs = (await s.execute(text("""
            SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'event_id' AND table_name <> 'events'"""))).scalars().all()
        print(f"{'write' if write else 'dry run'}: {len(plans)} duplicated report(s); event_id references in: {', '.join(refs) or 'none'}")
        for p in plans:
            print(f"  {p['symbol']} {p['event_date']}: keep {p['keep']}, drop {len(p['drop'])}, fill {p['fill'] or 'nothing'}")
        if not write:
            print("  dry run: nothing changed; rerun with --write")
            return 0
        for p in plans:
            if p["fill"]:
                sets = ", ".join(f"{k} = :{k}" for k in p["fill"])
                await s.execute(text(f"UPDATE events SET {sets} WHERE id = :id"), {**p["fill"], "id": p["keep"]})
            for t in refs:
                await s.execute(text(f'UPDATE "{t}" SET event_id = :k WHERE event_id = ANY(:d)'), {"k": p["keep"], "d": p["drop"]})
            await s.execute(text("DELETE FROM events WHERE id = ANY(:d)"), {"d": p["drop"]})
        await s.execute(text(INDEX_SQL))
        await s.commit()
        print(f"  removed {sum(len(p['drop']) for p in plans)} row(s); unique index uq_events_earnings_ticker_date in place")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
