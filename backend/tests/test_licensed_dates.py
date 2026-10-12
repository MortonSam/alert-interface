"""Vendor calendars are personal-use only (Intrinio's terms, 2026-10-12): with LICENSED_DATES_ONLY a page shows a date only when the
company's own words confirmed it, and otherwise an expected window from the company's past report dates in SEC filings."""
from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.services import report_windows as W
from app.services.earnings_calendar import AGREEMENT_NOTE, company_confirmed, shown_level
from app.services.next_earnings import EXPECTED_WINDOW, choose


def test_only_the_companys_own_words_confirm_a_shown_date():
    assert company_confirmed(True, "confirmed: 8-K Item 2.02 exhibit991.htm filed 2026-10-02: Tesla will post ...")
    assert company_confirmed(True, "confirmed: press release via Finnhub news 2026-09-21: CSX Corp. will release ...")
    assert company_confirmed(True, "confirmed: press release via IR feed 2026-10-06 https://x: ...")
    assert company_confirmed(True, "confirmed: events feed via IR 2026-10-06: ...")
    assert not company_confirmed(True, AGREEMENT_NOTE)                       # two vendor calendars agreeing is not the company
    assert not company_confirmed(False, "estimated (Yahoo Finance)")
    assert shown_level(True, AGREEMENT_NOTE, None, licensed_only=False) == "confirmed"      # unchanged while the flag is off
    assert shown_level(True, AGREEMENT_NOTE, None, licensed_only=True) is None              # no date at all with it on
    assert shown_level(False, "estimated (Finnhub)", None, licensed_only=True) is None
    assert shown_level(True, "confirmed: 8-K Item 7.01 filed 2026-09-10", None, licensed_only=True) == "confirmed"


def test_the_next_earnings_choice_hides_vendor_dates_under_the_flag():
    ev = lambda d, conf, note, src="yfinance": SimpleNamespace(event_date=d, is_confirmed=conf, confirmation_note=note, unresolved_since=None, source=src)
    today = date(2026, 10, 12)
    events = [ev(date(2026, 10, 21), False, "estimated (Yahoo Finance)"), ev(date(2027, 1, 27), True, AGREEMENT_NOTE, "finnhub")]
    assert choose(events, today, licensed_only=False)[0] == date(2027, 1, 27)          # today's rule: a confirmed date first, whoever confirmed it
    assert choose(events, today, licensed_only=True) == (None, None, None, None)
    events.append(ev(date(2026, 10, 21), True, "confirmed: 8-K Item 2.02 exhibit991.htm filed 2026-10-02: Tesla will post ...", "edgar"))
    assert choose(events, today, licensed_only=True) == (date(2026, 10, 21), "edgar", "confirmed", events[-1].confirmation_note)
    assert EXPECTED_WINDOW == "expected_window"


def test_the_expected_window_comes_from_the_companys_own_filing_dates():
    # eight quarters of Item 2.02 filings, each a day or two off its year-earlier date; the next report projects a year forward
    reports = [date(2026, 7, 23), date(2026, 4, 23), date(2026, 1, 22), date(2025, 10, 23), date(2025, 7, 24), date(2025, 4, 24), date(2025, 1, 23), date(2024, 10, 24),
               date(2024, 7, 25), date(2024, 4, 25), date(2024, 1, 25), date(2023, 10, 26)]
    w = W.expected_window("ZZW", reports, date(2026, 10, 12), datetime(2026, 10, 12, tzinfo=timezone.utc))
    assert w is not None and w.center == date(2025, 10, 23).replace(year=2026) + (date(2026, 10, 22) - date(2026, 10, 23))      # 2025-10-23 + 364 days = 2026-10-22
    assert w.start <= w.center <= w.end and (w.end - w.start).days <= 3 and w.pairs == 8 and w.computation_version == W.WINDOW_VERSION
    assert w.source == "past report dates in SEC filings (8-K Item 2.02)" and w.as_record()["center"] == "2026-10-22"
    assert W.expected_window("ZZW", reports[:3], date(2026, 10, 12)) is None                 # three reports, no year-over-year pairs
    assert W.yoy_pairs([date(2026, 7, 23), date(2025, 7, 24)]) == [(date(2026, 7, 23), date(2025, 7, 24))]
    recs = [{"filing_date": "2026-07-23", "items": "2.02,9.01", "accession": "a"}, {"filing_date": "2026-07-23", "items": "2.02", "accession": "dup"},
            {"filing_date": "2026-06-01", "items": "7.01", "accession": "b"}, {"filing_date": "2022-01-01", "items": "2.02", "accession": "old"}]
    assert [f["accession"] for f in W.release_filing_dates(recs, date(2026, 10, 12))] == ["a"]
    assert W.window_from_record('{"computation_version": 0}') is None and W.window_from_record(None) is None


def test_the_window_step_follows_the_reader_in_the_nightly():
    from app.scripts import refresh
    labels = [l for l, _ in refresh.STEPS]
    assert labels.index("Expected report windows (SEC filings)") == labels.index("Report date confirmations (reader)") + 1
