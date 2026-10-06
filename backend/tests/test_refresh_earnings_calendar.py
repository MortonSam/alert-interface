"""The calendar step applied to NKE's exact rows, against the database, with the sources injected.

Before: Sep 28 (Finnhub estimate, passed, no row), Dec 16 (Finnhub), reactions through Jun 30. Sources today:
Finnhub future Dec 16, Yahoo future Oct 1 16:00, no company announcement, no 8-K. After: Oct 1 estimated
(Yahoo Finance) is next, Dec 16 stays, Sep 28 is gone (replaced by the Oct 1 estimate), every ticker checked.
A second ticker with nothing but a passed estimate ends as 'expected around'. A third with no source
date at all is still marked checked. Uses synthetic tickers removed afterwards.
"""
from datetime import date, datetime, timedelta, timezone
import re
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.ticker import Ticker
from app.scripts.refresh_earnings_calendar import LOOKAHEAD_DAYS, finnhub_by_symbol, reconcile

NKE, LONE, NONE, CCL, UNH, UBER, VEEV = "ZZNKE", "ZZLONE", "ZZNONE", "ZZCCL", "ZZUNH", "ZZUBER", "ZZVEEV"
SYMS = (NKE, LONE, NONE, CCL, UNH, UBER, VEEV)
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
        assert plan.superseded == [f"{NKE}: 2026-06-25 the quarter was reported on 2026-06-30; the 2026-06-25 estimate is removed",      # an old estimate never stands beside a reported quarter
                                   f"{NKE}: 2026-09-28 replaced by the 2026-10-01 estimate"]
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
            (NKE, date(2026, 6, 30), "yfinance", False, None, None, "unknown"),
            (NKE, date(2026, 10, 1), "yfinance", False, None, "estimated (Yahoo Finance)", "amc"),
            (NKE, date(2026, 12, 16), "finnhub", False, None, "estimated (Finnhub)", "unknown"),
        ]
        assert all(checked[sym] == NOW for sym in (NKE, LONE, NONE))

        # the chooser: NKE next is Oct 1 estimated; LONE is 'expected around Sep 28'
        from app.services.next_earnings import batch_next_earnings
        async with ScriptSessionLocal() as s:
            ids = {t.symbol: t.id for t in (await s.execute(select(Ticker).where(Ticker.symbol.in_(SYMS)))).scalars().all()}
            picked = await batch_next_earnings(s, [ids[NKE], ids[LONE], ids[NONE]], today=TODAY)   # judged on the fixture's day, not the real one
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
        from app.models.event import Event
        from app.services.next_earnings import choose
        async with ScriptSessionLocal() as s:
            tid = (await s.execute(select(Ticker.id).where(Ticker.symbol == CCL))).scalar()
            events = list((await s.execute(select(Event).where(Event.ticker_id == tid))).scalars().all())
        assert choose(events, TODAY)[:3] == (date(2026, 9, 29), "edgar", "confirmed")

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


async def _ticker(s, sym):
    await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at) VALUES (gen_random_uuid(), :s, 'calendar test', true, now(), now())"), {"s": sym})


async def _rows(s, syms, since=None):
    rows = (await s.execute(text("""
        SELECT t.symbol, e.event_date, e.source::text, e.is_confirmed, e.confirmation_note
        FROM events e JOIN tickers t ON t.id = e.ticker_id WHERE t.symbol = ANY(:s) AND e.event_type = 'earnings'
        AND e.event_date >= CAST(:d AS date) ORDER BY t.symbol, e.event_date"""), {"s": list(syms), "d": since or date(2000, 1, 1)})).all()
    return [tuple(r) for r in rows]


@pytest.mark.asyncio
async def test_production_2026_09_29_a_silent_yahoo_drops_nothing_unh_uber_and_nke_exactly():
    """The step's Yahoo pass ran out of budget before the U-Z tail. Before the fix it dropped UNH's Oct 13 for
    Finnhub's Jan 25 and UBER's Nov 3 for nothing, and left NKE (Yahoo also silent) with Sep 28 unresolved and
    Dec 16. Now: an unanswered source drops nothing; UNH keeps Oct 13 and gains Jan 25 as the following estimate,
    UBER keeps Nov 3, NKE is unchanged, and Yahoo's answer on the next run confirms the standing dates."""
    syms = (UNH, UBER, NKE)
    async with ScriptSessionLocal() as s:
        await _cleanup(s)
        for sym in syms:
            await _ticker(s, sym)
        await _event(s, UNH, date(2026, 7, 16), "yfinance"); await _event(s, UNH, date(2026, 7, 28), "yfinance")
        await _event(s, UNH, date(2026, 10, 13), "yfinance", note="estimated (Yahoo Finance)")
        await _reaction(s, UNH, date(2026, 4, 21), 6.85, 6.75); await _reaction(s, UNH, date(2026, 7, 16), 4.08, 4.48)
        await _event(s, UBER, date(2026, 8, 5), "yfinance"); await _event(s, UBER, date(2026, 11, 3), "yfinance", note="estimated (Yahoo Finance)")
        await _reaction(s, UBER, date(2026, 5, 6), 0.83, 0.51); await _reaction(s, UBER, date(2026, 8, 5), 0.63, 0.62)
        await _event(s, NKE, date(2026, 9, 28), "finnhub", note="estimated (Finnhub)"); await _event(s, NKE, date(2026, 12, 16), "finnhub", note="estimated (Finnhub)")
        await _reaction(s, NKE, date(2026, 3, 31), 0.35, 0.28); await _reaction(s, NKE, date(2026, 6, 30), 0.72, 0.13)
        await s.commit()
    # what the sources returned that run: Finnhub's calendar, Yahoo nothing for these three
    silent = {"finnhub_future": {UNH: {date(2027, 1, 25): "unknown"}, NKE: {date(2026, 12, 16): "unknown"}}, "finnhub_actual": {},
              "yfinance_future": {}, "yfinance_reported": {}, "company": {}}
    try:
        async with ScriptSessionLocal() as s:
            tickers = list((await s.execute(select(Ticker).where(Ticker.symbol.in_(syms)).order_by(Ticker.symbol))).scalars().all())
            plan = await reconcile(s, tickers, silent, NOW, edgar=None)
        assert plan.dropped == [] and plan.replaced == [] and plan.no_date == []
        assert plan.superseded == [f"{UNH}: 2026-07-28 the quarter was reported on 2026-07-16; the 2026-07-28 estimate is removed"]   # the stale July estimate goes
        assert plan.inserted == [f"{UNH}: 2027-01-25 estimated (Finnhub)"]
        assert plan.standing == [
            f"{UBER}: 2026-11-03 (yfinance) stands; Yahoo Finance returned no future date this run",
            f"{UNH}: 2026-10-13 (yfinance) stands; Yahoo Finance returned no future date this run",
        ]
        assert plan.unresolved == [f"{NKE}: 2026-09-28 expected around 2026-09-28; not confirmed by Finnhub, Yahoo Finance or EDGAR"]
        async with ScriptSessionLocal() as s:
            got = await _rows(s, syms, since=date(2026, 9, 1))
        assert got == [
            (NKE, date(2026, 9, 28), "finnhub", False, "expected around 2026-09-28; not confirmed by Finnhub, Yahoo Finance or EDGAR"),
            (NKE, date(2026, 12, 16), "finnhub", False, "estimated (Finnhub); the last report was 2026-06-30, so a quarterly report would usually be due around 2026-09-29"),
            (UBER, date(2026, 11, 3), "yfinance", False, "estimated (Yahoo Finance)"),
            (UNH, date(2026, 10, 13), "yfinance", False, "estimated (Yahoo Finance)"),
            (UNH, date(2027, 1, 25), "finnhub", False, "estimated (Finnhub)"),
        ]

        # the next run reaches Yahoo (what it answers when asked, probed 2026-09-30): the standing dates are its word
        answered = {"finnhub_future": silent["finnhub_future"], "finnhub_actual": {},
                    "yfinance_future": {UNH: {date(2026, 10, 13): "bmo"}, UBER: {date(2026, 11, 3): "bmo"}, NKE: {date(2026, 10, 1): "amc"}},
                    "yfinance_reported": {UNH: [date(2026, 7, 16)], UBER: [date(2026, 8, 5)], NKE: [date(2026, 6, 30)]}, "company": {}}
        async with ScriptSessionLocal() as s:
            tickers = list((await s.execute(select(Ticker).where(Ticker.symbol.in_(syms)).order_by(Ticker.symbol))).scalars().all())
            plan = await reconcile(s, tickers, answered, NOW, edgar=None)
        assert plan.standing == [] and plan.dropped == []
        assert plan.inserted == [f"{NKE}: 2026-10-01 estimated (Yahoo Finance)"]
        assert plan.superseded == [f"{NKE}: 2026-09-28 replaced by the 2026-10-01 estimate"]
        async with ScriptSessionLocal() as s:
            got = await _rows(s, syms, since=date(2026, 9, 1))
        assert got == [
            (NKE, date(2026, 10, 1), "yfinance", False, "estimated (Yahoo Finance)"),
            (NKE, date(2026, 12, 16), "finnhub", False, "estimated (Finnhub)"),
            (UBER, date(2026, 11, 3), "yfinance", False, "estimated (Yahoo Finance)"),
            (UNH, date(2026, 10, 13), "yfinance", False, "estimated (Yahoo Finance)"),
            (UNH, date(2027, 1, 25), "finnhub", False, "estimated (Finnhub)"),
        ]
    finally:
        async with ScriptSessionLocal() as s:
            await _cleanup(s)


@pytest.mark.asyncio
async def test_a_stored_estimate_is_dropped_only_by_its_own_source_or_a_higher_one_and_a_dry_run_writes_nothing():
    """VEEV holds Finnhub's Nov 18 and Yahoo now says Nov 25: both full sessions, neither confirmed, so the stored
    date stands and Yahoo's day goes in the note. A Finnhub estimate that Finnhub itself now lists elsewhere is
    dropped with the reason. With write=False the same plan is computed and nothing reaches the table."""
    async with ScriptSessionLocal() as s:
        await _cleanup(s)
        await _ticker(s, VEEV); await _ticker(s, UNH)
        await _event(s, VEEV, date(2026, 11, 18), "finnhub", note="estimated (Finnhub)")
        await _reaction(s, VEEV, date(2026, 8, 26), 1.9, 1.8)
        await _event(s, UNH, date(2026, 10, 13), "finnhub", note="estimated (Finnhub)")
        await _reaction(s, UNH, date(2026, 7, 16), 4.08, 4.48)
        await s.commit()
    sources = {"finnhub_future": {UNH: {date(2027, 1, 25): "unknown"}, VEEV: {date(2026, 11, 18): "unknown"}}, "finnhub_actual": {},
               "yfinance_future": {VEEV: {date(2026, 11, 25): "amc"}}, "yfinance_reported": {}, "company": {}}
    try:
        async with ScriptSessionLocal() as s:
            tickers = list((await s.execute(select(Ticker).where(Ticker.symbol.in_((VEEV, UNH))).order_by(Ticker.symbol))).scalars().all())
            dry = await reconcile(s, tickers, sources, NOW, edgar=None, write=False)
        assert dry.dropped == [f"{UNH}: dropped 2026-10-13 (finnhub); Finnhub now lists 2027-01-25"]
        assert dry.inserted == [f"{UNH}: 2027-01-25 estimated (Finnhub); the last report was 2026-07-16, so a quarterly report would usually be due around 2026-10-15"]
        async with ScriptSessionLocal() as s:
            assert await _rows(s, (VEEV, UNH)) == [(UNH, date(2026, 10, 13), "finnhub", False, "estimated (Finnhub)"),
                                                    (VEEV, date(2026, 11, 18), "finnhub", False, "estimated (Finnhub)")]
            checked = (await s.execute(text("SELECT earnings_checked_at FROM tickers WHERE symbol = :s"), {"s": VEEV})).scalar()
            assert checked is None, "a dry run marks nothing checked"

        async with ScriptSessionLocal() as s:
            tickers = list((await s.execute(select(Ticker).where(Ticker.symbol.in_((VEEV, UNH))).order_by(Ticker.symbol))).scalars().all())
            wet = await reconcile(s, tickers, sources, NOW, edgar=None)
        assert (wet.dropped, wet.inserted) == (dry.dropped, dry.inserted)
        async with ScriptSessionLocal() as s:
            assert await _rows(s, (VEEV, UNH)) == [
                (UNH, date(2027, 1, 25), "finnhub", False, "estimated (Finnhub); the last report was 2026-07-16, so a quarterly report would usually be due around 2026-10-15"),
                (VEEV, date(2026, 11, 18), "finnhub", False, "estimated (Finnhub); Yahoo Finance says 2026-11-25"),   # both full sessions: the stored date stands
            ]
    finally:
        async with ScriptSessionLocal() as s:
            await _cleanup(s)


def test_the_yahoo_pass_rotates_daily_treats_an_empty_frame_as_no_answer_and_the_restore_runs_the_step_without_budgets():
    from pathlib import Path
    from app.scripts.refresh_earnings_calendar import announcement_targets, yfinance_order
    syms = ["A", "B", "C", "D"]
    assert yfinance_order(syms, date(2026, 9, 29)) != yfinance_order(syms, date(2026, 9, 30))
    assert sorted(yfinance_order(syms, date(2026, 9, 30))) == syms and yfinance_order([], TODAY) == []
    src = (Path(__file__).resolve().parents[1] / "app" / "scripts" / "refresh_earnings_calendar.py").read_text()
    assert "if df is None or df.empty:\n        return None" in src
    assert re.search(r"if isinstance\(res, Exception\) or res is None:\s+continue", src)
    restore = (Path(__file__).resolve().parents[1] / "app" / "scripts" / "restore_yfinance_estimates.py").read_text()
    assert "run(yf_budget_s=None, announce_budget_s=None, write=write" in restore and 'write = "--write" in argv' in restore
    # who is asked for an announcement: a date within 60 days, or a report due with nothing on the calendar (NKE with Yahoo silent)
    got = announcement_targets(["NKE", "UNH", "FAR"], {"NKE": {date(2026, 12, 16): "unknown"}, "FAR": {date(2027, 1, 25): "unknown"}},
                               {}, {"UNH": [date(2026, 10, 13)]}, {"NKE": date(2026, 6, 30), "UNH": date(2026, 7, 16), "FAR": date(2026, 8, 20)}, TODAY)
    assert got == ["NKE", "UNH"]


def test_no_ticker_is_unreached_three_runs_in_a_row_when_a_run_reaches_a_third_of_them():
    """The pass asks last run's unreached tickers first, then rotates. With a budget that reaches a third of the
    active tickers per run, every ticker is asked within three runs from any starting day; a ticker Yahoo never
    answers for is asked first every run, and its streak names it in the outcome."""
    import math
    from app.scripts.refresh_earnings_calendar import UNREACHED_RUNS_WARN, unreached_streak, yfinance_order
    symbols = [f"T{i:03d}" for i in range(512)]
    per_run = math.ceil(len(symbols) / 3)
    for first_day in range(7):
        streak, seen = {}, set()
        for run in range(3):
            order = yfinance_order(symbols, date(2026, 9, 29) + timedelta(days=first_day + run), streak)
            assert sorted(order) == symbols
            reached = set(order[:per_run])            # the budget runs out after a third of the list
            seen |= reached
            unreached = [s for s in symbols if s not in reached]
            streak = unreached_streak(streak, unreached)
        assert seen == set(symbols), f"unreached after three runs from day {first_day}: {sorted(set(symbols) - seen)[:5]}"
        assert max(streak.values(), default=0) < UNREACHED_RUNS_WARN

    # a ticker Yahoo never answers for: asked first each run, counted, named at three
    streak = {}
    for run in range(3):
        order = yfinance_order(symbols, date(2026, 10, 1) + timedelta(days=run), streak)
        if run:
            assert order.index("T100") < per_run, "asked again every run, ahead of the rotation"
        reached = set(order[:per_run + 1]) - {"T100"}      # the budget covers a third of the tickers plus the failure
        unreached = [s for s in symbols if s not in reached]
        streak = unreached_streak(streak, unreached)
    assert streak["T100"] == 3 and UNREACHED_RUNS_WARN == 3
    assert all(n < 3 for s, n in streak.items() if s != "T100")
    src = (Path(__file__).resolve().parents[1] / "app" / "scripts" / "refresh_earnings_calendar.py").read_text()
    assert '"yfinance_unreached": self.yfinance_unreached' in src and 'last.get("yfinance_unreached_streak")' in src
    assert 'yfinance_unreached_3_runs' in src


def test_a_manual_restore_records_its_exit_so_health_does_not_read_it_as_a_failure():
    from app.scripts.refresh_earnings_calendar import outcome_fields
    started = datetime(2026, 9, 30, 12, 0, 0, tzinfo=timezone.utc)
    got = outcome_fields({"checked": 512}, 0, started)
    assert got["checked"] == 512 and got["exit"] == 0 and got["seconds"] >= 0 and got["at"].endswith("+00:00")
    assert outcome_fields({}, 1, started)["exit"] == 1
    src = (Path(__file__).resolve().parents[1] / "app" / "scripts" / "refresh_earnings_calendar.py").read_text()
    assert "record_step_fields(step_label, outcome_fields(plan.fields(), 0, now))" in src
    assert 'outcome_fields({"checked": 0, "error": "Finnhub returned no calendar entries"}, 1, now)' in src
    # the health page's rule this satisfies
    from app.services.nightly_run import auto_pick_status
    assert auto_pick_status({"Auto-pick": {"at": "2026-09-30T06:30:00+00:00"}}).failed is True
