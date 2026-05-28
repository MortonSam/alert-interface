"""yfinance wrapper — ticker info, earnings calendar, price history."""

from __future__ import annotations

from typing import Any

import yfinance as yf


class YFinanceClient:
    @staticmethod
    def get_info(symbol: str) -> dict[str, Any]:
        return yf.Ticker(symbol).info or {}

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

    @staticmethod
    def get_daily_closes(symbol: str, period: str = "1mo") -> list[dict[str, Any]]:
        """Daily close prices for charting / sparklines.

        Args:
            period: yfinance period string — "1mo", "3mo", "1y", etc.

        Returns list of {"date": "YYYY-MM-DD", "close": float}, oldest first.
        Returns [] if no data is available.
        """
        hist = yf.Ticker(symbol).history(period=period, auto_adjust=True)
        if hist is None or hist.empty:
            return []
        return [
            {
                "date":  idx.strftime("%Y-%m-%d"),
                "close": float(close),
            }
            for idx, close in zip(hist.index, hist["Close"])
        ]
