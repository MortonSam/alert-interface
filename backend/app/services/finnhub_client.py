"""Finnhub API client.

Implemented
-----------
  get_quote(symbol)                       → raw quote dict {c, d, dp, h, l, o, pc, t}
  get_candles(symbol, resolution, from, to) → raw candle dict {c, h, l, o, s, t, v}
  get_daily_candles(symbol, days)         → list of DayCandle dicts
  get_company_news(symbol, from_date, to_date) → list of article dicts
  get_basic_financials(symbol)               → raw metric dict from /stock/metric
  get_earnings_surprises(symbol)             → list of quarterly EPS + revenue surprise dicts

Stubbed (raise NotImplementedError until needed)
-----------
  get_recommendation_trends(symbol)

Finnhub field key reference
---------------------------
  Quote   : c=current, d=change, dp=%change, h=high, l=low, o=open, pc=prev_close, t=timestamp
  Candles : c=closes, h=highs, l=lows, o=opens, v=volumes, t=timestamps, s=status
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings

FINNHUB_BASE = "https://finnhub.io/api/v1"


class FinnhubClient:
    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=FINNHUB_BASE,
            # token injected on every request via default params
            params={"token": settings.finnhub_api_key},
            timeout=10.0,
        )

    # ── Quote ──────────────────────────────────────────────────────────────────

    async def get_quote(self, symbol: str) -> dict[str, Any]:
        """Real-time quote for a symbol.

        Returns Finnhub's raw dict::

            {
                "c":  213.07,   # current price
                "d":  2.35,     # change
                "dp": 1.12,     # % change
                "h":  214.50,   # day high
                "l":  210.20,   # day low
                "o":  211.00,   # day open
                "pc": 210.72,   # previous close
                "t":  1716912000 # Unix timestamp
            }
        """
        resp = await self._client.get("/quote", params={"symbol": symbol})
        resp.raise_for_status()
        return resp.json()

    # ── Candles ────────────────────────────────────────────────────────────────

    async def get_candles(
        self,
        symbol: str,
        resolution: str,
        from_ts: int,
        to_ts: int,
    ) -> dict[str, Any]:
        """Raw OHLCV candles from Finnhub.

        Args:
            resolution: "1" | "5" | "15" | "30" | "60" | "D" | "W" | "M"
            from_ts / to_ts: Unix timestamps (inclusive)

        Returns Finnhub's raw dict::

            {
                "c": [...],   # close prices
                "h": [...],   # highs
                "l": [...],   # lows
                "o": [...],   # opens
                "v": [...],   # volumes
                "t": [...],   # Unix timestamps
                "s": "ok"     # status — "no_data" when no bars exist
            }
        """
        resp = await self._client.get(
            "/stock/candle",
            params={
                "symbol": symbol,
                "resolution": resolution,
                "from": from_ts,
                "to": to_ts,
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def get_daily_candles(
        self,
        symbol: str,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Daily OHLCV for the last ``days`` calendar days (~20-22 trading days).

        NOTE: ``/stock/candle`` requires a Finnhub paid plan (Starter+).
        On the free tier this raises a 403.  For free historical data use
        ``YFinanceClient.get_daily_closes()`` instead.

        Returns a list of dicts in chronological order::

            [{"date": "2024-04-01", "open": 171.0, "high": 173.5,
              "low": 170.1, "close": 171.2, "volume": 54_000_000}, ...]

        Returns ``[]`` when Finnhub has no data for the symbol.
        """
        now = datetime.now(timezone.utc)
        to_ts = int(now.timestamp())
        from_ts = int((now - timedelta(days=days)).timestamp())

        data = await self.get_candles(symbol, "D", from_ts, to_ts)
        if data.get("s") != "ok":
            return []

        return [
            {
                "date":   datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%d"),
                "open":   o,
                "high":   h,
                "low":    l,
                "close":  c,
                "volume": v,
            }
            for t, o, h, l, c, v in zip(
                data["t"], data["o"], data["h"], data["l"], data["c"], data["v"]
            )
        ]

    # ── Future endpoints ───────────────────────────────────────────────────────
    # These are stubbed so callers know the intended signatures and Finnhub
    # endpoints before implementation.  Uncomment / fill in when needed.

    async def get_company_news(
        self,
        symbol: str,
        from_date: str,   # "YYYY-MM-DD"
        to_date: str,     # "YYYY-MM-DD"
    ) -> list[dict[str, Any]]:
        """News articles for a symbol between two dates.
        Finnhub endpoint: GET /company-news?symbol=&from=&to=

        Each dict has: category, datetime (unix s), headline, id, image,
        related, source, summary, url.
        """
        resp = await self._client.get(
            "/company-news",
            params={"symbol": symbol, "from": from_date, "to": to_date},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_basic_financials(self, symbol: str) -> dict[str, Any]:
        """Basic financials / key metrics for a symbol.
        Finnhub endpoint: GET /stock/metric?symbol=&metric=all
        """
        resp = await self._client.get(
            "/stock/metric",
            params={"symbol": symbol, "metric": "all"},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_earnings_surprises(self, symbol: str) -> list[dict[str, Any]]:
        """Historical EPS + revenue surprises per quarter.
        Finnhub endpoint: GET /stock/earnings?symbol=
        Each dict: actual, estimate, period, quarter, year,
        revenueActual, revenueEstimate, surprise, surprisePercent, symbol.
        """
        resp = await self._client.get("/stock/earnings", params={"symbol": symbol})
        resp.raise_for_status()
        return resp.json()

    async def get_recommendation_trends(self, symbol: str) -> list[dict[str, Any]]:
        """Monthly analyst buy / hold / sell consensus trends.
        Finnhub endpoint: GET /stock/recommendation?symbol=
        """
        raise NotImplementedError

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def close(self) -> None:
        await self._client.aclose()
