"""Precompute RV rank/percentile for all active tickers and store in rv_snapshots.

Uses bulk yf.download() in batches of 100 for speed, with per-ticker straggler
retry for any symbols missing from the bulk response.

Usage
-----
    python -m app.scripts.compute_rv_ranks
    python -m app.scripts.compute_rv_ranks --symbol AAPL
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from datetime import date, timedelta

import sqlalchemy as sa
import yfinance as yf

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.ticker import Ticker
from app.services.corporate_actions import load_action_dates
from app.services.rv_math import compute_rv_metrics
from app.services.system_metadata_service import set_value

BATCH_SIZE = 100
STRAGGLER_BACKOFF = (2, 5, 12)


def _last_trading_day(d: date | None = None) -> date:
    """Roll weekends back to Friday.  Mon-Fri pass through unchanged."""
    d = d or date.today()
    wd = d.weekday()
    if wd == 5:
        return d - timedelta(days=1)
    if wd == 6:
        return d - timedelta(days=2)
    return d


async def _upsert_snapshot(symbol: str, as_of: date, metrics: dict) -> None:
    stmt = sa.text("""
        INSERT INTO rv_snapshots
            (id, symbol, as_of_date, rv_20d, rv_rank, rv_percentile,
             rv_min_1y, rv_max_1y, sample_days, status,
             last_bar_date, last_bar_close, created_at)
        VALUES
            (gen_random_uuid(), :symbol, :as_of_date, :rv_20d, :rv_rank,
             :rv_percentile, :rv_min_1y, :rv_max_1y,
             :sample_days, :status, :last_bar_date, :last_bar_close, now())
        ON CONFLICT (symbol, as_of_date) DO UPDATE SET
            rv_20d        = EXCLUDED.rv_20d,
            rv_rank       = EXCLUDED.rv_rank,
            rv_percentile = EXCLUDED.rv_percentile,
            rv_min_1y     = EXCLUDED.rv_min_1y,
            rv_max_1y     = EXCLUDED.rv_max_1y,
            sample_days   = EXCLUDED.sample_days,
            status        = EXCLUDED.status,
            last_bar_date  = EXCLUDED.last_bar_date,
            last_bar_close = EXCLUDED.last_bar_close
    """)
    async with AsyncSessionLocal() as session:
        await session.execute(stmt, {
            "symbol": symbol,
            "as_of_date": as_of,
            "rv_20d": metrics["rv_20d"],
            "rv_rank": metrics["rv_rank"],
            "rv_percentile": metrics["rv_percentile"],
            "rv_min_1y": metrics.get("rv_min"),
            "rv_max_1y": metrics.get("rv_max"),
            "sample_days": metrics["sample_days"],
            "status": metrics["status"],
            "last_bar_date": metrics.get("last_bar_date"),
            "last_bar_close": metrics.get("last_bar_close"),
        })
        await session.commit()


async def _has_recent_row(symbol: str, as_of: date) -> bool:
    """Check if a row exists within last 5 trading days."""
    cutoff = as_of - timedelta(days=7)  # ~5 trading days
    stmt = sa.text("""
        SELECT 1 FROM rv_snapshots
        WHERE symbol = :symbol AND as_of_date >= :cutoff
        LIMIT 1
    """)
    async with AsyncSessionLocal() as session:
        result = await session.execute(stmt, {"symbol": symbol, "cutoff": cutoff})
        return result.scalar() is not None


def _bars(frame) -> "pd.DataFrame | None":
    """Close and Volume columns of a yfinance frame, rows with a close only."""
    import pandas as pd

    if not isinstance(frame, pd.DataFrame) or "Close" not in frame:
        return None
    bars = frame[["Close", "Volume"]] if "Volume" in frame else frame[["Close"]].assign(Volume=float("nan"))
    bars = bars[bars["Close"].notna()]
    return bars if not bars.empty else None


def _fetch_bulk(symbols: list[str]) -> dict:
    """Bulk download 2y daily bars. Returns {symbol: DataFrame[Close, Volume]}."""
    import pandas as pd

    data = yf.download(
        symbols,
        period="2y",
        interval="1d",
        auto_adjust=True,
        group_by="ticker",
        threads=True,
        progress=False,
    )
    result = {}
    if data is None or data.empty:
        return result

    for sym in symbols:
        try:
            bars = _bars(data if len(symbols) == 1 else data[sym])
            if bars is not None:
                result[sym] = bars
        except (KeyError, TypeError):
            pass
    return result


def _fetch_single(symbol: str):
    """Straggler retry: per-ticker fetch with backoff."""
    import pandas as pd

    for wait in STRAGGLER_BACKOFF:
        try:
            hist = yf.Ticker(symbol).history(period="2y", interval="1d", auto_adjust=True)
            bars = _bars(hist)
            if bars is not None:
                return bars
        except Exception:
            pass
        time.sleep(wait)
    return None


async def main(only_symbol: str | None = None) -> int:
    today = _last_trading_day()
    t0 = time.time()
    print(f"\nRV Rank Precompute — {today}")
    print("─" * 60)

    # ── Load universe ─────────────────────────────────────────────────────
    if only_symbol:
        symbols = [only_symbol.upper()]
    else:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                sa.select(Ticker.symbol)
                .where(Ticker.is_active.is_(True))
                .order_by(Ticker.symbol)
            )
            symbols = [row[0] for row in result.fetchall()]

    print(f"  Universe: {len(symbols)} ticker(s)")

    # Recorded splits and ex-dividends: a price gap on one of these dates is
    # not a data error (the guard in rv_math reads them).
    async with AsyncSessionLocal() as session:
        action_dates = await load_action_dates(session, symbols)

    # ── Bulk fetch in batches ─────────────────────────────────────────────
    all_bars: dict = {}
    for i in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[i : i + BATCH_SIZE]
        print(f"  Fetching batch {i // BATCH_SIZE + 1} ({len(batch)} tickers)...")
        all_bars.update(_fetch_bulk(batch))

    fetched = set(all_bars.keys())
    missing = [s for s in symbols if s not in fetched]
    print(f"  Bulk fetched: {len(fetched)}, stragglers: {len(missing)}")

    # ── Straggler retry ───────────────────────────────────────────────────
    for sym in missing:
        bars = _fetch_single(sym)
        if bars is not None:
            all_bars[sym] = bars

    # ── Compute and upsert ────────────────────────────────────────────────
    counts: dict[str, int] = {}
    ok = err = 0
    for sym in symbols:
        try:
            bars = all_bars.get(sym)
            if bars is not None:
                closes = bars["Close"]
                metrics = compute_rv_metrics(
                    closes, volumes=bars["Volume"], action_dates=action_dates.get(sym, set()),
                )
                metrics["last_bar_date"] = closes.index[-1].date()
                metrics["last_bar_close"] = round(float(closes.iloc[-1]), 4)
            else:
                # Only write fetch_failed if no recent row exists
                if await _has_recent_row(sym, today):
                    print(f"  {sym:8s}  SKIP (recent row exists, fetch failed)")
                    continue
                metrics = {
                    "rv_20d": None, "rv_rank": None, "rv_percentile": None,
                    "rv_min": None, "rv_max": None,
                    "sample_days": 0, "status": "fetch_failed",
                }

            await _upsert_snapshot(sym, today, metrics)
            status = metrics["status"]
            counts[status] = counts.get(status, 0) + 1

            rv_str = f"{metrics['rv_20d'] * 100:.2f}%" if metrics["rv_20d"] is not None else "—"
            rank_str = f"{metrics['rv_rank']:.1f}" if metrics["rv_rank"] is not None else "—"
            print(f"  {sym:8s}  RV={rv_str:8s}  rank={rank_str:5s}  [{status}]")
            ok += 1
        except Exception as exc:
            print(f"  {sym:8s}  ERROR: {exc}")
            err += 1

    duration = round(time.time() - t0, 1)
    print(f"\n  Done: {ok} OK, {err} error(s), {duration}s elapsed.")
    print(f"  Status breakdown: {counts}")

    # ── Write summary to system_metadata ──────────────────────────────────
    summary = {
        "timestamp": today.isoformat(),
        "counts_by_status": counts,
        "total_ok": ok,
        "total_err": err,
        "duration_seconds": duration,
    }
    try:
        async with AsyncSessionLocal() as session:
            await set_value(session, "rv_last_run", json.dumps(summary))
            await session.commit()
    except Exception as exc:
        print(f"  WARNING: Could not write rv_last_run metadata: {exc}")

    return 0 if err == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Precompute RV rank/percentile for tickers.")
    parser.add_argument("--symbol", metavar="SYM", default=None,
                        help="Compute for a single ticker only (default: all active).")
    args = parser.parse_args()
    sys.exit(asyncio.run(main(only_symbol=args.symbol)))
