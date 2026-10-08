"""A report that happened with no reaction row is found from Finnhub or EDGAR, whatever the calendar said."""
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.ticker import Ticker
from app.scripts.catch_up_reports import (
    LOOKBACK_DAYS, MATCH_TOLERANCE_DAYS, REPORT_DUE_DAYS, catch_up, edgar_release_dates, find_missing, finnhub_reports,
    missing_reports,
)

TODAY = date(2026, 9, 29)


def test_finnhub_reports_are_past_entries_with_an_actual():
    entries = [
        {"symbol": "COST", "date": "2026-09-24", "epsActual": 6.6},
        {"symbol": "ACN", "date": "2026-09-25", "epsActual": None},        # not reported yet
        {"symbol": "OLD", "date": "2026-09-01", "epsActual": 1.0},         # outside the window
        {"symbol": "FUT", "date": "2026-10-02", "epsActual": 1.0},         # in the future
        {"symbol": "COST", "date": "bad"},
    ]
    assert finnhub_reports(entries, TODAY) == {"COST": [date(2026, 9, 24)]}
    assert LOOKBACK_DAYS == 21


def test_edgar_release_is_an_8k_with_item_202_in_the_window():
    records = [
        {"filing_date": "2026-09-24", "items": "2.02,9.01"},
        {"filing_date": "2026-09-20", "items": "5.02"},
        {"filing_date": "2026-08-01", "items": "2.02"},
        {"filing_date": "2026-09-24", "items": " 2.02 , 7.01"},
    ]
    assert edgar_release_dates(records, TODAY) == [date(2026, 9, 24)]


def test_missing_is_a_report_with_no_row_within_the_tolerance():
    reported = {"COST": [(date(2026, 9, 24), "finnhub")], "AAPL": [(date(2026, 9, 10), "finnhub")],
                "SNPS": [(date(2026, 9, 12), "edgar")]}
    rows = {"AAPL": [date(2026, 9, 11)], "SNPS": [date(2026, 9, 9)]}   # AAPL within 1 day: has its row; SNPS 3 days: missing
    got = missing_reports(reported, rows, TODAY)
    assert [(m.symbol, m.report_date, m.source, m.age_days) for m in got] == [
        ("COST", date(2026, 9, 24), "finnhub", 5), ("SNPS", date(2026, 9, 12), "edgar", 17),
    ]
    assert MATCH_TOLERANCE_DAYS == 2


def test_the_step_runs_after_the_seeder_and_records_caught_up():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "scripts" / "refresh.py").read_text()
    assert src.index("Historical reactions (--all)") < src.index("Missed reports (catch_up_reports)")
    script = (Path(__file__).resolve().parents[1] / "app" / "scripts" / "catch_up_reports.py").read_text()
    assert '"caught_up": by["caught_up"]' in script
    assert 'write = "--report" not in argv' in script


class _Edgar:
    """EDGAR as it answered for CCL on 2026-09-29: one 8-K carrying Item 2.02 filed that day."""
    calls: list[str] = []

    async def get_cik(self, symbol):
        self.calls.append(symbol)
        return "0000815097" if symbol == "ZZCCL" else None

    async def get_all_8k_records(self, cik):
        return [{"filing_date": "2026-09-29", "items": "2.02,9.01"}, {"filing_date": "2026-06-23", "items": "2.02,9.01"}]


@pytest.mark.asyncio
async def test_ccl_is_found_again_from_edgar_with_no_stored_date_in_the_window_and_its_sep_29_row_is_re_inserted():
    """Production, 2026-09-29: the calendar step deleted CCL's Sep 29 (EDGAR) row. On the next run Finnhub still
    lists no CCL report and there is no stored date in the window; CCL's last reaction row is Jun 23, 98 days
    old, so a report was due and EDGAR is asked. The Sep 29 row comes back, confirmed, pending its reaction."""
    sym = "ZZCCL"
    async def _cleanup(s):
        await s.execute(text("DELETE FROM historical_reactions WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
        await s.execute(text("DELETE FROM events WHERE ticker_id IN (SELECT id FROM tickers WHERE symbol = :s)"), {"s": sym})
        await s.execute(text("DELETE FROM tickers WHERE symbol = :s"), {"s": sym})
        await s.commit()
    async with ScriptSessionLocal() as s:
        await _cleanup(s)
        await s.execute(text("INSERT INTO tickers (id, symbol, name, is_active, created_at, updated_at) VALUES (gen_random_uuid(), :s, 'catch-up test', true, now(), now())"), {"s": sym})
        for d in (date(2026, 3, 27), date(2026, 6, 23)):
            await s.execute(text("""
                INSERT INTO historical_reactions (id, ticker_id, event_type, event_date, pct_change_1d, eps_estimate, eps_actual, outcome, computation_version, created_at)
                SELECT gen_random_uuid(), id, 'earnings', :d, 1.0, 0.3, 0.4, 'beat', 3, now() FROM tickers WHERE symbol = :s"""), {"d": d, "s": sym})
        await s.execute(text("""
            INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, metadata, created_at, updated_at)
            SELECT gen_random_uuid(), id, 'earnings', '2026-12-18', 'ZZCCL Earnings', 'finnhub', false, '{}', now(), now() FROM tickers WHERE symbol = :s"""), {"s": sym})
        await s.commit()
    try:
        async with ScriptSessionLocal() as s:
            tickers = list((await s.execute(select(Ticker.id, Ticker.symbol).where(Ticker.symbol == sym))).all())
            missing = await find_missing(s, tickers, entries=[], edgar=_Edgar(), today=TODAY)
        assert [(m.symbol, m.report_date, m.source, m.age_days) for m in missing] == [(sym, date(2026, 9, 29), "edgar", 0)]
        assert _Edgar.calls == [sym]

        await catch_up(missing, {t.symbol: t.id for t in tickers}, write=True)
        assert missing[0].status == "pending" and missing[0].detail.startswith("event inserted; reaction window not settled")
        async with ScriptSessionLocal() as s:
            rows = (await s.execute(text("""
                SELECT e.event_date, e.source::text, e.is_confirmed, e.confirmation_note, e.checked_at IS NOT NULL
                FROM events e JOIN tickers t ON t.id = e.ticker_id WHERE t.symbol = :s ORDER BY e.event_date"""), {"s": sym})).all()
        assert [tuple(r) for r in rows] == [
            (date(2026, 9, 29), "edgar", True, "reported on 2026-09-29 per EDGAR (8-K Item 2.02)", True),
            (date(2026, 12, 18), "finnhub", False, None, False),
        ]
        # and the calendar step, run next, keeps it (see test_refresh_earnings_calendar): the row is beyond its reach
        from app.services.earnings_calendar import StoredDate, beyond_calendar_reach
        assert beyond_calendar_reach(StoredDate(date(2026, 9, 29), "edgar", True, rows[0][3]), [date(2026, 6, 23)], []) == "EDGAR"
        assert REPORT_DUE_DAYS == 80
    finally:
        async with ScriptSessionLocal() as s:
            await _cleanup(s)

# shares the ZZCCL and ZZNONE symbols with the other files of this group: one xdist worker runs them (scripts/push_window.py runs pytest -n auto --dist loadgroup)
pytestmark = pytest.mark.xdist_group(name="calendar_and_bars")
