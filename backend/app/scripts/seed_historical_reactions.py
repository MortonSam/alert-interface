"""Seed historical earnings reactions from yfinance.

For each past earnings date (up to 5 years back) we pull daily price history
and compute price moves relative to the open on the event day:

  open_after   : open price on event day T  (the baseline)
  close_after  : close price on event day T
  close_before : close price on the last trading day before T
  pct_change_1d: (close on first trading day >= T+1 - open_T) / open_T * 100
  pct_change_3d: (close on first trading day >= T+3 - open_T) / open_T * 100
  pct_change_5d: (close on first trading day >= T+5 - open_T) / open_T * 100
  volume_after : volume on event day T

"T+N" counts calendar days from event_date and rolls forward to the next
trading day when the target falls on a weekend or market holiday.

Upserts match on (ticker_id, event_date, event_type).

Usage
-----
    python -m app.scripts.seed_historical_reactions AAPL
    python -m app.scripts.seed_historical_reactions AAPL MSFT NVDA
    make seed-reactions TICKER=AAPL
    make seed-reactions TICKER="AAPL MSFT NVDA"
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import AsyncSessionLocal
from app.models.enums import EarningsOutcome, EventType
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker

LOOKBACK_YEARS = 5
# We need T+5 data, so skip very recent earnings to avoid incomplete windows
MIN_AGE_DAYS = 8


# ── Price helpers ─────────────────────────────────────────────────────────────

def _build_date_cache(hist: pd.DataFrame) -> np.ndarray:
    """Return numpy array of Python date objects parallel to hist rows."""
    return hist.index.map(lambda ts: ts.date()).values


def _close_on_or_after(
    hist: pd.DataFrame, dates: np.ndarray, target: date
) -> float | None:
    """Close on the first trading day on or after target."""
    mask = dates >= target
    if not mask.any():
        return None
    return float(hist["Close"].iloc[int(np.argmax(mask))])


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
    diff = eps_actual - eps_estimate
    if abs(diff) <= Decimal("0.01"):
        return EarningsOutcome.MEET
    return EarningsOutcome.BEAT if diff > 0 else EarningsOutcome.MISS


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

def _compute(
    hist: pd.DataFrame,
    dates: np.ndarray,
    event_date: date,
) -> dict | None:
    ov = _open_vol_on_or_after(hist, dates, event_date)
    if ov is None:
        return None
    open_t, vol_t = ov
    if open_t == 0:
        return None

    actual_t_date = dates[int(np.argmax(dates >= event_date))]

    def d2(v: float | None) -> Decimal | None:
        return Decimal(str(round(v, 4))) if v is not None else None

    def pct(close: float | None) -> Decimal | None:
        if close is None:
            return None
        return Decimal(str(round((close - open_t) / open_t * 100, 4)))

    close_t      = _close_on_or_after(hist, dates, event_date)
    close_before = _close_strictly_before(hist, dates, actual_t_date)

    # Resolve T+1 and T+3 normally: first trading day on or after the calendar target.
    t1_date = _resolved_date_on_or_after(dates, event_date + timedelta(days=1))
    t3_date = _resolved_date_on_or_after(dates, event_date + timedelta(days=3))

    # T+5: roll forward to the first trading day on or after (event_date + 5), BUT
    # it must be strictly later than T+3's resolved date.  Without this guard,
    # Wednesday earnings collapse T+3 and T+5 onto the same Monday
    # (Sat→Mon for +3 and Mon→Mon for +5).
    t5_calendar = event_date + timedelta(days=5)
    if t3_date is not None:
        t5_calendar = max(t5_calendar, t3_date + timedelta(days=1))
    t5_date = _resolved_date_on_or_after(dates, t5_calendar)

    close_t1 = _close_on_date(hist, dates, t1_date) if t1_date else None
    close_t3 = _close_on_date(hist, dates, t3_date) if t3_date else None
    close_t5 = _close_on_date(hist, dates, t5_date) if t5_date else None

    return dict(
        close_before  = d2(close_before),
        open_after    = d2(open_t),
        close_after   = d2(close_t),
        pct_change_1d = pct(close_t1),
        pct_change_3d = pct(close_t3),
        pct_change_5d = pct(close_t5),
        volume_after  = vol_t,
    )


# ── DB upsert ─────────────────────────────────────────────────────────────────

async def upsert_reaction(
    session,
    ticker: Ticker,
    event_date: date,
    data: dict,
) -> bool:
    """Upsert on (ticker_id, event_date, event_type). Returns True if inserted."""
    stmt = (
        pg_insert(HistoricalReaction)
        .values(
            ticker_id  = ticker.id,
            event_type = EventType.EARNINGS,
            event_date = event_date,
            **data,
        )
        .on_conflict_do_update(
            constraint = "uq_hist_reaction_ticker_date_type",
            set_       = data,
        )
        .returning(HistoricalReaction.id)
    )
    # pg_insert returns a scalar — we can't easily tell insert vs update here,
    # so we check for pre-existence first.
    existing = await session.scalar(
        select(HistoricalReaction.id).where(
            HistoricalReaction.ticker_id  == ticker.id,
            HistoricalReaction.event_date == event_date,
            HistoricalReaction.event_type == EventType.EARNINGS,
        )
    )
    await session.execute(stmt)
    return existing is None


# ── Per-ticker seed ───────────────────────────────────────────────────────────

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
        for event_date, eps_estimate, eps_actual in earnings_entries:
            data = _compute(hist, dates_cache, event_date)
            if data is None:
                skipped += 1
                continue
            data["eps_estimate"] = eps_estimate
            data["eps_actual"]   = eps_actual
            data["outcome"]      = _compute_outcome(eps_estimate, eps_actual)
            created = await upsert_reaction(session, ticker, event_date, data)
            if created:
                inserted += 1
            else:
                updated += 1
        await session.commit()

    print(f"  ✓ {inserted} inserted, {updated} updated, {skipped} skipped")


# ── Entry point ───────────────────────────────────────────────────────────────

async def main() -> None:
    symbols = [s.upper() for s in sys.argv[1:]]
    if not symbols:
        print("Usage: python -m app.scripts.seed_historical_reactions SYMBOL [SYMBOL ...]")
        sys.exit(1)

    for sym in symbols:
        await seed(sym)

    print("\n✓ Done.\n")


if __name__ == "__main__":
    asyncio.run(main())
