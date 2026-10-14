"""The live layer behind LIVE_DATA_ENABLED: 15-minute delayed quotes from Intrinio for every active ticker during market
hours, and intraday bars for the 1-day chart. Off in production; the admin token (a browser with preview on) sees it while the
flag is off, as DISCOVER_NEWS_ENABLED and ASK_IVY_ENABLED do. Finnhub quotes stay the source while the flag is off.

Collection (startup._live_quote_loop) runs whenever LIVE_DATA_COLLECT_ENABLED is on and an Intrinio key is set, every
QUOTE_REFRESH_SECONDS inside market hours, one bulk call per refresh (/stock_exchanges/USCOMP/prices/realtime with the tickers
listed, source cboe_one_delayed, up to 10,000 rows a page). Each quote is stored with the vendor's own last-trade time and basis
"delayed"; the delay figure (DELAY_MINUTES) is the source's stated delay (the Intrinio spec: "Realtime or 15-minute delayed")
and travels in the record as delay_minutes, so the pages render it, never type it.

Serving: a delayed quote is served only while it is current, which means its last trade is on the latest session and, while the
market is open, within QUOTE_MAX_AGE_MINUTES. Otherwise the reader gets the stored Intrinio close with its date (basis "close"),
never a stale price shown as current. Intraday options are not on the plan (every realtime option price endpoint returns 403 on
2026-10-12), so the intraday chain is not built; the nightly chain stays the only options source.
"""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.config import settings

NY = ZoneInfo("America/New_York")
MARKET_OPEN = dtime(9, 30)
MARKET_CLOSE = dtime(16, 0)
HALF_DAY_CLOSE = dtime(13, 0)
QUOTE_REFRESH_SECONDS = 120            # one bulk refresh every two minutes in market hours
QUOTE_MAX_AGE_MINUTES = 20             # a delayed quote older than this during market hours is stale: the stored close is served
DELAY_MINUTES = 15                     # the source's stated delay (Intrinio spec: cboe_one_delayed / delayed_sip are 15-minute delayed)
DELAYED_BASIS = "delayed"
QUOTE_SOURCE = "cboe_one_delayed"
EXCHANGE = "USCOMP"                    # Intrinio's US composite: every active ticker in one listing
PAGE_SIZE = 10000                      # the endpoint's maximum page size, so one page holds the whole universe
CHART_INTERVAL = "5m"
CHART_CACHE_SECONDS = 120
INTRINIO_LIMIT_PER_MINUTE = 2000
BUDGET_WARN_SHARE = 0.5                # validate warns when full load would use more than this share of the limit
QUOTES_KEY = "live_quotes"             # system_metadata: {"captured_at", "source", "delay_minutes", "quotes": {SYM: record}}
STATUS_KEY = "live_data_status"        # system_metadata: the last refresh's figures, for /health and validate


def serving_enabled(admin: bool = False) -> bool:
    """The live layer is shown when the flag is on, or to the admin token (preview) while it is off."""
    return bool(settings.live_data_enabled or admin)


def collecting() -> bool:
    return bool(settings.live_data_collect_enabled and settings.intrinio_api_key)


def session_close(d: date) -> dtime:
    from app.services.trading_calendar import is_half_day
    return HALF_DAY_CLOSE if is_half_day(d) else MARKET_CLOSE


def market_open(now: datetime) -> bool:
    """Pure: the market is open at `now` (any zone): a trading day on the New York clock, 09:30 up to the close."""
    from app.services.trading_calendar import is_trading_day
    local = now.astimezone(NY)
    if not is_trading_day(local.date()):
        return False
    return MARKET_OPEN <= local.time() < session_close(local.date())


def latest_session(now: datetime) -> date:
    """Pure: the session whose prices are the newest at `now`: today once the market has opened, else the last session before."""
    from app.services.trading_calendar import is_trading_day, last_session_before
    local = now.astimezone(NY)
    if is_trading_day(local.date()) and local.time() >= MARKET_OPEN:
        return local.date()
    return last_session_before(local.date())


def refresh_due(now: datetime, last_run: datetime | None) -> bool:
    """Pure: a refresh is due in market hours once QUOTE_REFRESH_SECONDS have passed since the last one."""
    if not market_open(now):
        return False
    return last_run is None or (now - last_run).total_seconds() >= QUOTE_REFRESH_SECONDS


def _unix(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return None


def quote_record(row: dict, captured_at: datetime) -> dict | None:
    """Pure: one vendor row to the Finnhub-shaped quote every reader takes (c, d, dp, h, l, o, pc, t), basis "delayed",
    the delay figure, and the capture time. None without a last price and its time."""
    price, t = row.get("last_price"), _unix(row.get("last_time"))
    if price is None or t is None:
        return None
    prev = row.get("eod_close_price")
    change = round(price - prev, 4) if prev else None
    return {"c": price, "d": change, "dp": round(change / prev * 100, 4) if prev and change is not None else None,
            "h": row.get("high_price"), "l": row.get("low_price"), "o": row.get("open_price"), "pc": prev, "t": t,
            "basis": DELAYED_BASIS, "delay_minutes": DELAY_MINUTES, "source": row.get("source") or QUOTE_SOURCE,
            "captured_at": captured_at.isoformat()}


def quote_current(record: dict | None, now: datetime) -> bool:
    """Pure: the delayed quote may be shown: its last trade is on the latest session, and, while the market is open, no older
    than QUOTE_MAX_AGE_MINUTES. A quote that fails this is never shown as current; the stored close is served instead."""
    if not record or record.get("t") is None:
        return False
    traded = datetime.fromtimestamp(int(record["t"]), tz=timezone.utc)
    if traded.astimezone(NY).date() != latest_session(now):
        return False
    if market_open(now) and (now - traded).total_seconds() > QUOTE_MAX_AGE_MINUTES * 60:
        return False
    return True


def calls_per_hour_full_load(active: int, chart_viewers: int | None = None) -> dict:
    """Pure: the Intrinio calls an hour of market time costs at full load: one bulk quote page per PAGE_SIZE tickers every refresh,
    plus one interval-bars call per distinct 1-day chart view per CHART_CACHE_SECONDS (every active ticker viewed, worst case)."""
    refreshes = 3600 // QUOTE_REFRESH_SECONDS
    quote_calls = max(1, math.ceil(active / PAGE_SIZE)) * refreshes
    chart_calls = (active if chart_viewers is None else chart_viewers) * (3600 // CHART_CACHE_SECONDS)
    total = quote_calls + chart_calls
    per_minute = total / 60
    return {"quote_calls": quote_calls, "chart_calls": chart_calls, "total": total, "per_minute": round(per_minute, 1),
            "limit_per_minute": INTRINIO_LIMIT_PER_MINUTE, "share_of_limit": round(per_minute / INTRINIO_LIMIT_PER_MINUTE, 4)}


# ── collection ────────────────────────────────────────────────────────────────

async def fetch_quotes(client, symbols: list[str], captured_at: datetime) -> tuple[dict[str, dict], int]:
    """({SYM: record}, calls): the bulk endpoint, one page per PAGE_SIZE tickers, following next_page."""
    out: dict[str, dict] = {}
    calls = 0
    for i in range(0, len(symbols), PAGE_SIZE):
        chunk = symbols[i:i + PAGE_SIZE]
        params: dict = {"tickers": ",".join(chunk), "source": QUOTE_SOURCE, "page_size": PAGE_SIZE}
        while True:
            body = await client._get(f"/stock_exchanges/{EXCHANGE}/prices/realtime", params)
            calls += 1
            for row in body.get("stock_prices") or []:
                sym = ((row.get("security") or {}).get("ticker") or "").upper()
                rec = quote_record(row, captured_at)
                if sym and rec:
                    out[sym] = rec
            if not body.get("next_page"):
                break
            params = {**params, "next_page": body["next_page"]}
    return out, calls


async def refresh_quotes(now: datetime | None = None) -> dict:
    """One refresh: fetch every active ticker's delayed quote, store them under QUOTES_KEY, record the figures under STATUS_KEY."""
    from sqlalchemy import text
    from app.database import ScriptSessionLocal
    from app.services.intrinio_client import IntrinioClient
    from app.services.redact import redact
    from app.services.system_metadata_service import set_value
    now = now or datetime.now(timezone.utc)
    async with ScriptSessionLocal() as s:
        symbols = list((await s.execute(text("SELECT symbol FROM tickers WHERE is_active ORDER BY symbol"))).scalars().all())
    status = {"last_run_at": now.isoformat(), "tickers": len(symbols), "quotes_stored": 0, "calls": 0, "error": None,
              "budget": calls_per_hour_full_load(len(symbols)), "source": QUOTE_SOURCE, "delay_minutes": DELAY_MINUTES}
    client = IntrinioClient()
    try:
        quotes, calls = await fetch_quotes(client, symbols, now)
        status.update(quotes_stored=len(quotes), calls=calls)
        async with ScriptSessionLocal() as s:
            await set_value(s, QUOTES_KEY, json.dumps({"captured_at": now.isoformat(), "source": QUOTE_SOURCE, "delay_minutes": DELAY_MINUTES, "quotes": quotes}))
            await s.commit()
        _cache.clear()
    except Exception as exc:
        status["error"] = redact(exc)[:200]
    finally:
        await client.close()
    try:
        async with ScriptSessionLocal() as s:
            await set_value(s, STATUS_KEY, json.dumps(status))
            await s.commit()
    except Exception:
        pass
    return status


# ── serving ───────────────────────────────────────────────────────────────────

_cache: dict[str, tuple[float, dict]] = {}
_CACHE_SECONDS = 30


async def stored_quotes(db) -> dict:
    """The stored live quotes, read once per _CACHE_SECONDS per process."""
    from app.services.system_metadata_service import get_value
    hit = _cache.get("quotes")
    if hit and time.monotonic() - hit[0] < _CACHE_SECONDS:
        return hit[1]
    raw = await get_value(db, QUOTES_KEY)
    data = json.loads(raw) if raw else {}
    _cache["quotes"] = (time.monotonic(), data)
    return data


async def served_quote(db, symbol: str, admin: bool = False, now: datetime | None = None) -> dict | None:
    """The quote the live layer serves for `symbol`, Finnhub-shaped, or None when the layer is off for this reader: the current
    delayed quote, else the stored Intrinio close with its date (basis "close"). Never a stale price."""
    if not serving_enabled(admin):
        return None
    now = now or datetime.now(timezone.utc)
    data = await stored_quotes(db)
    rec = (data.get("quotes") or {}).get(symbol.upper())
    if quote_current(rec, now):
        return rec
    import asyncio
    from app.services.quote_fallback import stored_close_quote_sync
    return await asyncio.get_event_loop().run_in_executor(None, stored_close_quote_sync, symbol.upper())


_chart_cache: dict[str, tuple[float, dict]] = {}


def bars_to_history(intervals: list[dict]) -> list[dict]:
    """Pure: the vendor's newest-first 5-minute bars to the chart's oldest-first {date (ISO with offset), close} points."""
    pts = [{"date": b["time"], "close": float(b["close"])} for b in intervals if b.get("close") is not None and b.get("time")]
    return sorted(pts, key=lambda p: p["date"])


WEEK_INTERVAL = "30m"          # the 7-day chart's bars (the 1-day chart reads CHART_INTERVAL)
WEEK_SPAN_DAYS = 9             # calendar days back for the 7-day view: seven sessions and a weekend


async def intraday_chart(symbol: str, on: date, prev_close: float | None, start: date | None = None, interval: str = CHART_INTERVAL) -> dict | None:
    """The intraday chart from Intrinio's bars (5-minute for one session, 30-minute over a week) from `start` (default `on`) through
    `on`, cached CHART_CACHE_SECONDS; None when the call fails. Every bar carries its own time. Serves every visitor since 2026-10-12
    (the chart's intraday periods left yfinance); the live flag only governs quotes."""
    start = start or on
    key = f"{symbol}:{start.isoformat()}:{on.isoformat()}:{interval}"
    hit = _chart_cache.get(key)
    if hit and time.monotonic() - hit[0] < CHART_CACHE_SECONDS:
        return hit[1]
    from app.services.intrinio_client import IntrinioClient
    client = IntrinioClient()
    try:
        # Intrinio's end_date is exclusive (start = end returns no bars): the day after `on`, so the session's own bars come back
        body = await client._get(f"/securities/{symbol}/prices/intervals", {"interval_size": interval, "start_date": start.isoformat(), "end_date": (on + timedelta(days=1)).isoformat(),
                                                                          "timezone": "America/New_York", "page_size": 1000})
    except Exception:
        return None
    finally:
        await client.close()
    history = bars_to_history(body.get("intervals") or [])
    out = {"history": history, "start_price": prev_close if start == on else (history[0]["close"] if history else None),
           "bars_source": body.get("source"), "bars_through": history[-1]["date"] if history else None}
    _chart_cache[key] = (time.monotonic(), out)
    return out


@dataclass(frozen=True)
class LiveStatus:
    last_run_at: datetime | None
    quotes_stored: int
    error: str | None
    budget: dict


def parse_status(raw: str | None) -> LiveStatus | None:
    if not raw:
        return None
    try:
        d = json.loads(raw)
        at = datetime.fromisoformat(d["last_run_at"]) if d.get("last_run_at") else None
    except (ValueError, TypeError, KeyError):
        return None
    return LiveStatus(at, int(d.get("quotes_stored") or 0), d.get("error"), d.get("budget") or {})
