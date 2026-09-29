"""One answer to 'when next': confirmed future, else nearest estimate, else a passed estimate as 'expected around'."""
from datetime import date
from types import SimpleNamespace

from app.services.next_earnings import choose

TODAY = date(2026, 9, 29)


def ev(d, confirmed=False, unresolved=None, source="finnhub", note=None):
    return SimpleNamespace(event_date=d, is_confirmed=confirmed, unresolved_since=unresolved, source=source, confirmation_note=note)


def test_confirmed_future_beats_a_nearer_estimate():
    got = choose([ev(date(2026, 10, 1), source="yfinance", note="estimated (Yahoo Finance)"),
                  ev(date(2026, 10, 2), confirmed=True, source="edgar", note="confirmed: 8-K Item 7.01 filed 2026-09-16")], TODAY)
    assert got == (date(2026, 10, 2), "edgar", "confirmed", "confirmed: 8-K Item 7.01 filed 2026-09-16")


def test_nearest_estimate_then_the_passed_estimate_as_expected_around():
    assert choose([ev(date(2026, 12, 16), note="estimated (Finnhub)"), ev(date(2026, 10, 1), source="yfinance", note="estimated (Yahoo Finance)")], TODAY)[0] == date(2026, 10, 1)
    got = choose([ev(date(2026, 9, 28), unresolved=date(2026, 9, 29), note="expected around 2026-09-28; not confirmed by Finnhub, Yahoo Finance or EDGAR"),
                  ev(date(2026, 6, 30), source="yfinance")], TODAY)
    assert got[0] == date(2026, 9, 28) and got[2] == "expected_unconfirmed"
    assert choose([ev(date(2026, 6, 30))], TODAY) == (None, None, None, None)
