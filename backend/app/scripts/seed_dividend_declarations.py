"""Declared dividends from stored 8-K filings onto the upcoming ex-dividend events. Dry run by default; --write stores
amount, payable and record dates, declared_on (the filing date) and the accession as the receipt.

    python -m app.scripts.seed_dividend_declarations                 # every active ticker with an upcoming ex-dividend date
    python -m app.scripts.seed_dividend_declarations --symbols=MU --write
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.dividend_declarations import parse_declaration
from app.services.edgar_client import EdgarClient
from app.services.redact import redact
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "Dividend declarations (EDGAR)"
FILING_LOOKBACK_DAYS = 60
MATCH_DAYS = 1


async def cik_for(edgar: EdgarClient, session, symbol: str) -> str | None:
    """The CIK by the symbol, else by an old symbol the ticker was renamed from."""
    cik = await edgar.get_cik(symbol)
    if cik:
        return cik
    for old in (await session.execute(text("SELECT old_symbol FROM ticker_aliases WHERE symbol = :s"), {"s": symbol})).scalars().all():
        cik = await edgar.get_cik(old)
        if cik:
            return cik
    return None


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    only = next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), None)
    only_set = {x.strip().upper() for x in only.split(",")} if only else None
    today = date.today()
    async with ScriptSessionLocal() as s:
        rows = (await s.execute(text("""
            SELECT e.id, t.symbol, e.event_date, e.metadata FROM events e JOIN tickers t ON t.id = e.ticker_id
            WHERE e.event_type = 'ex_dividend' AND e.event_date >= :today AND t.is_active ORDER BY t.symbol"""), {"today": today})).mappings().all()
    rows = [r for r in rows if not only_set or r["symbol"] in only_set]
    print(f"{STEP_LABEL} ({'write' if write else 'dry run'}): {len(rows)} upcoming ex-dividend event(s)")
    edgar = EdgarClient()
    declared, unmatched, nothing, failed = [], [], [], []
    try:
        async with ScriptSessionLocal() as s:
            for r in rows:
                try:
                    cik = await cik_for(edgar, s, r["symbol"])
                    if not cik:
                        nothing.append(f"{r['symbol']}: no CIK"); continue
                    recent = [x for x in await edgar.get_all_8k_records(cik) if x["filing_date"] >= (today - timedelta(days=FILING_LOOKBACK_DAYS)).isoformat()]
                    found = None
                    for rec in recent:
                        for name, body in await edgar.filing_texts(cik, rec["accession"], rec.get("primary_document") or ""):   # the cover and its exhibits
                            decl = parse_declaration(body, date.fromisoformat(rec["filing_date"]))
                            if decl:
                                found = (decl, {**rec, "document": name}); break
                        if found:
                            break
                    if not found:
                        nothing.append(f"{r['symbol']}: no declaration in {len(recent)} 8-K(s)"); continue
                    decl, rec = found
                    if decl["record_date"] is None or abs((decl["record_date"] - r["event_date"]).days) > MATCH_DAYS:
                        unmatched.append(f"{r['symbol']}: declaration record {decl['record_date']} vs stored ex-date {r['event_date']}"); continue
                    meta = {**(r["metadata"] or {}), "dividend_amount": decl["amount"], "basis": "declared_8k", "declared": True,
                            "declared_on": decl["declared_on"].isoformat(), "payable_date": decl["payable_date"].isoformat() if decl["payable_date"] else None,
                            "record_date": decl["record_date"].isoformat(), "declaration_accession": rec["accession"]}
                    label = f"{r['symbol']} {r['event_date']}: ${decl['amount']:.2f} declared {decl['declared_on']} (8-K {rec['accession']} {rec.get('document', '')}), payable {decl['payable_date']}"
                    declared.append(label)
                    print("  " + label)
                    if write:
                        import json
                        await s.execute(text("UPDATE events SET metadata = CAST(:m AS jsonb), updated_at = now() WHERE id = :i"), {"m": json.dumps(meta), "i": r["id"]})
                except Exception as exc:
                    failed.append(f"{r['symbol']}: {redact(exc)[:100]}")
            if write:
                await s.commit()
    finally:
        await edgar.close()
    print(f"  declared {len(declared)}, unmatched {len(unmatched)}, none found {len(nothing)}, failed {len(failed)}" + ("" if write else "; dry run, nothing written"))
    if write:
        await record_step_fields(STEP_LABEL, {"events": len(rows), "declared": len(declared), "unmatched": unmatched[:40], "none": len(nothing), "failed": failed[:40], "error": None})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
