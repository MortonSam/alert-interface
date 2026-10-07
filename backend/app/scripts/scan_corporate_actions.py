"""Corporate actions from filings: for every active ticker, the 8-Ks with Item 2.01 (completion of acquisition or disposition)
filed in the last MONTHS months, each classified from its own text (services/corporate_filings) as spin_off, merger, acquisition
by share exchange or other, with the completion date and the counterparty's name. Dry run by default: lists ticker, kind, date,
counterparty and accession. --write records spin-offs, mergers and share-exchange acquisitions as corporate actions (the
events row record_corporate_action writes, with the accession as the receipt) and attaches the counterparty's name to an
Intrinio spin-off row dated within a week of the filing's date. "other" (cash deals, asset sales) is listed, never recorded.

    python -m app.scripts.scan_corporate_actions                  # every active ticker, dry run
    python -m app.scripts.scan_corporate_actions FDX CTVA BDX DD  # a few
    python -m app.scripts.scan_corporate_actions --recent=45 --write   # the nightly: filings of the last 45 days
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta

from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.services.corporate_filings import classify_item_201
from app.services.edgar_client import EdgarClient
from app.services.redact import redact
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "Corporate actions (8-K Item 2.01)"
MONTHS = 15
RECORDED_KINDS = ("spin_off", "merger", "acquisition")
MATCH_SPIN_DAYS = 7


async def record(session, ticker: Ticker, kind: str, day: date, name: str | None, accession: str) -> str:
    """Record an action as record_corporate_action does, with the filing as its receipt; returns what happened."""
    existing = (await session.execute(select(Event).where(Event.ticker_id == ticker.id, Event.event_type == EventType.OTHER, Event.event_date == day))).scalars().all()
    if any((e.metadata_ or {}).get("corporate_action") == kind for e in existing):
        return "already recorded"
    session.add(Event(ticker_id=ticker.id, event_type=EventType.OTHER, event_date=day, title=f"{ticker.symbol} {kind.replace('_', ' ')}: {name or 'a business'}", source=DataSource.EDGAR,
                      is_confirmed=True, confirmation_note=f"8-K Item 2.01 {accession}", metadata_={"corporate_action": kind, "counterparty": name, "accession": accession}))
    return "recorded"


async def attach_name(session, ticker: Ticker, day: date, name: str, accession: str) -> bool:
    """Attach the counterparty's name to an Intrinio spin-off row dated within MATCH_SPIN_DAYS of the filing's date."""
    rows = (await session.execute(select(Event).where(Event.ticker_id == ticker.id, Event.event_type == EventType.SPIN_OFF,
                                                      Event.event_date.between(day - timedelta(days=MATCH_SPIN_DAYS), day + timedelta(days=MATCH_SPIN_DAYS))))).scalars().all()
    changed = False
    for e in rows:
        if not (e.metadata_ or {}).get("counterparty"):
            e.metadata_ = {**(e.metadata_ or {}), "counterparty": name, "accession": accession}
            changed = True
    return changed


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    recent = next((int(a.split("=", 1)[1]) for a in argv if a.startswith("--recent=")), None)
    only = [a.upper() for a in argv if not a.startswith("--")]
    today = date.today()
    since = today - timedelta(days=recent) if recent else today - timedelta(days=30 * MONTHS)
    async with ScriptSessionLocal() as s:
        tickers = list((await s.execute(select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol))).scalars().all())
    if only:
        tickers = [t for t in tickers if t.symbol in only]
    print(f"{STEP_LABEL}: {len(tickers)} ticker(s), filings since {since} ({'write' if write else 'dry run'})", flush=True)
    edgar = EdgarClient()
    found: list[dict] = []
    failed = 0
    try:
        for t in tickers:
            try:
                cik = await edgar.get_cik(t.symbol)
                if not cik:
                    continue
                recs = [r for r in await edgar.get_all_8k_records(cik) if "2.01" in (r.get("items") or "") and date.fromisoformat(r["filing_date"]) >= since]
                for r in recs:
                    texts = await edgar.filing_texts(cik, r["accession"], r.get("primary_document") or r.get("primaryDocument", ""))
                    cover = next((tx for n, tx in texts if "index" not in n.lower()), "")
                    c = classify_item_201(cover, date.fromisoformat(r["filing_date"]), t.name)
                    if c is None:
                        for n, tx in texts[1:]:
                            c = classify_item_201(tx, date.fromisoformat(r["filing_date"]), t.name)
                            if c:
                                break
                    if c and c["kind"] in RECORDED_KINDS and not c["name"]:
                        for n, tx in texts[1:]:                     # an exhibit (the press release) may name the counterparty
                            c2 = classify_item_201("Item 2.01 " + tx, date.fromisoformat(r["filing_date"]), t.name)
                            if c2 and c2["name"]:
                                c["name"] = c2["name"]; break
                    if c is None:
                        c = {"kind": "unclassified", "date": date.fromisoformat(r["filing_date"]), "name": None, "evidence": ""}
                    row = {"symbol": t.symbol, "kind": c["kind"], "date": c["date"], "name": c["name"], "accession": r["accession"], "filed": r["filing_date"]}
                    found.append(row)
                    print(f"  {t.symbol:6s} {c['kind']:12s} {c['date']}  {c['name'] or '(no name read)':40s}  8-K {r['accession']} filed {r['filing_date']}", flush=True)
                    if write and c["kind"] in RECORDED_KINDS and c["date"]:
                        async with ScriptSessionLocal() as s:
                            tk = (await s.execute(select(Ticker).where(Ticker.symbol == t.symbol))).scalar_one()
                            what = await record(s, tk, c["kind"], c["date"], c["name"], r["accession"])
                            attached = c["kind"] == "spin_off" and c["name"] and await attach_name(s, tk, c["date"], c["name"], r["accession"])
                            await s.commit()
                            print(f"         {what}" + ("; name attached to the Intrinio spin-off row" if attached else ""), flush=True)
            except Exception as exc:
                failed += 1
                print(f"  {t.symbol}: failed: {redact(exc)[:100]}", flush=True)
    finally:
        await edgar.close()
    by_kind = {k: sum(1 for f in found if f["kind"] == k) for k in ("spin_off", "merger", "acquisition", "other", "unclassified")}
    print(f"  {len(found)} Item 2.01 filing(s): {by_kind}; {failed} ticker(s) failed" + ("" if write else "; dry run, nothing written"))
    if write:
        await record_step_fields(STEP_LABEL, {"filings": len(found), **by_kind, "failed": failed,
                                              "rows": [{**f, "date": f["date"].isoformat() if f["date"] else None} for f in found if f["kind"] in RECORDED_KINDS][:50], "error": None})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
