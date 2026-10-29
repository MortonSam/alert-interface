"""The stuck-count guard (services/reaction_count_guard): a count unchanged over 3 trading sessions while 5+ S&P 500 companies
reported warns; a moving count, a quiet week or a short history passes."""
from datetime import date

from app.services.reaction_count_guard import STUCK_MIN_REPORTS, STUCK_SESSIONS, stuck_window, verdict

SESSIONS = [date(2026, 10, 22), date(2026, 10, 23), date(2026, 10, 26), date(2026, 10, 27), date(2026, 10, 28)]


def test_the_count_that_sat_at_10000_while_companies_reported_warns():
    counts = {"2026-10-24": 10000, "2026-10-26": 10000, "2026-10-27": 10000, "2026-10-28": 10000, "2026-10-29": 10000}
    w = stuck_window(counts, SESSIONS)
    assert w == (date(2026, 10, 26), date(2026, 10, 28), 10000, 10000)
    stuck, detail = verdict(w, reports=92)
    assert stuck and "10,000" in detail and "92 S&P 500 companies" in detail


def test_a_moving_count_passes():
    counts = {"2026-10-26": 10000, "2026-10-29": 10026}
    assert verdict(stuck_window(counts, SESSIONS), reports=92)[0] is False


def test_a_quiet_stretch_with_few_reports_passes():
    counts = {"2026-10-26": 10000, "2026-10-29": 10000}
    assert verdict(stuck_window(counts, SESSIONS), reports=STUCK_MIN_REPORTS - 1)[0] is False


def test_too_little_history_passes():
    assert verdict(stuck_window({"2026-10-29": 10000}, SESSIONS), reports=50) == (False, "not enough nightly counts recorded yet")
    assert stuck_window({"2026-10-29": 1}, SESSIONS[:STUCK_SESSIONS - 1]) is None
