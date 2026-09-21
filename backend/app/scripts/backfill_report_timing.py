"""Backfill earnings_report_timing from EDGAR 8-K filings (primary) and Finnhub (secondary).

Populates the earnings_report_timing table from:
  - Every earnings row in historical_reactions
  - Every earnings event with event_date <= today

Then resolves timing via EDGAR (primary) and Finnhub per-symbol calendar (secondary).

Timing rules (EDGAR):
  - Accepted before 12:00 ET on event_date -> bmo
  - Accepted at or after 16:00 ET on event_date, or before 09:30 ET on event_date+1 -> amc
  - Anything else -> unknown

Usage
-----
    python -m app.scripts.backfill_report_timing
    python -m app.scripts.backfill_report_timing --edgar-only
    python -m app.scripts.backfill_report_timing --finnhub-only
    python -m app.scripts.backfill_report_timing --symbol CAT
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select, func as sa_func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.earnings_report_timing import EarningsReportTiming
from app.models.enums import EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.services.edgar_client import EdgarClient
from app.services.finnhub_client import FinnhubClient

ET = ZoneInfo("America/New_York")

# SEC company_tickers.json maps some tickers to the wrong CIK (holding company
# vs operating entity) or drops them entirely. After a reorganization the
# ticker moves to a new CIK and the earlier 8-Ks stay under the predecessor,
# so each ticker takes a list: predecessor first, current filer last.
CIK_OVERRIDES: dict[str, list[str]] = {
    "XOM":  ["0000034088"],   # EXXON MOBIL CORP (not ExxonMobil Holdings 0002115436)
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

def _classify_timing(acceptance_str: str, event_date: date) -> str:
    """Classify report timing from EDGAR 8-K acceptanceDateTime.

    Rules:
      - Accepted before 12:00 ET on event_date -> bmo
      - Accepted at or after 16:00 ET on event_date -> amc
      - Accepted before 09:30 ET on event_date+1 -> amc
      - Accepted at or after 16:00 ET on event_date-1 -> bmo
        (filed after close the prior day; yfinance records reaction day as event_date,
         gap lands at open(T), so the correct window is bmo)
      - Anything else -> unknown
    """
    try:
        dt_utc = datetime.fromisoformat(acceptance_str.replace("Z", "+00:00"))
        dt_et = dt_utc.astimezone(ET)
    except (ValueError, TypeError):
        return "unknown"

    accept_date = dt_et.date()
    accept_hour = dt_et.hour
    accept_minute = dt_et.minute

    if accept_date == event_date:
        # Same day: before 12:00 ET = bmo, at or after 16:00 ET = amc
        if accept_hour < 12:
            return "bmo"
        if accept_hour >= 16:
            return "amc"
        return "unknown"
    elif accept_date == event_date + timedelta(days=1):
        # Next calendar day: before 09:30 ET = amc (filed overnight after close)
        if accept_hour < 9 or (accept_hour == 9 and accept_minute < 30):
            return "amc"
        return "unknown"
    elif accept_date == event_date - timedelta(days=1):
        # Prior day after close: yfinance records reaction day as event_date
        if accept_hour >= 16:
            return "bmo"
        return "unknown"
    else:
        return "unknown"


EARNINGS_ITEM = "2.02"          # 8-K item "Results of Operations and Financial Condition"
ITEM_202_WINDOW_DAYS = 3        # how far from event_date an Item 2.02 filing may sit


def _has_earnings_item(items: str) -> bool:
    return EARNINGS_ITEM in [i.strip() for i in items.split(",")]


def _parse_acceptance(at_str: str) -> datetime | None:
    try:
        return datetime.fromisoformat(at_str.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def select_timing(
    filings: list[tuple[str, str, str]], event_date: date,
) -> tuple[str, datetime | None, str]:
    """Pick the 8-K that dates this earnings report. Returns (timing, acceptance, basis).

    Prefers the Item 2.02 filing nearest event_date (within ITEM_202_WINDOW_DAYS;
    ties go to the earliest acceptance). Only when no Item 2.02 filing exists
    does it fall back to any 8-K filed on event_date or the day after.
    """
    dated: list[tuple[date, str, str]] = []
    for fd_str, at_str, items in filings:
        try:
            dated.append((date.fromisoformat(fd_str), at_str, items))
        except (ValueError, TypeError):
            continue

    earnings = [
        f for f in dated
        if _has_earnings_item(f[2]) and abs((f[0] - event_date).days) <= ITEM_202_WINDOW_DAYS
    ]
    if earnings:
        fd, at_str, _ = min(earnings, key=lambda f: (abs((f[0] - event_date).days), f[1]))
        timing = _classify_timing(at_str, event_date)
        return timing, _parse_acceptance(at_str) if timing != "unknown" else None, f"item 2.02 filed {fd}"

    for fd, at_str, _ in dated:
        if fd in (event_date, event_date + timedelta(days=1)):
            timing = _classify_timing(at_str, event_date)
            if timing != "unknown":
                return timing, _parse_acceptance(at_str), f"any 8-K filed {fd} (no item 2.02 nearby)"
    return "unknown", None, "no usable 8-K"


# ── Phase 1: EDGAR backfill ──────────────────────────────────────────────────

async def _phase_edgar(
    session, ticker_by_sym: dict, symbol_filter: str | None,
) -> dict[str, int]:
    """Resolve timing via EDGAR 8-K acceptanceDateTime (primary source)."""
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

            for row in rows:
                best_timing, best_acceptance, _basis = select_timing(all_8ks, row.event_date)
                if best_timing == "unknown":
                    no_8k_match += 1
                    continue

                row.timing = best_timing
                row.source = "edgar"
                row.acceptance_datetime = best_acceptance
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


# ── Phase 2: Finnhub per-symbol fallback ─────────────────────────────────────

async def _phase_finnhub(
    session, ticker_by_sym: dict, symbol_filter: str | None,
) -> dict[str, int]:
    """Resolve remaining unknowns via Finnhub per-symbol calendar (secondary)."""
    q = select(EarningsReportTiming).where(EarningsReportTiming.timing == "unknown")
    if symbol_filter:
        t = ticker_by_sym.get(symbol_filter)
        if t:
            q = q.where(EarningsReportTiming.ticker_id == t.id)
    unknown_rows = (await session.execute(q)).scalars().all()

    rows_by_ticker: dict[str, list[EarningsReportTiming]] = defaultdict(list)
    for row in unknown_rows:
        rows_by_ticker[str(row.ticker_id)].append(row)

    id_to_sym = {str(t.id): sym for sym, t in ticker_by_sym.items()}

    print(f"\nPhase 2: Finnhub per-symbol calendar")
    print(f"  Tickers with unknowns: {len(rows_by_ticker)}")
    print(f"  Rows to resolve: {len(unknown_rows)}")

    if not unknown_rows:
        print("  Nothing to do.")
        return {"updated": 0}

    finnhub = FinnhubClient()
    updated = 0
    no_data = 0

    try:
        for i, (tid, rows) in enumerate(sorted(rows_by_ticker.items(), key=lambda x: id_to_sym.get(x[0], ""))):
            sym = id_to_sym.get(tid, "?")
            if (i + 1) % 50 == 0 or i == 0:
                print(f"  [{i+1}/{len(rows_by_ticker)}] {sym}...", flush=True)

            # Get the full 5-year range for this ticker
            min_date = min(r.event_date for r in rows)
            max_date = max(r.event_date for r in rows)
            try:
                raw = await finnhub.get_earnings_calendar(
                    min_date.isoformat(),
                    (max_date + timedelta(days=1)).isoformat(),
                    symbol=sym,
                )
            except Exception:
                no_data += len(rows)
                continue

            entries = raw.get("earningsCalendar", [])
            if not entries:
                no_data += len(rows)
                continue

            # Build date -> hour lookup
            hour_by_date: dict[date, str] = {}
            for entry in entries:
                try:
                    edate = date.fromisoformat(entry["date"])
                    hour_raw = entry.get("hour", "")
                    if hour_raw in ("bmo", "amc"):
                        hour_by_date[edate] = hour_raw
                except (KeyError, ValueError):
                    continue

            for row in rows:
                hour = hour_by_date.get(row.event_date)
                if hour:
                    row.timing = hour
                    row.source = "finnhub"
                    updated += 1
                else:
                    no_data += 1

        await session.commit()
    finally:
        await finnhub.close()

    print(f"\n  Finnhub results:")
    print(f"    Updated: {updated}")
    print(f"    No data: {no_data}")

    return {"updated": updated}


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

async def _dry_run_reclassify(session, ticker_by_sym: dict, symbols: list[str] | None, detail: set[str]) -> int:
    """Report what select_timing would give for every earnings row. Writes nothing."""
    q = (
        select(HistoricalReaction.ticker_id, HistoricalReaction.event_date, HistoricalReaction.report_timing)
        .where(HistoricalReaction.event_type == EventType.EARNINGS)
        .order_by(HistoricalReaction.event_date)
    )
    id_to_sym = {t.id: sym for sym, t in ticker_by_sym.items()}
    by_sym: dict[str, list] = defaultdict(list)
    for tid, d, timing in (await session.execute(q)).all():
        sym = id_to_sym.get(tid)
        if sym and (not symbols or sym in symbols):
            by_sym[sym].append((d, (timing or "unknown").lower()))

    print(f"DRY RUN: reclassifying {sum(len(v) for v in by_sym.values())} earnings rows "
          f"across {len(by_sym)} tickers. Nothing is written.", flush=True)
    counts: dict[str, int] = defaultdict(int)
    lines: dict[str, list[str]] = defaultdict(list)
    edgar = EdgarClient()
    try:
        for i, sym in enumerate(sorted(by_sym)):
            if i % 100 == 0:
                print(f"  [{i}/{len(by_sym)}] {sym}...", flush=True)
            filings: list[tuple[str, str, str]] = []
            try:
                for cik in await _ciks_for(sym, edgar):
                    filings.extend(await edgar.get_all_8k_filings(cik))
                    await asyncio.sleep(0.12)
            except Exception as exc:
                counts["edgar error (rows)"] += len(by_sym[sym])
                lines[sym].append(f"  EDGAR error: {exc}")
                continue
            for d, old in by_sym[sym]:
                new, acc, basis = select_timing(filings, d)
                if old == new:
                    key = "unchanged"
                elif old == "unknown":
                    key = "unknown -> known"
                elif new == "unknown":
                    key = "known -> unknown (not applied: backfill only touches unknown rows)"
                else:
                    key = f"{old} -> {new}"
                counts[key] += 1
                if sym in detail:
                    acc_s = acc.astimezone(ET).strftime("%Y-%m-%d %H:%M ET") if acc else "-"
                    lines[sym].append(f"  {d}  {old:<7} -> {new:<7} accepted {acc_s:<20} {basis}"
                                      + ("" if old == new else "   <-- changes"))
    finally:
        await edgar.close()

    print("\n── Transition counts ──")
    for k in sorted(counts, key=lambda k: -counts[k]):
        print(f"  {counts[k]:>6}  {k}")
    for sym in sorted(detail):
        if sym in lines:
            print(f"\n── {sym} ──")
            print("\n".join(lines[sym]))
    return 0


async def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill earnings_report_timing")
    parser.add_argument("--edgar-only", action="store_true")
    parser.add_argument("--finnhub-only", action="store_true")
    parser.add_argument("--symbol", type=str, default=None)
    parser.add_argument("--dry-run-reclassify", action="store_true",
                        help="report what the 8-K selection gives for every earnings row; writes nothing")
    parser.add_argument("--symbols", type=str, default=None,
                        help="comma-separated tickers to limit --dry-run-reclassify to")
    parser.add_argument("--detail", type=str, default="",
                        help="comma-separated tickers whose rows are listed in full in the dry run")
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

        if args.dry_run_reclassify:
            only = [x.strip().upper() for x in args.symbols.split(",")] if args.symbols else None
            detail = {x.strip().upper() for x in args.detail.split(",") if x.strip()}
            return await _dry_run_reclassify(session, ticker_by_sym, only, detail)

        # Phase 0: Populate the table
        await _populate_table(session, ticker_by_sym, symbol_filter)

        run_edgar = not args.finnhub_only
        run_finnhub = not args.edgar_only

        # Phase 1: EDGAR
        if run_edgar:
            await _phase_edgar(session, ticker_by_sym, symbol_filter)

        # Phase 2: Finnhub
        if run_finnhub:
            await _phase_finnhub(session, ticker_by_sym, symbol_filter)

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
