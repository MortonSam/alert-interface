"""Nightly: every active company's new 8-Ks read for a material event (services/material_filings), so tonight's research notes are
written again after one (Sam, 2026-11-02). Runs before "Research notes (nightly)"; the SEC filing index is the one the earlier 8-K
steps read tonight (cached SUBMISSIONS_CACHE_H hours), so a company with nothing new costs no extra request.

    python -m app.scripts.scan_material_filings              # the nightly step, every active ticker
    python -m app.scripts.scan_material_filings NVDA PANW    # a few
"""
from __future__ import annotations

import asyncio
import sys
import time
from datetime import date

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.redact import redact
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "Material filings (8-K)"
SYMBOL_SECONDS = 180


async def run(argv: list[str]) -> int:
    from app.services.edgar_client import EdgarClient
    from app.services.material_filings import scan
    symbols = [a.upper() for a in argv if not a.startswith("--")]
    async with ScriptSessionLocal() as db:
        if not symbols:
            symbols = list((await db.execute(text("SELECT symbol FROM tickers WHERE is_active ORDER BY symbol"))).scalars())
    edgar = EdgarClient()
    t0 = time.monotonic()
    read = material = 0
    found: list[str] = []
    failed: dict[str, str] = {}
    try:
        for sym in symbols:
            try:
                async with ScriptSessionLocal() as db:
                    r = await asyncio.wait_for(scan(db, edgar, sym, date.today()), SYMBOL_SECONDS)
                read += r.get("new", 0)
                material += r.get("material_new", 0)
                if r.get("material_new"):
                    found.append(sym)
            except Exception as exc:                   # one company's index failing never stops the rest
                failed[sym] = redact(exc)[:120]
    finally:
        await edgar.close()
    fields = {"symbols": len(symbols), "filings_read": read, "material_new": material, "with_material": found[:60],
              "failed_count": len(failed), "failed": dict(list(failed.items())[:20]), "seconds": round(time.monotonic() - t0)}
    await record_step_fields(STEP_LABEL, fields)
    print(f"{STEP_LABEL}: {fields}", flush=True)
    return 1 if len(failed) > len(symbols) // 10 else 0     # a few unreadable indexes are named; most of them failing fails the step


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
