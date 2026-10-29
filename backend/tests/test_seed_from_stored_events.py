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


# ── The nightly (bulk) path reads the stored reports first (2026-10-29: PGR, SYF, FAST, CB) ──
from app.scripts.seed_historical_reactions import DUPLICATE_GUARD_DAYS, merge_report_entries, misdated_plan


def test_a_stored_report_replaces_yfinance_s_date_for_the_same_quarter():
    yf = [(date(2026, 10, 13), None, Decimal("4.10")), (date(2026, 7, 15), None, Decimal("3.00"))]     # PGR: yfinance a day early
    stored = [(date(2026, 10, 14), None, Decimal("4.14"))]
    assert [e[0] for e in merge_report_entries(yf, stored)] == [date(2026, 7, 15), date(2026, 10, 14)]


def test_a_stored_report_yfinance_never_listed_is_measured():
    yf = [(date(2026, 7, 14), None, None), (date(2026, 4, 13), None, None)]                            # FAST: no Oct 14 in yfinance
    stored = [(date(2026, 10, 14), None, Decimal("0.35"))]
    assert date(2026, 10, 14) in [e[0] for e in merge_report_entries(yf, stored)]


def test_yfinance_dates_far_from_every_stored_report_stay():
    yf = [(date(2024, 1, 20), None, None)]
    assert merge_report_entries(yf, [(date(2024, 1, 20) + __import__("datetime").timedelta(days=DUPLICATE_GUARD_DAYS + 1), None, None)])[0][0] == date(2024, 1, 20)


def test_an_unmeasured_row_a_day_off_a_stored_report_is_replaced():
    drop, skip = misdated_plan([date(2026, 10, 20)], {date(2026, 10, 19): False, date(2026, 7, 21): True})   # SYF
    assert drop == {date(2026, 10, 19)} and skip == set()


def test_a_measured_row_near_a_stored_report_is_kept_and_the_report_skipped():
    drop, skip = misdated_plan([date(2026, 9, 9)], {date(2026, 9, 10): True})                           # ORCL: never two rows, never a move lost
    assert drop == set() and skip == {date(2026, 9, 9)}


def test_a_report_with_its_own_row_and_rows_on_other_stored_dates_are_left_alone():
    drop, skip = misdated_plan([date(2026, 10, 20), date(2026, 10, 27)], {date(2026, 10, 20): False, date(2026, 10, 27): False})
    assert drop == set() and skip == set()
