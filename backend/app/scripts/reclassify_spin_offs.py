"""Move split rows that are spin-off adjustments to event_type spin_off. Dry run by default; --write applies.

A stored split (since the first shadow bar) with no split factor on the shadow bars within one session is not a
split: yfinance recorded a distribution or separation adjustment (CMCSA 16:15, HON 1:1, SPGI 37:35, BDX 41:40,
DTE 47:40) as one. The row and its metadata are kept; event_type becomes spin_off, the title says what it is, and
the metadata records the reclassification. split_basis and validate's split_factor_match read event_type split only,
so the EPS re-basing stops using these ratios; the RV guard still counts the day as an explained gap.

    python -m app.scripts.reclassify_spin_offs
    python -m app.scripts.reclassify_spin_offs --write
"""
from __future__ import annotations

import asyncio
import json
import sys

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.seed_historical_reactions import REFERENCE_SYMBOL, _build_date_cache
from app.services import price_bars
from app.services.corporate_actions import spin_off_reclassification, splits_from_adjustments
from app.services.security_records import STORED_START
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "Reclassify spin-offs"
REASON = "no split factor on the shadow bars within one session; Intrinio books the day as a spin-off or separation adjustment"


async def plan() -> list[dict]:
    async with ScriptSessionLocal() as s:
        stored = [{"id": r.id, "symbol": r.symbol, "date": r.event_date, "split_ratio": r.split_ratio, "title": r.title} for r in (await s.execute(text("""
            select e.id, t.symbol, e.event_date, e.metadata->>'split_ratio' as split_ratio, e.title from events e join tickers t on t.id = e.ticker_id
            where e.event_type = 'split' and e.event_date >= :start order by t.symbol, e.event_date"""), {"start": STORED_START})).all()]
        bar_rows = (await s.execute(text("select symbol, date, split_ratio, factor, dividend from price_bars_shadow where split_ratio <> 1 or (factor <> 1 and dividend = 0)"))).all()
    bar_splits = [{"symbol": r.symbol, **sp} for r in bar_rows for sp in splits_from_adjustments([r])]
    sessions = _build_date_cache(price_bars.history_sync(REFERENCE_SYMBOL, STORED_START))
    return spin_off_reclassification(stored, bar_splits, sessions)


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    rows = await plan()
    print(f"{STEP_LABEL} ({'write' if write else 'dry run'}): {len(rows)} split row(s) are spin-off adjustments")
    for r in rows:
        print(f"  {r['symbol']:6} {r['date']} {r['split_ratio'] or '-':>6}  {r['title']}")
    if write and rows:
        async with ScriptSessionLocal() as s:
            for r in rows:
                await s.execute(text("""update events set event_type = 'spin_off', title = :title,
                                        metadata = coalesce(metadata, CAST('{}' AS jsonb)) || CAST(:extra AS jsonb) where id = :id"""),
                                {"id": r["id"], "title": f"{r['symbol']} Spin-off Adjustment ({r['split_ratio']})" if r["split_ratio"] else f"{r['symbol']} Spin-off Adjustment",
                                 "extra": json.dumps({"reclassified_from": "split", "reclassified_reason": REASON})})
            await s.commit()
        await record_step_fields(STEP_LABEL, {"reclassified": [f"{r['symbol']} {r['date'].isoformat()} {r['split_ratio']}" for r in rows]})
        print(f"  written: {len(rows)} row(s) now event_type spin_off")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
