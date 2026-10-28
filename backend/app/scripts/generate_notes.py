"""Nightly: a research note for every active ticker (Sam, 2026-10-27: before launch no page shows "No research note yet"), then each
note again after its company's next report.

Each night writes at most MAX_PER_NIGHT notes with production's key, through the same path a visitor's generation takes
(research_note_service.run_research_note_background: generation, the stats strip, the second model's verification; a note whose
check fails is never served). The order: tickers with no note, then tickers whose last generation failed, then notes checked before
the current check (note_claims.NOTE_CHECK_VERSION: checked again against Item 1 of the 10-K, and written again once when they would
lose more than MAX_LOST sentences, research_note_service.recheck_note), then notes the company has reported since
(note_currency.report_since). The site-wide AI cap (services/ai_spend) stays in force: the step stops before today's
spend would come within RESERVE_USD of the cap, so visitors keep that much for the day. CONCURRENCY notes run at a time.

    python -m app.scripts.generate_notes                  # the nightly step
    python -m app.scripts.generate_notes --limit=5        # a few, by hand
    python -m app.scripts.generate_notes --dry-run        # what tonight would write, nothing generated
"""
from __future__ import annotations

import asyncio
import sys
import time
from datetime import date

from sqlalchemy import text

from app.database import AsyncSessionLocal

STEP_LABEL = "Research notes (nightly)"
MAX_PER_NIGHT = 170
RESERVE_USD = 4.0              # left under the daily AI cap for the day's visitors
CONCURRENCY = 4
NOTE_SECONDS = 840             # one note's generation and verification, and its second writing, each bounded by MODEL_TIMEOUT_SECONDS


def due_kind(status: str | None, stale: bool, check_version: int | None = None) -> tuple[int, str] | None:
    """Pure: (rank, "write" or "recheck") for one note tonight, or None when it is current."""
    from app.services.note_claims import NOTE_CHECK_VERSION
    rank = {None: 0, "failed": 1, "verification_failed": 1}     # a check that errored (AVY, CARR 2026-10-28) is retried like a failure
    if status in rank:
        return rank[status], "write"
    if stale:
        return 3, "write"
    if status == "complete" and (check_version or 1) < NOTE_CHECK_VERSION:
        return 2, "recheck"
    return None


def queue(rows: list[tuple], limit: int) -> list[str]:
    """Pure: (symbol, note status or None, reported since the note[, the check's version]) rows to tonight's symbols: no note first,
    then a failed generation or check, then a note checked before the current check, then a note the company has reported since; a
    current note is left alone."""
    due = [(k[0], r[0]) for r in rows if (k := due_kind(r[1], r[2], r[3] if len(r) > 3 else None)) is not None]
    return [sym for _, sym in sorted(due)][:limit]


async def candidates(today: date) -> list[tuple[str, str | None, bool]]:
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text("""
            SELECT t.symbol, n.status, (n.verification->>'version')::int AS check_version,
                   EXISTS (SELECT 1 FROM events e WHERE e.ticker_id = t.id AND e.event_type = 'earnings' AND e.is_confirmed
                           AND e.event_date >= (n.generated_at AT TIME ZONE 'America/New_York')::date AND e.event_date <= :today) AS stale
            FROM tickers t LEFT JOIN research_notes n ON n.ticker_id = t.id
            WHERE t.is_active ORDER BY t.symbol"""), {"today": today})).all()
    return [(r.symbol, r.status, bool(r.stale) if r.status not in (None, "failed", "verification_failed") else False, r.check_version)
            for r in rows]


async def outcome_of(symbol: str) -> str:
    async with AsyncSessionLocal() as db:
        row = (await db.execute(text("""SELECT n.status, n.verification IS NOT NULL AS checked, n.estimated_cost_usd
            FROM research_notes n JOIN tickers t ON t.id = n.ticker_id WHERE t.symbol = :s"""), {"s": symbol})).first()
    if row is None:
        return "missing"
    return "passed" if row.status == "complete" and row.checked else row.status


async def run(argv: list[str]) -> int:
    from app.services import ai_spend
    from app.services.prod_key_guard import check_production_key
    from app.services.research_note_service import recheck_note, run_research_note_background, start_research_note_generation
    check_production_key()
    limit = next((int(a.split("=", 1)[1]) for a in argv if a.startswith("--limit=")), MAX_PER_NIGHT)
    rows = await candidates(date.today())
    todo = queue(rows, limit)
    kind = {r[0]: due_kind(r[1], r[2], r[3])[1] for r in rows if r[0] in set(todo)}
    print(f"{STEP_LABEL}: {len(todo)} note(s) due tonight (at most {limit})", flush=True)
    if "--dry-run" in argv:
        print("  " + ", ".join(todo), flush=True)
        return 0
    results: dict[str, str] = {}
    stopped = None
    sem = asyncio.Semaphore(CONCURRENCY)
    t0 = time.monotonic()

    async def one(sym: str) -> None:
        nonlocal stopped
        async with sem:
            if stopped:
                return
            async with AsyncSessionLocal() as db:
                spent = await ai_spend.spend_today(db)
                if spent >= ai_spend.cap_usd() - RESERVE_USD:
                    stopped = f"stopped at ${spent:.2f} of the ${ai_spend.cap_usd():.0f} daily cap (keeping ${RESERVE_USD:.0f} for visitors)"
                    return
                if kind[sym] == "write":
                    ticker_id = (await start_research_note_generation(db, None, sym)).ticker_id
            try:
                if kind[sym] == "recheck":
                    await asyncio.wait_for(recheck_note(sym), NOTE_SECONDS)
                else:
                    await asyncio.wait_for(run_research_note_background(ticker_id=ticker_id, symbol=sym), NOTE_SECONDS)
            except Exception as exc:                      # the background path records its own failure; a timeout is noted here
                from app.services.redact import redact
                print(f"  {sym}: {redact(exc)[:120]}", flush=True)
            results[sym] = await outcome_of(sym)
            print(f"  {sym}: {results[sym]}", flush=True)

    await asyncio.gather(*(one(s) for s in todo))
    async with AsyncSessionLocal() as db:
        spent = await ai_spend.spend_today(db)
        from app.services.system_metadata_service import get_value
        note_spend = await get_value(db, f"research_gen:spend:{__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d')}")
    counts = {k: sum(1 for v in results.values() if v == k) for k in set(results.values())}
    fields = {"due": len(todo), "written": len(results), "rechecked": sum(1 for s in results if kind[s] == "recheck"), "outcomes": counts, "stopped": stopped, "spend_today_usd": round(spent, 2),
              "note_spend_utc_day_usd": float(note_spend) if note_spend else None, "seconds": round(time.monotonic() - t0),
              "not_passed": sorted(f"{s}: {v}" for s, v in results.items() if v != "passed")[:40], "error": None}
    from app.services.step_outcomes import record_step_fields
    await record_step_fields(STEP_LABEL, fields)
    print(f"{STEP_LABEL}: {fields}", flush=True)
    return 0                                     # a note that fails its checks is the checks' verdict, never a failed step


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
