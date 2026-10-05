"""Two event rows for one ticker, type and date are one event stored twice. Dry run by default; --write keeps the row
with the most data (EPS actual, EPS estimate, a known report timing, a confirmation note, confirmation itself; ties to the
oldest), carries any field it lacks over from the others, repoints every event_id reference, deletes the rest, and creates
the unique index that stops it recurring. Analyst actions are exempt: two firms acting on one day are two events.

    python -m app.scripts.dedupe_earnings_events
    python -m app.scripts.dedupe_earnings_events --write

The migration f4a5b6c7d8e9 runs this same plan before creating the index and fails loudly if any duplicate remains.
"""
from __future__ import annotations

import asyncio
import sys

from sqlalchemy import text

from app.database import ScriptSessionLocal

INDEX_NAME = "uq_events_ticker_type_date"
EXEMPT_TYPES = ("analyst_action",)          # legitimately several per ticker per day
INDEX_SQL = f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} ON events (ticker_id, event_type, event_date) WHERE event_type <> 'analyst_action'"
MERGE_FIELDS = ("eps_actual", "eps_estimate", "eps_source", "eps_fetched_at", "confirmation_note", "report_timing", "report_timing_source")
DUP_ROWS_SQL = """
    SELECT e.id, e.ticker_id, t.symbol, e.event_type::text AS event_type, e.event_date, e.created_at, e.is_confirmed,
           e.eps_actual, e.eps_estimate, e.eps_source, e.eps_fetched_at, e.confirmation_note, e.report_timing, e.report_timing_source
    FROM events e JOIN tickers t ON t.id = e.ticker_id
    WHERE e.event_type <> 'analyst_action' AND (e.ticker_id, e.event_type, e.event_date) IN (
        SELECT ticker_id, event_type, event_date FROM events WHERE event_type <> 'analyst_action'
        GROUP BY ticker_id, event_type, event_date HAVING count(*) > 1)"""
REMAINING_SQL = """
    SELECT count(*) FROM (SELECT 1 FROM events WHERE event_type <> 'analyst_action'
                          GROUP BY ticker_id, event_type, event_date HAVING count(*) > 1) d"""


class DuplicateEventsRemain(RuntimeError):
    """Raised by the migration when duplicates survive the dedupe: nothing is indexed over a lie."""


def richness(row: dict) -> int:
    """How much a row knows: EPS actual, EPS estimate, a known timing, a confirmation note, confirmation."""
    return sum([row.get("eps_actual") is not None, row.get("eps_estimate") is not None, (row.get("report_timing") or "unknown") != "unknown",
                bool(row.get("confirmation_note")), bool(row.get("is_confirmed"))])


def dedupe_plan(rows: list[dict]) -> list[dict]:
    """Pure: one plan per duplicated (ticker, type, date): {keep, drop, fill}; keep is the richest row, ties to the oldest."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault((r["ticker_id"], r.get("event_type", "earnings"), r["event_date"]), []).append(r)
    plans = []
    for (tid, et, d), members in sorted(groups.items(), key=lambda kv: (str(kv[1][0]["symbol"]), kv[0][1], kv[0][2])):
        if len(members) < 2:
            continue
        members = sorted(members, key=lambda r: (-richness(r), r["created_at"], str(r["id"])))
        keep, drop = members[0], members[1:]
        fill = {}
        for f in MERGE_FIELDS:
            if keep.get(f) in (None, "unknown"):
                val = next((m.get(f) for m in drop if m.get(f) not in (None, "unknown")), None)
                if val is not None:
                    fill[f] = val
        plans.append({"symbol": keep["symbol"], "event_type": et, "event_date": d, "keep": keep["id"], "drop": [m["id"] for m in drop], "fill": fill})
    return plans


def assert_no_duplicates(remaining: int) -> None:
    if remaining:
        raise DuplicateEventsRemain(f"{remaining} duplicated event(s) remain; run app.scripts.dedupe_earnings_events --write and retry")


def apply_plans_sync(conn, plans: list[dict], refs: list[str]) -> None:
    """The write, on a synchronous connection (the migration's or a session's sync connection)."""
    for p in plans:
        if p["fill"]:
            sets = ", ".join(f"{k} = :{k}" for k in p["fill"])
            conn.execute(text(f"UPDATE events SET {sets} WHERE id = :id"), {**p["fill"], "id": p["keep"]})
        for t in refs:
            conn.execute(text(f'UPDATE "{t}" SET event_id = :k WHERE event_id = ANY(:d)'), {"k": p["keep"], "d": p["drop"]})
        conn.execute(text("DELETE FROM events WHERE id = ANY(:d)"), {"d": p["drop"]})


def dedupe_sync(conn, write: bool) -> tuple[list[dict], int]:
    """Plan (and with write, apply) the dedupe on a sync connection; returns (plans, duplicates remaining afterwards)."""
    rows = [dict(r) for r in conn.execute(text(DUP_ROWS_SQL)).mappings().all()]
    plans = dedupe_plan(rows)
    refs = conn.execute(text("SELECT table_name FROM information_schema.columns WHERE table_schema = 'public' AND column_name = 'event_id' AND table_name <> 'events'")).scalars().all()
    if write:
        apply_plans_sync(conn, plans, list(refs))
    remaining = conn.execute(text(REMAINING_SQL)).scalar() or 0
    return plans, (0 if write else remaining)


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    async with ScriptSessionLocal() as s:
        plans, _ = await s.run_sync(lambda sync_session: dedupe_sync(sync_session.connection(), False))
        print(f"{'write' if write else 'dry run'}: {len(plans)} duplicated event(s) (analyst actions exempt)")
        for p in plans:
            print(f"  {p['symbol']} {p['event_type']} {p['event_date']}: keep {p['keep']}, drop {len(p['drop'])}, fill {p['fill'] or 'nothing'}")
        if not write:
            print("  dry run: nothing changed; rerun with --write")
            return 0
        await s.run_sync(lambda sync_session: dedupe_sync(sync_session.connection(), True))
        remaining = (await s.execute(text(REMAINING_SQL))).scalar() or 0
        assert_no_duplicates(remaining)
        await s.execute(text("DROP INDEX IF EXISTS uq_events_earnings_ticker_date"))
        await s.execute(text(INDEX_SQL))
        await s.commit()
        print(f"  removed {sum(len(p['drop']) for p in plans)} row(s); unique index {INDEX_NAME} in place")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
