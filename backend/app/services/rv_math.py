"""Pure realized-volatility math — no I/O, no side effects.

compute_rv_metrics(closes)  →  {rv_20d, rv_rank, rv_percentile, rv_min, rv_max, sample_days, status}

Used by:
- yfinance_client.get_realized_vol_data()  (single-ticker live path)
- compute_rv_ranks.py                      (batch precompute job)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Any single-day |log return| above this threshold indicates a failed split
# adjustment or corrupt bar.  ln(1.50) ≈ 0.405 → a 50% price move.
_RETURN_THRESHOLD = 0.405

_EMPTY: dict = {
    "rv_20d": None,
    "rv_rank": None,
    "rv_percentile": None,
    "rv_min": None,
    "rv_max": None,
    "sample_days": 0,
    "status": "no_data",
}


def compute_rv_metrics(closes: pd.Series, rv_window: int = 20) -> dict:
    """Compute 20-day annualised realised vol with trailing rank and percentile.

    Parameters
    ----------
    closes : pd.Series
        Daily close prices, datetime-indexed, oldest-first.
    rv_window : int
        Rolling window in trading days (default 20).

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
    # exceeds the threshold — the data contains a bad split adjustment or
    # corrupt bar, and any number we produce would be wrong.
    trailing_returns = log_returns.iloc[-(252 + rv_window):]  # generous lookback
    if (trailing_returns.abs() > _RETURN_THRESHOLD).any():
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
