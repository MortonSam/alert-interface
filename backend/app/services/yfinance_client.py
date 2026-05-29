"""yfinance wrapper — ticker info, earnings calendar, price history."""

from __future__ import annotations

from typing import Any

import pandas as pd
import yfinance as yf


def _parse_option_df(df) -> list[dict]:
    rows = []
    for _, row in df.iterrows():
        iv_raw = row["impliedVolatility"]
        iv = None if pd.isna(iv_raw) else (float(iv_raw) if 0 < float(iv_raw) <= 3.0 else None)
        vol_raw = row["volume"]
        vol = None if pd.isna(vol_raw) else int(vol_raw)
        oi_raw = row["openInterest"]
        oi = None if pd.isna(oi_raw) else int(oi_raw)
        def _f(v): return None if pd.isna(v) else float(v)
        rows.append({
            "strike": float(row["strike"]),
            "bid": _f(row["bid"]), "ask": _f(row["ask"]),
            "lastPrice": _f(row["lastPrice"]),
            "volume": vol, "openInterest": oi, "impliedVolatility": iv,
        })
    return rows


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
    def get_option_expirations(symbol: str) -> list[str]:
        try:
            return list(yf.Ticker(symbol).options)
        except Exception:
            return []

    @staticmethod
    def get_option_chain(symbol: str, expiration: str) -> dict:
        try:
            chain = yf.Ticker(symbol).option_chain(expiration)
            return {"calls": _parse_option_df(chain.calls), "puts": _parse_option_df(chain.puts), "expiration": expiration}
        except Exception:
            return {"calls": [], "puts": [], "expiration": expiration}

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

    @staticmethod
    def get_chart_history(symbol: str, period: str) -> dict[str, Any]:
        """Price history for the interactive chart, supporting intraday and daily ranges.

        period='1d'  → intraday 1-minute bars; start_price = previous session close.
        period='5d'  → past 5 trading days at daily interval.
        All others   → daily bars; start_price = first close in the series.

        Returns {"history": [{"date": str, "close": float}, ...], "start_price": float | None}.
        Intraday dates are UTC ISO-8601 strings ("YYYY-MM-DDTHH:MM:SSZ").
        Daily dates are "YYYY-MM-DD".
        """
        ticker = yf.Ticker(symbol)

        if period == "1d":
            intraday = ticker.history(period="1d", interval="1m", auto_adjust=True)
            # Previous session close — fetch a short daily window
            daily5 = ticker.history(period="5d", interval="1d", auto_adjust=True)

            prev_close: float | None = None
            if daily5 is not None and not daily5.empty:
                closes = daily5["Close"].dropna()
                if len(closes) >= 2:
                    prev_close = float(closes.iloc[-2])
                elif len(closes) == 1:
                    prev_close = float(closes.iloc[0])

            if intraday is None or intraday.empty:
                return {"history": [], "start_price": prev_close}

            history: list[dict[str, Any]] = []
            for idx, close_val in zip(intraday.index, intraday["Close"]):
                if pd.isna(close_val):
                    continue
                utc = idx.tz_convert("UTC") if idx.tzinfo else idx
                history.append({
                    "date": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "close": float(close_val),
                })
            return {"history": history, "start_price": prev_close}

        else:
            # Explicit interval="1d" prevents yfinance defaulting to intraday for short periods
            hist = ticker.history(period=period, interval="1d", auto_adjust=True)
            if hist is None or hist.empty:
                return {"history": [], "start_price": None}

            closes = hist["Close"].dropna()
            start_price: float | None = float(closes.iloc[0]) if not closes.empty else None

            history = [
                {"date": idx.strftime("%Y-%m-%d"), "close": float(close)}
                for idx, close in zip(hist.index, hist["Close"])
                if not pd.isna(close)
            ]
            return {"history": history, "start_price": start_price}
