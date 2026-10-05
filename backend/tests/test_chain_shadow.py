"""Intrinio's EOD chain beside the courier's: scheduled on the New York clock, stored in the courier's shape under its own
key, compared on the front expiry, judged over a week."""
import json
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts import refresh
from app.scripts.shadow_option_chains import STEP_LABEL
from app.scripts.validate_data import CHECKS, ERROR, PASS, WARN, check_chain_shadow, run_checks
from app.services import chain_store
from app.scripts.chain_courier import capture_stamp
from app.services.chain_shadow import (IMPLIED_MOVE_TOLERANCE_PP, INTRADAY_NOTE, MIN_NIGHTS, PER_TICKER_COLUMNS, SCHEDULE_CLOCK, SCHEDULED_LOCAL,
                                       captured_after_close, clock_fields, compare_front, criteria_failures, evaluate, expected_session,
                                       front_expiration, night_totals, to_stored_chain, wait_seconds)

NY = ZoneInfo("America/New_York")


# ── schedule: the New York clock, never UTC ───────────────────────────────────

def test_the_schedule_is_a_local_time_on_the_new_york_clock_and_the_wait_follows_daylight_saving():
    assert (SCHEDULED_LOCAL.hour, SCHEDULED_LOCAL.minute, SCHEDULE_CLOCK) == (3, 5, "America/New_York")
    summer = datetime(2026, 7, 10, 6, 20, tzinfo=timezone.utc)      # 02:20 EDT: 45 min early
    winter = datetime(2026, 12, 10, 6, 20, tzinfo=timezone.utc)     # 01:20 EST: 105 min early, same UTC instant of day
    assert wait_seconds(summer) == 45 * 60
    assert wait_seconds(winter) == 105 * 60
    assert wait_seconds(datetime(2026, 7, 10, 7, 6, tzinfo=timezone.utc)) == 0      # 03:06 EDT: passed, run now


def test_the_outcome_names_the_clock_the_local_time_and_the_offset():
    f = clock_fields(datetime(2026, 12, 10, 8, 5, 30, tzinfo=timezone.utc), waited=120)
    assert f["clock"] == "America/New_York" and f["scheduled_local"] == "03:05"
    assert f["started_local"] == "2026-12-10T03:05:30-05:00" and f["utc_offset"] == "-05:00" and f["tzname"] == "EST" and f["waited_seconds"] == 120
    assert "ran_early_reason" not in f
    assert clock_fields(datetime(2026, 7, 10, 7, 5, tzinfo=timezone.utc), 0, "too early")["ran_early_reason"] == "too early"


def test_the_expected_session_is_the_last_close_on_the_new_york_clock():
    assert expected_session(datetime(2026, 10, 3, 3, 5, tzinfo=NY)) == date(2026, 10, 2)     # Saturday 03:05: Friday's close
    assert expected_session(datetime(2026, 10, 2, 3, 5, tzinfo=NY)) == date(2026, 10, 1)     # Friday 03:05: Thursday's close
    assert expected_session(datetime(2026, 10, 2, 18, 0, tzinfo=NY)) == date(2026, 10, 2)    # Friday evening: Friday's close
    assert expected_session(datetime(2026, 9, 8, 3, 5, tzinfo=NY)) == date(2026, 9, 4)       # Tuesday after Labor Day: Friday's close


# ── storage: the courier's shape, quote stamps kept, the source named ────────

def contract(kind, strike, bid, ask, last, iv=0.5, bid_t="2026-10-01T20:00:01Z", ask_t="2026-10-01T20:00:02Z", last_t="2026-10-01T19:59:00Z"):
    return {"option": {"strike": strike, "type": kind, "expiration": "2026-10-09"},
            "prices": {"date": "2026-10-01", "close_bid": bid, "close_ask": ask, "close": last, "mark": (bid + ask) / 2, "implied_volatility": iv,
                       "volume": 10, "open_interest": 100, "delta": 0.5, "close_bid_time": bid_t, "close_ask_time": ask_t, "close_time": last_t}}


RECORD = {"id": "rec-1", "intrinio_security_id": "sec_x", "intrinio_ticker": "MU"}


def test_to_stored_chain_keeps_quote_timestamps_sets_the_eod_date_and_names_the_source():
    chain = to_stored_chain([contract("call", 100, 5.0, 5.4, 5.2), contract("put", 100, 4.0, 4.4, 4.2, last_t="2026-10-01T20:00:09Z")],
                            "2026-10-09", date(2026, 10, 1), 101.5, "price_bars_shadow", RECORD, datetime(2026, 10, 2, 7, 5, tzinfo=timezone.utc), date(2026, 10, 1))
    assert chain["chain_source"] == "intrinio" and chain["chain_last_trade"] == "2026-10-01" and chain["expiration"] == "2026-10-09"
    assert chain["underlying_price"] == 101.5 and chain["underlying_price_source"] == "price_bars_shadow"
    assert chain["calls"][0]["bid_time"] == "2026-10-01T20:00:01Z" and chain["puts"][0]["last_time"] == "2026-10-01T20:00:09Z"
    assert chain["quote_times"] == {"earliest": "2026-10-01T19:59:00Z", "latest": "2026-10-01T20:00:09Z"}
    assert {"strike", "bid", "ask", "lastPrice", "volume", "openInterest", "impliedVolatility"} <= set(chain["calls"][0])   # the courier's fields
    assert chain["security_record_id"] == "rec-1" and chain["intrinio_ticker"] == "MU"
    assert chain["late"] is False and chain["expected_session"] == "2026-10-01"
    late = to_stored_chain([contract("call", 100, 5.0, 5.4, 5.2)], "2026-10-09", date(2026, 9, 30), None, None, RECORD, datetime.now(timezone.utc), date(2026, 10, 1))
    assert late["late"] is True and late["underlying_price"] is None


def test_chain_keys_and_sources_are_told_apart_and_the_courier_dict_names_its_source():
    assert chain_store.chain_key("MU", "2026-10-09") == "chain:MU:2026-10-09"
    assert chain_store.chain_key("MU", "2026-10-09", chain_store.INTRINIO) == "intrinio_chain:MU:2026-10-09"
    c = chain_store.build_courier_chain([], [], "2026-10-09", "2026-10-01", 100.0, "2026-10-01T16:06:12-04:00")
    assert c["chain_source"] == "courier" and chain_store.chain_source(c) == "courier" and c["chain_captured_at"] == "2026-10-01T16:06:12-04:00"
    assert chain_store.build_courier_chain([], [], "2026-10-09", "2026-10-01", 100.0)["chain_captured_at"] is None   # a pre-stamp courier
    assert chain_store.chain_source({"calls": []}) == "courier"            # stored before the field existed
    assert chain_store.chain_source({"chain_source": "intrinio"}) == "intrinio"


@pytest.mark.asyncio
async def test_put_chain_refuses_a_chain_whose_source_does_not_match_the_key():
    async with ScriptSessionLocal() as s:
        with pytest.raises(ValueError):
            await chain_store.put_chain(s, "ZZX", "2026-10-09", {"chain_source": "courier"}, chain_store.INTRINIO)


# ── comparison on the front expiry ───────────────────────────────────────────

def side(rows):
    return [{"strike": k, "bid": b, "ask": a, "lastPrice": (b + a) / 2} for k, b, a in rows]


COURIER = {"expiration": "2026-10-09", "chain_last_trade": "2026-10-01", "underlying_price": 100.0, "chain_captured_at": "2026-10-01T16:06:12-04:00",
           "calls": side([(95, 6.0, 6.4), (100, 2.0, 2.4), (105, 0.5, 0.7)]),
           "puts": side([(95, 0.4, 0.6), (100, 1.8, 2.2), (105, 5.0, 5.4)])}


def test_front_expiration_is_the_nearest_after_the_chain_date():
    assert front_expiration(["2026-10-02", "2026-10-09", "2026-09-30"], "2026-10-01") == "2026-10-02"
    assert front_expiration(["2026-09-30"], "2026-10-01") is None


def test_identical_chains_compare_clean_and_a_strike_missing_on_one_side_is_counted():
    same = {**COURIER, "chain_source": "intrinio", "late": False}
    f = compare_front(COURIER, same)
    assert f["courier_only_strikes"] == [] and f["intrinio_only_strikes"] == 0 and f["shared_contracts"] == 6
    assert f["mid_median"] == 0 and f["mid_mean_abs"] == 0
    assert f["implied_move_courier_pct"] == f["implied_move_intrinio_pct"] == 4.2        # (2.2 + 2.0) / 100
    assert f["atm_strike"] == 100 and f["atm_call_mid_courier"] == f["atm_call_mid_intrinio"] == 2.2 and f["atm_put_mid_intrinio"] == 2.0
    assert list(f) == PER_TICKER_COLUMNS
    # Intrinio lacks the 105 strike and adds a 110; its mids sit a cent higher
    intr = {"expiration": "2026-10-09", "chain_last_trade": "2026-10-01", "underlying_price": 100.0, "late": False,
            "calls": side([(95, 6.01, 6.41), (100, 2.01, 2.41), (110, 0.1, 0.2)]), "puts": side([(95, 0.41, 0.61), (100, 1.81, 2.21), (110, 9.0, 9.4)])}
    g = compare_front(COURIER, intr)
    assert g["courier_only_strikes"] == [105.0] and g["intrinio_only_strikes"] == 1 and g["shared_contracts"] == 4
    assert g["mid_median"] == 0.01 and g["mid_mean_abs"] == 0.01
    assert abs(g["implied_move_intrinio_pct"] - 4.22) < 1e-9
    assert g["atm_call_mid_intrinio"] == 2.21


def test_the_courier_capture_is_stamped_on_the_new_york_clock_and_carried_into_the_row():
    stamp = capture_stamp(datetime(2026, 10, 5, 20, 6, 12, tzinfo=timezone.utc))
    assert stamp == "2026-10-05T16:06:12-04:00"
    assert captured_after_close(stamp) is True
    assert captured_after_close("2026-10-01T14:31:03-04:00") is False          # the old 2:30pm schedule
    assert captured_after_close("2026-10-01T20:00:00+00:00") is True          # 16:00 New York exactly, in UTC
    assert captured_after_close(None) is None and captured_after_close("not a time") is None
    f = compare_front(COURIER, {**COURIER, "late": False})
    assert f["chain_captured_at"] == "2026-10-01T16:06:12-04:00" and f["courier_after_close"] is True
    g = compare_front({**COURIER, "chain_captured_at": "2026-10-01T14:31:03-04:00"}, {**COURIER, "late": False})
    assert g["courier_after_close"] is False


def test_an_intraday_capture_is_not_judged_on_implied_move_and_a_night_of_them_says_so():
    close_row = compare_front(COURIER, {**COURIER, "late": False})
    intraday_row = compare_front({**COURIER, "chain_captured_at": "2026-10-01T14:31:03-04:00"}, {**COURIER, "underlying_price": 90.0, "late": False})
    unstamped_row = compare_front({**COURIER, "chain_captured_at": None}, {**COURIER, "late": False})
    t = night_totals("2026-10-01", {"A": close_row, "B": intraday_row, "C": unstamped_row}, [])
    assert (t["implied_move_judged"], t["implied_move_intraday"], t["implied_move_within_tolerance"], t["implied_move_share"]) == (1, 2, 1, 1.0)
    assert criteria_failures(t) == []
    all_intraday = night_totals("2026-10-01", {"B": intraday_row, "C": unstamped_row}, [])
    assert all_intraday["implied_move_judged"] == 0 and all_intraday["implied_move_share"] is None
    assert criteria_failures(all_intraday) == []                                  # intraday: not judged, not failed
    v = evaluate([all_intraday])
    assert v.level == "warn" and INTRADAY_NOTE in v.rows[0] and "at or after 16:00 New York" in v.rows[0]
    bad = night_totals("2026-10-01", {"A": compare_front(COURIER, {**COURIER, "underlying_price": 90.0, "late": False})}, [])
    assert any("closing-capture tickers" in f and "below 95%" in f for f in criteria_failures(bad))


def test_the_intrinio_implied_move_uses_its_own_spot_and_is_absent_without_one():
    intr = {**COURIER, "underlying_price": None, "late": False}
    f = compare_front(COURIER, intr)
    assert f["implied_move_intrinio_pct"] is None and f["implied_move_courier_pct"] == 4.2
    t = night_totals("2026-10-01", {"MU": f}, [])
    assert t["implied_move_judged"] == 1 and t["implied_move_within_tolerance"] == 0 and t["implied_move_share"] == 0


# ── the week's verdict ────────────────────────────────────────────────────────

def clean_night(d, **over):
    t = {"date": d, "tickers_both": 400, "tickers_missing_intrinio": 0, "missing_intrinio": [], "tickers_with_courier_only_strikes": [],
         "courier_only_strikes": 0, "intrinio_only_strikes": 12, "implied_move_judged": 400, "implied_move_intraday": 0,
         "implied_move_within_tolerance": 392, "implied_move_share": 0.98,
         "mid_median_of_medians": 0.0, "mid_mean_abs_mean": 0.02, "late": []}
    t.update(over)
    return t


def test_warn_until_seven_nights_then_pass_when_every_night_meets_the_criteria():
    days = [f"2026-10-{d:02d}" for d in range(1, 8)]
    v = evaluate([clean_night(d) for d in days[:6]])
    assert v.level == "warn" and "6 of 7" in v.message and "tonight passes" in v.message
    v = evaluate([clean_night(d) for d in days])
    assert v.level == "pass" and "2026-10-01..2026-10-07" in v.message
    assert evaluate([]).level == "warn"


def test_each_retirement_criterion_fails_the_week_on_its_own():
    days = [f"2026-10-{d:02d}" for d in range(1, 8)]
    base = [clean_night(d) for d in days]
    for over, phrase in (
        ({"courier_only_strikes": 3, "tickers_with_courier_only_strikes": ["MU"]}, "courier strike(s) absent on the Intrinio side"),
        ({"implied_move_within_tolerance": 370, "implied_move_share": 0.925}, "below 95%"),
        ({"tickers_missing_intrinio": 2, "missing_intrinio": ["CAT", "MU"]}, "no Intrinio chain"),
        ({"late": ["MU"]}, "published late"),
    ):
        nights = base[:-1] + [clean_night(days[-1], **over)]
        v = evaluate(nights)
        assert v.level == "error" and any(phrase in r for r in v.rows), phrase
    assert criteria_failures(clean_night("2026-10-01", tickers_both=0)) == ["2026-10-01: no ticker had both chains"]
    assert f"{IMPLIED_MOVE_TOLERANCE_PP}" == "0.3" and MIN_NIGHTS == 7


# ── wiring ────────────────────────────────────────────────────────────────────

def test_the_step_runs_before_validate_with_room_to_wait_and_the_check_is_registered():
    labels = [label for label, _ in refresh.STEPS]
    assert labels.index(STEP_LABEL) < labels.index("Validate data")
    assert refresh.STEP_TIMEOUTS[STEP_LABEL] > 3 * 3600
    assert check_chain_shadow in CHECKS


# ── a synthetic night: the step records it, the check judges it ──────────────

@pytest.mark.asyncio
async def test_a_synthetic_night_with_a_missing_strike_is_recorded_by_the_step_and_judged_by_the_check():
    from app.scripts.shadow_option_chains import record_night
    sym, night = "ZZSHD", "2099-01-02"
    intr = {"expiration": "2026-10-09", "chain_last_trade": night, "underlying_price": 100.0, "chain_source": "intrinio", "late": False,
            "calls": side([(95, 6.0, 6.4), (100, 2.0, 2.4)]), "puts": side([(95, 0.4, 0.6), (100, 1.8, 2.2)])}     # no 105 strike
    courier = {**COURIER, "chain_last_trade": night, "chain_source": "courier"}
    try:
        totals = await record_night(night, {sym: compare_front(courier, intr)}, ["ZZMISS"])
        assert totals["courier_only_strikes"] == 1 and totals["tickers_missing_intrinio"] == 1
        result = (await run_checks([check_chain_shadow]))[0]
        assert result.level in (WARN, ERROR), result.message
        async with ScriptSessionLocal() as s:
            raw = (await s.execute(text("select value from system_metadata where key = :k"), {"k": f"chain_shadow:{night}"})).scalar()
            outcome = json.loads((await s.execute(text("select value from system_metadata where key = 'step_outcomes'"))).scalar())
        stored = json.loads(raw)
        assert stored["per_ticker"][sym]["courier_only_strikes"] == [105.0] and sym in stored["totals"]["tickers_with_courier_only_strikes"]
        comp = outcome[STEP_LABEL]["comparison"]
        assert comp["per_ticker_columns"] == PER_TICKER_COLUMNS
        assert comp["per_ticker"][sym][PER_TICKER_COLUMNS.index("courier_only_strikes")] == 1
        assert any("courier strike(s) absent" in r or "no Intrinio chain" in r for r in result.rows)
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("delete from system_metadata where key = :k"), {"k": f"chain_shadow:{night}"})
            await s.commit()


def test_the_check_is_one_query_over_stored_nights_and_coverage_is_one_query_over_chain_dates():
    import inspect
    from app.scripts.validate_data import check_chain_coverage, fresh_chain_symbols
    assert inspect.getsource(check_chain_shadow).count("await session.execute") == 1
    assert inspect.getsource(check_chain_coverage).count("await session.execute") == 2       # the active tickers, then every chain date
    rows = [("chain:MU:2026-10-09", date.today().isoformat()), ("chain:MU:2027-01-15", "2026-01-02"), ("chain:OLD:2026-10-09", "2026-01-02"), ("junk", None)]
    assert fresh_chain_symbols(rows) == {"MU"}
