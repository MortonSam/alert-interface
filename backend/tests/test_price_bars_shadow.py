"""Shadow bars: fetched by record id for the days each record still lacks; adjusted from stored factors, not stale adj_* columns."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts import refresh
from app.scripts.shadow_intrinio import frame, stored_bars
from app.scripts.shadow_price_bars import STEP_LABEL, _rows, _upsert
from app.services.price_bars_shadow import BENCHMARKS, OVERLAP_DAYS, Fetch, adjusted_frame, plan_fetches
from app.services.security_records import CURRENT, PREDECESSOR, STORED_HISTORY, STORED_START, Record

TODAY = date(2026, 10, 1)

# Intrinio bars for NVDA around its 10:1 split (2024-06-10) and a $0.01 dividend (2024-06-11), as fetched 2026-10-01
NVDA = [
    {"date": "2024-06-05", "open": 1222.0, "high": 1230.0, "low": 1210.0, "close": 1224.4, "volume": 52840178, "adj_close": 122.0919, "factor": 1.0, "split_ratio": 1.0, "dividend": 0.0},
    {"date": "2024-06-06", "open": 1210.0, "high": 1230.0, "low": 1205.0, "close": 1209.98, "volume": 66469619, "adj_close": 120.654, "factor": 1.0, "split_ratio": 1.0, "dividend": 0.0},
    {"date": "2024-06-07", "open": 1200.0, "high": 1215.0, "low": 1195.0, "close": 1208.88, "volume": 41238580, "adj_close": 120.5443, "factor": 1.0, "split_ratio": 1.0, "dividend": 0.0},
    {"date": "2024-06-10", "open": 120.4, "high": 123.1, "low": 117.0, "close": 121.79, "volume": 308134791, "adj_close": 121.4437, "factor": 0.1, "split_ratio": 0.1, "dividend": 0.0},
    {"date": "2024-06-11", "open": 121.8, "high": 122.9, "low": 118.0, "close": 120.91, "volume": 222551158, "adj_close": 120.5761, "factor": 0.9999178914525, "split_ratio": 1.0, "dividend": 0.01},
    {"date": "2024-06-12", "open": 123.0, "high": 126.9, "low": 122.0, "close": 125.2, "volume": 299595001, "adj_close": 124.8543, "factor": 1.0, "split_ratio": 1.0, "dividend": 0.0},
]
# the series ends 2026-10-01 with further dividends; within this window the adjusted series is raw x later factors x a
# constant tail, so the ratio of any two adjusted closes must match Intrinio's.


def rec(symbol, sid, start, end=None, role=CURRENT, source="intrinio"):
    return Record(symbol, sid, "f", None, None, start, end, role, source)


# ── adjusted_frame ────────────────────────────────────────────────────────────

def test_adjusted_closes_from_raw_and_factors_keep_intrinio_s_ratios_across_the_split_and_dividend():
    df = adjusted_frame(NVDA)
    ours = df["Close"] / df["Close"].iloc[-1]
    theirs = [b["adj_close"] / NVDA[-1]["adj_close"] for b in NVDA]
    for o, t in zip(ours, theirs):
        assert abs(o - t) < 1e-4, (o, t)
    assert abs(df["Close"].loc["2024-06-07"] - 1208.88 * 0.1 * 0.9999178914525) < 1e-6   # raw x every later factor
    assert df["Close"].loc["2024-06-12"] == 125.2                                        # nothing later: raw
    assert df["Volume"].loc["2024-06-07"] == 412385800                                   # shares split-adjusted, not dividend-adjusted
    assert df["Volume"].loc["2024-06-10"] == 308134791
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]


def test_adjusted_frame_has_the_live_frame_s_shape_and_is_empty_on_no_rows():
    live = frame([{**b, "adj_open": b["open"], "adj_high": b["high"], "adj_low": b["low"], "adj_volume": b["volume"]} for b in NVDA])
    stored = adjusted_frame(NVDA)
    assert list(live.columns) == list(stored.columns) and list(live.index) == list(stored.index)
    assert adjusted_frame([]).empty


# ── plan_fetches ──────────────────────────────────────────────────────────────

def test_a_fresh_symbol_fetches_its_current_record_from_the_stored_start():
    plan = plan_fetches({"AAPL": [rec("AAPL", "sec_a", date(1980, 12, 12))]}, {}, TODAY)
    assert plan == [Fetch("AAPL", rec("AAPL", "sec_a", date(1980, 12, 12)), STORED_START, TODAY)]


def test_an_incremental_fetch_starts_a_few_days_before_the_last_stored_bar():
    plan = plan_fetches({"AAPL": [rec("AAPL", "sec_a", date(1980, 12, 12))]}, {"AAPL": date(2026, 9, 30)}, TODAY)
    assert plan[0].start == date(2026, 9, 30 - OVERLAP_DAYS) and plan[0].end == TODAY


def test_predecessor_and_current_records_are_fetched_by_their_own_ids_over_their_own_spans_then_the_predecessor_rests():
    tel = [rec("TEL", "sec_gAD5Jy", date(2007, 6, 14), date(2024, 9, 27), PREDECESSOR), rec("TEL", "sec_zq8bAk", date(2024, 9, 30))]
    first = plan_fetches({"TEL": tel}, {}, TODAY)
    assert [(f.record.intrinio_security_id, f.start, f.end) for f in first] == [
        ("sec_gAD5Jy", STORED_START, date(2024, 9, 27)), ("sec_zq8bAk", date(2024, 9, 30), TODAY)]
    later = plan_fetches({"TEL": tel}, {"TEL": date(2026, 9, 30)}, TODAY)
    assert [f.record.intrinio_security_id for f in later] == ["sec_zq8bAk"]


def test_a_closed_record_whose_bars_reach_its_end_fetches_nothing_more():
    """A delisted ticker's record ends on its last session; once that bar is stored the nightly sends no request for it."""
    avb = [rec("AVB", "sec_NX6ajg", date(1994, 3, 11), date(2026, 8, 14))]
    assert [(f.start, f.end) for f in plan_fetches({"AVB": avb}, {}, TODAY)] == [(STORED_START, date(2026, 8, 14))]
    assert plan_fetches({"AVB": avb}, {"AVB": date(2026, 8, 14)}, TODAY) == []
    assert [f.start for f in plan_fetches({"AVB": avb}, {"AVB": date(2026, 8, 12)}, TODAY)] == [date(2026, 8, 12 - OVERLAP_DAYS)]


def test_a_stored_history_row_fetches_nothing_and_a_record_ending_before_the_window_fetches_nothing():
    psky = [rec("PSKY", None, STORED_START, date(2025, 8, 6), STORED_HISTORY, "stored"), rec("PSKY", "sec_z9qYDq", date(2025, 8, 7))]
    plan = plan_fetches({"PSKY": psky}, {}, TODAY)
    assert [(f.record.intrinio_security_id, f.start) for f in plan] == [("sec_z9qYDq", date(2025, 8, 7))]
    old = [rec("X", "sec_old", date(2000, 1, 1), date(2010, 1, 1), PREDECESSOR), rec("X", "sec_new", date(2010, 1, 2))]
    assert [f.record.intrinio_security_id for f in plan_fetches({"X": old}, {}, TODAY)] == ["sec_new"]


# ── the nightly step is wired ─────────────────────────────────────────────────

def test_the_step_runs_after_security_records_and_before_validate_with_a_timeout():
    labels = [label for label, _ in refresh.STEPS]
    assert labels.index("Security records (Intrinio)") < labels.index(STEP_LABEL) < labels.index("Validate data")
    assert refresh.STEP_TIMEOUTS[STEP_LABEL] >= 1200
    assert BENCHMARKS == ("SPY",)


# ── rows upsert on (symbol, date) and read back adjusted ─────────────────────

@pytest.mark.asyncio
async def test_bars_upsert_by_symbol_and_date_and_read_back_adjusted_from_the_stored_factors():
    sym = "ZZBARS"
    fetch = Fetch(sym, rec(sym, "sec_zz", date(2024, 1, 1)), date(2024, 6, 5), date(2024, 6, 12))
    now = datetime.now(timezone.utc)
    try:
        bars = [{**b, "adj_open": b["open"], "adj_high": b["high"], "adj_low": b["low"], "adj_volume": b["volume"]} for b in NVDA]
        rows = _rows(fetch, bars, None, now)
        assert len(rows) == 6 and rows[3]["factor"] == 0.1 and rows[3]["intrinio_security_id"] == "sec_zz"
        assert await _upsert(rows) == 6
        rows[-1]["close"] = 126.0                             # a corrected bar refetched the next night replaces the row
        assert await _upsert(rows[-2:]) == 2
        async with ScriptSessionLocal() as s:
            n, last = (await s.execute(text("select count(*), max(close) filter (where date = '2024-06-12') from price_bars_shadow where symbol = :s"), {"s": sym})).one()
        assert (n, last) == (6, 126.0)
        df = await stored_bars(sym)
        assert len(df) == 6 and abs(df["Close"].loc["2024-06-07"] - 1208.88 * 0.1 * 0.9999178914525) < 1e-6
        assert _rows(Fetch(sym, fetch.record, date(2024, 6, 10), date(2024, 6, 10)), bars, None, now)[0]["date"] == date(2024, 6, 10)   # clipped to the fetch span
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": sym})
            await s.commit()
