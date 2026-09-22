"""Compute price reactions for analyst upgrades/downgrades.

For each active ticker:
1. Query all upgrade/downgrade events within 5 years from the events table.
2. Fetch 5-year daily price history from yfinance (one call per ticker).
3. Compute 1d and 5d price moves for each event, enriching event metadata.
4. Aggregate per-ticker stats and upsert into analyst_reaction_stats.
   Medians, averages and continuation rates count distinct sessions: three
   downgrades on one day share one price move, so they are one observation.
   *_count is the number of actions, *_sessions the number of observations.

Price convention (pre-market events — differs from earnings pipeline):
- Day 0 = event_date rolled to first trading day on/after
- Baseline = close on the last trading day strictly before day 0
- pct_change_1d = (close day 0 − baseline) / baseline × 100
- pct_change_5d = (close T+4 − baseline) / baseline × 100

CLI
---
    python -m app.scripts.compute_analyst_reactions
    python -m app.scripts.compute_analyst_reactions --limit 5
"""

from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tqdm import tqdm

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.analyst_reaction_stats import AnalystReactionStats
from app.models.enums import EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.services.price_history_exclusion import apply_exclusion
from app.scripts.seed_historical_reactions import (
    FETCH_TIMEOUT,
    _build_date_cache,
    _close_at_offset,
    _close_on_date,
    _close_prior_session,
    _fetch_price_history,
    _session_on_or_after,
    _zero_volume,
    load_reference_sessions,
)

LOOKBACK_YEARS = 5
MIN_AGE_DAYS = 8       # skip very recent events (incomplete T+5 window)
MIN_SESSIONS = 3       # null aggregates below this many distinct sessions per category
BATCH_SIZE = 5
BATCH_SLEEP = 2.0
RETRY_DELAYS = (3, 8, 15)
COMPUTATION_VERSION = 3  # v3: aggregates count distinct sessions, not actions


# ── yfinance fetch ───────────────────────────────────────────────────────────

def _fetch_history_sync(symbol: str) -> pd.DataFrame:
    """Fetch ~5 years of daily OHLCV for a ticker."""
    lookback = date.today() - timedelta(days=LOOKBACK_YEARS * 366)
    t = yf.Ticker(symbol)
    return _fetch_price_history(t, lookback)


# ── Pre-market reaction computation ─────────────────────────────────────────

def _compute_pre_market(
    hist: pd.DataFrame,
    dates: np.ndarray,
    event_date: date,
    sessions: np.ndarray,
) -> dict | None:
    """Compute reaction for a pre-market event (analyst action).

    Baseline = close of the last trading day strictly before day 0.
    pct_change_1d = (close day 0 − baseline) / baseline × 100
    pct_change_5d = (close T+4 − baseline) / baseline × 100
    """
    # Day 0 = first exchange session on or after event_date. The ticker must
    # have a bar on that exact session, and on the session before it, or the
    # move would be measured across a gap in its history.
    t0 = _session_on_or_after(sessions, event_date)
    if t0 is None:
        return None
    close_t0 = _close_on_date(hist, dates, t0)
    if close_t0 is None or _zero_volume(hist["Volume"].iloc[int(np.flatnonzero(dates == t0)[0])]):
        return None

    baseline = _close_prior_session(hist, dates, sessions, t0)
    if baseline is None or baseline == 0:
        return None

    t4 = _session_on_or_after(sessions, event_date + timedelta(days=4))
    close_t4 = None
    if t4 is not None and t4 > t0:
        n = int(np.searchsorted(sessions, t4) - np.searchsorted(sessions, t0))
        close_t4 = _close_at_offset(hist, dates, sessions, t0, n)

    def pct(close: float | None) -> float | None:
        if close is None:
            return None
        return round((close - baseline) / baseline * 100, 4)

    return {
        "pct_change_1d": pct(close_t0),
        "pct_change_5d": pct(close_t4),
        "close_before": float(baseline),
        "close_after": float(close_t0) if close_t0 is not None else None,
    }


# ── Aggregation helpers ──────────────────────────────────────────────────────

def _aggregate(rows: list[tuple[date, float, float | None]]) -> dict:
    """Aggregate (event_date, move_1d, move_5d) rows for one direction.

    Rows on the same event_date measure the same price move, so they collapse
    to one observation per session before any statistic is taken. Returns
    count (actions), sessions (distinct dates), avg_1d, median_1d, avg_5d,
    continuation_pct, sample_5d (sessions with a 5d move). Statistics are
    None below MIN_SESSIONS.
    """
    count = len(rows)
    by_session: dict[date, tuple[float, float | None]] = {}
    for event_date, d1, d5 in rows:
        by_session.setdefault(event_date, (d1, d5))
    sessions = len(by_session)
    if sessions < MIN_SESSIONS:
        return {
            "count": count, "sessions": sessions,
            "avg_1d": None, "median_1d": None,
            "avg_5d": None, "continuation_pct": None, "sample_5d": 0,
        }

    moves_1d = [d1 for d1, _ in by_session.values()]
    avg_1d = round(sum(moves_1d) / sessions, 4)
    median_1d = round(statistics.median(moves_1d), 4)

    # 5d follow-through
    pairs = [(d1, d5) for d1, d5 in by_session.values() if d5 is not None]
    if pairs:
        fives = [d5 for _, d5 in pairs]
        avg_5d = round(sum(fives) / len(fives), 4)
        continued = sum(1 for d1, d5 in pairs if (d1 >= 0) == (d5 >= 0))
        cont_pct = round(continued / len(pairs) * 100, 1)
    else:
        avg_5d = None
        cont_pct = None

    return {
        "count": count, "sessions": sessions,
        "avg_1d": avg_1d, "median_1d": median_1d,
        "avg_5d": avg_5d, "continuation_pct": cont_pct,
        "sample_5d": len(pairs),
    }


# ── Per-ticker processing ───────────────────────────────────────────────────

async def _process_ticker(ticker: Ticker, loop) -> tuple[bool, int]:
    """Process one ticker. Returns (ok, events_computed)."""
    symbol = ticker.symbol
    cutoff_old = date.today() - timedelta(days=LOOKBACK_YEARS * 366)
    cutoff_new = date.today() - timedelta(days=MIN_AGE_DAYS)

    # 1. Load upgrade/downgrade events from DB
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Event)
            .where(
                Event.ticker_id == ticker.id,
                Event.event_type == EventType.ANALYST_ACTION,
                Event.event_date >= cutoff_old,
                Event.event_date <= cutoff_new,
                Event.metadata_["action"].astext.in_(["up", "down"]),
            )
            .order_by(Event.event_date.asc())
        )
        events = list(result.scalars().all())

        if not events:
            # Clear stale analyst_action reactions for this ticker
            await session.execute(
                delete(HistoricalReaction).where(
                    HistoricalReaction.ticker_id == ticker.id,
                    HistoricalReaction.event_type == EventType.ANALYST_ACTION,
                )
            )
            await session.commit()
            await _upsert_stats(symbol, _aggregate([]), _aggregate([]))
            return True, 0

        # 2. Fetch price history (sync, in executor)
        hist = await asyncio.wait_for(
            loop.run_in_executor(None, _fetch_history_sync, symbol),
            timeout=FETCH_TIMEOUT,
        )
        if hist.empty:
            return True, 0

        dates_cache = _build_date_cache(hist)

        # 3. Delete existing analyst_action reactions (will be re-inserted below)
        await session.execute(
            delete(HistoricalReaction).where(
                HistoricalReaction.ticker_id == ticker.id,
                HistoricalReaction.event_type == EventType.ANALYST_ACTION,
            )
        )

        # 4. Compute and persist per-event reactions
        computed = 0
        for event in events:
            reaction = _compute_pre_market(hist, dates_cache, event.event_date, load_reference_sessions())

            pct_1d = None
            pct_5d = None
            close_before = None
            close_after = None
            if reaction is not None:
                pct_1d = reaction["pct_change_1d"]
                pct_5d = reaction["pct_change_5d"]
                close_before = reaction.get("close_before")
                close_after = reaction.get("close_after")

            # Persist to historical_reactions
            session.add(HistoricalReaction(
                ticker_id=ticker.id,
                event_id=event.id,
                event_type=EventType.ANALYST_ACTION,
                event_date=event.event_date,
                close_before=Decimal(str(close_before)) if close_before is not None else None,
                close_after=Decimal(str(close_after)) if close_after is not None else None,
                pct_change_1d=Decimal(str(pct_1d)) if pct_1d is not None else None,
                pct_change_5d=Decimal(str(pct_5d)) if pct_5d is not None else None,
                computation_version=COMPUTATION_VERSION,
            ))

            if pct_1d is not None:
                computed += 1

            # Enrich event metadata with reaction data
            merged = dict(event.metadata_)
            merged["pct_1d"] = round(pct_1d, 4) if pct_1d is not None else None
            merged["pct_5d"] = round(pct_5d, 4) if pct_5d is not None else None
            event.metadata_ = merged

        await session.flush()

        # 5. Recompute aggregates FROM stored rows (guarantees sample_count == total_with_moves)
        stored = (await session.execute(
            select(
                HistoricalReaction.event_date,
                HistoricalReaction.pct_change_1d,
                HistoricalReaction.pct_change_5d,
                Event.metadata_["action"].astext.label("action"),
            )
            .join(Event, HistoricalReaction.event_id == Event.id)
            .where(
                HistoricalReaction.ticker_id == ticker.id,
                HistoricalReaction.event_type == EventType.ANALYST_ACTION,
                HistoricalReaction.pct_change_1d.isnot(None),
            )
        )).all()

        def _rows(action: str) -> list[tuple[date, float, float | None]]:
            return [
                (r.event_date, float(r.pct_change_1d),
                 float(r.pct_change_5d) if r.pct_change_5d is not None else None)
                for r in stored if r.action == action
            ]
        upgrades = _rows("up")
        downgrades = _rows("down")

        await session.commit()

    # 6. Aggregate and store
    up_agg = _aggregate(upgrades)
    dn_agg = _aggregate(downgrades)
    await _upsert_stats(symbol, up_agg, dn_agg)

    return True, computed


async def _upsert_stats(symbol: str, up: dict, dn: dict) -> None:
    """Upsert aggregate stats into analyst_reaction_stats."""
    now = datetime.now(timezone.utc)
    values = dict(
        symbol=symbol,
        upgrade_count=up["count"],
        upgrade_sessions=up["sessions"],
        avg_1d_upgrade=up["avg_1d"],
        median_1d_upgrade=up["median_1d"],
        avg_5d_upgrade=up["avg_5d"],
        upgrade_5d_continuation_pct=up["continuation_pct"],
        upgrade_5d_sample=up["sample_5d"],
        downgrade_count=dn["count"],
        downgrade_sessions=dn["sessions"],
        avg_1d_downgrade=dn["avg_1d"],
        median_1d_downgrade=dn["median_1d"],
        avg_5d_downgrade=dn["avg_5d"],
        downgrade_5d_continuation_pct=dn["continuation_pct"],
        downgrade_5d_sample=dn["sample_5d"],
        computed_at=now,
    )
    update_values = {k: v for k, v in values.items() if k != "symbol"}

    async with AsyncSessionLocal() as session:
        stmt = (
            pg_insert(AnalystReactionStats)
            .values(**values)
            .on_conflict_do_update(
                constraint="uq_analyst_reaction_stats_symbol",
                set_=update_values,
            )
        )
        await session.execute(stmt)
        await session.commit()


# ── Bulk processing with retries ─────────────────────────────────────────────

async def _process_ticker_with_retries(ticker: Ticker, loop) -> tuple[bool, int]:
    last_exc: Exception | None = None
    for attempt, delay in enumerate(RETRY_DELAYS, start=1):
        try:
            return await _process_ticker(ticker, loop)
        except Exception as exc:
            last_exc = exc
            if attempt < len(RETRY_DELAYS):
                await asyncio.sleep(delay)
    tqdm.write(f"  ✗ {ticker.symbol}: failed after {len(RETRY_DELAYS)} attempts — {last_exc}")
    return False, 0


# ── Main ─────────────────────────────────────────────────────────────────────

async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compute price reactions for analyst upgrades/downgrades"
    )
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Cap the candidate list at N (for testing)")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        all_tickers: list[Ticker] = list(
            (await session.execute(
                select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
            )).scalars().all()
        )
        # Price history the RV guard rejected is not used here either.
        excluded = await apply_exclusion(session, "Analyst reaction stats")

    candidates = [t for t in all_tickers if t.symbol not in excluded]
    if args.limit is not None:
        candidates = candidates[:args.limit]
        print(f"--limit {args.limit}: processing first {len(candidates)} tickers.", flush=True)

    if not candidates:
        print("No tickers in database.")
        return 0

    loop = asyncio.get_event_loop()
    succeeded = 0
    total_computed = 0
    failed_list: list[str] = []

    batches = [candidates[i:i + BATCH_SIZE] for i in range(0, len(candidates), BATCH_SIZE)]

    with tqdm(total=len(candidates), unit="ticker", dynamic_ncols=True) as bar:
        for batch_idx, batch in enumerate(batches):
            tasks = [_process_ticker_with_retries(t, loop) for t in batch]
            results = await asyncio.gather(*tasks)

            for ticker, (ok, computed) in zip(batch, results):
                if ok:
                    succeeded += 1
                    total_computed += computed
                else:
                    failed_list.append(ticker.symbol)
                bar.update(1)
                bar.set_postfix(ok=succeeded, computed=total_computed, fail=len(failed_list))

            if batch_idx < len(batches) - 1:
                await asyncio.sleep(BATCH_SLEEP)

    print()
    print(f"{'─' * 60}")
    print(f"  ✓ {succeeded} tickers processed  📊 {total_computed} event reactions computed  ✗ {len(failed_list)} failed")
    if failed_list:
        print(f"\n  Failed: {', '.join(failed_list)}")
    print(f"{'─' * 60}")
    if len(failed_list) > 10:
        print(f"  Too many failures ({len(failed_list)} > 10) — marking step as failed.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
