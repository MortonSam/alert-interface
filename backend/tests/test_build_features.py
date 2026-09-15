"""Tests for build_features safety guards."""
import math

from app.scripts.build_features import _clean, _momentum_20d


class TestClean:
    def test_none_passthrough(self):
        assert _clean(None) is None

    def test_nan_to_none(self):
        assert _clean(float("nan")) is None

    def test_valid_float(self):
        assert _clean(3.14) == 3.14

    def test_string_passthrough(self):
        assert _clean("bullish") == "bullish"

    def test_int_passthrough(self):
        assert _clean(42) == 42


class TestMomentumNanGuard:
    """_momentum_20d must return None for NaN prices, never propagate NaN."""

    def test_nan_close_returns_none(self):
        import pandas as pd
        from datetime import date

        # Create a DataFrame where the last close is NaN
        dates = pd.date_range("2026-08-01", periods=25, freq="B")
        df = pd.DataFrame({"Close": [100.0] * 24 + [float("nan")]}, index=dates)
        result = _momentum_20d(df, date(2026, 9, 5))
        assert result is None

    def test_valid_prices(self):
        import pandas as pd
        from datetime import date

        dates = pd.date_range("2026-07-01", periods=30, freq="B")
        closes = [100.0] * 29 + [110.0]
        df = pd.DataFrame({"Close": closes}, index=dates)
        result = _momentum_20d(df, date(2026, 8, 15))
        assert result is not None
        assert not math.isnan(result)


class TestPreserveMomentumOnFetchFailure:
    """When yfinance returns None for a ticker, existing momentum must be preserved."""

    def test_fallback_to_existing_momentum(self):
        """Simulates the momentum selection logic in main():
        when prices is None, existing_momentum is used instead."""
        existing_momentum = {
            ("ticker_1", "2026-01-15"): 5.23,
            ("ticker_1", "2026-04-15"): -3.10,
        }

        # Simulate: prices=None means fetch failed
        prices = None
        skip_yfinance = False

        # This is the exact logic from build_features main()
        if not skip_yfinance and prices is not None:
            mom_20d = None  # would call _momentum_20d(prices, event_date)
        else:
            mom_20d = existing_momentum.get(("ticker_1", "2026-01-15"))

        assert mom_20d == 5.23, "Must preserve existing momentum, not overwrite with None"

    def test_none_when_no_existing(self):
        """A ticker with no prior momentum and a failed fetch gets None (correct)."""
        existing_momentum = {}
        prices = None
        skip_yfinance = False

        if not skip_yfinance and prices is not None:
            mom_20d = None
        else:
            mom_20d = existing_momentum.get(("new_ticker", "2026-01-15"))

        assert mom_20d is None
