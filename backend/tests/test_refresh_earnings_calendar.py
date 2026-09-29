"""The calendar refresh makes stored future dates equal to Finnhub's, every ticker, every run.

A differing date is replaced, a date Finnhub no longer lists is dropped, a
ticker with no Finnhub date is still marked checked, and past dates are never
touched. Uses a synthetic ticker removed afterwards.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.event import Event
from app.models.ticker import Ticker
from app.scripts.refresh_earnings_calendar import LOOKAHEAD_DAYS, finnhub_dates_by_symbol, reconcile

SYMS = ("ZZCAL1", "ZZCAL2", "ZZCAL3")
NOW = datetime(2026, 9, 29, 6, 5, tzinfo=timezone.utc)
TODAY = NOW.date()


async def _cleanup(s):
    await s.execute(text("DELETE FROM earnings_report_timing WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = ANY(:s))"), {"s": list(SYMS)})
    await s.execute(text("DELETE FROM events WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = ANY(:s))"), {"s": list(SYMS)})
    await s.execute(text("DELETE FROM tickers WHERE symbol = ANY(:s)"), {"s": list(SYMS)})
    await s.commit()


async def _event(s, sym, d, source="yfinance"):
    await s.execute(text("""
        INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata, created_at, updated_at)
        SELECT gen_random_uuid(), id, 'earnings', :d, :t, :src, false, '{}', now(), now() FROM tickers WHERE symbol = :s
    """), {"d": d, "t": f"{sym} Earnings", "src": source, "s": sym})


@pytest.mark.asyncio
async def test_reconcile_replaces_drops_inserts_and_marks_checked():
    async with ScriptSessionLocal() as s:
        await _cleanup(s)
        for sym in SYMS:
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at) VALUES (gen_random_uuid(), :s, 'cal test', true, now(), now())"), {"s": sym})
        await _event(s, "ZZCAL1", TODAY + timedelta(days=29), "finnhub")   # Finnhub now says a day later
        await _event(s, "ZZCAL1", TODAY - timedelta(days=90), "finnhub")   # past: the record of a report, untouched
        await _event(s, "ZZCAL2", TODAY - timedelta(days=5), "yfinance")   # reported 5 days ago (past, untouched)
        await _event(s, "ZZCAL2", TODAY + timedelta(days=40), "yfinance")  # a future date Finnhub does not list
        await s.commit()
    try:
        entries = [
            {"symbol": "ZZCAL1", "date": (TODAY + timedelta(days=30)).isoformat(), "hour": "amc"},
            {"symbol": "ZZCAL3", "date": (TODAY + timedelta(days=70)).isoformat(), "hour": ""},
            {"symbol": "OTHER", "date": (TODAY + timedelta(days=3)).isoformat(), "hour": "bmo"},
            {"symbol": "ZZCAL1", "date": (TODAY - timedelta(days=1)).isoformat(), "hour": "bmo"},   # yesterday: not a future date
        ]
        async with ScriptSessionLocal() as s:
            tickers = list((await s.execute(select(Ticker).where(Ticker.symbol.in_(SYMS)).order_by(Ticker.symbol))).scalars().all())
            plan = await reconcile(s, tickers, entries, NOW)
        assert plan.checked == 3
        assert plan.replaced == [f"ZZCAL1: {(TODAY + timedelta(days=29)).isoformat()} -> {(TODAY + timedelta(days=30)).isoformat()}"]
        assert plan.inserted == [f"ZZCAL1: {(TODAY + timedelta(days=30)).isoformat()}", f"ZZCAL3: {(TODAY + timedelta(days=70)).isoformat()}"]
        assert len(plan.dropped) == 2 and any(d.startswith("ZZCAL2: dropped") and "Finnhub lists nothing" in d for d in plan.dropped)
        assert plan.no_date == ["ZZCAL2"]

        async with ScriptSessionLocal() as s:
            rows = (await s.execute(text("""
                SELECT t.symbol, e.event_date, e.source::text, e.report_timing FROM events e JOIN tickers t ON t.id = e.ticker_id
                WHERE t.symbol = ANY(:s) AND e.event_type = 'earnings' ORDER BY t.symbol, e.event_date"""), {"s": list(SYMS)})).all()
            checked = dict((await s.execute(text("SELECT symbol, earnings_checked_at FROM tickers WHERE symbol = ANY(:s)"), {"s": list(SYMS)})).all())
        got = [(r[0], r[1], r[2], r[3]) for r in rows]
        assert got == [
            ("ZZCAL1", TODAY - timedelta(days=90), "finnhub", "unknown"),
            ("ZZCAL1", TODAY + timedelta(days=30), "finnhub", "amc"),
            ("ZZCAL2", TODAY - timedelta(days=5), "yfinance", "unknown"),
            ("ZZCAL3", TODAY + timedelta(days=70), "finnhub", "unknown"),
        ]
        assert all(checked[sym] == NOW for sym in SYMS), "every ticker is marked checked, with or without a date"
    finally:
        async with ScriptSessionLocal() as s:
            await _cleanup(s)


def test_finnhub_dates_by_symbol_keeps_only_future_dates_and_maps_hour():
    entries = [{"symbol": "A", "date": "2026-10-29", "hour": "amc"}, {"symbol": "A", "date": "2026-09-28", "hour": "bmo"},
               {"symbol": "B", "date": "bad"}, {"symbol": "C", "date": "2027-01-27", "hour": "dmh"}]
    got = finnhub_dates_by_symbol(entries, date(2026, 9, 29))
    assert got == {"A": {date(2026, 10, 29): "amc"}, "C": {date(2027, 1, 27): "unknown"}}
    assert LOOKAHEAD_DAYS == 120


def test_the_script_never_keeps_a_date_as_confirmed():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "scripts" / "refresh_earnings_calendar.py").read_text()
    assert "CONFIRMED_HORIZON" not in src and "kept_confirmed" not in src
