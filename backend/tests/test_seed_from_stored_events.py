"""The one-off reactions seeder reads the ticker's stored earnings events before asking yfinance: which stored rows count
as reports, the timing they carry, the typical move the rows yield, and the report-history seeder's confirmation of a
stored row that matches a filing."""
from datetime import date
from decimal import Decimal

from app.scripts.seed_historical_reactions import LOOKBACK_YEARS, MIN_AGE_DAYS, stored_report_entries, typical_abs_move

T = date(2026, 10, 6)


def row(d, est=None, act=None, timing="unknown", confirmed=True, unresolved=None):
    return (d, est, act, timing, confirmed, unresolved)


def test_confirmed_reports_count_with_their_timing():
    entries, timing = stored_report_entries([row(date(2026, 7, 22), timing="amc"), row(date(2026, 4, 28), timing="amc"), row(date(2025, 2, 3))], T)
    assert [e[0] for e in entries] == [date(2025, 2, 3), date(2026, 4, 28), date(2026, 7, 22)]          # oldest first
    assert timing == {date(2026, 4, 28): "amc", date(2026, 7, 22): "amc"}                                # unknown stays out of the map


def test_unconfirmed_dates_and_passed_estimates_never_count():
    entries, _ = stored_report_entries([row(date(2026, 8, 4), confirmed=False), row(date(2026, 7, 1), confirmed=True, unresolved=date(2026, 7, 2))], T)
    assert entries == []


def test_an_unconfirmed_row_with_a_reported_eps_counts():
    entries, _ = stored_report_entries([row(date(2026, 6, 25), est=Decimal("1.00"), act=Decimal("1.20"), confirmed=False)], T)
    assert entries == [(date(2026, 6, 25), Decimal("1.00"), Decimal("1.20"))]


def test_window_matches_the_yfinance_path():
    too_old = T.replace(year=T.year - LOOKBACK_YEARS) .replace(day=1)
    too_young = date.fromordinal(T.toordinal() - MIN_AGE_DAYS + 1)
    inside = date(2024, 1, 30)
    entries, _ = stored_report_entries([row(too_old), row(too_young), row(inside)], T)
    assert [e[0] for e in entries] == [inside]


def test_future_dates_never_count():
    entries, _ = stored_report_entries([row(date(2026, 10, 21), timing="amc")], T)
    assert entries == []


def test_typical_abs_move_is_the_mean_absolute_move_of_measured_rows():
    assert typical_abs_move([Decimal("1.33"), Decimal("-3.37"), None, Decimal("4.43")]) == 3.04
    assert typical_abs_move([None]) is None
    assert typical_abs_move([]) is None
