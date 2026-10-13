"""Nightly: an expected report window per active ticker from its own past report dates in SEC filings (services/report_windows).

For each active ticker: its 8-K Item 2.02 filings of the last three years from the SEC submissions index (one request; older
index pages only until three years are covered). A company filing about four a year is taken at the item's word; one filing
more than AMBIGUOUS_PER_YEAR has each filing's documents read for per-share results. Every filing's verdict is stored per company
(release_filing_verdicts:{SYM}), so a night reads documents only for filings it has not judged. Stored under
expected_report_window:{SYM}. Tickers are visited soonest-expected first, each under TICKER_TIMEOUT_S, and the run stops at
BUDGET_SECONDS; the next night continues. SEC reads are paced at 8 a second (edgar_client). --dry-run computes and prints,
writing nothing.

    python -m app.scripts.expected_report_windows --dry-run --symbols=TSLA,JPM
    python -m app.scripts.expected_report_windows                  # the nightly step
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

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
TICKER_TIMEOUT_S = 120          # one company's index pages and document reads, before the run moves on


def _arg(argv: list[str], name: str) -> str | None:
    return next((a.split("=", 1)[1] for a in argv if a.startswith(f"--{name}=")), None)


async def order(only: set[str] | None) -> list[str]:
    """Active tickers, the soonest stored report first (a name with no stored date comes next, then the rest)."""
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""SELECT t.symbol, min(e.event_date) FILTER (WHERE e.event_date >= current_date) AS nxt FROM tickers t
            LEFT JOIN events e ON e.ticker_id = t.id AND e.event_type = 'earnings' WHERE t.is_active GROUP BY t.symbol
            ORDER BY nxt NULLS FIRST, t.symbol"""))).all()
    return [r[0] for r in rows if not only or r[0] in only]


async def window_for(edgar: EdgarClient, sym: str, today: date, write: bool, stats: dict) -> tuple[W.Window | None, str]:
    cik = await edgar.get_cik(sym)
    if not cik:
        return None, "no CIK"
    since = (today - timedelta(days=W.HISTORY_DAYS)).isoformat()
    records, reach = await edgar.get_8k_records_since(cik, since)
    filings = W.release_filing_dates(records, today)
    async with ScriptSessionLocal() as s:
        raw = await get_value(s, W.VERDICTS_KEY.format(sym=sym))
    try:
        stored = json.loads(raw) if raw else {}
    except ValueError:
        stored = {}
    ambiguous = W.is_ambiguous(filings, reach, today)
    read: dict[str, bool] = {}
    for f in W.to_read(filings, stored, ambiguous):
        try:
            read[f["accession"]] = await is_earnings_release(edgar, cik, f["accession"])
        except Exception as exc:
            stats["read_errors"] += 1
            print(f"  {sym}: {f['accession']} unread ({redact(exc)[:80]}); judged the next night", flush=True)
    stats["documents_judged"] += len(read)
    judged = W.verdicts(filings, stored, ambiguous, read)
    if write and judged != stored:
        async with ScriptSessionLocal() as s:
            await set_value(s, W.VERDICTS_KEY.format(sym=sym), json.dumps(judged, sort_keys=True))
            await s.commit()
    dates = [date.fromisoformat(v["filed"]) for v in judged.values() if v["earnings"]]
    w = W.expected_window(sym, dates, today, datetime.now(timezone.utc))
    how = f"{len(filings)} Item 2.02 filing(s) since {reach or '?'}, " + (f"ambiguous: {len(dates)} with per-share results ({len(read)} read tonight)" if ambiguous else "taken at the item")
    return w, how


async def main(argv: list[str]) -> int:
    dry = "--dry-run" in argv
    only = {x.strip().upper() for x in (_arg(argv, "symbols") or "").split(",") if x.strip()} or None
    budget = float(_arg(argv, "budget") or BUDGET_SECONDS)
    today = date.today()
    symbols = await order(only)
    edgar = EdgarClient()
    stats = {"documents_judged": 0, "read_errors": 0}
    done, windows, none, errors = 0, {}, {}, []
    t0 = time.time()
    try:
        for sym in symbols:
            if time.time() - t0 > budget:
                print(f"  budget of {budget:.0f}s reached after {done} ticker(s); the rest wait for the next night", flush=True)
                break
            try:
                w, how = await asyncio.wait_for(window_for(edgar, sym, today, not dry, stats), TICKER_TIMEOUT_S)
            except Exception as exc:          # a timeout included: the ticker waits for the next night
                errors.append(f"{sym}: {type(exc).__name__} {redact(exc)[:120]}")
                continue
            done += 1
            if w is None:
                none[sym] = how
                print(f"  {sym}: no window ({how})", flush=True)
                if not dry:              # a window an earlier night stored no longer holds: absent, never a stale projection
                    async with ScriptSessionLocal() as s:
                        await s.execute(text("DELETE FROM system_metadata WHERE key = :k"), {"k": W.KEY.format(sym=sym)})
                        await s.commit()
                continue
            windows[sym] = w.as_record()
            print(f"  {sym}: expected {w.start} to {w.end} (centre {w.center}, {w.pairs} pairs; {how})", flush=True)
            if not dry:
                async with ScriptSessionLocal() as s:
                    await set_value(s, W.KEY.format(sym=sym), json.dumps(w.as_record()))
                    await s.commit()
    finally:
        await edgar.close()
    summary = {"tickers": len(symbols), "computed": done, "windows": len(windows), "no_window": len(none), "errors": len(errors), **stats, "seconds": round(time.time() - t0),
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
