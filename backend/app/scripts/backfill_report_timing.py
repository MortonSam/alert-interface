"""Backfill earnings_report_timing from EDGAR 8-K filings.

Populates the earnings_report_timing table from:
  - Every earnings row in historical_reactions
  - Every earnings event with event_date <= today

Unknown rows are then decided by app.services.report_timing.classify, the single
timing rule also used by reclassify_report_timing. Ticker price patterns are read
from ticker_timing_patterns (a ticker without one is treated as mixed).

Usage
-----
    python -m app.scripts.backfill_report_timing
    python -m app.scripts.backfill_report_timing --symbol CAT
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.earnings_report_timing import EarningsReportTiming
from app.models.enums import EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.models.ticker_timing_pattern import TickerTimingPattern
from app.services.edgar_client import EdgarClient
from app.services.report_timing import TIMING_RULE_VERSION, classify, select_filing


# SEC company_tickers.json maps some tickers to the wrong CIK (holding company
# vs operating entity) or drops them entirely. After a reorganization the
# ticker moves to a new CIK and the earlier 8-Ks stay under the predecessor,
# so each ticker takes a list: predecessor first, current filer last.
CIK_OVERRIDES: dict[str, list[str]] = {
    "XOM":  ["0000034088", "0002115436"],   # Exxon Mobil Corp -> ExxonMobil Holdings (files from 2026)
    "AVB":  ["0000915912"],   # AVALONBAY COMMUNITIES INC
    "EA":   ["0000712515"],   # ELECTRONIC ARTS INC
    "EQR":  ["0000906107"],   # EQUITY RESIDENTIAL
    "PSKY": ["0000813828", "0002041610"],   # Paramount Global -> Paramount Skydance Corp
    "BLK":  ["0001364742", "0002012383"],   # BlackRock Finance (old BlackRock) -> BlackRock, Inc.
    "BG":   ["0001144519", "0001996862"],   # Bunge Ltd -> Bunge Global SA
    "FERG": ["0001832433", "0002011641"],   # Ferguson plc -> Ferguson Enterprises Inc.
}


async def _ciks_for(sym: str, edgar: EdgarClient) -> list[str]:
    """CIKs whose 8-Ks belong to this ticker."""
    if sym in CIK_OVERRIDES:
        return list(CIK_OVERRIDES[sym])
    cik = await edgar.get_cik(sym)
    return [cik] if cik else []


# ── Phase 0: Populate earnings_report_timing rows ────────────────────────────

async def _populate_table(session, ticker_by_sym: dict, symbol_filter: str | None) -> int:
    """Insert one row per (ticker_id, event_date) from reactions and events."""
    today = date.today()
    pairs: set[tuple] = set()  # (ticker_id, event_date)

    # From historical_reactions (earnings only)
    q_hr = select(
        HistoricalReaction.ticker_id,
        HistoricalReaction.event_date,
    ).where(HistoricalReaction.event_type == EventType.EARNINGS)
    if symbol_filter:
        t = ticker_by_sym.get(symbol_filter)
        if t:
            q_hr = q_hr.where(HistoricalReaction.ticker_id == t.id)
    for row in (await session.execute(q_hr)).all():
        pairs.add((row.ticker_id, row.event_date))

    # From events (earnings, event_date <= today)
    q_ev = select(
        Event.ticker_id,
        Event.event_date,
    ).where(
        Event.event_type == EventType.EARNINGS,
        Event.event_date <= today,
        Event.ticker_id.isnot(None),
    )
    if symbol_filter:
        t = ticker_by_sym.get(symbol_filter)
        if t:
            q_ev = q_ev.where(Event.ticker_id == t.id)
    for row in (await session.execute(q_ev)).all():
        pairs.add((row.ticker_id, row.event_date))

    # Upsert all pairs (skip existing)
    inserted = 0
    for ticker_id, event_date in pairs:
        stmt = (
            pg_insert(EarningsReportTiming)
            .values(ticker_id=ticker_id, event_date=event_date)
            .on_conflict_do_nothing(index_elements=["ticker_id", "event_date"])
        )
        result = await session.execute(stmt)
        if result.rowcount:
            inserted += 1
    await session.commit()

    print(f"Phase 0: Populated earnings_report_timing")
    print(f"  Total (ticker, event_date) pairs: {len(pairs)}")
    print(f"  Newly inserted: {inserted}")
    return len(pairs)


# ── EDGAR timing classification ──────────────────────────────────────────────

# ── Phase 1: EDGAR backfill ──────────────────────────────────────────────────

async def _phase_edgar(
    session, ticker_by_sym: dict, symbol_filter: str | None,
) -> dict[str, int]:
    """Resolve unknown rows with app.services.report_timing.classify, the single timing rule."""
    # Get all unresolved rows
    q = select(EarningsReportTiming).where(EarningsReportTiming.timing == "unknown")
    if symbol_filter:
        t = ticker_by_sym.get(symbol_filter)
        if t:
            q = q.where(EarningsReportTiming.ticker_id == t.id)
    unknown_rows = (await session.execute(q)).scalars().all()

    # Group by ticker_id
    rows_by_ticker: dict[str, list[EarningsReportTiming]] = defaultdict(list)
    for row in unknown_rows:
        rows_by_ticker[str(row.ticker_id)].append(row)

    # Build ticker_id -> symbol map
    id_to_sym = {str(t.id): sym for sym, t in ticker_by_sym.items()}

    print(f"\nPhase 1: EDGAR 8-K backfill")
    print(f"  Tickers to check: {len(rows_by_ticker)}")
    print(f"  Rows to resolve: {len(unknown_rows)}")

    # Ticker-level price patterns, maintained by reclassify_report_timing.
    patterns = {
        p.symbol: p.pattern
        for p in (await session.execute(select(TickerTimingPattern))).scalars().all()
    }

    edgar = EdgarClient()
    updated = 0
    no_cik = 0
    no_8k_match = 0
    errors = 0

    try:
        for i, (tid, rows) in enumerate(sorted(rows_by_ticker.items(), key=lambda x: id_to_sym.get(x[0], ""))):
            sym = id_to_sym.get(tid, "?")
            if (i + 1) % 50 == 0 or i == 0:
                print(f"  [{i+1}/{len(rows_by_ticker)}] {sym}...", flush=True)

            ciks = await _ciks_for(sym, edgar)
            if not ciks:
                no_cik += len(rows)
                continue

            try:
                all_8ks = []
                for cik in ciks:
                    all_8ks.extend(await edgar.get_all_8k_filings(cik))
            except Exception as exc:
                if i < 3:
                    print(f"    {sym}: EDGAR error: {exc}")
                errors += len(rows)
                continue

            await asyncio.sleep(0.12)

            pattern = patterns.get(sym, "mixed")
            for row in rows:
                filing = select_filing(all_8ks, row.event_date)
                decision = classify(sym, row.event_date, filing, pattern, "unknown")
                if decision.timing == "unknown":
                    no_8k_match += 1
                    continue

                row.timing = decision.timing
                row.source = "edgar"
                row.acceptance_datetime = filing.acceptance if filing else None
                row.timing_source = decision.source
                row.timing_rule_version = TIMING_RULE_VERSION
                updated += 1

        await session.commit()
    finally:
        await edgar.close()

    print(f"\n  EDGAR results:")
    print(f"    Updated: {updated}")
    print(f"    No CIK: {no_cik}")
    print(f"    No 8-K match: {no_8k_match}")
    print(f"    Errors: {errors}")

    return {"updated": updated, "no_match": no_8k_match}


# ── Phase 3: Copy timing to historical_reactions ─────────────────────────────

async def _phase_copy(session, symbol_filter: str | None, ticker_by_sym: dict) -> int:
    """Copy resolved timing from earnings_report_timing to historical_reactions."""
    from sqlalchemy import text

    where_clause = ""
    if symbol_filter:
        t = ticker_by_sym.get(symbol_filter)
        if t:
            where_clause = f"AND hr.ticker_id = '{t.id}'"

    result = await session.execute(text(f"""
        UPDATE historical_reactions hr
        SET report_timing = ert.timing
        FROM earnings_report_timing ert
        WHERE hr.ticker_id = ert.ticker_id
          AND hr.event_date = ert.event_date
          AND hr.event_type = 'earnings'
          AND ert.timing != 'unknown'
          AND hr.report_timing = 'unknown'
          {where_clause}
    """))
    count = result.rowcount
    await session.commit()
    print(f"\nPhase 3: Copied timing to {count} historical_reactions rows")
    return count


# ── Coverage report ──────────────────────────────────────────────────────────

async def _print_coverage(session, symbol_filter: str | None, ticker_by_sym: dict) -> float:
    """Print coverage by year (past events only). Returns unknown percentage."""
    today = date.today()

    q = select(
        EarningsReportTiming.event_date,
        EarningsReportTiming.timing,
        EarningsReportTiming.source,
    ).where(EarningsReportTiming.event_date <= today)
    if symbol_filter:
        t = ticker_by_sym.get(symbol_filter)
        if t:
            q = q.where(EarningsReportTiming.ticker_id == t.id)

    rows = (await session.execute(q)).all()

    year_stats: dict[int, dict[str, int]] = defaultdict(lambda: {"bmo": 0, "amc": 0, "unknown": 0})
    source_stats: dict[str, int] = defaultdict(int)

    for row in rows:
        year_stats[row.event_date.year][row.timing] += 1
        if row.timing != "unknown":
            source_stats[row.source] += 1

    total = len(rows)
    total_unknown = sum(s["unknown"] for s in year_stats.values())
    unknown_pct = (total_unknown / total * 100) if total else 0

    print(f"\nCoverage by year (past events only, n={total}):")
    print(f"  {'Year':<6} {'bmo':>6} {'amc':>6} {'unknown':>8} {'total':>6} {'known%':>7}")
    print(f"  {'─' * 42}")
    for year in sorted(year_stats):
        s = year_stats[year]
        yr_total = sum(s.values())
        known_pct = ((s["bmo"] + s["amc"]) / yr_total * 100) if yr_total else 0
        print(f"  {year:<6} {s['bmo']:>6} {s['amc']:>6} {s['unknown']:>8} {yr_total:>6} {known_pct:>6.1f}%")

    print(f"\n  Sources: {dict(source_stats)}")
    print(f"  Unknown: {total_unknown}/{total} ({unknown_pct:.1f}%)")

    # Active ticker check
    total_active = len(ticker_by_sym)
    # Count active tickers where ALL past earnings have unknown timing
    unknown_ticker_count = 0
    q2 = (
        select(EarningsReportTiming.ticker_id)
        .where(
            EarningsReportTiming.event_date <= today,
            EarningsReportTiming.timing == "unknown",
        )
        .group_by(EarningsReportTiming.ticker_id)
    )
    unknown_tickers = set(str(r) for r in (await session.execute(q2)).scalars().all())
    unknown_ticker_count = len(unknown_tickers)

    print(f"\n  Tickers with any unknown: {unknown_ticker_count}/{total_active}")

    if unknown_pct > 25:
        print(f"\n  ERROR: Unknown share ({unknown_pct:.1f}%) > 25%. Investigate before proceeding.")

    return unknown_pct


# ── Main ─────────────────────────────────────────────────────────────────────

async def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill earnings_report_timing")
    parser.add_argument("--symbol", type=str, default=None)
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        tickers = (await session.execute(
            select(Ticker).where(Ticker.is_active.is_(True))
        )).scalars().all()
        ticker_by_sym = {t.symbol: t for t in tickers}
        print(f"Active tickers: {len(ticker_by_sym)}")

        symbol_filter = args.symbol.upper() if args.symbol else None
        if symbol_filter and symbol_filter not in ticker_by_sym:
            print(f"ERROR: {symbol_filter} not found in active tickers")
            return 1

        # Phase 0: Populate the table
        await _populate_table(session, ticker_by_sym, symbol_filter)

        # Phase 1: EDGAR filings through the single timing rule
        await _phase_edgar(session, ticker_by_sym, symbol_filter)

        # Phase 3: Copy to historical_reactions
        await _phase_copy(session, symbol_filter, ticker_by_sym)

        # Coverage
        unknown_pct = await _print_coverage(session, symbol_filter, ticker_by_sym)

        if unknown_pct > 25:
            return 1

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
