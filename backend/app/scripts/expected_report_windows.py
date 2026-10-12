"""Nightly: an expected report window per active ticker from its own past report dates in SEC filings (services/report_windows).

For each active ticker: the 8-K Item 2.02 filings of the last three years (EdgarClient, cached submissions), each judged once by
the per-share rule (services/earnings_release.is_earnings_release; the verdict is kept under release_filing_verdict:{accession} so
a filing is read from EDGAR once), then the window. Stored under expected_report_window:{SYM}. Tickers are visited soonest-expected
first and the run stops at BUDGET_SECONDS; the next night continues. --dry-run computes and prints, writing nothing.

    python -m app.scripts.expected_report_windows --dry-run --symbols=TSLA,JPM
    python -m app.scripts.expected_report_windows                  # the nightly step
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import date, datetime, timezone

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services import report_windows as W
from app.services.earnings_release import is_earnings_release
from app.services.edgar_client import EdgarClient
from app.services.redact import redact
from app.services.step_outcomes import record_step_fields
from app.services.system_metadata_service import get_value, set_value

STEP_LABEL = "Expected report windows (SEC filings)"
BUDGET_SECONDS = 1200
VERDICT_KEY = "release_filing_verdict:{accession}"


def _arg(argv: list[str], name: str) -> str | None:
    return next((a.split("=", 1)[1] for a in argv if a.startswith(f"--{name}=")), None)


async def order(only: set[str] | None) -> list[str]:
    """Active tickers, the soonest stored report first (a name with no stored date comes next, then the rest)."""
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""SELECT t.symbol, min(e.event_date) FILTER (WHERE e.event_date >= current_date) AS nxt FROM tickers t
            LEFT JOIN events e ON e.ticker_id = t.id AND e.event_type = 'earnings' WHERE t.is_active GROUP BY t.symbol
            ORDER BY nxt NULLS FIRST, t.symbol"""))).all()
    return [r[0] for r in rows if not only or r[0] in only]


async def verdict(edgar: EdgarClient, cik: str, accession: str, cache: dict, write: bool) -> bool:
    key = VERDICT_KEY.format(accession=accession)
    if key in cache:
        return cache[key]
    async with ScriptSessionLocal() as s:
        raw = await get_value(s, key)
    if raw in ("true", "false"):
        cache[key] = raw == "true"
        return cache[key]
    ok = await is_earnings_release(edgar, cik, accession)
    cache[key] = ok
    if write:
        async with ScriptSessionLocal() as s:
            await set_value(s, key, "true" if ok else "false")
            await s.commit()
    return ok


async def window_for(edgar: EdgarClient, sym: str, today: date, cache: dict, write: bool) -> tuple[W.Window | None, str]:
    cik = await edgar.get_cik(sym)
    if not cik:
        return None, "no CIK"
    filings = W.release_filing_dates(await edgar.get_all_8k_records(cik), today)
    dates = [date.fromisoformat(f["filing_date"]) for f in filings if f["accession"] and await verdict(edgar, cik, f["accession"], cache, write)]
    w = W.expected_window(sym, dates, today, datetime.now(timezone.utc))
    return w, f"{len(filings)} Item 2.02 filing(s), {len(dates)} with per-share results"


async def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    only = {x.strip().upper() for x in (_arg(argv, "symbols") or "").split(",") if x.strip()} or None
    budget = float(_arg(argv, "budget") or BUDGET_SECONDS)
    today = date.today()
    symbols = await order(only)
    edgar = EdgarClient()
    cache: dict = {}
    done, windows, none, errors = 0, {}, {}, []
    t0 = time.time()
    try:
        for sym in symbols:
            if time.time() - t0 > budget:
                print(f"  budget of {budget:.0f}s reached after {done} ticker(s); the rest wait for the next night", flush=True)
                break
            try:
                w, how = await window_for(edgar, sym, today, cache, not dry)
            except Exception as exc:
                errors.append(f"{sym}: {redact(exc)[:120]}")
                continue
            done += 1
            if w is None:
                none[sym] = how
                print(f"  {sym}: no window ({how})", flush=True)
                continue
            windows[sym] = w.as_record()
            print(f"  {sym}: expected {w.start} to {w.end} (centre {w.center}, {w.pairs} pairs; {how})", flush=True)
            if not dry:
                async with ScriptSessionLocal() as s:
                    await set_value(s, W.KEY.format(sym=sym), json.dumps(w.as_record()))
                    await s.commit()
    finally:
        await edgar.close()
    summary = {"tickers": len(symbols), "computed": done, "windows": len(windows), "no_window": len(none), "errors": len(errors), "seconds": round(time.time() - t0),
               "version": W.WINDOW_VERSION, "dry_run": dry}
    print(json.dumps(summary))
    if not dry:
        await record_step_fields(STEP_LABEL, {**summary, "no_window_sample": dict(list(none.items())[:30]), "error_lines": errors[:20], "error": None})
    out = os.environ.get("REPORT_WINDOWS_OUT")
    if out:
        with open(out, "w") as fh:
            json.dump({"summary": summary, "windows": windows, "no_window": none, "errors": errors}, fh)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
