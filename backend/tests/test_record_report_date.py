"""record_report_date: the company's own date replaces the estimates for the same report and nothing else."""
from datetime import date, timedelta
from types import SimpleNamespace

from app.scripts.record_report_date import note_for, plan_changes


def test_plan_replaces_the_same_reports_estimates_only():
    today = date(2026, 10, 7)
    ev = lambda d, confirmed=False: SimpleNamespace(event_date=d, is_confirmed=confirmed)
    stored = [ev(date(2026, 9, 16)), ev(date(2026, 10, 12)), ev(date(2026, 12, 16)), ev(date(2027, 1, 20), True)]
    same, drop = plan_changes(stored, date(2026, 10, 28), today)
    assert same is None and [e.event_date for e in drop] == [date(2026, 10, 12)]     # Sep 16 is past; Dec 16 is later (the next quarter); Jan 20 is confirmed
    same, drop = plan_changes(stored + [ev(date(2026, 10, 28))], date(2026, 10, 28), today)
    assert same is not None and same.event_date == date(2026, 10, 28)
    assert note_for("https://investors.fedex.com/x") == "confirmed: company announcement https://investors.fedex.com/x"
