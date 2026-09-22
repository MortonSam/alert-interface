"""Check every stored earnings actual against EDGAR XBRL diluted EPS and store the result.

For each ticker with earnings rows: CIK -> companyfacts (cached on disk per
CIK for the run) -> quarterly EPS facts (services/eps_basis) -> one
eps_basis_checks row per earnings row with match_status matched /
off_by_split / unmatched / no_fact / no_filing, plus basis_mismatch (estimate
matches GAAP, actual does not: services/eps_basis.classify). Then applies the
exclusion: flagged rows get outcome 'unknown' in historical_reactions and
rows no longer flagged get their outcome re-derived. Writes nothing else.

Nightly it runs right after the earnings seeder with --incremental: only rows
with no check row yet, or whose stored actual changed since the last check,
are re-matched; companyfacts come from the on-disk cache when fresh; the run
stops cleanly at TIME_BUDGET_SECONDS and the rest waits for the next night.

CLI
---
    python -m app.scripts.check_eps_basis
    python -m app.scripts.check_eps_basis --incremental
    python -m app.scripts.check_eps_basis --symbol UBER
    python -m app.scripts.check_eps_basis --limit 20
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import Counter
from datetime import datetime, timezone

import httpx
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.eps_basis_check import EpsBasisCheck
from app.scripts.backfill_report_timing import CIK_OVERRIDES
from app.services.edgar_client import EdgarClient, _cache_fresh, _cache_path
from app.services.basis_exclusion import apply_basis_exclusion
from app.services.eps_basis import apply_min_rows, classify, quarter_facts
from app.services.split_basis import candidates, load_splits, splits_after

REQUEST_GAP_SECONDS = 0.12   # EDGAR fair-use: under 10 requests/second
CACHE_MAX_AGE_H = 24
TIME_BUDGET_SECONDS = 600    # nightly: stop after this and leave the rest for the next run

ROWS_SQL = text("""
    SELECT hr.ticker_id, t.symbol, hr.event_date, hr.eps_actual, hr.eps_estimate,
           c.stored_actual AS checked_actual
    FROM historical_reactions hr
    JOIN tickers t ON t.id = hr.ticker_id
    LEFT JOIN eps_basis_checks c ON c.ticker_id = hr.ticker_id AND c.event_date = hr.event_date
    WHERE hr.event_type = 'earnings' AND hr.eps_actual IS NOT NULL
    ORDER BY t.symbol, hr.event_date
""")


def needs_check(row, incremental: bool) -> bool:
    """Incremental: rows with no check row, or whose stored actual changed since it was checked."""
    if not incremental:
        return True
    return row.checked_actual is None or row.checked_actual != row.eps_actual


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
    classified = []
    for r in rows:
        if not filing_found:
            classified.append((r, None))
        else:
            classified.append((r, classify(r.eps_actual, r.eps_estimate, r.event_date, facts_by_end,
                                           candidates(splits_after(splits, r.event_date)))))
    # A basis pattern belongs to the ticker's feed: fewer than the minimum flagged rows means none
    flags = apply_min_rows([bool(c and c.basis_mismatch) for _, c in classified])
    for (r, c), mismatch in zip(classified, flags):
        m = c.actual if c else None
        status = m.status if m else "no_filing"
        est_status = c.estimate_status if c else None
        counts[status] += 1
        if mismatch:
            counts["basis_mismatch"] += 1
        # split_factor: the actual's when it matched by a split, else the estimate's when that did
        factor = (m.split_factor if m and m.split_factor is not None else (c.estimate_split_factor if c else None))
        values = dict(
            ticker_id=ticker_id, event_date=r.event_date, stored_actual=r.eps_actual,
            xbrl_eps=m.xbrl_eps if m else None, xbrl_tag=m.tag if m else None,
            xbrl_period_end=m.period_end if m else None, match_status=status,
            split_factor=factor, estimate_status=est_status,
            basis_mismatch=mismatch, checked_at=now,
        )
        stmt = pg_insert(EpsBasisCheck).values(**values).on_conflict_do_update(
            constraint="uq_eps_basis_checks_ticker_event",
            set_={k: v for k, v in values.items() if k not in ("ticker_id", "event_date")},
        )
        await session.execute(stmt)
    await session.commit()
    return counts


async def main(only_symbol: str | None, limit: int | None, incremental: bool = False,
               budget_seconds: float = TIME_BUDGET_SECONDS) -> int:
    edgar = EdgarClient()
    total: Counter = Counter()
    t0 = time.monotonic()
    stopped_early = False
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(ROWS_SQL)).all()
            by_ticker: dict = {}
            skipped = 0
            for r in rows:
                if only_symbol and r.symbol != only_symbol.upper():
                    continue
                if not needs_check(r, incremental):
                    skipped += 1
                    continue
                by_ticker.setdefault((r.ticker_id, r.symbol), []).append(r)
            items = list(by_ticker.items())[:limit] if limit else list(by_ticker.items())
            print(f"Checking {sum(len(v) for _, v in items)} earnings rows across {len(items)} tickers"
                  + (f" ({skipped} already checked and unchanged)" if incremental else ""), flush=True)
            for i, ((ticker_id, symbol), trs) in enumerate(items, 1):
                if time.monotonic() - t0 > budget_seconds:
                    stopped_early = True
                    print(f"  Time budget of {budget_seconds:.0f}s reached after {i - 1}/{len(items)} tickers; "
                          f"the rest waits for the next run", flush=True)
                    break
                try:
                    counts = await check_ticker(session, edgar, ticker_id, symbol, trs)
                except Exception as exc:
                    await session.rollback()
                    print(f"  {symbol:6s} ERROR {exc}", flush=True)
                    continue
                total.update(counts)
                if i % 25 == 0 or only_symbol:
                    print(f"  [{i}/{len(items)}] {symbol:6s} {dict(counts)}", flush=True)
            # Flagged rows carry no outcome; rows no longer flagged get theirs back.
            cleared, restored = await apply_basis_exclusion(session)
            await session.commit()
            print(f"Basis exclusion: {cleared} outcome(s) cleared, {restored} restored")
    finally:
        await edgar.close()
    print(f"Done: {dict(total)}" + (" (stopped at the time budget)" if stopped_early else ""))
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check stored EPS actuals against EDGAR XBRL")
    parser.add_argument("--symbol", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--incremental", action="store_true",
                        help="Only rows without a check row or whose stored actual changed")
    parser.add_argument("--budget", type=float, default=TIME_BUDGET_SECONDS, help="Seconds before stopping cleanly")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(args.symbol, args.limit, args.incremental, args.budget)))
