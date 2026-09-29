"""A report that happened with no reaction row is found from Finnhub or EDGAR, whatever the calendar said."""
from datetime import date

from app.scripts.catch_up_reports import (
    LOOKBACK_DAYS, MATCH_TOLERANCE_DAYS, edgar_release_dates, finnhub_reports, missing_reports,
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
