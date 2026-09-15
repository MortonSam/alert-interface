"""Build the earnings_features table from historical data.

Computes pre-event features for every historical earnings reaction,
replays v1 lean logic with exact thresholds, and stores the results.
All features use only data available before the event (strict no-leakage).

CLI
---
    python -m app.scripts.build_features
    python -m app.scripts.build_features --limit 10
    python -m app.scripts.build_features --skip-yfinance
"""

from __future__ import annotations

import argparse
import asyncio
import math
import statistics
import sys
import time
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

import pandas as pd
import yfinance as yf
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database import ScriptSessionLocal
from app.models.analyst_recommendation import AnalystRecommendation
from app.models.earnings_feature import EarningsFeature
from app.models.event import Event
from app.models.historical_reaction import HistoricalReaction
from app.models.iv_history import IVHistory
from app.models.ticker import Ticker

# ── V1 thresholds (exact match to thesis.py lines 1032-1155) ────────────────

EARNINGS_THRESHOLD = 0.5      # weighted_1d ±0.5%
ANALYST_THRESHOLD = 0.03      # buy-share delta ±3%
ANALYST_MIN_TOTAL = 5         # minimum analysts in each period
MOMENTUM_THRESHOLD = 5.0      # 20d return ±5%
MIN_HIST_SAMPLE = 8           # minimum prior events for earnings lean

BATCH_SIZE = 5
BATCH_SLEEP = 2.0
YF_TIMEOUT = 45


def _clean(val):
    """Convert NaN floats to None so PostgreSQL stores NULL, not 'NaN'::numeric."""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    return val


# ── Lean replay (v1 exact logic) ────────────────────────────────────────────

def _lean_earnings(weighted_1d: float | None, n_prior: int, beat_rate: float | None) -> str:
    """Replay earnings lean from thesis.py lines 1032-1057."""
    if weighted_1d is None or n_prior < MIN_HIST_SAMPLE or beat_rate is None:
        return "neutral"
    if weighted_1d > EARNINGS_THRESHOLD:
        return "bullish"
    elif weighted_1d < -EARNINGS_THRESHOLD:
        return "bearish"
    return "neutral"


def _lean_analyst(analyst_delta: float | None, latest_total: int | None, earlier_total: int | None) -> str:
    """Replay analyst lean from thesis.py lines 1059-1120."""
    if analyst_delta is None:
        return "neutral"
    if latest_total is None or earlier_total is None:
        return "neutral"
    if latest_total < ANALYST_MIN_TOTAL or earlier_total < ANALYST_MIN_TOTAL:
        return "neutral"
    if analyst_delta >= ANALYST_THRESHOLD:
        return "bullish"
    elif analyst_delta <= -ANALYST_THRESHOLD:
        return "bearish"
    return "neutral"


def _lean_momentum(momentum_20d: float | None) -> str:
    """Replay momentum lean from thesis.py lines 1122-1143."""
    if momentum_20d is None:
        return "neutral"
    if momentum_20d > MOMENTUM_THRESHOLD:
        return "bullish"
    elif momentum_20d < -MOMENTUM_THRESHOLD:
        return "bearish"
    return "neutral"


def _decision(lean_e: str, lean_a: str, lean_m: str) -> str:
    """Replay decision rule from thesis.py lines 1145-1155."""
    leans = [lean_e, lean_a, lean_m]
    bullish = sum(1 for l in leans if l == "bullish")
    bearish = sum(1 for l in leans if l == "bearish")
    if bullish >= 2 and bearish == 0:
        return "bullish"
    elif bearish >= 2 and bullish == 0:
        return "bearish"
    return "mixed"


# ── Analyst action classifier ────────────────────────────────────────────────

def _classify_action(title: str) -> str | None:
    """Map event title to upgrade/downgrade/None."""
    if ": " not in title:
        return None
    action = title.split(": ", 1)[1].strip()
    verb = action.split(" to ")[0].split(" (")[0].strip().lower()
    if verb == "upgrade":
        return "upgrade"
    elif verb == "downgrade":
        return "downgrade"
    return None  # initiate, maintain, reiterate


# ── Buy-share helper (mirrors thesis.py _buy_share) ─────────────────────────

def _buy_share(row: AnalystRecommendation) -> tuple[float, int]:
    total = row.strong_buy + row.buy + row.hold + row.sell + row.strong_sell
    if total == 0:
        return (0.0, 0)
    return ((row.strong_buy + row.buy) / total, total)


# ── yfinance price fetch ────────────────────────────────────────────────────

def _fetch_prices(symbol: str, start: date, end: date) -> pd.DataFrame | None:
    """Fetch daily close prices for a ticker."""
    try:
        t = yf.Ticker(symbol)
        df = t.history(
            start=start.isoformat(),
            end=(end + timedelta(days=5)).isoformat(),
            timeout=YF_TIMEOUT,
        )
        if df is not None and not df.empty:
            return df
    except Exception as e:
        print(f"  yfinance error for {symbol}: {e}")
    return None


def _momentum_20d(prices: pd.DataFrame, event_date: date) -> float | None:
    """Compute 20-day return as of the day before event_date."""
    if prices is None or prices.empty:
        return None

    # Get trading dates as date objects
    dates = prices.index.date
    # Find the last trading day strictly before event_date
    before_mask = dates < event_date
    if not any(before_mask):
        return None
    before_prices = prices.loc[before_mask]
    if len(before_prices) < 2:
        return None

    day_before_close = float(before_prices["Close"].iloc[-1])
    if math.isnan(day_before_close):
        return None

    # Go back ~20 trading days
    if len(before_prices) < 21:
        # Use whatever we have
        ref_close = float(before_prices["Close"].iloc[0])
    else:
        ref_close = float(before_prices["Close"].iloc[-21])

    if math.isnan(ref_close):
        return None
    if ref_close == 0:
        return None
    return round((day_before_close - ref_close) / ref_close * 100, 4)


# ── Main ────────────────────────────────────────────────────────────────────

async def main(limit: int | None = None, skip_yfinance: bool = False) -> None:
    t0 = time.time()

    async with ScriptSessionLocal() as session:
        # 1. Load all historical reactions (earnings only), ordered for grouping
        result = await session.execute(
            select(HistoricalReaction, Ticker.symbol)
            .join(Ticker, HistoricalReaction.ticker_id == Ticker.id)
            .where(HistoricalReaction.event_type == "earnings")
            .order_by(HistoricalReaction.ticker_id, HistoricalReaction.event_date)
        )
        rows = result.all()
        print(f"Loaded {len(rows)} earnings reactions")

        if not rows:
            print("No earnings reactions found. Exiting.")
            return

        # 2. Group by ticker_id
        by_ticker: dict[str, list] = defaultdict(list)
        ticker_symbols: dict[str, str] = {}
        for reaction, symbol in rows:
            by_ticker[reaction.ticker_id].append(reaction)
            ticker_symbols[reaction.ticker_id] = symbol

        tickers_list = list(by_ticker.keys())
        if limit:
            tickers_list = tickers_list[:limit]

        print(f"Processing {len(tickers_list)} tickers")

        # 3. Pre-load analyst recommendations
        rec_result = await session.execute(
            select(AnalystRecommendation).order_by(
                AnalystRecommendation.ticker_id,
                AnalystRecommendation.period.desc(),
            )
        )
        all_recs = rec_result.scalars().all()
        recs_by_ticker: dict[str, list[AnalystRecommendation]] = defaultdict(list)
        for rec in all_recs:
            recs_by_ticker[rec.ticker_id].append(rec)

        # 4. Pre-load IV history
        iv_result = await session.execute(
            select(IVHistory).order_by(IVHistory.symbol, IVHistory.date)
        )
        all_iv = iv_result.scalars().all()
        iv_by_symbol: dict[str, list[IVHistory]] = defaultdict(list)
        for iv in all_iv:
            iv_by_symbol[iv.symbol].append(iv)

        # 4b. Pre-load analyst_action events (upgrades/downgrades)
        action_result = await session.execute(
            select(Event).where(Event.event_type == "analyst_action")
            .order_by(Event.ticker_id, Event.event_date)
        )
        all_actions = action_result.scalars().all()
        actions_by_ticker: dict[str, list] = defaultdict(list)
        for ev in all_actions:
            if ev.ticker_id is not None:
                classified = _classify_action(ev.title)
                if classified:
                    actions_by_ticker[ev.ticker_id].append((ev.event_date, classified))
        print(f"Loaded {len(all_actions)} analyst_action events, {sum(len(v) for v in actions_by_ticker.values())} classified upgrade/downgrade")

        # 5. Fetch yfinance prices per ticker (batched), or load existing momentum
        prices_by_ticker: dict[str, pd.DataFrame | None] = {}
        existing_momentum: dict[tuple, float | None] = {}
        if not skip_yfinance:
            symbols_to_fetch = []
            for tid in tickers_list:
                sym = ticker_symbols[tid]
                events = by_ticker[tid]
                first_date = events[0].event_date - timedelta(days=40)
                last_date = events[-1].event_date
                symbols_to_fetch.append((tid, sym, first_date, last_date))

            print(f"Fetching yfinance prices for {len(symbols_to_fetch)} tickers...")
            for i in range(0, len(symbols_to_fetch), BATCH_SIZE):
                batch = symbols_to_fetch[i:i + BATCH_SIZE]
                for tid, sym, start, end in batch:
                    prices_by_ticker[tid] = _fetch_prices(sym, start, end)
                if i + BATCH_SIZE < len(symbols_to_fetch):
                    await asyncio.sleep(BATCH_SLEEP)
                done = min(i + BATCH_SIZE, len(symbols_to_fetch))
                print(f"  {done}/{len(symbols_to_fetch)} tickers fetched")

            # Abort if too many fetches failed (rate-limiting, outage)
            failed_tids = [tid for tid in tickers_list if prices_by_ticker.get(tid) is None]
            fail_rate = len(failed_tids) / len(tickers_list) * 100 if tickers_list else 0
            if failed_tids:
                print(f"\n  yfinance failures: {len(failed_tids)}/{len(tickers_list)} ({fail_rate:.1f}%)")
                for tid in failed_tids[:20]:
                    print(f"    fetch-failed: {ticker_symbols[tid]}")
                if len(failed_tids) > 20:
                    print(f"    ... and {len(failed_tids) - 20} more")

            if fail_rate > 10:
                print(f"\nABORT: {fail_rate:.1f}% of yfinance fetches failed (threshold 10%). "
                      "No data was changed. Retry later or use --skip-yfinance.")
                return

            # For failed tickers, load existing momentum so we don't overwrite
            # valid values with NULL
            if failed_tids:
                ef_result = await session.execute(
                    select(EarningsFeature.ticker_id, EarningsFeature.event_date,
                           EarningsFeature.momentum_20d)
                    .where(EarningsFeature.ticker_id.in_(failed_tids))
                )
                for tid, edate, mom in ef_result.all():
                    existing_momentum[(tid, edate)] = float(mom) if mom is not None else None
                print(f"  Preserved {sum(1 for v in existing_momentum.values() if v is not None)} "
                      f"existing momentum values for fetch-failed tickers")
        else:
            print("Skipping yfinance — loading existing momentum_20d from DB")
            ef_result = await session.execute(
                select(EarningsFeature.ticker_id, EarningsFeature.event_date, EarningsFeature.momentum_20d)
            )
            for tid, edate, mom in ef_result.all():
                existing_momentum[(tid, edate)] = float(mom) if mom is not None else None

        # 6. Build feature rows
        feature_rows = []
        null_counts: dict[str, int] = defaultdict(int)

        for tid in tickers_list:
            sym = ticker_symbols[tid]
            events = by_ticker[tid]
            prices = prices_by_ticker.get(tid)
            recs = recs_by_ticker.get(tid, [])
            iv_list = iv_by_symbol.get(sym, [])

            for idx, reaction in enumerate(events):
                # Prior events (strict: only events before this one)
                prior = events[:idx]
                n_prior = len(prior)

                # Beat rate from prior events only
                beat_rate = None
                median_1d_beat = None
                median_1d_miss = None
                weighted_1d = None

                if n_prior >= 1:
                    beats = [e for e in prior if e.outcome and e.outcome.value == "beat"]
                    misses = [e for e in prior if e.outcome and e.outcome.value == "miss"]
                    beat_rate = len(beats) / n_prior * 100  # percentage

                    beat_1ds = [float(e.pct_change_1d) for e in beats if e.pct_change_1d is not None]
                    miss_1ds = [float(e.pct_change_1d) for e in misses if e.pct_change_1d is not None]

                    if len(beat_1ds) >= 3:
                        median_1d_beat = round(statistics.median(beat_1ds), 4)
                    if len(miss_1ds) >= 3:
                        median_1d_miss = round(statistics.median(miss_1ds), 4)

                    # weighted_1d: use available medians, default missing to 0
                    med_b = median_1d_beat if median_1d_beat is not None else 0.0
                    med_m = median_1d_miss if median_1d_miss is not None else 0.0
                    br_frac = beat_rate / 100
                    weighted_1d = round(br_frac * med_b + (1 - br_frac) * med_m, 4)

                # Analyst features: latest rec before event, and rec ~60d before
                buy_share_latest_val = None
                buy_share_60d_val = None
                analyst_delta = None
                latest_total = None
                earlier_total = None

                if recs:
                    # recs are sorted by period desc
                    latest_rec = None
                    earlier_rec = None
                    for r in recs:
                        if r.period < reaction.event_date:
                            if latest_rec is None:
                                latest_rec = r
                            if (reaction.event_date - r.period).days >= 60:
                                earlier_rec = r
                                break

                    if latest_rec:
                        share, total = _buy_share(latest_rec)
                        buy_share_latest_val = round(share * 100, 4)
                        latest_total = total

                    if earlier_rec:
                        share, total = _buy_share(earlier_rec)
                        buy_share_60d_val = round(share * 100, 4)
                        earlier_total = total

                    if buy_share_latest_val is not None and buy_share_60d_val is not None:
                        if latest_total and latest_total >= ANALYST_MIN_TOTAL and earlier_total and earlier_total >= ANALYST_MIN_TOTAL:
                            analyst_delta = round(buy_share_latest_val - buy_share_60d_val, 4)

                # Prior average absolute 1d move
                prior_abs_1ds = [abs(float(e.pct_change_1d)) for e in prior if e.pct_change_1d is not None]
                prior_avg_abs_1d = round(sum(prior_abs_1ds) / len(prior_abs_1ds), 4) if prior_abs_1ds else None

                # Stage 2: prior 5d features (strict no-leakage)
                prior_5ds = [float(e.pct_change_5d) for e in prior if e.pct_change_5d is not None]
                prior_n_5d = len(prior_5ds)
                prior_avg_abs_5d = round(sum(abs(v) for v in prior_5ds) / prior_n_5d, 4) if prior_5ds else None
                prior_up_5d_rate = round(sum(1 for v in prior_5ds if v > 0) / prior_n_5d, 4) if prior_5ds else None

                # Analyst net 90d: upgrades minus downgrades in 90 days before event
                ticker_actions = actions_by_ticker.get(tid, [])
                cutoff_90 = reaction.event_date - timedelta(days=90)
                net_90 = 0
                for adate, atype in ticker_actions:
                    if cutoff_90 <= adate < reaction.event_date:
                        net_90 += 1 if atype == "upgrade" else -1
                analyst_net_90d = net_90 if ticker_actions else None

                # Momentum (from yfinance prices, or preserve existing on fetch failure)
                if not skip_yfinance and prices is not None:
                    mom_20d = _momentum_20d(prices, reaction.event_date)
                else:
                    mom_20d = existing_momentum.get((tid, reaction.event_date))

                # ATM IV: closest date before event within 30d
                atm_iv_val = None
                if iv_list:
                    best_iv = None
                    best_gap = 999
                    for iv in iv_list:
                        if iv.date < reaction.event_date:
                            gap = (reaction.event_date - iv.date).days
                            if gap <= 30 and gap < best_gap and iv.atm_iv is not None:
                                best_gap = gap
                                best_iv = iv
                    if best_iv:
                        atm_iv_val = float(best_iv.atm_iv)

                # V1 lean replay
                lean_e = _lean_earnings(weighted_1d, n_prior, beat_rate)
                # For analyst lean, convert buy_share percentages back to fractions for threshold comparison
                lean_a = _lean_analyst(
                    analyst_delta / 100 if analyst_delta is not None else None,
                    latest_total,
                    earlier_total,
                )
                lean_m = _lean_momentum(mom_20d)
                dec = _decision(lean_e, lean_a, lean_m)

                # Targets
                actual_1d = float(reaction.pct_change_1d) if reaction.pct_change_1d is not None else None
                actual_3d = float(reaction.pct_change_3d) if reaction.pct_change_3d is not None else None
                actual_5d = float(reaction.pct_change_5d) if reaction.pct_change_5d is not None else None
                outcome_val = reaction.outcome.value.upper() if reaction.outcome else "UNKNOWN"

                row = {
                    "ticker_id": tid,
                    "event_date": reaction.event_date,
                    "symbol": sym,
                    "beat_rate": beat_rate,
                    "median_1d_beat": median_1d_beat,
                    "median_1d_miss": median_1d_miss,
                    "weighted_1d": weighted_1d,
                    "n_prior_events": n_prior,
                    "buy_share_latest": buy_share_latest_val,
                    "buy_share_60d_ago": buy_share_60d_val,
                    "analyst_delta": analyst_delta,
                    "momentum_20d": mom_20d,
                    "prior_avg_abs_1d": prior_avg_abs_1d,
                    "analyst_net_90d": analyst_net_90d,
                    "atm_iv": atm_iv_val,
                    "prior_avg_abs_5d": prior_avg_abs_5d,
                    "prior_n": prior_n_5d,
                    "prior_up_5d_rate": prior_up_5d_rate,
                    "lean_earnings": lean_e,
                    "lean_analyst": lean_a,
                    "lean_momentum": lean_m,
                    "decision": dec,
                    "actual_1d": actual_1d,
                    "actual_3d": actual_3d,
                    "actual_5d": actual_5d,
                    "outcome": outcome_val,
                }
                # Sanitize NaN → None for all numeric values
                for key in row:
                    row[key] = _clean(row[key])

                feature_rows.append(row)

                # Track nulls
                for col in ["beat_rate", "median_1d_beat", "median_1d_miss", "weighted_1d",
                            "buy_share_latest", "buy_share_60d_ago", "analyst_delta",
                            "momentum_20d", "prior_avg_abs_1d", "analyst_net_90d",
                            "atm_iv", "prior_avg_abs_5d", "prior_n", "prior_up_5d_rate",
                            "actual_1d"]:
                    if row[col] is None:
                        null_counts[col] += 1

        # 7. Bulk upsert
        print(f"\nUpserting {len(feature_rows)} feature rows...")
        for i in range(0, len(feature_rows), 500):
            batch = feature_rows[i:i + 500]
            stmt = pg_insert(EarningsFeature).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["ticker_id", "event_date"],
                set_={
                    col: stmt.excluded[col]
                    for col in batch[0].keys()
                    if col not in ("ticker_id", "event_date")
                },
            )
            await session.execute(stmt)
        await session.commit()

        elapsed = time.time() - t0
        print(f"\nDone in {elapsed:.1f}s")
        print(f"Total rows: {len(feature_rows)}")
        print(f"Tickers: {len(tickers_list)}")

        # Null rates
        print("\nNull rates:")
        for col, cnt in sorted(null_counts.items()):
            pct = cnt / len(feature_rows) * 100 if feature_rows else 0
            print(f"  {col:25s} {cnt:5d} / {len(feature_rows)} ({pct:.1f}%)")

        # Sample rows
        print("\nSample rows (first 5):")
        for row in feature_rows[:5]:
            print(f"  {row['symbol']:6s} {row['event_date']}  w1d={row['weighted_1d']}  "
                  f"lean={row['lean_earnings']}/{row['lean_analyst']}/{row['lean_momentum']}  "
                  f"dec={row['decision']}  actual_1d={row['actual_1d']}  outcome={row['outcome']}")


def cli():
    parser = argparse.ArgumentParser(description="Build earnings_features table")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of tickers")
    parser.add_argument("--skip-yfinance", action="store_true", help="Skip yfinance price fetches")
    args = parser.parse_args()
    asyncio.run(main(limit=args.limit, skip_yfinance=args.skip_yfinance))


if __name__ == "__main__":
    cli()
