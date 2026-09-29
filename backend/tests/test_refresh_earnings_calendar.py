"""The calendar step applied to NKE's exact rows, against the database, with the sources injected.

Before: Sep 28 (Finnhub estimate, passed, no row), Dec 16 (Finnhub), reactions through Jun 30. Sources today:
Finnhub future Dec 16, Yahoo future Oct 1 16:00, no company announcement, no 8-K. After: Oct 1 estimated
(Yahoo Finance) is next, Dec 16 stays, Sep 28 is gone (replaced by the Oct 1 estimate), every ticker checked.
A second ticker with nothing but a passed estimate ends as 'expected around'. A third with no source
date at all is still marked checked. Uses synthetic tickers removed afterwards.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.ticker import Ticker
from app.scripts.refresh_earnings_calendar import LOOKAHEAD_DAYS, finnhub_by_symbol, reconcile

NKE, LONE, NONE, CCL = "ZZNKE", "ZZLONE", "ZZNONE", "ZZCCL"
SYMS = (NKE, LONE, NONE, CCL)
NOW = datetime(2026, 9, 29, 16, 2, 47, tzinfo=timezone.utc)
TODAY = NOW.date()


async def _cleanup(s):
    await s.execute(text("DELETE FROM earnings_report_timing WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = ANY(:s))"), {"s": list(SYMS)})
    await s.execute(text("DELETE FROM historical_reactions WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = ANY(:s))"), {"s": list(SYMS)})
    await s.execute(text("DELETE FROM events WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = ANY(:s))"), {"s": list(SYMS)})
    await s.execute(text("DELETE FROM tickers WHERE symbol = ANY(:s)"), {"s": list(SYMS)})
    await s.commit()


async def _event(s, sym, d, source, confirmed=False, note=None):
    await s.execute(text("""
        INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, confirmation_note, metadata, created_at, updated_at)
        SELECT gen_random_uuid(), id, 'earnings', :d, :t, :src, :c, :n, '{}', now(), now() FROM tickers WHERE symbol = :s
    """), {"d": d, "t": f"{sym} Earnings", "src": source, "c": confirmed, "n": note, "s": sym})


async def _reaction(s, sym, d, actual, est):
    await s.execute(text("""
        INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, pct_change_1d, eps_estimate, eps_actual, outcome, computation_version, created_at)
        SELECT gen_random_uuid(), id, 'earnings', :d, 1.0, :e, :a, 'beat', 3, now() FROM tickers WHERE symbol = :s
    """), {"d": d, "e": est, "a": actual, "s": sym})


@pytest.mark.asyncio
async def test_nke_rows_resolve_to_oct_1_estimated_and_the_lone_estimate_becomes_expected_around():
    async with ScriptSessionLocal() as s:
        await _cleanup(s)
        for sym in (NKE, LONE, NONE):
            await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at) VALUES (gen_random_uuid(), :s, 'calendar test', true, now(), now())"), {"s": sym})
        # NKE exactly
        await _event(s, NKE, date(2026, 6, 25), "yfinance"); await _event(s, NKE, date(2026, 6, 30), "yfinance")
        await _event(s, NKE, date(2026, 9, 28), "finnhub"); await _event(s, NKE, date(2026, 12, 16), "finnhub")
        await _reaction(s, NKE, date(2025, 12, 18), 0.53, 0.37); await _reaction(s, NKE, date(2026, 3, 31), 0.35, 0.28); await _reaction(s, NKE, date(2026, 6, 30), 0.72, 0.13)
        # a passed estimate with no alternative anywhere
        await _event(s, LONE, date(2026, 9, 28), "finnhub"); await _reaction(s, LONE, date(2026, 6, 30), 1.0, 0.9)
        await s.commit()
    sources = {
        "finnhub_future": {NKE: {date(2026, 12, 16): "unknown"}},
        "finnhub_actual": {},
        "yfinance_future": {NKE: {date(2026, 10, 1): "amc"}},
        "yfinance_reported": {NKE: [date(2026, 6, 30)], LONE: [date(2026, 6, 30)]},
        "company": {},
    }
    try:
        async with ScriptSessionLocal() as s:
            tickers = list((await s.execute(select(Ticker).where(Ticker.symbol.in_((NKE, LONE, NONE))).order_by(Ticker.symbol))).scalars().all())
            plan = await reconcile(s, tickers, sources, NOW, edgar=None)
        assert plan.checked == 3
        assert plan.inserted == [f"{NKE}: 2026-10-01 estimated (Yahoo Finance)"]
        assert plan.superseded == [f"{NKE}: 2026-09-28 replaced by the 2026-10-01 estimate"]
        assert plan.unresolved == [f"{LONE}: 2026-09-28 expected around 2026-09-28; not confirmed by Finnhub, Yahoo Finance or EDGAR"]
        assert plan.no_date == [LONE, NONE]
        assert plan.replaced == [f"{NKE}: 2026-12-16 -> 2026-10-01"]
        assert plan.dropped == [] and plan.kept == []

        async with ScriptSessionLocal() as s:
            rows = (await s.execute(text("""
                SELECT t.symbol, e.event_date, e.source::text, e.is_confirmed, e.unresolved_since, e.confirmation_note, e.report_timing
                FROM events e JOIN tickers t ON t.id = e.ticker_id WHERE t.symbol = ANY(:s) AND e.event_type = 'earnings'
                ORDER BY t.symbol, e.event_date"""), {"s": list(SYMS)})).all()
            checked = dict((await s.execute(text("SELECT symbol, earnings_checked_at FROM tickers WHERE symbol = ANY(:s)"), {"s": list(SYMS)})).all())
        got = [tuple(r) for r in rows]
        assert got == [
            (LONE, date(2026, 9, 28), "finnhub", False, TODAY, "expected around 2026-09-28; not confirmed by Finnhub, Yahoo Finance or EDGAR", "unknown"),
            (NKE, date(2026, 6, 25), "yfinance", False, None, None, "unknown"),
            (NKE, date(2026, 6, 30), "yfinance", False, None, None, "unknown"),
            (NKE, date(2026, 10, 1), "yfinance", False, None, "estimated (Yahoo Finance)", "amc"),
            (NKE, date(2026, 12, 16), "finnhub", False, None, "estimated (Finnhub)", "unknown"),
        ]
        assert all(checked[sym] == NOW for sym in (NKE, LONE, NONE))

        # the chooser: NKE next is Oct 1 estimated; LONE is 'expected around Sep 28'
        from app.services.next_earnings import batch_next_earnings
        async with ScriptSessionLocal() as s:
            ids = {t.symbol: t.id for t in (await s.execute(select(Ticker).where(Ticker.symbol.in_(SYMS)))).scalars().all()}
            picked = await batch_next_earnings(s, [ids[NKE], ids[LONE], ids[NONE]])
        nke, lone, none = picked[ids[NKE]], picked[ids[LONE]], picked[ids[NONE]]
        assert (nke.date, nke.source, nke.confirmation, nke.note) == (date(2026, 10, 1), "yfinance", "estimated", "estimated (Yahoo Finance)")
        assert (lone.date, lone.confirmation) == (date(2026, 9, 28), "expected_unconfirmed")
        assert none.date is None and none.checked_at == NOW
    finally:
        async with ScriptSessionLocal() as s:
            await _cleanup(s)


def test_finnhub_entries_split_into_future_dates_and_past_actuals():
    future, actual = finnhub_by_symbol([
        {"symbol": "NKE", "date": "2026-09-28", "epsActual": None}, {"symbol": "NKE", "date": "2026-12-16", "hour": "amc"},
        {"symbol": "COST", "date": "2026-09-24", "epsActual": 6.6}, {"symbol": "X", "date": "bad"},
    ], TODAY)
    assert future == {"NKE": {date(2026, 12, 16): "amc"}} and actual == {"COST": [date(2026, 9, 24)]}
    assert LOOKAHEAD_DAYS == 120


def test_the_script_never_keeps_a_date_as_confirmed_without_evidence():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "scripts" / "refresh_earnings_calendar.py").read_text()
    assert "CONFIRMED_HORIZON" not in src and "kept_confirmed" not in src
    assert "is_confirmed=f.confirmed" in src and "resolve_past(" in src


@pytest.mark.asyncio
async def test_ccl_the_edgar_report_date_is_kept_and_finnhubs_dec_18_is_added_as_the_following_estimate():
    """CCL, production, 2026-09-29: the catch-up step stored Sep 29 from EDGAR (8-K Item 2.02) the day CCL
    reported; the calendar step then ran with Finnhub listing only Dec 18 and deleted it. Now: Sep 29 stays as
    it was, Dec 18 is inserted as the estimate that follows, nothing is dropped or replaced."""
    async with ScriptSessionLocal() as s:
        await _cleanup(s)
        await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at) VALUES (gen_random_uuid(), :s, 'calendar test', true, now(), now())"), {"s": CCL})
        await _event(s, CCL, date(2026, 6, 24), "yfinance")
        await _event(s, CCL, date(2026, 9, 29), "edgar", confirmed=True, note="reported on 2026-09-29 per EDGAR (8-K Item 2.02)")
        await _reaction(s, CCL, date(2026, 3, 27), 0.20, 0.08); await _reaction(s, CCL, date(2026, 6, 23), 0.41, 0.31)
        await s.commit()
    sources = {"finnhub_future": {CCL: {date(2026, 12, 18): "amc"}}, "finnhub_actual": {},
               "yfinance_future": {}, "yfinance_reported": {CCL: [date(2026, 6, 23)]}, "company": {}}
    try:
        async with ScriptSessionLocal() as s:
            tickers = list((await s.execute(select(Ticker).where(Ticker.symbol == CCL))).scalars().all())
            plan = await reconcile(s, tickers, sources, NOW, edgar=None)
        assert plan.dropped == [] and plan.replaced == [] and plan.superseded == [] and plan.no_date == []
        assert plan.inserted == [f"{CCL}: 2026-12-18 estimated (Finnhub)"]
        assert plan.kept == [f"{CCL}: kept 2026-09-29 (EDGAR); calendar sources list 2026-12-18"]
        async with ScriptSessionLocal() as s:
            rows = (await s.execute(text("""
                SELECT e.event_date, e.source::text, e.is_confirmed, e.confirmation_note, e.checked_at
                FROM events e JOIN tickers t ON t.id = e.ticker_id WHERE t.symbol = :s AND e.event_type = 'earnings' ORDER BY e.event_date"""), {"s": CCL})).all()
        assert [tuple(r) for r in rows] == [
            (date(2026, 6, 24), "yfinance", False, None, None),
            (date(2026, 9, 29), "edgar", True, "reported on 2026-09-29 per EDGAR (8-K Item 2.02)", NOW),
            (date(2026, 12, 18), "finnhub", False, "estimated (Finnhub)", NOW),
        ]
        from app.services.next_earnings import batch_next_earnings
        async with ScriptSessionLocal() as s:
            tid = (await s.execute(select(Ticker.id).where(Ticker.symbol == CCL))).scalar()
            picked = (await batch_next_earnings(s, [tid]))[tid]
        assert (picked.date, picked.source, picked.confirmation) == (date(2026, 9, 29), "edgar", "confirmed")

        # a second run with Yahoo now also listing Sep 30 for the same report: absorbed, not inserted beside it
        sources["yfinance_future"] = {CCL: {date(2026, 9, 30): "bmo", date(2026, 12, 18): "amc"}}
        async with ScriptSessionLocal() as s:
            tickers = list((await s.execute(select(Ticker).where(Ticker.symbol == CCL))).scalars().all())
            plan = await reconcile(s, tickers, sources, NOW, edgar=None)
        assert plan.inserted == [] and plan.dropped == [] and plan.replaced == []
        assert plan.kept == [f"{CCL}: 2026-09-30 (yfinance) is the 2026-09-29 report (EDGAR); not inserted",
                             f"{CCL}: kept 2026-09-29 (EDGAR); calendar sources list 2026-09-30, 2026-12-18"]
        async with ScriptSessionLocal() as s:
            rows = (await s.execute(text("""
                SELECT e.event_date, e.source::text, e.is_confirmed, e.confirmation_note FROM events e JOIN tickers t ON t.id = e.ticker_id
                WHERE t.symbol = :s AND e.event_type = 'earnings' AND e.event_date >= :d ORDER BY e.event_date"""), {"s": CCL, "d": TODAY})).all()
        assert [tuple(r) for r in rows] == [
            (date(2026, 9, 29), "edgar", True, "reported on 2026-09-29 per EDGAR (8-K Item 2.02)"),
            (date(2026, 12, 18), "finnhub", True, "confirmed: Finnhub and Yahoo Finance agree"),
        ]
    finally:
        async with ScriptSessionLocal() as s:
            await _cleanup(s)


def test_a_finnhub_entry_with_an_actual_eps_is_evidence_whatever_its_date():
    future, actual = finnhub_by_symbol([{"symbol": "CCL", "date": TODAY.isoformat(), "epsActual": 1.51, "hour": "bmo"}], TODAY)
    assert future == {} and actual == {"CCL": [TODAY]}
