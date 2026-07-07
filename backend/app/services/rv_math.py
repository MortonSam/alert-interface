"""Pure realized-volatility math — no I/O, no side effects.

compute_rv_metrics(closes)  →  {rv_20d, rv_rank, rv_percentile, sample_days, status}

Used by:
- yfinance_client.get_realized_vol_data()  (single-ticker live path)
- compute_rv_ranks.py                      (batch precompute job)
"""
from __future__ import annotations

import numpy as np
import pandas as pd


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
        sample_days  – int, number of trailing RV observations (max 252)
        status       – str, one of "ok", "insufficient", "degenerate", "no_data"
    """
    if closes is None or len(closes) < rv_window + 2:
        return {
            "rv_20d": None,
            "rv_rank": None,
            "rv_percentile": None,
            "sample_days": 0,
            "status": "no_data",
        }

    log_returns = np.log(closes / closes.shift(1)).dropna()
    rolling_rv = (log_returns.rolling(window=rv_window).std() * np.sqrt(252)).dropna()

    if rolling_rv.empty:
        return {
            "rv_20d": None,
            "rv_rank": None,
            "rv_percentile": None,
            "sample_days": 0,
            "status": "no_data",
        }

    trailing = rolling_rv.iloc[-252:]
    current_rv = float(rolling_rv.iloc[-1])
    sample_days = len(trailing)

    # Guardrail: not enough history for a meaningful rank
    if sample_days < 120:
        return {
            "rv_20d": current_rv,
            "rv_rank": None,
            "rv_percentile": None,
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
        "sample_days": sample_days,
        "status": "ok",
    }
