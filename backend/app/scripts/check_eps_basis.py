"""Check every stored earnings actual against EDGAR XBRL diluted EPS and store the result.

For each ticker with earnings rows: CIK -> companyfacts (cached on disk per
CIK for the run) -> quarterly EPS facts (services/eps_basis) -> one
eps_basis_checks row per earnings row with match_status matched /
off_by_split / unmatched / no_fact / no_filing. Read-only on every other table.

CLI
---
    python -m app.scripts.check_eps_basis
    python -m app.scripts.check_eps_basis --symbol UBER
    python -m app.scripts.check_eps_basis --limit 20
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.eps_basis_check import EpsBasisCheck
from app.scripts.backfill_report_timing import CIK_OVERRIDES
from app.services.edgar_client import EdgarClient, _cache_fresh, _cache_path
from app.services.eps_basis import match_actual, quarter_facts
from app.services.split_basis import candidates, load_splits, splits_after

REQUEST_GAP_SECONDS = 0.12   # EDGAR fair-use: under 10 requests/second
CACHE_MAX_AGE_H = 24

ROWS_SQL = text("""
    SELECT hr.ticker_id, t.symbol, hr.event_date, hr.eps_actual
    FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id
    WHERE hr.event_type = 'earnings' AND hr.eps_actual IS NOT NULL
    ORDER BY t.symbol, hr.event_date
""")


async def _company_facts(edgar: EdgarClient, cik: str) -> dict | None:
    """companyfacts for a CIK, from the on-disk cache when fresh; None on 404."""
    path = _cache_path(f"companyfacts_{cik}.json")
    if _cache_fresh(path, CACHE_MAX_AGE_H):
        return json.loads(path.read_text())
    try:
        facts = await edgar.get_company_facts(cik)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return None
        raise
    finally:
        await asyncio.sleep(REQUEST_GAP_SECONDS)
    path.write_text(json.dumps(facts))
    return facts


async def _ciks_for(symbol: str, edgar: EdgarClient) -> list[str]:
    if symbol in CIK_OVERRIDES:
        return list(CIK_OVERRIDES[symbol])
    cik = await edgar.get_cik(symbol)
    return [cik] if cik else []


async def check_ticker(session, edgar: EdgarClient, ticker_id, symbol: str, rows: list) -> Counter:
    """Match every earnings row of one ticker; upsert eps_basis_checks; return status counts."""
    facts_by_end: dict = {}
    filing_found = False
    for cik in await _ciks_for(symbol, edgar):
        facts = await _company_facts(edgar, cik)
        if facts is None:
            continue
        filing_found = True
        for end, fs in quarter_facts(facts).items():
            facts_by_end.setdefault(end, []).extend(fs)     # predecessor and current filer both count
    splits = await load_splits(session, ticker_id)
    counts: Counter = Counter()
    now = datetime.now(timezone.utc)
    for r in rows:
        if not filing_found:
            m = None
            status = "no_filing"
        else:
            m = match_actual(r.eps_actual, r.event_date, facts_by_end, candidates(splits_after(splits, r.event_date)))
            status = m.status
        counts[status] += 1
        values = dict(
            ticker_id=ticker_id, event_date=r.event_date, stored_actual=r.eps_actual,
            xbrl_eps=m.xbrl_eps if m else None, xbrl_tag=m.tag if m else None,
            xbrl_period_end=m.period_end if m else None, match_status=status,
            split_factor=m.split_factor if m else None, checked_at=now,
        )
        stmt = pg_insert(EpsBasisCheck).values(**values).on_conflict_do_update(
            constraint="uq_eps_basis_checks_ticker_event",
            set_={k: v for k, v in values.items() if k not in ("ticker_id", "event_date")},
        )
        await session.execute(stmt)
    await session.commit()
    return counts


async def main(only_symbol: str | None, limit: int | None) -> int:
    edgar = EdgarClient()
    total: Counter = Counter()
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(ROWS_SQL)).all()
            by_ticker: dict = {}
            for r in rows:
                if only_symbol and r.symbol != only_symbol.upper():
                    continue
                by_ticker.setdefault((r.ticker_id, r.symbol), []).append(r)
            items = list(by_ticker.items())[:limit] if limit else list(by_ticker.items())
            print(f"Checking {sum(len(v) for _, v in items)} earnings rows across {len(items)} tickers", flush=True)
            for i, ((ticker_id, symbol), trs) in enumerate(items, 1):
                try:
                    counts = await check_ticker(session, edgar, ticker_id, symbol, trs)
                except Exception as exc:
                    await session.rollback()
                    print(f"  {symbol:6s} ERROR {exc}", flush=True)
                    continue
                total.update(counts)
                if i % 25 == 0 or only_symbol:
                    print(f"  [{i}/{len(items)}] {symbol:6s} {dict(counts)}", flush=True)
    finally:
        await edgar.close()
    print(f"Done: {dict(total)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check stored EPS actuals against EDGAR XBRL")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.symbol, args.limit)))
