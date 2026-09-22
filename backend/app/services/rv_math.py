"""Pure realized-volatility math — no I/O, no side effects.

compute_rv_metrics(closes, volumes=, action_dates=)
    →  {rv_20d, rv_rank, rv_percentile, rv_min, rv_max, sample_days, status}

Used by:
- yfinance_client.get_realized_vol_data()  (single-ticker live path)
- compute_rv_ranks.py                      (batch precompute job)
"""
from __future__ import annotations

from collections.abc import Collection
from datetime import date

import numpy as np
import pandas as pd

# A single-day |log return| above this threshold is either a failed split
# adjustment / corrupt bar, or a real crash or squeeze.  ln(1.50) ≈ 0.405 → a
# 50% price move.  The two are told apart by volume and corporate actions:
# a real move trades at many multiples of normal volume, and a split or
# ex-dividend date explains a price gap; a bad adjustment shows neither.
_RETURN_THRESHOLD = 0.405
VOLUME_SPIKE_MULTIPLE = 5.0     # session volume >= 5x trailing median → real move
VOLUME_MEDIAN_SESSIONS = 60     # trailing sessions the median is taken over

_EMPTY: dict = {
    "rv_20d": None,
    "rv_rank": None,
    "rv_percentile": None,
    "rv_min": None,
    "rv_max": None,
    "sample_days": 0,
    "status": "no_data",
}


def extreme_return_is_real(
    day: date,
    volumes: pd.Series | None,
    action_dates: Collection[date] | None,
) -> bool:
    """A return above the threshold is a real move when a split or dividend is
    recorded for that date, or the session's volume is >= VOLUME_SPIKE_MULTIPLE
    times the median of the trailing VOLUME_MEDIAN_SESSIONS sessions.

    Without volumes and without a recorded action nothing can clear it, so the
    conservative answer is False (data_error).
    """
    if action_dates and day in action_dates:
        return True
    if volumes is None or volumes.empty:
        return False
    days = np.array([d.date() if hasattr(d, "date") else d for d in volumes.index])
    pos = np.flatnonzero(days == day)
    if len(pos) == 0:
        return False
    i = int(pos[0])
    trailing = volumes.iloc[max(0, i - VOLUME_MEDIAN_SESSIONS):i].dropna()
    trailing = trailing[trailing > 0]
    if trailing.empty:
        return False
    vol = volumes.iloc[i]
    return bool(pd.notna(vol) and vol >= VOLUME_SPIKE_MULTIPLE * float(trailing.median()))


def compute_rv_metrics(
    closes: pd.Series,
    rv_window: int = 20,
    volumes: pd.Series | None = None,
    action_dates: Collection[date] | None = None,
) -> dict:
    """Compute 20-day annualised realised vol with trailing rank and percentile.

    Parameters
    ----------
    closes : pd.Series
        Daily close prices, datetime-indexed, oldest-first.
    rv_window : int
        Rolling window in trading days (default 20).
    volumes : pd.Series | None
        Daily volumes on the same index; lets a real crash or squeeze clear the
        extreme-return guard.  Without it every extreme return is data_error.
    action_dates : Collection[date] | None
        Dates with a recorded split or ex-dividend for this ticker.

    Returns
    -------
    dict with keys:
        rv_20d       – float | None, most-recent annualised RV (decimal, e.g. 0.25)
        rv_rank      – float | None, 0-100 linear rank within trailing 252 range
        rv_percentile – float | None, 0-100 pct of trailing 252 days below current
        rv_min       – float | None, trailing 252-day min RV
        rv_max       – float | None, trailing 252-day max RV
        sample_days  – int, number of trailing RV observations (max 252)
        status       – str, one of "ok", "insufficient", "degenerate", "no_data",
                       "data_error"
    """
    if closes is None or len(closes) < rv_window + 2:
        return dict(_EMPTY)

    log_returns = np.log(closes / closes.shift(1)).dropna()

    # Guard: reject the entire series if any return in the trailing window
    # exceeds the threshold and is not explained by a volume spike or a
    # recorded corporate action — the data contains a bad split adjustment or
    # corrupt bar, and any number we produce would be wrong.
    trailing_returns = log_returns.iloc[-(252 + rv_window):]  # generous lookback
    extreme = trailing_returns[trailing_returns.abs() > _RETURN_THRESHOLD]
    unexplained = [
        d for d in extreme.index
        if not extreme_return_is_real(d.date() if hasattr(d, "date") else d, volumes, action_dates)
    ]
    if unexplained:
        return {
            "rv_20d": None,
            "rv_rank": None,
            "rv_percentile": None,
            "rv_min": None,
            "rv_max": None,
            "sample_days": 0,
            "status": "data_error",
        }

    rolling_rv = (log_returns.rolling(window=rv_window).std() * np.sqrt(252)).dropna()

    if rolling_rv.empty:
        return dict(_EMPTY)

    trailing = rolling_rv.iloc[-252:]
    current_rv = float(rolling_rv.iloc[-1])
    sample_days = len(trailing)

    # Guardrail: not enough history for a meaningful rank
    if sample_days < 120:
        return {
            "rv_20d": current_rv,
            "rv_rank": None,
            "rv_percentile": None,
            "rv_min": None,
            "rv_max": None,
            "sample_days": sample_days,
            "status": "insufficient",
        }

    rv_min = float(trailing.min())
    rv_max = float(trailing.max())

    # Guardrail: degenerate range (constant RV)
    if rv_max - rv_min < 1e-12:
        return {
            "rv_20d": current_rv,
            "rv_rank": None,
            "rv_percentile": None,
            "rv_min": rv_min,
            "rv_max": rv_max,
            "sample_days": sample_days,
            "status": "degenerate",
        }

    rv_rank = (current_rv - rv_min) / (rv_max - rv_min) * 100
    rv_rank = max(0.0, min(100.0, rv_rank))
    rv_percentile = sum(1 for v in trailing if v < current_rv) / sample_days * 100

    return {
        "rv_20d": current_rv,
        "rv_rank": round(rv_rank, 1),
        "rv_percentile": round(rv_percentile, 1),
        "rv_min": rv_min,
        "rv_max": rv_max,
        "sample_days": sample_days,
        "status": "ok",
    }
