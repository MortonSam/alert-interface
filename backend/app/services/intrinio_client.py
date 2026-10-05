"""Intrinio: daily prices and end-of-day options chains, nothing else.

Two read paths, both paced and retried, with a request counter so a run can say what it cost:

  daily_prices(identifier, start, end)        /securities/{id}/prices, daily, raw and split/dividend-adjusted
  options_expirations_eod(symbol, after, before)   /options/expirations/{symbol}/eod
  options_chain_eod(symbol, expiration, on)   /options/chain/{symbol}/{expiration}/eod

The spec (api-v2.intrinio.com, 2.142.5) documents no rate limits; the plan's limits arrive as 429s, which are
retried with backoff and any Retry-After honoured. One request every MIN_INTERVAL_SECONDS by default keeps a
full 512-ticker price pass (one request per ticker, page_size 10000 covers five years of bars) under a
minute-level cap. Nothing imports this module yet.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import httpx

BASE_URL = "https://api-v2.intrinio.com"
MIN_INTERVAL_SECONDS = 0.25
RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0)       # after a 429 or a 5xx; Retry-After wins when present
PAGE_SIZE = 10000                         # the spec's maximum for price pages


class IntrinioAuthError(RuntimeError):
    """The API refused the key: nothing retries this."""


@dataclass
class RequestLog:
    count: int = 0
    retries: int = 0
    last_status: int | None = None
    rate_limit_headers: dict[str, str] = field(default_factory=dict)


class IntrinioClient:
    def __init__(self, api_key: str | None = None, min_interval: float = MIN_INTERVAL_SECONDS, timeout: float = 30.0):
        from app.config import settings
        self.api_key = (api_key or os.environ.get("INTRINIO_API_KEY") or settings.intrinio_api_key or "").strip()
        self.min_interval = min_interval
        self._client = httpx.AsyncClient(base_url=BASE_URL, timeout=timeout)
        self._last_at = 0.0
        self.log = RequestLog()

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def request_count(self) -> int:
        return self.log.count

    async def _get(self, path: str, params: dict[str, Any]) -> dict:
        if not self.api_key:
            raise IntrinioAuthError("INTRINIO_API_KEY is not set")
        params = {k: v for k, v in params.items() if v is not None}
        params["api_key"] = self.api_key
        for attempt in range(len(RETRY_DELAYS) + 1):
            wait = self.min_interval - (time.monotonic() - self._last_at)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_at = time.monotonic()
            self.log.count += 1
            resp = await self._client.get(path, params=params)
            self.log.last_status = resp.status_code
            self.log.rate_limit_headers = {k: v for k, v in resp.headers.items() if "limit" in k.lower() or "retry" in k.lower()}
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in (401, 403):
                raise IntrinioAuthError(f"{resp.status_code}: {resp.text[:200]}")
            if resp.status_code == 404:
                return {}
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt == len(RETRY_DELAYS):
                    resp.raise_for_status()
                delay = RETRY_DELAYS[attempt]
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    delay = max(delay, float(retry_after))
                self.log.retries += 1
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
        raise RuntimeError("unreachable")

    async def _paged(self, path: str, params: dict[str, Any], key: str) -> list[dict]:
        out: list[dict] = []
        next_page: str | None = None
        while True:
            body = await self._get(path, {**params, "next_page": next_page})
            out.extend(body.get(key) or [])
            next_page = body.get("next_page")
            if not next_page:
                return out

    async def daily_prices(self, identifier: str, start: date, end: date) -> list[dict]:
        """Daily bars ascending by date: {date, open, high, low, close, volume, adj_open, adj_close, ...}."""
        rows = await self._paged(f"/securities/{identifier}/prices",
                                 {"start_date": start.isoformat(), "end_date": end.isoformat(), "frequency": "daily", "page_size": PAGE_SIZE},
                                 "stock_prices")
        return sorted(rows, key=lambda r: r["date"])

    async def price_adjustments(self, identifier: str, start: date | None = None, end: date | None = None) -> list[dict]:
        """Every split and dividend adjustment for a security, ascending by date:
        [{date, factor, dividend, dividend_currency, split_ratio}] (split_ratio is the price factor: 0.1 for a 10-for-1)."""
        rows = await self._paged(f"/securities/{identifier}/prices/adjustments",
                                 {"start_date": start.isoformat() if start else None, "end_date": end.isoformat() if end else None, "page_size": PAGE_SIZE},
                                 "stock_price_adjustments")
        return sorted(rows, key=lambda r: r["date"])

    async def options_expirations_eod(self, symbol: str, after: date | None = None, before: date | None = None) -> list[str]:
        body = await self._get(f"/options/expirations/{symbol}/eod",
                               {"after": after.isoformat() if after else None, "before": before.isoformat() if before else None})
        return sorted(body.get("expirations") or [])

    async def options_chain_eod(self, symbol: str, expiration: str, on: date | None = None) -> list[dict]:
        """[{option: {code, ticker, expiration, strike, type}, prices: {date, close, close_bid, close_ask, mark,
        implied_volatility, close_time, close_bid_time, close_ask_time, ...}}] for one expiration."""
        body = await self._get(f"/options/chain/{symbol}/{expiration}/eod", {"date": on.isoformat() if on else None})
        return body.get("chain") or []


async def self_test() -> str:
    """One request: says whether the key works and what rate-limit headers the API sends."""
    c = IntrinioClient()
    try:
        rows = await c.daily_prices("AAPL", date(2026, 9, 20), date(2026, 9, 30))
        return f"ok: {len(rows)} AAPL bars, {c.request_count} request(s), headers {c.log.rate_limit_headers}"
    except IntrinioAuthError as exc:
        return f"auth failed: {exc}"
    finally:
        await c.close()


if __name__ == "__main__":
    print(asyncio.run(self_test()))
