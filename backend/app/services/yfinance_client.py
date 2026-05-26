"""yfinance wrapper — ticker info, earnings calendar, price history."""

from __future__ import annotations

from typing import Any

import yfinance as yf


class YFinanceClient:
    @staticmethod
    def get_info(symbol: str) -> dict[str, Any]:
        return yf.Ticker(symbol).info

    @staticmethod
    def get_earnings_calendar(symbol: str) -> dict[str, Any]:
        """Returns the next earnings date and any available estimates."""
        return yf.Ticker(symbol).calendar or {}

    @staticmethod
    def get_price_history(symbol: str, period: str = "1y") -> Any:
        """Returns a pandas DataFrame of OHLCV data."""
        return yf.Ticker(symbol).history(period=period)

    @staticmethod
    def get_ex_dividend_date(symbol: str) -> str | None:
        info = yf.Ticker(symbol).info
        return info.get("exDividendDate")
