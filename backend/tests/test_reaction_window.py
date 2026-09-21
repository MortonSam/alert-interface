"""Unit tests for timing-aware reaction window computation (v3).

These test _compute_v3 with synthetic price series -- no DB required.
"""

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from app.scripts.seed_historical_reactions import _compute_v3


def _make_hist(prices: list[tuple[date, float, float, float, int]]) -> tuple[pd.DataFrame, np.ndarray]:
    """Build a DataFrame and date cache from (date, open, close, volume) tuples.

    Simplified: High=max(open,close), Low=min(open,close).
    """
    data = {
        "Open": [p[1] for p in prices],
        "High": [max(p[1], p[2]) for p in prices],
        "Low": [min(p[1], p[2]) for p in prices],
        "Close": [p[2] for p in prices],
        "Volume": [p[3] for p in prices],
    }
    index = pd.DatetimeIndex([pd.Timestamp(p[0]) for p in prices])
    df = pd.DataFrame(data, index=index)
    dates = df.index.map(lambda ts: ts.date()).values
    return df, dates


def _td(days: int) -> date:
    """Trading day offset from a base Thursday 2026-01-15."""
    # Simple: map offset to weekday-only dates
    # 0=Thu 1/15, 1=Fri 1/16, 2=Mon 1/19 (skip weekend), etc.
    base = date(2026, 1, 14)  # Wednesday before event
    d = base
    remaining = days
    while remaining > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            remaining -= 1
    return d


class TestBMOWindow:
    """Pre-market reporter: base = close(T-1), 1d = close(T)."""

    def test_bmo_captures_gap(self):
        event_date = date(2026, 1, 15)  # Thursday
        prices = [
            # (date, open, close, volume)
            (date(2026, 1, 14), 99.0, 100.0, 1_000_000),  # T-1 Wed
            (date(2026, 1, 15), 110.0, 112.0, 5_000_000),  # T Thu (gap up on bmo)
            (date(2026, 1, 16), 111.0, 111.0, 2_000_000),  # T+1 Fri
            (date(2026, 1, 19), 112.0, 113.0, 2_000_000),  # T+2 Mon
            (date(2026, 1, 20), 113.0, 114.0, 2_000_000),  # T+3 Tue
            (date(2026, 1, 21), 114.0, 115.0, 2_000_000),  # T+4 Wed
            (date(2026, 1, 22), 115.0, 116.0, 2_000_000),  # T+5 Thu
        ]
        hist, dates = _make_hist(prices)
        result = _compute_v3(hist, dates, event_date, "bmo", dates)

        assert result is not None
        # base = close(T-1) = 100
        # 1d = close(T) = 112 -> pct = (112-100)/100 * 100 = 12.0%
        assert float(result["pct_change_1d"]) == pytest.approx(12.0, abs=0.01)
        # 3d = close(T+2) = 113 -> pct = (113-100)/100 * 100 = 13.0%
        assert float(result["pct_change_3d"]) == pytest.approx(13.0, abs=0.01)
        # 5d = close(T+4) = 115 -> pct = (115-100)/100 * 100 = 15.0%
        assert float(result["pct_change_5d"]) == pytest.approx(15.0, abs=0.01)

    def test_bmo_stores_price_metadata(self):
        event_date = date(2026, 1, 15)
        prices = [
            (date(2026, 1, 14), 99.0, 100.0, 1_000_000),
            (date(2026, 1, 15), 110.0, 112.0, 5_000_000),
            (date(2026, 1, 16), 111.0, 111.0, 2_000_000),
            (date(2026, 1, 19), 112.0, 113.0, 2_000_000),
            (date(2026, 1, 20), 113.0, 114.0, 2_000_000),
            (date(2026, 1, 21), 114.0, 115.0, 2_000_000),
        ]
        hist, dates = _make_hist(prices)
        result = _compute_v3(hist, dates, event_date, "bmo", dates)

        assert result is not None
        assert float(result["close_before"]) == pytest.approx(100.0, abs=0.01)
        assert float(result["open_after"]) == pytest.approx(110.0, abs=0.01)
        assert float(result["close_after"]) == pytest.approx(112.0, abs=0.01)
        assert result["volume_after"] == 5_000_000


class TestAMCWindow:
    """After-close reporter: base = close(T), 1d = close(T+1)."""

    def test_amc_captures_gap(self):
        event_date = date(2026, 1, 15)  # Thursday
        prices = [
            (date(2026, 1, 14), 99.0, 99.0, 1_000_000),    # T-1 Wed
            (date(2026, 1, 15), 99.5, 100.0, 2_000_000),    # T Thu (report after close)
            (date(2026, 1, 16), 110.0, 112.0, 5_000_000),   # T+1 Fri (gap up)
            (date(2026, 1, 19), 112.0, 111.0, 2_000_000),   # T+2 Mon
            (date(2026, 1, 20), 111.0, 113.0, 2_000_000),   # T+3 Tue
            (date(2026, 1, 21), 113.0, 114.0, 2_000_000),   # T+4 Wed
            (date(2026, 1, 22), 114.0, 115.0, 2_000_000),   # T+5 Thu
        ]
        hist, dates = _make_hist(prices)
        result = _compute_v3(hist, dates, event_date, "amc", dates)

        assert result is not None
        # base = close(T) = 100
        # 1d = close(T+1) = 112 -> pct = (112-100)/100 * 100 = 12.0%
        assert float(result["pct_change_1d"]) == pytest.approx(12.0, abs=0.01)
        # 3d = close(T+3) = 113 -> pct = 13.0%
        assert float(result["pct_change_3d"]) == pytest.approx(13.0, abs=0.01)
        # 5d = close(T+5) = 115 -> pct = 15.0%
        assert float(result["pct_change_5d"]) == pytest.approx(15.0, abs=0.01)


class TestUnknownWindow:
    """Unknown timing: all pct fields NULL, metadata stored."""

    def test_unknown_nulls_pct(self):
        event_date = date(2026, 1, 15)
        prices = [
            (date(2026, 1, 14), 99.0, 100.0, 1_000_000),
            (date(2026, 1, 15), 110.0, 112.0, 5_000_000),
            (date(2026, 1, 16), 111.0, 111.0, 2_000_000),
            (date(2026, 1, 19), 112.0, 113.0, 2_000_000),
            (date(2026, 1, 20), 113.0, 114.0, 2_000_000),
            (date(2026, 1, 21), 114.0, 115.0, 2_000_000),
        ]
        hist, dates = _make_hist(prices)
        result = _compute_v3(hist, dates, event_date, "unknown", dates)

        assert result is not None
        assert result["pct_change_1d"] is None
        assert result["pct_change_3d"] is None
        assert result["pct_change_5d"] is None
        # Price metadata still stored
        assert result["close_before"] is not None
        assert result["open_after"] is not None
        assert result["close_after"] is not None
        assert result["volume_after"] == 5_000_000
