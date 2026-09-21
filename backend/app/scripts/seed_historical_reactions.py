"""Seed historical earnings reactions from yfinance.

v3: Timing-aware reaction windows.
  bmo: base = close(T-1), 1d = close(T), 3d = close(T+2), 5d = close(T+4)
  amc: base = close(T),   1d = close(T+1), 3d = close(T+3), 5d = close(T+5)
  unknown: pct fields NULL, price metadata still stored

Upserts match on (ticker_id, event_date, event_type).

CLI flags
---------
  TICKER [...]   Seed specific ticker(s) — one-off mode (unchanged)
  --all          Process every ticker in the database
  --retry-only   Only retry symbols from cache/failed_reactions.json
  --limit N      Cap the candidate list at N (for testing)

Usage
-----
    python -m app.scripts.seed_historical_reactions AAPL
    python -m app.scripts.seed_historical_reactions AAPL MSFT NVDA
    python -m app.scripts.seed_historical_reactions --all
    python -m app.scripts.seed_historical_reactions --all --limit 20
    python -m app.scripts.seed_historical_reactions --retry-only
    make seed-reactions TICKER=AAPL
    make seed-reactions-all
    make seed-reactions-retry
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import delete as sa_delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from tqdm import tqdm

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.earnings_report_timing import EarningsReportTiming
from app.models.enums import EarningsOutcome, EventType
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker


LOOKBACK_YEARS = 5
# We need T+5 data, so skip very recent earnings to avoid incomplete windows
MIN_AGE_DAYS = 8
# Never insert an earnings row when the ticker already has one this close.
DUPLICATE_GUARD_DAYS = 10
# Must match the step label in refresh.py so /health shows the refusals on that step.
SEEDER_STEP_LABEL = "Historical reactions (--all)"
# Each refused insert this run: {"symbol", "refused_date", "existing_date"}
GUARD_REFUSALS: list[dict] = []

# Bump when reaction computation logic changes, so history stays comparable.
COMPUTATION_VERSION = 3  # v3: timing-aware windows (bmo/amc)

# ── Paths ─────────────────────────────────────────────────────────────────────

CACHE_DIR              = Path(__file__).parent / "cache"
FAILED_REACTIONS_CACHE = CACHE_DIR / "failed_reactions.json"

# ── Bulk-run tuning ───────────────────────────────────────────────────────────

BULK_BATCH_SIZE    = 5
BULK_BATCH_SLEEP   = 3.0          # seconds between batches
BULK_RETRY_DELAYS  = (3, 8, 15)   # seconds for retry 1, 2, 3
FETCH_TIMEOUT      = 45           # per-ticker yfinance fetch timeout (seconds)


# ── Price helpers ─────────────────────────────────────────────────────────────

def _build_date_cache(hist: pd.DataFrame) -> np.ndarray:
    """Return numpy array of Python date objects parallel to hist rows."""
    return hist.index.map(lambda ts: ts.date()).values


def _resolved_date_on_or_after(dates: np.ndarray, target: date) -> date | None:
    """Return the actual trading date that is on or after target."""
    mask = dates >= target
    if not mask.any():
        return None
    return dates[int(np.argmax(mask))]


def _close_on_date(
    hist: pd.DataFrame, dates: np.ndarray, target: date
) -> float | None:
    """Close on an exact date (must be a trading day)."""
    mask = dates == target
    if not mask.any():
        return None
    return float(hist["Close"].iloc[int(np.argmax(mask))])


def _open_vol_on_or_after(
    hist: pd.DataFrame, dates: np.ndarray, target: date
) -> tuple[float, int] | None:
    """(open, volume) on the first trading day on or after target."""
    mask = dates >= target
    if not mask.any():
        return None
    idx = int(np.argmax(mask))
    return float(hist["Open"].iloc[idx]), int(hist["Volume"].iloc[idx])


def _close_strictly_before(
    hist: pd.DataFrame, dates: np.ndarray, target: date
) -> float | None:
    """Close on the last trading day strictly before target."""
    mask = dates < target
    if not mask.any():
        return None
    return float(hist["Close"].iloc[int(np.sum(mask)) - 1])


# ── yfinance fetch ────────────────────────────────────────────────────────────

def _compute_outcome(
    eps_estimate: Decimal | None, eps_actual: Decimal | None
) -> EarningsOutcome:
    if eps_estimate is None or eps_actual is None:
        return EarningsOutcome.UNKNOWN
    if eps_actual > eps_estimate:
        return EarningsOutcome.BEAT
    if eps_actual < eps_estimate:
        return EarningsOutcome.MISS
    return EarningsOutcome.MEET


def _fetch_earnings_dates(t: yf.Ticker) -> list[tuple[date, Decimal | None, Decimal | None]]:
    """Return list of (event_date, eps_estimate, eps_actual) within the lookback window, oldest first."""
    today = date.today()
    lookback = today - timedelta(days=LOOKBACK_YEARS * 366)
    cutoff = today - timedelta(days=MIN_AGE_DAYS)

    try:
        df = t.earnings_dates
    except Exception as exc:
        print(f"    ⚠  earnings_dates error: {exc}")
        return []

    if df is None or df.empty:
        return []

    results: list[tuple[date, Decimal | None, Decimal | None]] = []
    for ts, row in df.iterrows():
        try:
            d = ts.date() if hasattr(ts, "date") else None
        except Exception:
            continue
        if not (d and lookback <= d <= cutoff):
            continue

        def _to_dec(val) -> Decimal | None:
            try:
                if val is None or (isinstance(val, float) and np.isnan(val)):
                    return None
                return Decimal(str(round(float(val), 4)))
            except Exception:
                return None

        eps_est = _to_dec(row.get("EPS Estimate"))
        eps_act = _to_dec(row.get("Reported EPS"))
        results.append((d, eps_est, eps_act))

    return sorted(results, key=lambda x: x[0])


def _fetch_price_history(t: yf.Ticker, lookback: date) -> pd.DataFrame:
    """Fetch daily OHLCV from lookback-30d to today+2d for roll-forward buffer."""
    start = (lookback - timedelta(days=30)).isoformat()
    end   = (date.today() + timedelta(days=2)).isoformat()
    hist = t.history(start=start, end=end, auto_adjust=True)
    return hist.sort_index()


# ── Reaction computation ──────────────────────────────────────────────────────

def _close_at_offset(hist: pd.DataFrame, t_idx: int, offset: int) -> float | None:
    """Close on the Nth trading day after t_idx (1-indexed offset).
    Returns None if the target row has zero or NaN volume (halted/stale)."""
    target_idx = t_idx + offset
    if target_idx >= len(hist):
        return None
    vol = hist["Volume"].iloc[target_idx]
    if vol == 0 or (isinstance(vol, float) and np.isnan(vol)):
        return None
    return float(hist["Close"].iloc[target_idx])


def _compute(
    hist: pd.DataFrame,
    dates: np.ndarray,
    event_date: date,
) -> dict | None:
    # If the price history starts after the event, we have no coverage.
    if dates[0] > event_date:
        return None

    ov = _open_vol_on_or_after(hist, dates, event_date)
    if ov is None:
        return None
    open_t, vol_t = ov
    if open_t == 0:
        return None

    t_idx = int(np.argmax(dates >= event_date))

    # Event-day row with zero volume means the ticker was halted/stale.
    if vol_t == 0 or (isinstance(vol_t, float) and np.isnan(vol_t)):
        return None

    actual_t_date = dates[t_idx]

    def d2(v: float | None) -> Decimal | None:
        return Decimal(str(round(v, 4))) if v is not None else None

    def pct(close: float | None) -> Decimal | None:
        if close is None:
            return None
        return Decimal(str(round((close - open_t) / open_t * 100, 4)))

    close_t      = float(hist["Close"].iloc[t_idx])
    close_before = _close_strictly_before(hist, dates, actual_t_date)

    # Trading-day offsets: 1st, 3rd, 5th trading day after event day T.
    close_t1 = _close_at_offset(hist, t_idx, 1)
    close_t3 = _close_at_offset(hist, t_idx, 3)
    close_t5 = _close_at_offset(hist, t_idx, 5)

    # Frozen-price guard: if all available closes are identical to the event-day
    # close, the price data is stale (halted/delisted ticker).  Return price
    # metadata but null out the pct_change windows.
    closes = [c for c in (close_t1, close_t3, close_t5) if c is not None]
    frozen = closes and all(c == close_t for c in closes)

    pct_1d = None if frozen else pct(close_t1)
    pct_3d = None if frozen else pct(close_t3)
    pct_5d = None if frozen else pct(close_t5)

    # All-zero guard (v2): if every computed pct_change is exactly 0, the
    # price data is stale — a carried-forward quote with no real trading.
    # This catches edge cases the frozen guard misses (float-equality on
    # open vs close columns, volume corrections after initial fetch).
    non_none = [v for v in (pct_1d, pct_3d, pct_5d) if v is not None]
    if non_none and all(v == Decimal("0") for v in non_none):
        return None

    return dict(
        close_before  = d2(close_before),
        open_after    = d2(open_t),
        close_after   = d2(close_t),
        pct_change_1d = pct_1d,
        pct_change_3d = pct_3d,
        pct_change_5d = pct_5d,
        volume_after  = vol_t,
    )


def _compute_v3(
    hist: pd.DataFrame,
    dates: np.ndarray,
    event_date: date,
    report_timing: str,
) -> dict | None:
    """Timing-aware reaction windows.

    bmo: base = close(T-1), 1d = close(T), 3d = close(T+2), 5d = close(T+4)
    amc: base = close(T),   1d = close(T+1), 3d = close(T+3), 5d = close(T+5)
    unknown: pct fields NULL, price metadata still stored
    """
    if dates[0] > event_date:
        return None

    ov = _open_vol_on_or_after(hist, dates, event_date)
    if ov is None:
        return None
    open_t, vol_t = ov
    if open_t == 0:
        return None

    t_idx = int(np.argmax(dates >= event_date))

    if vol_t == 0 or (isinstance(vol_t, float) and np.isnan(vol_t)):
        return None

    actual_t_date = dates[t_idx]

    def d2(v: float | None) -> Decimal | None:
        return Decimal(str(round(v, 4))) if v is not None else None

    close_t = float(hist["Close"].iloc[t_idx])
    close_before = _close_strictly_before(hist, dates, actual_t_date)

    if report_timing == "bmo":
        # Pre-market report: gap is in open(T), base = close(T-1)
        base = close_before
        if base is None or base == 0:
            return None
        close_1d = close_t                              # close(T)
        close_3d = _close_at_offset(hist, t_idx, 2)     # close(T+2)
        close_5d = _close_at_offset(hist, t_idx, 4)     # close(T+4)
    elif report_timing == "amc":
        # After-close report: gap is in open(T+1), base = close(T)
        base = close_t
        if base == 0:
            return None
        close_1d = _close_at_offset(hist, t_idx, 1)     # close(T+1)
        close_3d = _close_at_offset(hist, t_idx, 3)     # close(T+3)
        close_5d = _close_at_offset(hist, t_idx, 5)     # close(T+5)
    else:
        # Unknown timing: store metadata, null out pct fields
        return dict(
            close_before  = d2(close_before),
            open_after    = d2(open_t),
            close_after   = d2(close_t),
            pct_change_1d = None,
            pct_change_3d = None,
            pct_change_5d = None,
            volume_after  = vol_t,
        )

    def pct(close: float | None) -> Decimal | None:
        if close is None:
            return None
        return Decimal(str(round((close - base) / base * 100, 4)))

    # Frozen-price guard
    closes = [c for c in (close_1d, close_3d, close_5d) if c is not None]
    frozen = closes and all(c == base for c in closes)

    pct_1d = None if frozen else pct(close_1d)
    pct_3d = None if frozen else pct(close_3d)
    pct_5d = None if frozen else pct(close_5d)

    # All-zero guard
    non_none = [v for v in (pct_1d, pct_3d, pct_5d) if v is not None]
    if non_none and all(v == Decimal("0") for v in non_none):
        return None

    return dict(
        close_before  = d2(close_before),
        open_after    = d2(open_t),
        close_after   = d2(close_t),
        pct_change_1d = pct_1d,
        pct_change_3d = pct_3d,
        pct_change_5d = pct_5d,
        volume_after  = vol_t,
    )


# ── DB upsert ─────────────────────────────────────────────────────────────────

async def upsert_reaction(
    session,
    ticker: Ticker,
    event_date: date,
    data: dict,
) -> bool | None:
    """Upsert on (ticker_id, event_date, event_type).

    Returns True if inserted, False if updated, None if the insert was refused
    because the ticker already has an earnings row within
    DUPLICATE_GUARD_DAYS (yfinance reporting one quarter under two dates).
    """
    # Check for pre-existence — also used to freeze settled estimates.
    existing = await session.execute(
        select(HistoricalReaction.id, HistoricalReaction.eps_actual).where(
            HistoricalReaction.ticker_id  == ticker.id,
            HistoricalReaction.event_date == event_date,
            HistoricalReaction.event_type == EventType.EARNINGS,
        )
    )
    row = existing.first()

    if row is None:
        neighbor = (await session.execute(
            select(HistoricalReaction.event_date).where(
                HistoricalReaction.ticker_id == ticker.id,
                HistoricalReaction.event_type == EventType.EARNINGS,
                HistoricalReaction.event_date != event_date,
                HistoricalReaction.event_date >= event_date - timedelta(days=DUPLICATE_GUARD_DAYS),
                HistoricalReaction.event_date <= event_date + timedelta(days=DUPLICATE_GUARD_DAYS),
            ).limit(1)
        )).scalar_one_or_none()
        if neighbor is not None:
            GUARD_REFUSALS.append({
                "symbol": ticker.symbol,
                "refused_date": event_date.isoformat(),
                "existing_date": neighbor.isoformat(),
            })
            print(
                f"  ⚠ {ticker.symbol}: not inserting earnings row {event_date}, "
                f"existing row {neighbor} is within {DUPLICATE_GUARD_DAYS} days",
                flush=True,
            )
            return None

    # Once a quarter has an actual, its estimates and outcome are frozen
    # facts — refreshes only update price reactions and volumes.
    _FROZEN_KEYS = {"eps_estimate", "revenue_estimate", "outcome"}
    if row is not None and row.eps_actual is not None:
        update_data = {k: v for k, v in data.items() if k not in _FROZEN_KEYS}
    else:
        update_data = data

    # Always stamp the computation version and report_timing on insert and update.
    data["computation_version"] = COMPUTATION_VERSION
    update_data["computation_version"] = COMPUTATION_VERSION
    # report_timing is passed in data dict by the caller if available
    if "report_timing" in data:
        update_data["report_timing"] = data["report_timing"]

    stmt = (
        pg_insert(HistoricalReaction)
        .values(
            ticker_id  = ticker.id,
            event_type = EventType.EARNINGS,
            event_date = event_date,
            **data,
        )
        .on_conflict_do_update(
            index_elements=["ticker_id", "event_date", "event_type"],
            index_where=text("event_type = 'earnings'"),
            set_=update_data,
        )
        .returning(HistoricalReaction.id)
    )
    await session.execute(stmt)
    return row is None


async def record_guard_refusals() -> None:
    """Write this run's duplicate-guard refusals into step_outcomes for /health."""
    from app.services.system_metadata_service import get_value, set_value

    async with AsyncSessionLocal() as session:
        raw = await get_value(session, "step_outcomes")
        outcomes = json.loads(raw) if raw else {}
        entry = outcomes.get(SEEDER_STEP_LABEL, {})
        entry["duplicate_guard_refusals"] = len(GUARD_REFUSALS)
        entry["duplicate_guard_refused"] = GUARD_REFUSALS[:50]
        outcomes[SEEDER_STEP_LABEL] = entry
        await set_value(session, "step_outcomes", json.dumps(outcomes))
        await session.commit()
    print(f"  duplicate guard: {len(GUARD_REFUSALS)} insert(s) refused", flush=True)


# ── Failed-ticker cache ───────────────────────────────────────────────────────

def load_failed_reactions() -> list[str]:
    if not FAILED_REACTIONS_CACHE.exists():
        return []
    return json.loads(FAILED_REACTIONS_CACHE.read_text())


def save_failed_reactions(symbols: list[str]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    FAILED_REACTIONS_CACHE.write_text(json.dumps(sorted(symbols), indent=2))


# ── Skip logic ────────────────────────────────────────────────────────────────

async def build_process_list(session) -> dict[str, str]:
    """Return {symbol: reason} for tickers that need processing.

    A ticker is processed only if at least one condition holds:
      (a) version_upgrade — any earnings reaction row has
          computation_version < COMPUTATION_VERSION.
      (b) new_earnings — the events table has a confirmed earnings event
          whose event_date > max(event_date) of that ticker's reactions
          AND event_date <= today - MIN_AGE_DAYS (enough time has passed
          for price data to settle).

    All other tickers are skipped.
    """
    today = date.today()
    age_cutoff = today - timedelta(days=MIN_AGE_DAYS)

    # (a) Tickers with any reaction row below current version
    needs_version = set((await session.execute(
        select(Ticker.symbol)
        .join(HistoricalReaction, HistoricalReaction.ticker_id == Ticker.id)
        .where(
            HistoricalReaction.event_type == EventType.EARNINGS,
            HistoricalReaction.computation_version < COMPUTATION_VERSION,
        )
        .group_by(Ticker.id, Ticker.symbol)
    )).scalars().all())

    # (b) Tickers with a new earnings event not yet covered by reactions.
    #     max_reaction_date = latest event_date in historical_reactions for earnings.
    #     If events has an earnings event with event_date > max_reaction_date
    #     and event_date <= age_cutoff, this ticker has an unreacted report.
    max_reaction = (
        select(
            HistoricalReaction.ticker_id,
            func.max(HistoricalReaction.event_date).label("max_date"),
        )
        .where(HistoricalReaction.event_type == EventType.EARNINGS)
        .group_by(HistoricalReaction.ticker_id)
        .subquery()
    )

    needs_new_earnings = set((await session.execute(
        select(Ticker.symbol)
        .join(Event, Event.ticker_id == Ticker.id)
        .outerjoin(max_reaction, Ticker.id == max_reaction.c.ticker_id)
        .where(
            Event.event_type == EventType.EARNINGS,
            Event.is_confirmed.is_(True),
            Event.event_date <= age_cutoff,
            # event_date > max_reaction_date (or ticker has no reactions yet)
            (max_reaction.c.max_date.is_(None))
            | (Event.event_date > max_reaction.c.max_date),
        )
        .group_by(Ticker.id, Ticker.symbol)
    )).scalars().all())

    # Build result dict with reasons
    result: dict[str, str] = {}
    for sym in sorted(needs_version | needs_new_earnings):
        reasons = []
        if sym in needs_version:
            reasons.append("version_upgrade")
        if sym in needs_new_earnings:
            reasons.append("new_earnings")
        result[sym] = ", ".join(reasons)

    return result


# ── Per-ticker seed (one-off, verbose) ────────────────────────────────────────

async def seed(symbol: str) -> None:
    sym = symbol.upper()
    print(f"\n── {sym} {'─' * (46 - len(sym))}")

    async with AsyncSessionLocal() as session:
        ticker = await session.scalar(
            select(Ticker).where(Ticker.symbol == sym)
        )
        if ticker is None:
            print(f"  ⚠  Not in DB — run `make seed TICKER={sym}` first")
            return

    lookback = date.today() - timedelta(days=LOOKBACK_YEARS * 366)
    yf_ticker = yf.Ticker(sym)

    print("  Fetching earnings dates...")
    earnings_entries = _fetch_earnings_dates(yf_ticker)
    if not earnings_entries:
        print("  ⚠  No past earnings dates found in 5-year window")
        return
    print(f"  Found {len(earnings_entries)} past earnings dates")

    print("  Fetching price history...")
    try:
        hist = _fetch_price_history(yf_ticker, lookback)
    except Exception as exc:
        print(f"  ERROR: price history failed — {exc}")
        return

    if hist.empty:
        print("  ⚠  No price history returned")
        return

    dates_cache = _build_date_cache(hist)

    inserted = updated = skipped = 0
    async with AsyncSessionLocal() as session:
        # Look up report_timing from earnings_report_timing table
        timing_rows = (await session.execute(
            select(EarningsReportTiming.event_date, EarningsReportTiming.timing)
            .where(EarningsReportTiming.ticker_id == ticker.id)
        )).all()
        timing_map = {r.event_date: r.timing for r in timing_rows}

        for event_date, eps_estimate, eps_actual in earnings_entries:
            report_timing = timing_map.get(event_date, "unknown")
            data = _compute_v3(hist, dates_cache, event_date, report_timing)
            if data is None:
                skipped += 1
                continue
            data["eps_estimate"] = eps_estimate
            data["eps_actual"]   = eps_actual
            data["outcome"]      = _compute_outcome(eps_estimate, eps_actual)
            data["report_timing"] = report_timing
            created = await upsert_reaction(session, ticker, event_date, data)
            if created is None:
                skipped += 1
            elif created:
                inserted += 1
            else:
                updated += 1
        await session.commit()

    print(f"  ✓ {inserted} inserted, {updated} updated, {skipped} skipped")


# ── Bulk infrastructure ───────────────────────────────────────────────────────

def _fetch_ticker_data_sync(symbol: str) -> tuple[list, pd.DataFrame]:
    """Sync yfinance fetch — called via run_in_executor.
    Returns (earnings_entries, hist_df); raises on hard failure.
    Always fetches price history (needed for stale-data deletion)."""
    yf_ticker = yf.Ticker(symbol)
    lookback = date.today() - timedelta(days=LOOKBACK_YEARS * 366)
    hist = _fetch_price_history(yf_ticker, lookback)
    earnings_entries = _fetch_earnings_dates(yf_ticker)
    return earnings_entries, hist


async def _seed_ticker_bulk(ticker: Ticker, loop) -> tuple[int, int, int]:
    """Seed one ticker in bulk mode. Returns (inserted, updated, no_price_data).
    Raises on any error so the retry wrapper can catch it."""
    # wait_for abandons the worker thread rather than killing it, which is
    # acceptable because the executor pool is large and the subprocess dies
    # at step end anyway.
    earnings_entries, hist = await asyncio.wait_for(
        loop.run_in_executor(None, _fetch_ticker_data_sync, ticker.symbol),
        timeout=FETCH_TIMEOUT,
    )
    if hist.empty:
        return 0, 0, 0

    dates_cache = _build_date_cache(hist)
    first_hist_date = dates_cache[0]
    inserted = updated = no_price = 0

    async with AsyncSessionLocal() as session:
        # Delete reactions whose event_date precedes available price history.
        del_result = await session.execute(
            sa_delete(HistoricalReaction).where(
                HistoricalReaction.ticker_id == ticker.id,
                HistoricalReaction.event_date < first_hist_date,
            )
        )
        n_deleted = del_result.rowcount
        if n_deleted:
            tqdm.write(f"  🗑 {ticker.symbol}: deleted {n_deleted} reaction(s) before {first_hist_date}")

        if not earnings_entries:
            await session.commit()
            return 0, 0, 0

        # Look up report_timing from earnings_report_timing table
        timing_rows = (await session.execute(
            select(EarningsReportTiming.event_date, EarningsReportTiming.timing)
            .where(EarningsReportTiming.ticker_id == ticker.id)
        )).all()
        timing_map = {r.event_date: r.timing for r in timing_rows}

        for event_date, eps_estimate, eps_actual in earnings_entries:
            report_timing = timing_map.get(event_date, "unknown")
            data = _compute_v3(hist, dates_cache, event_date, report_timing)
            if data is None:
                no_price += 1
                continue
            data["eps_estimate"] = eps_estimate
            data["eps_actual"]   = eps_actual
            data["outcome"]      = _compute_outcome(eps_estimate, eps_actual)
            data["report_timing"] = report_timing
            created = await upsert_reaction(session, ticker, event_date, data)
            if created is None:
                no_price += 1
            elif created:
                inserted += 1
            else:
                updated += 1
        await session.commit()

    return inserted, updated, no_price


async def process_ticker_bulk(ticker: Ticker, loop) -> tuple[bool, int, int, int]:
    """Fetch + upsert with retries. Returns (ok, inserted, updated, no_price)."""
    last_exc: Exception | None = None
    for attempt, delay in enumerate(BULK_RETRY_DELAYS, start=1):
        try:
            ins, upd, nop = await _seed_ticker_bulk(ticker, loop)
            return True, ins, upd, nop
        except Exception as exc:
            last_exc = exc
            if attempt < len(BULK_RETRY_DELAYS):
                await asyncio.sleep(delay)
    tqdm.write(f"  ✗ {ticker.symbol}: failed after {len(BULK_RETRY_DELAYS)} attempts — {last_exc}")
    return False, 0, 0, 0


# ── Bulk main ─────────────────────────────────────────────────────────────────

async def main_bulk(retry_only: bool, limit: int | None, force: bool = False) -> int:
    # 1. Load all active DB tickers
    async with AsyncSessionLocal() as session:
        all_tickers: list[Ticker] = list(
            (await session.execute(
                select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
            )).scalars().all()
        )

    by_symbol = {t.symbol: t for t in all_tickers}

    if retry_only:
        failed_symbols = load_failed_reactions()
        if not failed_symbols:
            print("No failed tickers in cache. Nothing to retry.")
            return 0
        candidates = [by_symbol[s] for s in failed_symbols if s in by_symbol]
        print(f"Retrying {len(candidates)} previously-failed tickers.", flush=True)
    else:
        candidates = all_tickers

    if limit is not None:
        candidates = candidates[:limit]
        print(f"--limit {limit}: processing first {len(candidates)} tickers.", flush=True)

    # 2. Build process list (all candidates when --force)
    if force:
        process_map = {t.symbol: "force" for t in candidates}
        print("--force: reprocessing all tickers.", flush=True)
    else:
        async with AsyncSessionLocal() as session:
            process_map = await build_process_list(session)

    to_process = [t for t in candidates if t.symbol in process_map]
    n_skipped = len(candidates) - len(to_process)

    print(f"{n_skipped} skipped (up-to-date, no new earnings).", flush=True)
    if to_process:
        print(f"{len(to_process)} to process:", flush=True)
        for t in to_process:
            print(f"  {t.symbol}: {process_map[t.symbol]}", flush=True)

    if not to_process:
        print("Nothing to process.")
        return 0

    # 3. Process in batches
    loop = asyncio.get_event_loop()
    succeeded: list[str] = []
    failed:    list[str] = []
    total_ins = total_upd = total_nop = 0

    batches = [to_process[i : i + BULK_BATCH_SIZE] for i in range(0, len(to_process), BULK_BATCH_SIZE)]

    with tqdm(total=len(to_process), unit="ticker", dynamic_ncols=True) as bar:
        for batch_idx, batch in enumerate(batches):
            tasks = [process_ticker_bulk(t, loop) for t in batch]
            results = await asyncio.gather(*tasks)

            for ticker, (ok, ins, upd, nop) in zip(batch, results):
                if ok:
                    succeeded.append(ticker.symbol)
                    total_ins += ins
                    total_upd += upd
                    total_nop += nop
                else:
                    failed.append(ticker.symbol)
                bar.update(1)
                bar.set_postfix(ok=len(succeeded), skip=n_skipped, fail=len(failed))

            if batch_idx < len(batches) - 1:
                await asyncio.sleep(BULK_BATCH_SLEEP)

    # 4. Persist failures
    if retry_only:
        still_failed = [s for s in load_failed_reactions() if s not in succeeded]
        save_failed_reactions(still_failed)
    else:
        existing_failed = load_failed_reactions()
        merged_failed   = sorted(set(existing_failed) | set(failed) - set(succeeded))
        save_failed_reactions(merged_failed)

    # 5. Summary
    print()
    print(f"{'─' * 50}")
    print(f"  ✓ {len(succeeded)} succeeded  ⚠ {n_skipped} skipped  ✗ {len(failed)} failed")
    print(f"  📊 {total_ins} inserted  {total_upd} updated  {total_nop} no-price-data")
    if failed:
        print(f"\n  Failed: {', '.join(failed)}")
        print("  Run `make seed-reactions-retry` to retry just those.")
    print(f"{'─' * 50}")
    return 1 if failed else 0


# ── Entry point ───────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Seed historical earnings reactions")
    p.add_argument("tickers", nargs="*", metavar="TICKER",
                   help="Specific ticker(s) to seed (one-off mode)")
    p.add_argument("--all", action="store_true", dest="all_tickers",
                   help="Process every ticker in the database")
    p.add_argument("--retry-only", action="store_true",
                   help="Only retry symbols from cache/failed_reactions.json")
    p.add_argument("--limit", type=int, default=None, metavar="N",
                   help="Cap the candidate list at N (for testing; use with --all or --retry-only)")
    p.add_argument("--force", action="store_true",
                   help="Skip the freshness check and reprocess all tickers")
    p.add_argument("--shadow", action="store_true",
                   help="Write v3 results to shadow_reactions table for comparison")
    return p.parse_args()


async def shadow_seed(symbols: list[str]) -> int:
    """Compute v3 for given symbols, compare with existing v2 data, print table."""
    print("\n── Shadow comparison (v2 vs v3) ──────────────────────────")

    for sym in symbols:
        async with AsyncSessionLocal() as session:
            ticker = await session.scalar(select(Ticker).where(Ticker.symbol == sym))
            if ticker is None:
                print(f"  {sym}: not in DB, skipping")
                continue

            # Get existing v2 reactions
            v2_rows = (await session.execute(
                select(HistoricalReaction)
                .where(
                    HistoricalReaction.ticker_id == ticker.id,
                    HistoricalReaction.event_type == EventType.EARNINGS,
                )
                .order_by(HistoricalReaction.event_date.desc())
            )).scalars().all()

            v2_by_date = {r.event_date: r for r in v2_rows}

            # Look up timing from earnings_report_timing
            timing_rows = (await session.execute(
                select(EarningsReportTiming.event_date, EarningsReportTiming.timing)
                .where(EarningsReportTiming.ticker_id == ticker.id)
            )).all()
            timing_map = {r.event_date: r.timing for r in timing_rows}

        # Fetch price history
        lookback = date.today() - timedelta(days=LOOKBACK_YEARS * 366)
        yf_ticker = yf.Ticker(sym)
        try:
            hist = _fetch_price_history(yf_ticker, lookback)
        except Exception as exc:
            print(f"  {sym}: price history failed -- {exc}")
            continue
        if hist.empty:
            continue

        dates_cache = _build_date_cache(hist)

        def fmt(val) -> str:
            if val is None:
                return "   --"
            v = float(val)
            return f"{v:+7.2f}"

        print(f"\n  {sym}:")
        print(f"  {'Date':<12} {'Timing':<8} {'v2 1d':>8} {'v3 1d':>8} {'v2 3d':>8} {'v3 3d':>8} {'v2 5d':>8} {'v3 5d':>8}")
        print(f"  {'─' * 72}")

        v2_abs_1d_vals: list[float] = []
        v3_abs_1d_vals: list[float] = []

        for edate in sorted(v2_by_date, reverse=True):
            v2 = v2_by_date[edate]
            timing = timing_map.get(edate, "unknown")
            v3_data = _compute_v3(hist, dates_cache, edate, timing)

            v2_1d = fmt(v2.pct_change_1d)
            v2_3d = fmt(v2.pct_change_3d)
            v2_5d = fmt(v2.pct_change_5d)
            v3_1d = fmt(v3_data.get("pct_change_1d") if v3_data else None)
            v3_3d = fmt(v3_data.get("pct_change_3d") if v3_data else None)
            v3_5d = fmt(v3_data.get("pct_change_5d") if v3_data else None)

            if v2.pct_change_1d is not None:
                v2_abs_1d_vals.append(abs(float(v2.pct_change_1d)))
            v3_pct = v3_data.get("pct_change_1d") if v3_data else None
            if v3_pct is not None:
                v3_abs_1d_vals.append(abs(float(v3_pct)))

            print(f"  {edate.isoformat():<12} {timing:<8} {v2_1d} {v3_1d} {v2_3d} {v3_3d} {v2_5d} {v3_5d}")

        v2_avg = sum(v2_abs_1d_vals) / len(v2_abs_1d_vals) if v2_abs_1d_vals else 0
        v3_avg = sum(v3_abs_1d_vals) / len(v3_abs_1d_vals) if v3_abs_1d_vals else 0
        print(f"  {'─' * 72}")
        print(f"  avg abs 1d: v2={v2_avg:.2f}%  v3={v3_avg:.2f}%  (n_v2={len(v2_abs_1d_vals)}, n_v3={len(v3_abs_1d_vals)})")

    return 0


async def main() -> int:
    args = parse_args()

    if args.shadow:
        symbols = [s.upper() for s in args.tickers]
        if not symbols:
            print("--shadow requires ticker symbols. Usage:")
            print("  python -m app.scripts.seed_historical_reactions --shadow CAT JCI JPM MU NVDA AAPL")
            return 1
        return await shadow_seed(symbols)

    if args.all_tickers or args.retry_only:
        rc = await main_bulk(retry_only=args.retry_only, limit=args.limit, force=args.force)
        await record_guard_refusals()
        return rc

    # One-off mode: positional TICKER args
    symbols = [s.upper() for s in args.tickers]
    if not symbols:
        print("Usage: python -m app.scripts.seed_historical_reactions SYMBOL [SYMBOL ...]")
        print("       python -m app.scripts.seed_historical_reactions --all [--limit N]")
        print("       python -m app.scripts.seed_historical_reactions --retry-only")
        return 1

    for sym in symbols:
        await seed(sym)
    print("\n✓ Done.\n")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
