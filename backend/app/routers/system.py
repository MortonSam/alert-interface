from __future__ import annotations

import asyncio
from datetime import date, datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import require_admin
from app.database import get_db
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.services.system_metadata_service import get_value

router = APIRouter(prefix="/system", tags=["system"])


class SystemStatus(BaseModel):
    last_refreshed_at: datetime | None
    total_tickers: int
    total_reactions: int
    most_recent_reaction_date: date | None


@router.get("/status", response_model=SystemStatus)
async def get_system_status(db: AsyncSession = Depends(get_db)) -> SystemStatus:
    last_refreshed_raw = await get_value(db, "last_refreshed_at")
    last_refreshed_at: datetime | None = None
    if last_refreshed_raw:
        try:
            last_refreshed_at = datetime.fromisoformat(last_refreshed_raw)
        except ValueError:
            pass

    total_tickers = await db.scalar(
        select(func.count()).select_from(Ticker).where(Ticker.is_active.is_(True))
    ) or 0

    total_reactions = await db.scalar(
        select(func.count()).select_from(HistoricalReaction)
    ) or 0

    most_recent_reaction_date: date | None = await db.scalar(
        select(func.max(HistoricalReaction.event_date))
    )

    return SystemStatus(
        last_refreshed_at=last_refreshed_at,
        total_tickers=total_tickers,
        total_reactions=total_reactions,
        most_recent_reaction_date=most_recent_reaction_date,
    )


@router.get("/debug-options-fetch", dependencies=[Depends(require_admin)])
async def debug_options_fetch(symbol: str = "AAPL", expiration: str = "2026-08-21") -> dict:
    """Temporary diagnostic: test three options-fetch methods and report results.

    (a) Current yfinance client (uses curl_cffi internally)
    (b) Raw requests with browser-like headers
    (c) curl_cffi impersonation directly

    Remove this endpoint once datacenter fetch behavior is characterized.
    """
    loop = asyncio.get_event_loop()
    results: dict = {}

    # ── (a) Current yfinance client ──────────────────────────────────────
    def _method_a():
        from app.services.yfinance_client import YFinanceClient
        chain = YFinanceClient.get_option_chain(symbol, expiration)
        calls = chain.get("calls", [])
        quality = [c for c in calls if (c.get("bid") or 0) > 0 or (c.get("ask") or 0) > 0]
        return {
            "total_calls": len(calls),
            "quality_calls": len(quality),
            "chain_last_trade": chain.get("chain_last_trade"),
            "sample": [
                {"strike": c["strike"], "bid": c.get("bid"), "ask": c.get("ask")}
                for c in quality[:3]
            ],
        }

    try:
        results["a_yfinance_client"] = await loop.run_in_executor(None, _method_a)
    except Exception as exc:
        results["a_yfinance_client"] = {"error": str(exc)}

    # ── (b) Raw requests with browser-like headers ───────────────────────
    def _method_b():
        import json
        import urllib.request
        url = f"https://query2.finance.yahoo.com/v7/finance/options/{symbol}?date="
        # Convert expiration to unix timestamp
        from datetime import datetime as _dt
        exp_dt = _dt.strptime(expiration, "%Y-%m-%d")
        epoch = int(exp_dt.timestamp())
        url += str(epoch)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            chain_data = data.get("optionChain", {}).get("result", [{}])[0]
            options = chain_data.get("options", [{}])[0] if chain_data.get("options") else {}
            calls = options.get("calls", [])
            quality = [c for c in calls if (c.get("bid") or 0) > 0 or (c.get("ask") or 0) > 0]
            return {
                "total_calls": len(calls),
                "quality_calls": len(quality),
                "sample": [
                    {"strike": c.get("strike", {}).get("raw"), "bid": c.get("bid", {}).get("raw"), "ask": c.get("ask", {}).get("raw")}
                    for c in quality[:3]
                ],
            }
        except Exception as e:
            return {"error": str(e)}

    try:
        results["b_browser_headers"] = await loop.run_in_executor(None, _method_b)
    except Exception as exc:
        results["b_browser_headers"] = {"error": str(exc)}

    # ── (c) curl_cffi impersonation ──────────────────────────────────────
    def _method_c():
        try:
            from curl_cffi import requests as cffi_requests
        except ImportError:
            return {"error": "curl_cffi not installed"}
        from datetime import datetime as _dt
        exp_dt = _dt.strptime(expiration, "%Y-%m-%d")
        epoch = int(exp_dt.timestamp())
        url = f"https://query2.finance.yahoo.com/v7/finance/options/{symbol}?date={epoch}"
        try:
            resp = cffi_requests.get(url, impersonate="chrome", timeout=10)
            import json
            data = json.loads(resp.text)
            chain_data = data.get("optionChain", {}).get("result", [{}])[0]
            options = chain_data.get("options", [{}])[0] if chain_data.get("options") else {}
            calls = options.get("calls", [])
            quality = [c for c in calls if (c.get("bid") or 0) > 0 or (c.get("ask") or 0) > 0]
            return {
                "total_calls": len(calls),
                "quality_calls": len(quality),
                "sample": [
                    {"strike": c.get("strike", {}).get("raw"), "bid": c.get("bid", {}).get("raw"), "ask": c.get("ask", {}).get("raw")}
                    for c in quality[:3]
                ],
            }
        except Exception as e:
            return {"error": str(e)}

    try:
        results["c_curl_cffi"] = await loop.run_in_executor(None, _method_c)
    except Exception as exc:
        results["c_curl_cffi"] = {"error": str(exc)}

    return {"symbol": symbol, "expiration": expiration, "methods": results}
