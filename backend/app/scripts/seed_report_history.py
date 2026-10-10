"""Earnings report history for a ticker from EDGAR by CIK: every 8-K with Item 2.02 (results of operations) becomes a
company-confirmed earnings event, with its timing read from the filing's acceptance time. The CIK is found by the symbol
or by an old symbol the ticker was renamed from (VMRK through its EQR alias). Dry run by default.

    python -m app.scripts.seed_report_history VMRK
    python -m app.scripts.seed_report_history VMRK --write
    python -m app.scripts.seed_historical_reactions VMRK          # then: the reactions, from the record's stored bars
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.scripts.seed_dividend_declarations import cik_for
from app.services.earnings_release import is_earnings_release
from app.services.edgar_client import EdgarClient

HISTORY_YEARS = 5
NY = ZoneInfo("America/New_York")


def timing_from_acceptance(acceptance: str | None) -> str:
    """bmo before 09:30 New York, amc at or after 16:00, else unknown: an Item 2.02 8-K is filed the day of the release."""
    if not acceptance:
        return "unknown"
    try:
        t = datetime.fromisoformat(acceptance.replace("Z", "+00:00")).astimezone(NY).time()
    except ValueError:
        return "unknown"
    if t < datetime.strptime("09:30", "%H:%M").time():
        return "bmo"
    if t >= datetime.strptime("16:00", "%H:%M").time():
        return "amc"
    return "unknown"


def report_dates(records: list[dict], today: date) -> list[dict]:
    """Pure: the Item 2.02 filings of the last HISTORY_YEARS, one per date, newest first."""
    since = (today - timedelta(days=366 * HISTORY_YEARS)).isoformat()
    out: dict[str, dict] = {}
    for r in records:
        items = r.get("items") or ""
        if "2.02" in items and r["filing_date"] >= since and r["filing_date"] not in out:
            out[r["filing_date"]] = {"date": date.fromisoformat(r["filing_date"]), "timing": timing_from_acceptance(r.get("acceptance")), "accession": r.get("accession", "")}
    return [out[k] for k in sorted(out, reverse=True)]


async def run(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    if len(args) != 1:
        print(__doc__); return 2
    sym, write = args[0].upper(), "--write" in argv
    edgar = EdgarClient()
    try:
        async with ScriptSessionLocal() as s:
            ticker = (await s.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one_or_none()
            if ticker is None:
                print(f"no ticker {sym}"); return 2
            cik = await cik_for(edgar, s, sym)
            if not cik:
                print(f"{sym}: no CIK by the symbol or any alias"); return 1
            reports = report_dates(await edgar.get_all_8k_records(cik), date.today())
            existing = {e.event_date: e for e in (await s.execute(select(Event).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS))).scalars().all()}
            print(f"{sym} (CIK {cik}): {len(reports)} Item 2.02 report(s) in {HISTORY_YEARS} years; {len(existing)} earnings event(s) stored ({'write' if write else 'dry run'})")
            inserted = kept = confirmed = skipped = 0
            for r in reports:
                if not await is_earnings_release(edgar, cik, r["accession"]):     # Item 2.02 without per-share results (Tesla's deliveries)
                    skipped += 1
                    print(f"  {r['date']} {r['timing']:7s} not an earnings release (no per-share results in 8-K {r['accession']}): skipped")
                    continue
                near = [d for d in existing if abs((d - r['date']).days) <= 3]
                if near:
                    kept += 1
                    ev = existing[near[0]]
                    confirm = not ev.is_confirmed or (ev.report_timing == "unknown" and r["timing"] != "unknown")
                    print(f"  {r['date']} {r['timing']:7s} already stored as {near[0]}" + (" (confirming it from the filing)" if confirm else ""))
                    if confirm:
                        confirmed += 1
                        if write:   # the stored row becomes a confirmed report with the filing's timing; the reactions seeder counts it
                            ev.is_confirmed = True
                            ev.confirmation_note = f"reported on {r['date'].isoformat()} per EDGAR (8-K Item 2.02 {r['accession']})"
                            ev.unresolved_since = None
                            if ev.report_timing == "unknown" and r["timing"] != "unknown":
                                ev.report_timing, ev.report_timing_source = r["timing"], "edgar"
                    continue
                inserted += 1
                print(f"  {r['date']} {r['timing']:7s} new (8-K {r['accession']})")
                if write:
                    s.add(Event(ticker_id=ticker.id, event_type=EventType.EARNINGS, event_date=r["date"], title=f"{sym} Earnings", source=DataSource.EDGAR,
                                is_confirmed=True, confirmation_note=f"reported on {r['date'].isoformat()} per EDGAR (8-K Item 2.02 {r['accession']})",
                                report_timing=r["timing"], report_timing_source="edgar" if r["timing"] != "unknown" else "unknown", metadata_={}))
            if write:
                await s.commit()
            print(f"  {inserted} to insert, {kept} already stored ({confirmed} to confirm from the filing), {skipped} not earnings" + ("" if write else "; dry run, nothing written") +
                  (f"\n  next: python -m app.scripts.seed_historical_reactions {sym}" if write else ""))
    finally:
        await edgar.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
