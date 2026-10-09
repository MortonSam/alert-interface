"""Read-only: active tickers whose price behaves like a pending cash deal, for a person to check for an acquisition.

A ticker is listed when its 20-day realized volatility has collapsed (at most RV_CEILING annualized and at most
RV_COLLAPSE_RATIO of its own median 20-day volatility over the prior year) and its last PIN_SESSIONS closes sit inside a
PIN_RANGE_PCT band. It is marked "under a round number" when the newest close is at most ROUND_GAP_PCT below the next
round level (round_step: $1 under $50, $5 under $250, $10 above). Writes nothing; prices are the stored Intrinio bars.

Usage: python -m app.scripts.list_pinned_tickers [--symbols=AES,HOLX]
"""
from __future__ import annotations

import math
import sys
from datetime import date, timedelta

import numpy as np
from sqlalchemy import create_engine, text

from app.config import settings
from app.services import price_bars

RV_WINDOW = 20
RV_CEILING = 0.10            # annualized
RV_COLLAPSE_RATIO = 0.40     # of the ticker's own median 20-day RV over the prior year
PIN_SESSIONS = 10
PIN_RANGE_PCT = 1.5          # (highest close - lowest close) / newest close over PIN_SESSIONS
ROUND_GAP_PCT = 2.0          # newest close at most this far below the next round level


def round_step(price: float) -> float:
    return 1.0 if price < 50 else 5.0 if price < 250 else 10.0


def round_gap(price: float) -> tuple[float, float]:
    """Pure: (the next round level at or above `price`, the gap below it as a percent of the level)."""
    step = round_step(price)
    level = math.ceil(round(price / step, 9)) * step
    return level, (level - price) / level * 100


def rolling_rv(closes: np.ndarray, window: int = RV_WINDOW) -> np.ndarray:
    """Pure: annualized realized volatility of daily log returns over each trailing `window`."""
    r = np.diff(np.log(closes))
    if len(r) < window:
        return np.array([])
    return np.array([r[i - window:i].std(ddof=1) * math.sqrt(252) for i in range(window, len(r) + 1)])


def assess(closes: np.ndarray) -> dict | None:
    """Pure: the detector's figures for one ticker's closes (oldest first), or None with too little history."""
    rvs = rolling_rv(closes)
    if len(rvs) < 60 or len(closes) < PIN_SESSIONS:
        return None
    rv20, median = float(rvs[-1]), float(np.median(rvs[:-RV_WINDOW] if len(rvs) > RV_WINDOW + 40 else rvs))
    last = closes[-PIN_SESSIONS:]
    pin = float((last.max() - last.min()) / closes[-1] * 100)
    level, gap = round_gap(float(closes[-1]))
    return {"close": float(closes[-1]), "rv20": rv20, "rv_median_1y": median, "ratio": rv20 / median if median else None,
            "pin_range_pct": pin, "round_level": level, "round_gap_pct": gap,
            "collapsed": rv20 <= RV_CEILING and median > 0 and rv20 / median <= RV_COLLAPSE_RATIO,
            "pinned": pin <= PIN_RANGE_PCT, "under_round": 0 <= gap <= ROUND_GAP_PCT}


def main(argv: list[str]) -> int:
    only = next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), None)
    with create_engine(settings.database_url_sync).connect() as c:
        syms = [r[0] for r in c.execute(text("SELECT symbol FROM tickers WHERE is_active ORDER BY symbol"))]
    if only:
        syms = [s for s in syms if s in {x.strip().upper() for x in only.split(",")}]
    bars = price_bars.bulk_closes_sync(syms, date.today() - timedelta(days=400))
    rows = []
    for sym in syms:
        df = bars.get(sym)
        if df is None:
            continue
        a = assess(df["Close"].astype(float).to_numpy())
        if a:
            rows.append((sym, df.index[-1].date(), a))
    hits = [r for r in rows if r[2]["collapsed"] and r[2]["pinned"]]
    print(f"{len(rows)} active tickers assessed; {len(hits)} with collapsed volatility and a pinned price "
          f"(20-day RV at most {RV_CEILING:.0%} and {RV_COLLAPSE_RATIO:.0%} of its prior-year median; last {PIN_SESSIONS} closes within {PIN_RANGE_PCT}%)")
    for sym, d, a in sorted(hits, key=lambda r: r[2]["rv20"]):
        where = f"{a['round_gap_pct']:.2f}% under ${a['round_level']:,.2f}" if a["under_round"] else "not near a round level"
        print(f"  {sym:6s} close ${a['close']:,.2f} on {d}  RV20 {a['rv20']:.1%} (prior-year median {a['rv_median_1y']:.1%})  "
              f"10-day range {a['pin_range_pct']:.2f}%  {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
