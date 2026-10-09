"""Finnhub API client.

Implemented
-----------
  get_quote(symbol)                       → raw quote dict {c, d, dp, h, l, o, pc, t}
  get_candles(symbol, resolution, from, to) → raw candle dict {c, h, l, o, s, t, v}
  get_daily_candles(symbol, days)         → list of DayCandle dicts
  get_company_news(symbol, from_date, to_date) → list of article dicts
  get_basic_financials(symbol)               → raw metric dict from /stock/metric
  get_earnings_surprises(symbol)             → list of quarterly EPS + revenue surprise dicts
  get_profile2(symbol)                       → company profile {name, marketCapitalization, ...}
  get_earnings_calendar(from_date, to_date)  → earnings calendar {earningsCalendar: [...]}

  get_recommendation_trends(symbol)       → list of monthly consensus dicts

Rate limiting
-------------
  One budget for every process (services/finnhub_limiter, kept in Postgres): a client is a visitor's (the routers) or a
  job's (the default), and jobs always leave part of each minute to visitors. When the database cannot be used, the
  in-process window (REQUESTS_PER_MINUTE) paces alone. A 429 is retried with backoff that honours Retry-After
  (RETRY_DELAYS), counted in STATS for step outcomes, and raised as FinnhubRateLimited only after the retries. Every
  error message passes through services.redact.

  A visitor's quote never waits: one with no answer within QUOTE_WAIT_SECONDS (or none at all) is the last stored close
  from the Intrinio bars (services/quote_fallback), dated by that session's close and marked basis "close".

Finnhub field key reference
---------------------------
  Quote   : c=current, d=change, dp=%change, h=high, l=low, o=open, pc=prev_close, t=timestamp
  Candles : c=closes, h=highs, l=lows, o=opens, v=volumes, t=timestamps, s=status
"""
from __future__ import annotations
from app.services.redact import redact

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.services import finnhub_limiter
from app.services.finnhub_limiter import BACKGROUND, VISITOR

FINNHUB_BASE = "https://finnhub.io/api/v1"

# ── Module-level pacing ───────────────────────────────────────────────────────
# One pace for every FinnhubClient in the process (profiles, share counts, EPS actuals, recommendations, calendar, quotes):
# at most REQUESTS_PER_MINUTE requests in any rolling minute, a 429 retried with backoff that honours Retry-After, and the
# counts kept for step outcomes.

REQUESTS_PER_MINUTE = 55                     # the in-process window, used only when the shared budget cannot be read
QUOTE_WAIT_SECONDS = 2.0                     # a visitor's quote waits no longer than this before the stored close serves
RETRY_DELAYS = (2.0, 5.0, 15.0, 30.0)        # after a 429 without a usable Retry-After; a Retry-After larger than these wins
_rate_lock = asyncio.Lock()
_recent_calls: list[float] = []              # monotonic times of the calls in the last minute
STATS = {"requests": 0, "rate_limited": 0, "retries_exhausted": 0}


def finnhub_stats() -> dict:
    """Counts since the process started, for step outcomes: requests, 429s met, requests given up after the retries."""
    return dict(STATS)


class FinnhubRateLimited(RuntimeError):
    """A request still 429 after every retry."""


async def _pace(priority: str = BACKGROUND) -> None:
    """Block until the shared budget has a slot for this priority; the in-process window when it cannot be read."""
    if await finnhub_limiter.acquire(priority):
        STATS["requests"] += 1
        return
    async with _rate_lock:
        loop = asyncio.get_event_loop()
        while True:
            now = loop.time()
            while _recent_calls and now - _recent_calls[0] >= 60.0:
                _recent_calls.pop(0)
            if len(_recent_calls) < REQUESTS_PER_MINUTE:
                _recent_calls.append(now)
                STATS["requests"] += 1
                return
            await asyncio.sleep(max(0.05, 60.0 - (now - _recent_calls[0])))


def retry_delay(retry_after: str | None, attempt: int) -> float:
    """Seconds to wait after a 429: Retry-After when the server sends one, never less than the backoff schedule."""
    base = RETRY_DELAYS[min(attempt, len(RETRY_DELAYS) - 1)]
    if retry_after and retry_after.strip().isdigit():
        return max(base, float(retry_after.strip()))
    return base


class FinnhubClient:
    def __init__(self, priority: str = BACKGROUND) -> None:
        self.priority = priority
        self._client = httpx.AsyncClient(
            base_url=FINNHUB_BASE,
            # token injected on every request via default params
            params={"token": settings.finnhub_api_key},
            timeout=10.0,
        )

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """A paced request; a 429 is retried with backoff honouring Retry-After; every error message is redacted."""
        attempt = 0
        while True:
            await _pace(self.priority)
            try:
                resp = await self._client.request(method, path, params=params)
            except httpx.HTTPError as exc:
                raise httpx.HTTPError(redact(exc)) from None
            if resp.status_code == 429:
                STATS["rate_limited"] += 1
                if attempt >= len(RETRY_DELAYS):
                    STATS["retries_exhausted"] += 1
                    raise FinnhubRateLimited(f"Finnhub 429 on {path} after {attempt} retries")
                await asyncio.sleep(retry_delay(resp.headers.get("Retry-After"), attempt))
                attempt += 1
                continue
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise httpx.HTTPStatusError(redact(exc), request=exc.request, response=exc.response) from None
            return resp.json()

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
        if self.priority != VISITOR:
            return await self._request("GET", "/quote", params={"symbol": symbol})
        from app.services.quote_fallback import stored_close_quote
        try:
            q = await asyncio.wait_for(self._request("GET", "/quote", params={"symbol": symbol}), QUOTE_WAIT_SECONDS)
            if q.get("c") and q.get("t"):
                return {**q, "basis": "last_trade"}
            reason = "no price in the answer"
        except asyncio.TimeoutError:
            reason = f"no answer within {QUOTE_WAIT_SECONDS:g}s"
        except Exception as exc:
            reason = redact(exc)[:120]
        print(f"[quote] {symbol}: serving the stored close ({reason})", flush=True)
        return await stored_close_quote(symbol)

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
        return await self._request(
            "GET",
            "/stock/candle",
            params={
                "symbol": symbol,
                "resolution": resolution,
                "from": from_ts,
                "to": to_ts,
            },
        )

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

    # ── Company profile ────────────────────────────────────────────────────────

    async def get_profile2(self, symbol: str) -> dict[str, Any]:
        """Company profile from Finnhub.
        Finnhub endpoint: GET /stock/profile2?symbol=

        Returns dict with: country, currency, exchange, finnhubIndustry, ipo,
        logo, marketCapitalization (in millions USD), name, phone, shareOutstanding,
        ticker, weburl.
        """
        return await self._request("GET", "/stock/profile2", params={"symbol": symbol})

    # ── Earnings calendar ──────────────────────────────────────────────────────

    async def get_earnings_calendar(
        self,
        from_date: str,   # "YYYY-MM-DD"
        to_date: str,     # "YYYY-MM-DD"
        symbol: str | None = None,
    ) -> dict[str, Any]:
        """Earnings calendar for a date range, optionally filtered by symbol.
        Finnhub endpoint: GET /calendar/earnings?from=&to=[&symbol=]

        Returns dict with earningsCalendar list of:
        {date, epsActual, epsEstimate, hour, quarter, revenueActual,
         revenueEstimate, symbol, year}.
        """
        params: dict[str, str] = {"from": from_date, "to": to_date}
        if symbol:
            params["symbol"] = symbol
        return await self._request(
            "GET", "/calendar/earnings",
            params=params,
        )

    # ── News ───────────────────────────────────────────────────────────────────

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
        return await self._request(
            "GET", "/company-news",
            params={"symbol": symbol, "from": from_date, "to": to_date},
        )

    async def get_general_news(self, category: str = "general") -> list[dict[str, Any]]:
        """Market news (GET /news?category=general): the same fields as company news; `related` is often empty."""
        return await self._request("GET", "/news", params={"category": category})

    async def get_basic_financials(self, symbol: str) -> dict[str, Any]:
        """Basic financials / key metrics for a symbol.
        Finnhub endpoint: GET /stock/metric?symbol=&metric=all
        """
        return await self._request(
            "GET", "/stock/metric",
            params={"symbol": symbol, "metric": "all"},
        )

    async def get_earnings_surprises(self, symbol: str) -> list[dict[str, Any]]:
        """Historical EPS + revenue surprises per quarter.
        Finnhub endpoint: GET /stock/earnings?symbol=
        Each dict: actual, estimate, period, quarter, year,
        revenueActual, revenueEstimate, surprise, surprisePercent, symbol.
        """
        return await self._request("GET", "/stock/earnings", params={"symbol": symbol})

    async def get_recommendation_trends(self, symbol: str) -> list[dict[str, Any]]:
        """Monthly analyst buy / hold / sell consensus trends.
        Finnhub endpoint: GET /stock/recommendation?symbol=
        """
        return await self._request("GET", "/stock/recommendation", params={"symbol": symbol})

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    async def close(self) -> None:
        await self._client.aclose()
