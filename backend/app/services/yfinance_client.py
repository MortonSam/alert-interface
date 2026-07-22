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
        period='7d'  → intraday 30-minute bars over 7 days; start_price = first bar's close.
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

        elif period == "7d":
            intraday = ticker.history(period="7d", interval="30m", auto_adjust=True)
            if intraday is None or intraday.empty:
                return {"history": [], "start_price": None}

            history = []
            for idx, close_val in zip(intraday.index, intraday["Close"]):
                if pd.isna(close_val):
                    continue
                utc = idx.tz_convert("UTC") if idx.tzinfo else idx
                history.append({
                    "date": utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "close": float(close_val),
                })
            start_price = history[0]["close"] if history else None
            return {"history": history, "start_price": start_price}

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

    @staticmethod
    def get_realized_vol_data(symbol: str, rv_window: int = 20) -> dict[str, Any]:
        """Compute 20-day annualized realized (historical) volatility and its
        trailing 1-year rank / percentile.

        Returns:
            {
                "current_rv":    float | None,
                "rv_series":     list[float],     # kept for backward compat
                "sample_days":   int,
                "rv_rank":       float | None,    # 0-100
                "rv_percentile": float | None,    # 0-100
                "status":        str,
            }
        """
        import numpy as np

        from app.services.rv_math import compute_rv_metrics

        hist = yf.Ticker(symbol).history(period="3y", interval="1d", auto_adjust=True)
        if hist is None or hist.empty:
            return {"current_rv": None, "rv_series": [], "sample_days": 0,
                    "rv_rank": None, "rv_percentile": None, "status": "no_data"}

        closes = hist["Close"].dropna()
        metrics = compute_rv_metrics(closes, rv_window=rv_window)

        # Build backward-compatible rv_series for callers that still need it
        # (batch-enrich, options-read, snapshot_iv).
        rv_series: list[float] = []
        if len(closes) >= rv_window + 2:
            log_returns = np.log(closes / closes.shift(1)).dropna()
            rolling_rv = (log_returns.rolling(window=rv_window).std() * np.sqrt(252)).dropna()
            if not rolling_rv.empty:
                rv_series = [float(v) for v in rolling_rv.iloc[-252:]]

        # 20-day price return for momentum signal
        pct_change_20d = None
        if len(closes) >= 21:
            pct_change_20d = round(((closes.iloc[-1] / closes.iloc[-21]) - 1) * 100, 2)

        return {
            "current_rv": metrics["rv_20d"],
            "rv_series": rv_series,
            "sample_days": metrics["sample_days"],
            "rv_rank": metrics["rv_rank"],
            "rv_percentile": metrics["rv_percentile"],
            "rv_min": metrics["rv_min"],
            "rv_max": metrics["rv_max"],
            "status": metrics["status"],
            "pct_change_20d": pct_change_20d,
        }

    @staticmethod
    def get_atm_iv_snapshot(symbol: str) -> dict[str, Any]:
        """Fetch ATM implied vol, current price, and ATM strike for daily snapshotting.

        Uses the nearest expiration >= 7 calendar days out for a stable IV reading.
        Returns a dict with keys: atm_iv, current_price, atm_strike (all may be None).
        """
        try:
            ticker = yf.Ticker(symbol)

            # Current price via recent daily history (more robust than .info in batch)
            hist = ticker.history(period="2d", interval="1d", auto_adjust=True)
            current_price: float | None = (
                float(hist["Close"].iloc[-1])
                if hist is not None and not hist.empty
                else None
            )

            exps = list(ticker.options) if ticker.options else []
            if not exps or current_price is None:
                return {"atm_iv": None, "current_price": current_price, "atm_strike": None}

            week_out = (pd.Timestamp.today() + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
            chosen = next((e for e in exps if e >= week_out), exps[0])

            chain = ticker.option_chain(chosen)
            calls = _parse_option_df(chain.calls)
            puts  = _parse_option_df(chain.puts)

            all_strikes = sorted({c["strike"] for c in calls} | {p["strike"] for p in puts})
            if not all_strikes:
                return {"atm_iv": None, "current_price": current_price, "atm_strike": None}

            atm_strike = min(all_strikes, key=lambda s: abs(s - current_price))
            atm_call = next((c for c in calls if c["strike"] == atm_strike), None)
            atm_put  = next((p for p in puts  if p["strike"] == atm_strike), None)
            ivs = [
                c["impliedVolatility"]
                for c in [atm_call, atm_put]
                if c and c.get("impliedVolatility") is not None
            ]
            atm_iv: float | None = sum(ivs) / len(ivs) if ivs else None

            return {"atm_iv": atm_iv, "current_price": current_price, "atm_strike": atm_strike}
        except Exception:
            return {"atm_iv": None, "current_price": None, "atm_strike": None}
