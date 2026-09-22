"""expected-move, options, strategy-data and options-bundle withhold every price-derived number when the quote is stale.

Same test as the quote endpoint (price_freshness.assess_quote): a last trade more
than MAX_STALE_SESSIONS sessions old is not current. The chain itself is still
served; the state and the price date ride along so the page can say why.
"""
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.routers import tickers as tickers_router
from app.services import chain_store, quote_cache
from app.services.finnhub_client import FinnhubClient

SYM = "AAPL"
EXP = "2026-10-16"
CONTRACT = {"bid": 4.0, "ask": 4.2, "lastPrice": 4.1, "volume": 500, "openInterest": 2000, "impliedVolatility": 0.30}
CHAIN = {
    "calls": [dict(CONTRACT, strike=k) for k in (95.0, 100.0, 105.0)],
    "puts": [dict(CONTRACT, strike=k) for k in (95.0, 100.0, 105.0)],
}
STALE_TS = int((datetime.now(timezone.utc) - timedelta(days=12)).timestamp())
FRESH_TS = int(datetime.now(timezone.utc).timestamp())


def _install(monkeypatch, ts: int):
    monkeypatch.setattr(quote_cache, "get", lambda sym: None)
    monkeypatch.setattr(quote_cache, "set", lambda sym, data: None)

    async def fake_quote(self, symbol):
        return {"c": 100.0, "t": ts, "d": 0.5, "dp": 0.5, "h": 101.0, "l": 99.0, "o": 99.5, "pc": 99.5}
    monkeypatch.setattr(FinnhubClient, "get_quote", fake_quote)

    async def exps(db, sym): return [EXP]
    async def pick(db, sym, min_exp): return EXP
    async def chain(db, sym, exp): return CHAIN, "2026-09-21"
    monkeypatch.setattr(chain_store, "get_ingested_expirations", exps)
    monkeypatch.setattr(chain_store, "pick_expiration", pick)
    monkeypatch.setattr(chain_store, "get_chain", chain)
    monkeypatch.setattr(chain_store, "is_fresh", lambda d, max_trading_days=3: True)


async def _get(path: str) -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get(path)
        assert resp.status_code == 200, resp.text
        return resp.json()


def _assert_stale(read: dict):
    assert read["quote_state"] == "stale"
    assert "no longer current" in read["quote_reason"]
    assert read["price_as_of"] is not None and read["price_as_of"].startswith(
        datetime.fromtimestamp(STALE_TS, tz=timezone.utc).date().isoformat())
    assert read["current_price"] is None


@pytest.mark.asyncio
async def test_expected_move_withholds_every_price_derived_figure_when_stale(monkeypatch):
    _install(monkeypatch, STALE_TS)
    em = await _get(f"/api/v1/tickers/expected-move/{SYM}")
    _assert_stale(em)
    for key in ("expected_move_pct", "expected_move_dollars", "implied_range_low", "implied_range_high",
                "straddle_price", "atm_strike"):
        assert em[key] is None, key
    assert em["expiration_used"] == EXP           # the chain is still named; only the price is withheld


@pytest.mark.asyncio
async def test_expected_move_computes_when_fresh(monkeypatch):
    _install(monkeypatch, FRESH_TS)
    em = await _get(f"/api/v1/tickers/expected-move/{SYM}")
    assert em["quote_state"] == "ok" and em["current_price"] == 100.0
    assert em["straddle_price"] == pytest.approx(8.2) and em["implied_range_low"] == pytest.approx(91.8)


@pytest.mark.asyncio
async def test_options_chain_serves_contracts_but_no_price_when_stale(monkeypatch):
    _install(monkeypatch, STALE_TS)
    chain = await _get(f"/api/v1/tickers/options/{SYM}")
    _assert_stale(chain)
    assert len(chain["calls"]) == 3 and len(chain["puts"]) == 3
    assert not any(c["is_atm"] for c in chain["calls"])   # ATM is price-derived


@pytest.mark.asyncio
async def test_strategy_data_has_no_strikes_or_range_when_stale(monkeypatch):
    _install(monkeypatch, STALE_TS)
    sd = await _get(f"/api/v1/tickers/strategy-data/{SYM}")
    _assert_stale(sd)
    assert sd["strikes"] == [] and sd["implied_range_low"] is None and sd["implied_range_high"] is None


@pytest.mark.asyncio
async def test_options_bundle_carries_the_stale_state_on_all_three_reads(monkeypatch):
    _install(monkeypatch, STALE_TS)
    b = await _get(f"/api/v1/tickers/options-bundle/{SYM}")
    for part in ("expected_move", "strategy_data", "chain"):
        _assert_stale(b[part])
    assert b["expected_move"]["implied_range_low"] is None
    assert b["strategy_data"]["strikes"] == []
    assert len(b["chain"]["calls"]) == 3


def test_all_four_endpoints_read_the_price_through_the_guard():
    import inspect
    src = inspect.getsource(tickers_router)
    start = src.index('@router.get("/expected-move/{symbol}"')
    end = src.index('@router.get("/options-read/{symbol}"')
    region = src[start:end]
    assert "finnhub.get_quote(" not in region
    assert region.count("await _guarded_price(sym)") == 4
