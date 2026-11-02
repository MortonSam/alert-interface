"""The price now, the same on every page (Sam, 2026-11-02): Build a Trade said "the stock is now $147.11 (last trade Oct 30)" on Monday
Nov 2 in market hours because its draft read Finnhub directly, past the live layer's delayed quote. services/live_data.now_quote is
the one way a route asks for the price now."""
import ast
from pathlib import Path

import pytest

from app.services import live_data

ROUTERS = Path(__file__).resolve().parents[1] / "app" / "routers"
# the routes that ask the live layer themselves first and fall back to Finnhub (each reads served_quote before get_quote)
ASKS_LIVE_FIRST = {"get_ticker_quote", "get_batch_quotes", "_guarded_price", "_price_now"}


@pytest.mark.asyncio
async def test_the_live_layers_delayed_quote_comes_first(monkeypatch):
    rec = {"c": 147.11, "t": 1793637720, "basis": "delayed", "delay_minutes": 15}

    async def served(db, sym, admin=False):
        return rec
    monkeypatch.setattr(live_data, "served_quote", served)
    assert await live_data.now_quote(object(), "BNY") == rec


@pytest.mark.asyncio
async def test_with_the_layer_off_the_shared_cache_then_finnhub(monkeypatch):
    from app.services import quote_cache

    async def off(db, sym, admin=False):
        return None
    monkeypatch.setattr(live_data, "served_quote", off)
    monkeypatch.setattr(quote_cache, "get", lambda s: {"price": 146.0, "change": 1.0, "change_pct": 0.7, "timestamp": 1793637000, "basis": "close"})
    q = await live_data.now_quote(object(), "BNY")
    assert q["c"] == 146.0 and q["basis"] == "close" and q["t"] == 1793637000


def test_no_route_asks_finnhub_for_the_price_now_past_the_live_layer():
    offenders = []
    for path in sorted(ROUTERS.glob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = {n.func.attr for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
            inner = [n for n in ast.walk(fn) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not fn]
            own_quote = "get_quote" in calls and not any("get_quote" in {c.func.attr for c in ast.walk(i) if isinstance(c, ast.Call)
                                                                          and isinstance(c.func, ast.Attribute)} for i in inner)
            if own_quote and fn.name not in ASKS_LIVE_FIRST:
                offenders.append(f"{path.name}:{fn.name}")
            if own_quote and fn.name in ASKS_LIVE_FIRST:
                assert "served_quote" in calls, f"{path.name}:{fn.name} must ask the live layer before Finnhub"
    assert offenders == []


def test_the_watchlist_reads_the_served_quotes_basis():
    """batch_enrich builds each row from _served_quote's shape, which serves the record's "basis" as quote_basis: a delayed quote is
    labeled delayed on the watchlist (2a0e304 read "basis" there and labeled every row last_trade)."""
    from app.routers.tickers import _quote_data_from, _served_quote
    import time
    served = _served_quote(_quote_data_from({"c": 148.14, "t": int(time.time()) - 60, "basis": "delayed", "delay_minutes": 15}))
    assert served["quote_basis"] == "delayed" and "basis" not in served
    src = (ROUTERS / "tickers.py").read_text()
    assert 'quote_basis=q.get("quote_basis")' in src
