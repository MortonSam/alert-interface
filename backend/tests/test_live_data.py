"""The live layer behind LIVE_DATA_ENABLED (services/live_data): market hours on the New York clock, a delayed quote served only
while current, the stored close otherwise, the admin token's preview while the flag is off, the API budget arithmetic, and the
validate checks that watch it."""
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.config import settings
from app.database import ScriptSessionLocal
from app.scripts.validate_data import CHECKS, check_live_api_budget, check_live_quote_age, check_live_quote_sanity, live_price_outliers, live_quote_contradiction, live_quote_stale
from app.services import live_data as L
from app.services.cadence import quote_cadence
from app.services.quote_fallback import BASIS_LABELS

pytestmark = pytest.mark.xdist_group(name="live_data")
NY = ZoneInfo("America/New_York")


def ny(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=NY)


def test_market_hours_and_the_latest_session_follow_the_new_york_clock():
    assert L.market_open(ny(2026, 10, 12, 9, 30)) and L.market_open(ny(2026, 10, 12, 15, 59)) and not L.market_open(ny(2026, 10, 12, 16, 0))
    assert not L.market_open(ny(2026, 10, 12, 9, 29)) and not L.market_open(ny(2026, 10, 11, 12, 0))          # before the open; a Sunday
    assert not L.market_open(ny(2026, 11, 27, 13, 30)) and L.market_open(ny(2026, 11, 27, 12, 30))             # the day after Thanksgiving closes at 13:00
    assert L.market_open(datetime(2026, 10, 12, 17, 0, tzinfo=timezone.utc))                                   # 13:00 New York, given in UTC
    assert L.latest_session(ny(2026, 10, 12, 10, 0)) == date(2026, 10, 12) and L.latest_session(ny(2026, 10, 12, 8, 0)) == date(2026, 10, 9)
    assert L.latest_session(ny(2026, 10, 11, 12, 0)) == date(2026, 10, 9)
    assert L.refresh_due(ny(2026, 10, 12, 10, 0), None) and not L.refresh_due(ny(2026, 10, 12, 10, 0), ny(2026, 10, 12, 9, 59))
    assert L.refresh_due(ny(2026, 10, 12, 10, 2), ny(2026, 10, 12, 10, 0)) and not L.refresh_due(ny(2026, 10, 12, 17, 0), None)
    assert L.QUOTE_REFRESH_SECONDS == 120 and L.QUOTE_MAX_AGE_MINUTES == 20 and L.DELAY_MINUTES == 15


def test_a_vendor_row_becomes_a_dated_delayed_quote_and_is_served_only_while_current():
    captured = ny(2026, 10, 12, 13, 2)
    row = {"last_price": 340.01, "last_time": "2026-10-12T16:44:13.496Z", "eod_close_price": 336.64, "high_price": 342.63, "low_price": 337.63, "open_price": 338.215,
           "source": "cboe_one_delayed", "security": {"ticker": "AAPL"}}
    rec = L.quote_record(row, captured)
    assert rec["c"] == 340.01 and rec["pc"] == 336.64 and rec["d"] == 3.37 and rec["dp"] == 1.0011 and rec["basis"] == "delayed" and rec["delay_minutes"] == 15
    assert rec["t"] == int(datetime(2026, 10, 12, 16, 44, 13, tzinfo=timezone.utc).timestamp()) and rec["captured_at"] == captured.isoformat()
    assert L.quote_record({"last_price": None, "last_time": "2026-10-12T16:44:13Z"}, captured) is None
    assert L.quote_current(rec, ny(2026, 10, 12, 12, 50))                     # six minutes old, market open
    assert not L.quote_current(rec, ny(2026, 10, 12, 13, 10))                 # 26 minutes old in market hours: stale, the close is served instead
    assert L.quote_current(rec, ny(2026, 10, 12, 18, 0))                      # after the close, the session's last delayed print stands, dated
    assert not L.quote_current(rec, ny(2026, 10, 13, 9, 40))                  # the next session: yesterday's print is never current
    assert not L.quote_current(None, ny(2026, 10, 12, 12, 50))
    assert BASIS_LABELS["delayed"] == "delayed"


def test_the_budget_counts_one_bulk_page_per_refresh_and_a_bars_call_per_cached_chart_view():
    b = L.calls_per_hour_full_load(503)
    assert b["quote_calls"] == 30 and b["chart_calls"] == 503 * 30 and b["total"] == 15120 and b["per_minute"] == 252.0 and b["limit_per_minute"] == 2000
    assert b["share_of_limit"] == 0.126 and L.BUDGET_WARN_SHARE == 0.5
    assert L.calls_per_hour_full_load(20000)["quote_calls"] == 60                # two pages of 10,000
    pts = L.bars_to_history([{"time": "2026-10-12T12:45:00.000-04:00", "close": 340.03}, {"time": "2026-10-12T09:30:00.000-04:00", "close": 338.5}, {"time": "x", "close": None}])
    assert [p["close"] for p in pts] == [338.5, 340.03]


def test_the_cadence_record_names_the_delay_only_when_the_live_layer_is_on():
    assert quote_cadence(live=False)["source"] == "Finnhub" and quote_cadence(live=False)["delay_statement"] is None
    q = quote_cadence(live=True)
    assert q["source"] == "Intrinio" and q["delay_statement"] == f"delayed {L.DELAY_MINUTES} min" and q["dated_by"] == "each quote's own last-trade time"


def test_the_validate_rules():
    assert check_live_quote_age in CHECKS and check_live_quote_sanity in CHECKS and check_live_api_budget in CHECKS
    assert live_quote_stale(ny(2026, 10, 12, 12, 30), ny(2026, 10, 12, 12, 55)) and not live_quote_stale(ny(2026, 10, 12, 12, 40), ny(2026, 10, 12, 12, 55))
    assert not live_quote_stale(None, ny(2026, 10, 12, 18, 0))                                          # closed: no stall to report
    quotes = {"AAPL": {"c": 340.0}, "CTVA": {"c": 13.9}, "BAD": {"c": 50.0}}
    closes = {"AAPL": 336.6, "CTVA": 77.6, "BAD": 100.0}
    assert live_price_outliers(quotes, closes, acted={"CTVA"}) == [
        "BAD: delayed 50.00 against the last close 100.00 (-50%), no day range or previous close in the quote to support it"]


def test_a_large_move_is_an_error_only_when_the_quote_contradicts_itself():
    # MRNA on 2026-10-22, as production stored it at 18:20 UTC: down 26% on leaked trial data, inside its own day range, its
    # previous close the stored 245.81
    mrna = {"c": 182.81, "d": -63.0, "dp": -25.6296, "h": 241.09, "l": 180.89, "o": 240.125, "pc": 245.81, "basis": "delayed"}
    assert live_quote_contradiction(mrna, 245.81) is None
    assert live_price_outliers({"MRNA": mrna}, {"MRNA": 245.81}, acted=set()) == []
    # a wrong last price: outside the quote's own range
    assert live_price_outliers({"MRNA": {**mrna, "c": 18.28}}, {"MRNA": 245.81}, acted=set()) == [
        "MRNA: delayed 18.28 against the last close 245.81 (-93%), outside its own day range 180.89 to 241.09"]
    # a quote for another session or another security: its previous close is not the stored close
    other = {"c": 50.0, "h": 52.0, "l": 49.0, "pc": 51.0}
    assert live_price_outliers({"X": other}, {"X": 100.0}, acted=set()) == [
        "X: delayed 50.00 against the last close 100.00 (-50%), its previous close 51.00 is not the stored close"]
    assert live_quote_contradiction({**mrna, "pc": 245.81 * 1.004}, 245.81) is None                    # within the tolerance
    assert live_quote_contradiction({**mrna, "h": None}, 245.81) == "no day range or previous close in the quote to support it"
    # a corporate action still exempts it, and a move under the threshold is never checked
    assert live_price_outliers({"X": other}, {"X": 100.0}, acted={"X"}) == []
    assert live_price_outliers({"X": {"c": 90.0}}, {"X": 100.0}, acted=set()) == []


@pytest.mark.asyncio
async def test_the_flag_gates_serving_and_the_admin_token_previews_it(monkeypatch):
    from httpx import ASGITransport, AsyncClient
    from app.main import app
    now = datetime.now(timezone.utc)
    sym = "MU"
    monkeypatch.setattr(settings, "live_data_enabled", False)
    monkeypatch.setattr(settings, "admin_token", "preview-token-for-this-test")
    monkeypatch.setattr(L, "market_open", lambda now: True)                 # the test runs at any hour: a market-hours rule
    monkeypatch.setattr(L, "latest_session", lambda now: now.astimezone(NY).date())
    rec = {"c": 123.45, "d": 1.0, "dp": 0.8, "h": 125.0, "l": 122.0, "o": 123.0, "pc": 122.45, "t": int(now.timestamp()) - 60, "basis": "delayed", "delay_minutes": 15, "source": "cboe_one_delayed", "captured_at": now.isoformat()}
    async with ScriptSessionLocal() as s:
        from app.services.system_metadata_service import set_value
        await set_value(s, L.QUOTES_KEY, json.dumps({"captured_at": now.isoformat(), "quotes": {sym: rec}}))
        await s.commit()
    L._cache.clear()
    try:
        async with ScriptSessionLocal() as s:
            assert await L.served_quote(s, sym, admin=False) is None                                      # off for everyone else
            q = await L.served_quote(s, sym, admin=True)
            assert q["c"] == 123.45 and q["basis"] == "delayed" and q["delay_minutes"] == 15
            stale = {**rec, "t": int(now.timestamp()) - 40 * 60}
            await set_value(s, L.QUOTES_KEY, json.dumps({"captured_at": now.isoformat(), "quotes": {sym: stale}}))
            await s.commit()
            L._cache.clear()
            fallback = await L.served_quote(s, sym, admin=True)
            assert fallback["basis"] == "close" and fallback.get("delay_minutes") is None                 # stale in market hours: the stored close, dated as a close
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            r = await c.get(f"/api/v1/tickers/quotes?symbols={sym}", headers={"X-Admin-Token": "preview-token-for-this-test"})
            assert r.status_code == 200 and r.json()[0]["quote_basis"] == "close"
            await set_value(s, L.QUOTES_KEY, json.dumps({"captured_at": now.isoformat(), "quotes": {sym: rec}})); await s.commit(); L._cache.clear()
            r = await c.get(f"/api/v1/tickers/quotes?symbols={sym}", headers={"X-Admin-Token": "preview-token-for-this-test"})
            assert r.json()[0]["quote_basis"] == "delayed" and r.json()[0]["delay_minutes"] == 15 and r.json()[0]["price"] == 123.45
            monkeypatch.setattr(settings, "live_data_enabled", True)
            r = await c.get(f"/api/v1/tickers/quotes?symbols={sym}")
            assert r.json()[0]["quote_basis"] == "delayed"                                             # the flag on: every visitor
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM system_metadata WHERE key = :k"), {"k": L.QUOTES_KEY})
            await s.commit()
        L._cache.clear()
