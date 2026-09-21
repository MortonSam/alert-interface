"""Re-decide every earnings row's report timing with app.services.report_timing.classify.

Dry run by default: prints transition counts and changes nothing.

With --write it:
  - upserts ticker_timing_patterns,
  - updates earnings_report_timing (timing, acceptance, timing_source, timing_rule_version),
  - updates historical_reactions.report_timing,
  - NULLs the pct and price fields on every reaction whose timing changed, so the
    row renders absent until recompute_null_reactions fills it with the right window.

Evidence (EDGAR filings and opening gaps) is fetched once and can be cached with
--cache so a --write run applies exactly what the dry run showed.

Usage:
    python -m app.scripts.reclassify_report_timing [--cache FILE] [--symbols A,B] [--write]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import yfinance as yf
from sqlalchemy import select, text

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.enums import EventType
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.scripts.backfill_report_timing import _ciks_for
from app.scripts.seed_historical_reactions import (
    LOOKBACK_YEARS,
    _build_date_cache,
    _fetch_price_history,
    _session_on_or_after,
    load_reference_sessions,
)
from app.services.edgar_client import EdgarClient
from app.services.report_timing import (
    TIMING_RULE_VERSION,
    Filing,
    classify,
    parse_acceptance,
    price_signal,
    select_filing,
    ticker_pattern,
)


def _fetch_prices(symbol: str):
    lookback = date.today() - timedelta(days=LOOKBACK_YEARS * 366)
    try:
        return symbol, _fetch_price_history(yf.Ticker(symbol), lookback)
    except Exception:
        return symbol, None


async def collect_evidence(by_sym: dict[str, list[date]]) -> dict[str, dict]:
    """{symbol: {event_date_iso: {"filing": [fd, raw, is_earnings] | None, "signal": str}}}"""
    sessions = load_reference_sessions()
    symbols = sorted(by_sym)
    with ThreadPoolExecutor(4) as pool:
        prices = dict(pool.map(_fetch_prices, symbols))

    out: dict[str, dict] = {}
    edgar = EdgarClient()
    try:
        for n, sym in enumerate(symbols):
            if n % 50 == 0:
                print(f"  evidence [{n}/{len(symbols)}] {sym}", flush=True)
            filings: list[tuple[str, str, str]] = []
            try:
                for cik in await _ciks_for(sym, edgar):
                    filings.extend(await edgar.get_all_8k_filings(cik))
                    await asyncio.sleep(0.12)
            except Exception as exc:
                print(f"  {sym}: EDGAR error, rows keep no filing: {exc}", flush=True)
            hist = prices.get(sym)
            dates = _build_date_cache(hist) if hist is not None and not hist.empty else None
            rows: dict[str, dict] = {}
            for event_date in by_sym[sym]:
                filing = select_filing(filings, event_date)
                signal = "none"
                if dates is not None:
                    # The price test anchors on an earnings filing's day; without one, on the event date.
                    anchor = filing.filing_date if filing and filing.is_earnings_item else event_date
                    f_sess = _session_on_or_after(sessions, anchor)
                    e_sess = _session_on_or_after(sessions, event_date)
                    if f_sess is not None and e_sess is not None:
                        signal = price_signal(hist, dates, sessions, f_sess, e_sess)[0]
                rows[event_date.isoformat()] = {
                    "filing": [filing.filing_date.isoformat(), filing.acceptance.isoformat(), filing.is_earnings_item]
                    if filing else None,
                    "signal": signal,
                }
            out[sym] = rows
    finally:
        await edgar.close()
    return out


def _filing_from_cache(raw) -> Filing | None:
    if not raw:
        return None
    return Filing(date.fromisoformat(raw[0]), parse_acceptance(raw[1]), bool(raw[2]))


async def _run(write: bool, cache: str | None, only: list[str] | None) -> int:
    async with AsyncSessionLocal() as session:
        tickers = {t.id: t.symbol for t in (await session.execute(
            select(Ticker).where(Ticker.is_active.is_(True)))).scalars().all()}
        stored: dict[str, list[tuple]] = defaultdict(list)
        for rid, tid, d, timing in (await session.execute(
            select(HistoricalReaction.id, HistoricalReaction.ticker_id,
                   HistoricalReaction.event_date, HistoricalReaction.report_timing)
            .where(HistoricalReaction.event_type == EventType.EARNINGS)
            .order_by(HistoricalReaction.event_date)
        )).all():
            sym = tickers.get(tid)
            if sym and (not only or sym in only):
                stored[sym].append((rid, tid, d, (timing or "unknown").lower()))

    n_rows = sum(len(v) for v in stored.values())
    print(f"Reclassifying {n_rows} earnings rows across {len(stored)} tickers "
          f"(rule v{TIMING_RULE_VERSION}, write={write})", flush=True)

    if cache and os.path.exists(cache):
        evidence = json.load(open(cache))
        print(f"Loaded evidence from {cache}")
    else:
        evidence = await collect_evidence({s: [r[2] for r in rows] for s, rows in stored.items()})
        if cache:
            json.dump(evidence, open(cache, "w"))
            print(f"Saved evidence to {cache}")

    transitions: Counter = Counter()
    sources: Counter = Counter()
    patterns = {}
    decisions = []   # (row_id, ticker_id, event_date, old, Decision, Filing | None)
    for sym, rows in stored.items():
        ev = evidence.get(sym, {})
        patterns[sym] = ticker_pattern([ev.get(r[2].isoformat(), {}).get("signal", "none") for r in rows])
        for rid, tid, d, old in rows:
            filing = _filing_from_cache(ev.get(d.isoformat(), {}).get("filing"))
            dec = classify(sym, d, filing, patterns[sym].pattern, old)
            transitions[(old, dec.timing)] += 1
            sources[(dec.timing, dec.source)] += 1
            decisions.append((rid, tid, d, old, dec, filing))

    print("\nTicker patterns:", dict(Counter(p.pattern for p in patterns.values())))
    print("\nstored -> rule : rows")
    for (old, new), n in sorted(transitions.items(), key=lambda kv: -kv[1]):
        print(f"  {old:8}-> {new:8}{n:>6}" + ("" if old == new else "   changes"))
    changed = [x for x in decisions if x[3] != x[4].timing]
    unknown_after = sum(n for (_, new), n in transitions.items() if new == "unknown")
    unknown_now = sum(n for (old, _), n in transitions.items() if old == "unknown")
    print(f"\nrows changed: {len(changed)} of {n_rows};  unknown after: {unknown_after} (now {unknown_now})")
    print("\nby rule branch:")
    for (timing, source), n in sorted(sources.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>6}  {timing:8} {source}")

    if not write:
        print("\nDry run. Re-run with --write to apply.")
        return 0

    async with AsyncSessionLocal() as session:
        for sym, p in patterns.items():
            await session.execute(text("""
                INSERT INTO ticker_timing_patterns (symbol, pattern, decisive_rows, bmo_share, rule_version, computed_at)
                VALUES (:s, :p, :n, :share, :v, now())
                ON CONFLICT (symbol) DO UPDATE SET pattern = :p, decisive_rows = :n, bmo_share = :share,
                    rule_version = :v, computed_at = now()
            """), {"s": sym, "p": p.pattern, "n": p.decisive_rows, "share": p.bmo_share, "v": TIMING_RULE_VERSION})

        for rid, tid, d, old, dec, filing in decisions:
            await session.execute(text("""
                INSERT INTO earnings_report_timing
                    (id, ticker_id, event_date, timing, source, acceptance_datetime, timing_source, timing_rule_version)
                VALUES (gen_random_uuid(), :tid, :d, :timing, :src, :acc, :tsrc, :v)
                ON CONFLICT (ticker_id, event_date) DO UPDATE SET
                    timing = :timing, source = :src, acceptance_datetime = :acc,
                    timing_source = :tsrc, timing_rule_version = :v
            """), {"tid": tid, "d": d, "timing": dec.timing,
                   "src": "edgar" if filing else "rule",
                   "acc": filing.acceptance if filing else None,
                   "tsrc": dec.source, "v": TIMING_RULE_VERSION})

        nulled = 0
        for rid, tid, d, old, dec, filing in changed:
            res = await session.execute(text("""
                UPDATE historical_reactions
                SET report_timing = :timing,
                    pct_change_1d = NULL, pct_change_3d = NULL, pct_change_5d = NULL,
                    close_before = NULL, open_after = NULL, close_after = NULL, volume_after = NULL
                WHERE id = :id
            """), {"timing": dec.timing, "id": rid})
            nulled += res.rowcount
        await session.commit()
    print(f"\nWrote {len(patterns)} ticker patterns, {len(decisions)} timing rows; "
          f"{nulled} reactions re-tagged and NULLed pending recompute.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Reclassify earnings report timing with the single rule")
    ap.add_argument("--write", action="store_true", help="apply (default: dry run)")
    ap.add_argument("--cache", default=None, help="evidence cache file: loaded if present, else written")
    ap.add_argument("--symbols", default=None)
    a = ap.parse_args()
    sys.exit(asyncio.run(_run(a.write, a.cache, [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else None)))
