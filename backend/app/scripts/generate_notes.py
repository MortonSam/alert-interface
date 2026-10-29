"""Nightly: a research note for every active ticker (Sam, 2026-10-27: before launch no page shows "No research note yet"), then each
note again after its company's next report.

Each night writes at most MAX_PER_NIGHT notes with production's key, through the same path a visitor's generation takes
(research_note_service.run_research_note_background: generation, the stats strip, the second model's verification; a note whose
check fails is never served). The order: tickers with no note, then tickers whose last generation failed, then notes checked before
the current check (note_claims.NOTE_CHECK_VERSION: checked again against Item 1 of the 10-K, and written again once when they would
lose more than MAX_LOST sentences, research_note_service.recheck_note), then notes the company has reported since
(note_currency.report_since). The site-wide AI cap (services/ai_spend) stays in force: the step stops before today's
notes' spend tonight reaches services/ai_spend.notes_night_budget (their share of the cap; visitors keep VISITOR_RESERVE_USD). CONCURRENCY notes run at a time.

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
CONCURRENCY = 4
NOTE_SECONDS = 840             # one note's generation and verification, and its second writing, each bounded by MODEL_TIMEOUT_SECONDS


def due_kind(status: str | None, stale: bool, check_version: int | None = None, hidden: bool = False, disagree: bool = False) -> tuple[int, str] | None:
    """Pure: (rank, "write" or "recheck") for one note tonight, or None when it is current. A note hidden from visitors ranks with
    the missing ones (Sam, 2026-10-29): one whose inputs name different quarters is written again (once they agree, write_due),
    one hidden by its check is checked again."""
    from app.services.note_claims import NOTE_CHECK_VERSION
    rank = {None: 0, "failed": 1, "verification_failed": 1}     # a check that errored (AVY, CARR 2026-10-28) is retried like a failure
    if status in rank:
        return rank[status], "write"
    if disagree:
        return 0, "write"
    old_check = status == "complete" and (check_version or 1) < NOTE_CHECK_VERSION
    if hidden and old_check:
        return 0, "recheck"
    if stale:
        return 3, "write"
    if old_check:
        return 2, "recheck"
    return None


def queue(rows: list[tuple], limit: int) -> list[str]:
    """Pure: rows (symbol, note status or None, reported since the note[, the check's version[, market value[, hidden from visitors[,
    inputs disagree]]]]) to tonight's symbols: no note and a hidden note first, then a failed generation or check, then a note
    checked before the current check, then a note the company has reported since; within each, the largest market value first
    (Sam, 2026-10-29: TSLA and the other big names are covered first). A current note is left alone."""
    due = []
    for r in rows:
        k = due_kind(r[1], r[2], r[3] if len(r) > 3 else None, bool(r[5]) if len(r) > 5 else False, bool(r[6]) if len(r) > 6 else False)
        if k is not None:
            due.append((k[0], -(r[4] or 0) if len(r) > 4 else 0, r[0]))
    return [sym for _, _, sym in sorted(due)][:limit]


async def candidates(today: date) -> list[tuple]:
    """(symbol, status, stale, check version, market value, hidden from visitors, inputs disagree) for every active stock."""
    from app.models.research_note import ResearchNote
    from app.services.note_quarters import disagreement, note_inputs
    from app.services.research_note_service import is_verified, withheld
    from sqlalchemy import select
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(text("""
            SELECT t.symbol, t.market_cap, n.id AS note_id, n.status, (n.verification->>'version')::int AS check_version,
                   EXISTS (SELECT 1 FROM events e WHERE e.ticker_id = t.id AND e.event_type = 'earnings' AND e.is_confirmed
                           AND e.event_date >= (n.generated_at AT TIME ZONE 'America/New_York')::date AND e.event_date <= :today) AS stale
            FROM tickers t LEFT JOIN research_notes n ON n.ticker_id = t.id
            WHERE t.is_active ORDER BY t.symbol"""), {"today": today})).all()
        notes = {n.id: n for n in (await db.execute(select(ResearchNote).where(ResearchNote.status == "complete"))).scalars().all()}
        out = []
        for r in rows:
            n = notes.get(r.note_id)
            hidden = bool(n and withheld(n))
            disagree = bool(n and is_verified(n) and disagreement(await note_inputs(db, n)))
            out.append((r.symbol, r.status, bool(r.stale) if r.status not in (None, "failed", "verification_failed") else False, r.check_version,
                        r.market_cap, hidden, disagree))
    return out


async def write_waits(edgar, symbol: str, today: date) -> str | None:
    """Why tonight's new note for `symbol` waits, or None: the inputs it would rest on name different quarters (note_quarters), so
    the existing note stays up unchanged (Sam, 2026-10-29). The filing is the one the note's text would be written from."""
    from app.services.note_quarters import current_inputs, disagreement
    cik = await edgar.get_cik(symbol)
    filing = await edgar.get_best_filing(cik) if cik else None
    async with AsyncSessionLocal() as db:
        tid = (await db.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": symbol})).scalar()
        why = disagreement(await current_inputs(db, tid, (filing or {}).get("filing_date"), today))
    return f"waiting: the inputs name different quarters ({why})" if why else None


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
    kind = {r[0]: due_kind(r[1], r[2], r[3], r[5], r[6])[1] for r in rows if r[0] in set(todo)}
    from app.services.edgar_client import EdgarClient
    edgar = EdgarClient()
    print(f"{STEP_LABEL}: {len(todo)} note(s) due tonight (at most {limit})", flush=True)
    if "--dry-run" in argv:
        print("  " + ", ".join(todo), flush=True)
        return 0
    results: dict[str, str] = {}
    stopped = None
    async with AsyncSessionLocal() as db:
        spent_at_start = await ai_spend.spend_today(db)
    budget = ai_spend.notes_night_budget(ai_spend.cap_usd(), ai_spend.walkthroughs_live())
    sem = asyncio.Semaphore(CONCURRENCY)
    t0 = time.monotonic()

    async def one(sym: str) -> None:
        nonlocal stopped
        async with sem:
            if stopped:
                return
            async with AsyncSessionLocal() as db:
                spent = await ai_spend.spend_today(db)
                if spent - spent_at_start >= budget or spent >= ai_spend.cap_usd() - ai_spend.VISITOR_RESERVE_USD:
                    stopped = (f"stopped at ${spent:.2f} of the ${ai_spend.cap_usd():.0f} daily cap: notes' ${budget:.0f} for the night used "
                               f"or ${ai_spend.VISITOR_RESERVE_USD:.0f} left for visitors")
                    return
                if kind[sym] == "write":
                    try:
                        waits = await write_waits(edgar, sym, date.today())
                    except Exception as exc:                    # the inputs could not be read: no new note tonight, the old one stays
                        from app.services.redact import redact
                        waits = f"waiting: the inputs could not be read ({redact(exc)[:80]})"
                    if waits:
                        results[sym] = waits
                        print(f"  {sym}: {waits}", flush=True)
                        return
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

    try:
        await asyncio.gather(*(one(s) for s in todo))
    finally:
        await edgar.close()
    async with AsyncSessionLocal() as db:
        spent = await ai_spend.spend_today(db)
        from app.services.system_metadata_service import get_value
        note_spend = await get_value(db, f"research_gen:spend:{__import__('datetime').datetime.utcnow().strftime('%Y-%m-%d')}")
    counts = {k: sum(1 for v in results.values() if (v.split(":")[0] if v.startswith("waiting") else v) == k)
              for k in {v.split(":")[0] if v.startswith("waiting") else v for v in results.values()}}
    fields = {"due": len(todo), "written": len(results), "rechecked": sum(1 for s in results if kind[s] == "recheck"), "outcomes": counts, "stopped": stopped, "spend_today_usd": round(spent, 2),
              "note_spend_utc_day_usd": float(note_spend) if note_spend else None, "seconds": round(time.monotonic() - t0),
              "waiting": sorted(f"{s}: {v}" for s, v in results.items() if v.startswith("waiting"))[:40],
              "not_passed": sorted(f"{s}: {v}" for s, v in results.items() if v != "passed" and not v.startswith("waiting"))[:40], "error": None}
    from app.services.step_outcomes import record_step_fields
    await record_step_fields(STEP_LABEL, fields)
    print(f"{STEP_LABEL}: {fields}", flush=True)
    return 0                                     # a note that fails its checks is the checks' verdict, never a failed step


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
