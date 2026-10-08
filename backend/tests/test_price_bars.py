"""Every daily price series reads the stored shadow bars: adjusted from factors, sliced by date, raw close for settlement;
stored_history rows are kept; the recompute classifies and plans; the source checks hold."""
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.models.enums import EventType
from app.models.historical_reaction import PRICE_SOURCES, SOURCE_INTRINIO, SOURCE_STORED_HISTORY
from app.scripts import compute_rv_ranks, seed_fomc_reactions, seed_historical_reactions
from app.scripts.compute_analyst_reactions import _fetch_history_sync
from app.scripts.recompute_reactions_intrinio import STEP_LABEL, VALUE_KEYS, classify, plan_update
from app.scripts.validate_data import CHECKS, ERROR, PASS, WARN, check_reaction_source_consistency, check_reaction_source_coverage, run_checks
from app.services import price_bars

SYM = "ZZPB"
# a 10:1 split on the 4th day and a dividend on the 5th, like NVDA June 2024
BARS = [("2024-06-05", 1222.0, 1224.4, 52840178, 1.0, 1.0), ("2024-06-06", 1210.0, 1209.98, 66469619, 1.0, 1.0), ("2024-06-07", 1200.0, 1208.88, 41238580, 1.0, 1.0),
        ("2024-06-10", 120.4, 121.79, 308134791, 0.1, 0.1), ("2024-06-11", 121.8, 120.91, 222551158, 0.9999178914525, 1.0), ("2024-06-12", 123.0, 125.2, 299595001, 1.0, 1.0)]


async def _put_bars(sym=SYM):
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": sym})
        for d, o, c, v, f, sr in BARS:
            await s.execute(text("""INSERT INTO price_bars_shadow (symbol, date, intrinio_security_id, open, high, low, close, volume, factor, split_ratio, dividend, fetched_at)
                                    VALUES (:s, :d, 'sec_zz', :o, :o, :c, :c, :v, :f, :sr, 0, :t)"""),
                            {"s": sym, "d": date.fromisoformat(d), "o": o, "c": c, "v": v, "f": f, "sr": sr, "t": datetime.now(timezone.utc)})
        await s.commit()


async def _drop_bars(sym=SYM):
    async with ScriptSessionLocal() as s:
        await s.execute(text("DELETE FROM price_bars_shadow WHERE symbol = :s"), {"s": sym})
        await s.commit()


@pytest.mark.asyncio
async def test_bars_are_adjusted_by_later_factors_even_past_the_requested_end_and_the_close_on_a_date_is_raw():
    await _put_bars()
    try:
        df = price_bars.bars_sync(SYM, date(2024, 6, 5), date(2024, 6, 7))          # the split is after the window
        assert list(df.index.date) == [date(2024, 6, 5), date(2024, 6, 6), date(2024, 6, 7)]
        assert abs(df["Close"].iloc[-1] - 1208.88 * 0.1 * 0.9999178914525) < 1e-6   # adjusted like yfinance auto_adjust
        assert df["Volume"].iloc[-1] == 412385800
        assert price_bars.close_on_date_sync(SYM, date(2024, 6, 7)) == 1208.88         # the official close, as traded
        assert price_bars.close_on_date_sync(SYM, "2024-06-08") is None               # a Saturday: no bar, no guess
        async with ScriptSessionLocal() as s:
            assert await price_bars.close_on_date(s, SYM, date(2024, 6, 10)) == 121.79
            adf = await price_bars.bars(s, SYM, date(2024, 6, 10))
        assert len(adf) == 3 and adf["Close"].iloc[-1] == 125.2
        assert price_bars.bars_sync("ZZNONE").empty
    finally:
        await _drop_bars()


@pytest.mark.asyncio
async def test_sparkline_chart_and_bulk_readers_serve_adjusted_closes_from_the_store():
    await _put_bars()
    try:
        today = date(2024, 6, 12)
        pts = price_bars.daily_closes_sync(SYM, "1mo", today)
        assert [p["date"] for p in pts][:2] == ["2024-06-05", "2024-06-06"] and pts[-1]["close"] == 125.2
        chart = price_bars.chart_history_daily_sync(SYM, "5d", today)
        assert chart["start_price"] == chart["history"][0]["close"] and chart["history"][-1]["date"] == "2024-06-12"
        with pytest.raises(ValueError):
            price_bars.chart_history_daily_sync(SYM, "1d")
        assert price_bars.INTRADAY_PERIODS == ("1d", "7d")
        bulk = price_bars.bulk_closes_sync([SYM, "ZZNONE"], date(2024, 6, 1))
        assert set(bulk) == {SYM} and list(bulk[SYM].columns) == ["Close", "Volume"] and len(bulk[SYM]) == 6
        full = price_bars.bulk_bars_sync([SYM], date(2024, 6, 6), date(2024, 6, 7))
        assert list(full[SYM].columns) == ["Open", "High", "Low", "Close", "Volume"] and len(full[SYM]) == 2
        assert abs(full[SYM]["Close"].iloc[-1] - 1208.88 * 0.1 * 0.9999178914525) < 1e-6      # still adjusted by the later split
        single = price_bars.closes_sync(SYM, date(2024, 6, 10))
        assert len(single) == 3 and price_bars.closes_sync("ZZNONE", date(2024, 6, 10)) is None
    finally:
        await _drop_bars()


@pytest.mark.asyncio
async def test_the_seeders_and_rv_read_the_store_not_yahoo():
    await _put_bars()
    try:
        import inspect
        lookback = date(2024, 6, 1)
        for frame in (seed_historical_reactions._fetch_price_history(SYM, lookback), seed_fomc_reactions._fetch_price_sync(SYM), _fetch_history_sync(SYM)):
            assert list(frame.columns) == ["Open", "High", "Low", "Close", "Volume"] and len(frame) == 6
        # RV reads two years back from today, so the 2024 fixture is outside its window: the wiring is checked by source
        assert "price_bars.bulk_closes_sync" in inspect.getsource(compute_rv_ranks._fetch_bulk)
        assert "price_bars.closes_sync" in inspect.getsource(compute_rv_ranks._fetch_single)
        assert compute_rv_ranks._fetch_single("ZZNONE") is None and compute_rv_ranks._fetch_bulk(["ZZNONE"]) == {}
        for mod in (seed_historical_reactions, seed_fomc_reactions, compute_rv_ranks):
            assert "yf.download" not in inspect.getsource(mod) and ".history(" not in inspect.getsource(mod)
        # the session calendar comes from stored SPY bars
        assert len(seed_historical_reactions.load_reference_sessions()) > 1000
    finally:
        await _drop_bars()


# ── stored-history rows are kept and stamped ─────────────────────────────────

@pytest.mark.asyncio
async def test_rows_on_a_stored_history_span_are_found_and_stamped_without_touching_values():
    sym = "ZZSH"
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Stored history test', true) ON CONFLICT (symbol) DO NOTHING"), {"s": sym})
            await s.execute(text("""INSERT INTO security_records (symbol, valid_from, valid_to, role, source, name) VALUES
                                    (:s, '2022-01-26', '2022-02-01', 'stored_history', 'stored', 't'), (:s, '2022-02-02', NULL, 'current', 'intrinio', 't')"""), {"s": sym})
            tid = (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": sym})).scalar()
            for d in ("2022-01-26", "2022-02-02", "2022-05-03"):
                await s.execute(text("""INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, pct_change_1d, computation_version)
                                        VALUES (gen_random_uuid(), :t, 'earnings', :d, 1.5, 3)"""), {"t": tid, "d": date.fromisoformat(d)})
            await s.commit()
        import numpy as np
        sessions = np.array([date(2022, 1, 25), date(2022, 1, 26), date(2022, 2, 1), date(2022, 2, 2), date(2022, 5, 2), date(2022, 5, 3)], dtype=object)
        price_bars.reset_record_map()                 # the map is loaded once per process; the rows above are new
        async with ScriptSessionLocal() as s:
            kept = await price_bars.stored_history_dates(s, sym, [date(2022, 1, 26), date(2022, 2, 2), date(2022, 5, 3)], sessions)
            assert len((await price_bars.record_map(s)).by) > 500 and price_bars.record_map_sync().stored_history_floor("SKYD") is not None
            assert kept == {date(2022, 1, 26), date(2022, 2, 2)}          # 02-02's prior session 02-01 is in the span
            assert await price_bars.stored_history_floor(s, sym) == date(2022, 1, 26)
            assert await price_bars.mark_stored_history(s, tid, EventType.EARNINGS, kept) == 2
            await s.commit()
            rows = (await s.execute(text("SELECT event_date, price_source, pct_change_1d FROM historical_reactions WHERE ticker_id = :t ORDER BY event_date"), {"t": tid})).all()
        assert [(r.event_date.isoformat(), r.price_source, r.pct_change_1d) for r in rows] == [
            ("2022-01-26", "stored_history", Decimal("1.5000")), ("2022-02-02", "stored_history", Decimal("1.5000")), ("2022-05-03", None, Decimal("1.5000"))]
        assert await _no_span_dates("AAPL") == set()
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM historical_reactions WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM security_records WHERE symbol = :s"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()
        price_bars.reset_record_map()


def test_bulk_bars_read_many_symbols_in_one_query_and_the_recompute_reads_in_batches():
    import inspect
    from app.scripts import recompute_reactions_intrinio as rr
    src = inspect.getsource(rr.run)
    assert "record_map_sync()" in src and "bulk_bars_sync(" in src and "stored_history_dates(s," not in src
    assert rr.BARS_BATCH >= 25


async def _no_span_dates(sym):
    import numpy as np
    async with ScriptSessionLocal() as s:
        return await price_bars.stored_history_dates(s, sym, [date(2026, 1, 5)], np.array([date(2026, 1, 2), date(2026, 1, 5)], dtype=object))


# ── the recompute's classification and write plan ─────────────────────────────

def test_classification_on_the_one_day_move_and_the_write_plan_per_event_type():
    assert classify(None, None) == "reproduced" and classify(Decimal("1.2345"), 1.2400) == "reproduced"
    assert classify(Decimal("1.2345"), 1.2500) == "changed" and classify(None, 0.5) == "filled" and classify(Decimal("2"), None) == "emptied"
    earn = plan_update({"event_type": "earnings"}, {"close_before": 1, "open_after": 2, "close_after": 3, "pct_change_1d": 4, "pct_change_3d": 5, "pct_change_5d": 6, "volume_after": 7})
    assert earn == {"close_before": 1, "open_after": 2, "close_after": 3, "pct_change_1d": 4, "pct_change_3d": 5, "pct_change_5d": 6, "volume_after": 7, "price_source": "intrinio"}
    gone = plan_update({"event_type": "analyst_action"}, None)
    assert gone == {"close_before": None, "close_after": None, "pct_change_1d": None, "pct_change_5d": None, "price_source": "intrinio"}
    assert set(VALUE_KEYS) == {"earnings", "fomc", "analyst_action"} and "computation_version" not in sum(VALUE_KEYS.values(), ())
    assert PRICE_SOURCES == ("yfinance", "intrinio", "stored_history") and STEP_LABEL == "Recompute reactions (Intrinio)"


# ── the checks ────────────────────────────────────────────────────────────────

def test_the_source_checks_are_registered():
    assert check_reaction_source_coverage in CHECKS and check_reaction_source_consistency in CHECKS


@pytest.mark.asyncio
async def test_source_consistency_allows_intrinio_beside_stored_history_only_on_a_declared_span():
    sym = "ZZSRC"
    try:
        async with ScriptSessionLocal() as s:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active) VALUES (gen_random_uuid(), :s, 'Source test', true) ON CONFLICT (symbol) DO NOTHING"), {"s": sym})
            tid = (await s.execute(text("SELECT id FROM tickers WHERE symbol = :s"), {"s": sym})).scalar()
            for d, src in (("2025-01-06", SOURCE_INTRINIO), ("2025-04-07", SOURCE_STORED_HISTORY)):
                await s.execute(text("INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, computation_version, price_source) VALUES (gen_random_uuid(), :t, 'fomc', :d, 1, :p)"),
                                {"t": tid, "d": date.fromisoformat(d), "p": src})
            await s.commit()
        r = (await run_checks([check_reaction_source_consistency]))[0]
        assert r.level == ERROR and any(r_.startswith(f"{sym} fomc") and "no stored_history span declared" in r_ for r_ in r.rows)
        async with ScriptSessionLocal() as s:
            await s.execute(text("UPDATE historical_reactions SET price_source = 'yfinance' WHERE ticker_id = :t AND event_date = '2025-04-07'"), {"t": tid})
            await s.commit()
        r = (await run_checks([check_reaction_source_consistency]))[0]
        assert r.level == ERROR and any("['intrinio', 'yfinance']" in r_ for r_ in r.rows)
        cov = (await run_checks([check_reaction_source_coverage]))[0]
        assert cov.level in (ERROR, PASS, WARN) and ("intrinio" in cov.message or "null" in cov.message)
    finally:
        async with ScriptSessionLocal() as s:
            await s.execute(text("DELETE FROM historical_reactions WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
            await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
            await s.commit()

# shares rows other files of this group read across tickers (alert picks, seeded ZZ symbols, index membership): one xdist worker runs them
# (scripts/push_window.py runs pytest -n auto --dist loadgroup)
pytestmark = pytest.mark.xdist_group(name="shared_rows")
