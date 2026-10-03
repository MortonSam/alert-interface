"""Plan what the nightly shadow-bar fetch asks Intrinio for, and rebuild adjusted series from stored bars.

Intrinio's adjusted price on a day is the raw price times the product of every later day's `factor` (0.1 on a
10:1 split day, 1 - dividend/prior close on an ex-dividend day; checked against NVDA 2024-06-10 and AAPL
2026-08-10). Stored adj_* columns are therefore only right as of the night they were fetched; adjusted_frame()
derives the series from raw bars and factors so an incremental append after a split still adjusts the past.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd

from app.services.security_records import INTRINIO, Record, STORED_START

OVERLAP_DAYS = 5          # refetch this many calendar days before the last stored bar so a late correction lands
BENCHMARKS = ("SPY",)     # fetched too: the seeder takes the session calendar from SPY


@dataclass(frozen=True)
class Fetch:
    symbol: str
    record: Record
    start: date
    end: date


def plan_fetches(records_by_symbol: dict[str, list[Record]], last_stored: dict[str, date | None], today: date,
                 start: date = STORED_START) -> list[Fetch]:
    """One fetch per Intrinio record whose span still has days to fetch: from max(start, record start, the last
    stored bar less the overlap) to min(record end, today). stored_history rows fetch nothing. A closed record
    (a predecessor, a delisted ticker's last record) whose bars reach its end fetches nothing."""
    out: list[Fetch] = []
    for sym, records in sorted(records_by_symbol.items()):
        last = last_stored.get(sym)
        floor = start if last is None else max(start, last - timedelta(days=OVERLAP_DAYS))
        for r in sorted(records, key=lambda r: r.valid_from):
            if r.source != INTRINIO or not r.intrinio_security_id:
                continue
            a = max(floor, r.valid_from)
            b = min(r.valid_to or today, today)
            if last is not None and r.valid_to is not None and r.valid_to <= last:
                continue            # a closed record (predecessor, delisted) whose bars are complete
            if a <= b:
                out.append(Fetch(sym, r, a, b))
    return out


def adjusted_frame(rows: list[dict]) -> pd.DataFrame:
    """A yfinance-shaped frame (Open, High, Low, Close, Volume; dated index) from stored bars, adjusted by the
    factors of every later day. `rows` hold date, open, high, low, close, volume, factor, split_ratio."""
    if not rows:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    df = pd.DataFrame([{"date": pd.Timestamp(r["date"]), "open": r["open"], "high": r["high"], "low": r["low"], "close": r["close"],
                        "volume": r["volume"], "factor": r.get("factor") or 1.0, "split_ratio": r.get("split_ratio") or 1.0} for r in rows])
    df = df.sort_values("date").set_index("date")
    # cumulative product of the factors strictly after each day: reverse cumprod shifted by one
    later = df["factor"][::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    later_split = df["split_ratio"][::-1].cumprod()[::-1].shift(-1).fillna(1.0)
    out = pd.DataFrame(index=df.index)
    for col, src in (("Open", "open"), ("High", "high"), ("Low", "low"), ("Close", "close")):
        out[col] = df[src] * later
    out["Volume"] = (df["volume"].fillna(0) / later_split).round().astype("int64")   # shares, so split-adjusted only
    return out.dropna(subset=["Open", "Close"])
