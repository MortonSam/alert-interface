"""Automation block B: the cadence record, the dated ledger price, index-member medians, fact reasons, first-bar floors,
and the trading calendar checked against SPY's bars."""
import inspect
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts import repair_fomc_dates, seed_fomc_reactions, seed_sp500
from app.scripts.validate_data import CHECKS, ERROR, PASS, calendar_mismatches, check_calendar_matches_spy_bars, check_fomc_before_first_bar, run_checks
from app.services import cadence as cad
from app.services import chain_store
from app.services.ivy_rule import ivy_rule


def test_the_cadence_record_names_the_nightly_on_the_new_york_clock_and_claims_no_quote_delay():
    c = cad.cadence(datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc))
    assert c["nightly"] == {"per_day": 1, "local_time": "02:30", "clock": "America/New_York", "utc_today": "06:30Z"}   # EDT
    assert cad.nightly_local_time(datetime(2026, 12, 10, 12, 0, tzinfo=timezone.utc)) == "02:30"                     # EST: the local time never moves
    assert cad.cadence(datetime(2026, 12, 10, 12, 0, tzinfo=timezone.utc))["nightly"]["utc_today"] == "07:30Z"
    assert c["options"] == {"per_day": 1, "captured_local": "16:05", "clock": "America/New_York", "fresh_sessions": chain_store.CHAIN_FRESH_TRADING_DAYS}
    assert c["quotes"]["source"] == "Finnhub" and c["quotes"]["delay_statement"] is None and c["quotes"]["delay_checked"] == "2026-10-05"
    assert ivy_rule()["cadence"]["nightly"]["clock"] == "America/New_York"


def test_the_ledger_price_goes_through_the_quote_freshness_check_and_is_dated():
    src = open(__import__("app.routers.discover", fromlist=["latest_pick"]).__file__).read()
    assert "state = assess_quote(cp, ts)" in src and "price_as_of = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()" in src
    assert "price_as_of=price_as_of,\n            quote_reason=quote_reason," in src
    assert 'Ticker.index_member.is_(True),          # "the S&P 500 median" means index members' in src


@pytest.mark.asyncio
async def test_index_membership_follows_the_constituent_list_each_night():
    syms = ["ZZIM1", "ZZIM2"]
    try:
        async with ScriptSessionLocal() as s:
            for sym in syms:
                await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, index_member) VALUES (gen_random_uuid(), :s, 'Index test', true, true) ON CONFLICT (symbol) DO NOTHING"), {"s": sym})
            await s.commit()
        async with ScriptSessionLocal() as s:
            active = (await s.execute(text("SELECT symbol FROM tickers WHERE is_active AND symbol NOT IN ('ZZIM2')"))).scalars().all()
            cleared = await seed_sp500.mark_index_members(s, list(active))
            await s.commit()
            flags = dict((await s.execute(text("SELECT symbol, index_member FROM tickers WHERE symbol = ANY(:s)"), {"s": syms})).all())
        assert cleared == ["ZZIM2"] and flags == {"ZZIM1": True, "ZZIM2": False}
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM tickers WHERE symbol = ANY(:s)"), {"s": syms})
            await s.commit()


def test_the_build_fact_block_says_why_a_fact_is_absent():
    from app.routers.thesis import fact_absence_reasons
    r = fact_absence_reasons(None, None, None, None, "2026-10-09", "2026-10-01")
    assert r["atm_iv_pct"] == "no implied volatility on the ATM strike of the 2026-10-09 chain (options data as of 2026-10-01)"
    assert r["rv_rank"].startswith("no realized-volatility snapshot within 7 days") and r["iv_rv_spread_pp"] == "needs implied volatility and realized volatility"
    assert fact_absence_reasons(0.5, 0.3, 40.0, 20.0, "2026-10-09", "2026-10-01") == {}
    assert fact_absence_reasons(0.5, None, None, None, None, None)["iv_rv_spread_pp"] == "needs realized volatility"


def test_listing_overrides_are_gone_and_floors_come_from_the_first_stored_bar():
    import app.constants as constants
    assert not hasattr(constants, "LISTING_DATE_OVERRIDES")
    for mod in (seed_fomc_reactions, repair_fomc_dates):
        src = inspect.getsource(mod)
        assert "LISTING_DATE_OVERRIDES" not in src and "first_bar_dates" in src
    assert check_fomc_before_first_bar in CHECKS and check_calendar_matches_spy_bars in CHECKS
    from app.scripts import validate_data
    assert not hasattr(validate_data, "check_fomc_pre_listing")


@pytest.mark.asyncio
async def test_first_bar_floors_are_one_query_and_match_the_store():
    from app.services import price_bars
    async with ScriptSessionLocal() as s:
        floors = await price_bars.first_bar_dates(s, ["SW", "TKO", "AAPL", "ZZNONE"])
        sw = (await s.execute(text("select min(date) from price_bars_shadow where symbol = 'SW'"))).scalar()
    assert floors.get("SW") == sw and "ZZNONE" not in floors
    assert price_bars.first_bar_dates_sync(["SW"]) == {"SW": sw}


def test_calendar_mismatches_name_both_directions_and_chain_freshness_skips_holidays():
    bars = {date(2026, 9, 3), date(2026, 9, 4), date(2026, 9, 8)}                 # Labor Day 2026-09-07 closed
    assert calendar_mismatches(bars, date(2026, 9, 3), date(2026, 9, 8)) == []
    assert calendar_mismatches(bars | {date(2026, 9, 7)}, date(2026, 9, 7), date(2026, 9, 7)) == ["2026-09-07: SPY has a bar but the calendar calls it closed"]
    assert calendar_mismatches(set(), date(2026, 9, 8), date(2026, 9, 8)) == ["2026-09-08: the calendar calls it a session but SPY has no bar"]
    # Friday 09-04 to Tuesday 09-08: one session (the Tuesday); the old weekday count said two
    assert chain_store.trading_days_since("2026-09-04", date(2026, 9, 8)) == 1
    assert chain_store.trading_days_since("2026-09-02", date(2026, 9, 8)) == 3      # 09-03, 09-04, 09-08
    assert not chain_store.is_fresh("2026-09-02", today=date(2026, 9, 8))           # three sessions: past the two-session limit
    assert chain_store.is_fresh("2026-09-03", today=date(2026, 9, 8))               # 09-04 and 09-08: the holiday does not count


@pytest.mark.asyncio
async def test_the_calendar_check_passes_on_the_stored_spy_bars():
    r = (await run_checks([check_calendar_matches_spy_bars]))[0]
    assert r.level in (PASS, ERROR), r.message
    if r.level == ERROR:
        pytest.fail("calendar disagrees with SPY bars: " + "; ".join(r.rows[:5]))

# shares the ZZCCL and ZZNONE symbols with the other files of this group: one xdist worker runs them (scripts/push_window.py runs pytest -n auto --dist loadgroup)
pytestmark = pytest.mark.xdist_group(name="calendar_and_bars")
