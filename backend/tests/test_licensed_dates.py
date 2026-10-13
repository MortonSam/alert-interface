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
    assert w.start <= w.center <= w.end and (w.end - w.start).days <= 3 + W.FILING_LAG_DAYS and w.pairs == 8 and w.computation_version == W.WINDOW_VERSION
    assert w.start == date(2026, 10, 21)                     # the earliest shift (none), then FILING_LAG_DAYS for a filing that trails the release
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


def test_item_202_marks_earnings_unless_a_company_files_it_more_than_about_four_times_a_year():
    today = date(2026, 10, 13)
    quarterly = [{"filing_date": f"20{y}-{m:02d}-20", "accession": f"q{y}{m}"} for y in (24, 25, 26) for m in (1, 4, 7, 10) if f"20{y}-{m:02d}-20" < "2026-10-13"]
    assert not W.is_ambiguous(quarterly, "2023-09-01", today)                  # four a year: the item's word
    tesla = quarterly + [{"filing_date": f"20{y}-{m:02d}-02", "accession": f"d{y}{m}"} for y in (24, 25, 26) for m in (1, 4, 7, 10) if f"20{y}-{m:02d}-02" < "2026-10-13"]
    assert W.is_ambiguous(tesla, "2023-09-01", today)                          # deliveries under the same item: documents decide
    stray = quarterly + [{"filing_date": "2025-11-03", "accession": "x"}]
    assert W.is_ambiguous(stray, "2023-09-01", today)                          # one stray filing in one year is enough, though it averages under five a year
    assert not W.is_ambiguous([{"filing_date": d} for d in ("2025-10-14", "2026-01-13", "2026-04-14", "2026-07-14", "2026-10-13")])   # five reports a year apart are four per span
    assert W.years_covered(None, today) == 0.25 and W.years_covered("2010-01-01", today) == W.HISTORY_DAYS / 365.25
    # not ambiguous: nothing is read and every filing is stored on the item's word
    assert W.to_read(quarterly, {}, False) == []
    v = W.verdicts(quarterly, {}, False, {})
    assert len(v) == len(quarterly) and all(x == {"filed": f["filing_date"], "earnings": True, "basis": "item"} for f, x in zip(quarterly, v.values()))
    # ambiguous: only filings without a stored document verdict are read; a failed read is left for the next night
    stored = {"q241": {"filed": "2024-01-20", "earnings": True, "basis": "document"}, "d241": {"filed": "2024-01-02", "earnings": False, "basis": "document"},
              "q244": {"filed": "2024-04-20", "earnings": True, "basis": "item"}}
    need = {f["accession"] for f in W.to_read(tesla, stored, True)}
    assert "q241" not in need and "d241" not in need and "q244" in need and len(need) == len(tesla) - 2
    out = W.verdicts(tesla, stored, True, {"q244": True, "d244": False})
    assert out["d241"]["earnings"] is False and out["q244"] == {"filed": "2024-04-20", "earnings": True, "basis": "document"}
    assert "q247" not in out and len(out) == 4                                 # unread tonight: no verdict stored, no date used
    assert W.WINDOW_VERSION == 2


def test_the_window_stays_until_its_end_passes():
    # reports a year ago on 2025-10-10 and shifts up to +4 days: on 2026-10-12 the centre (2026-10-09) has passed but the window is open
    reports = [date(2026, 7, 14), date(2026, 4, 14), date(2026, 1, 14), date(2025, 10, 10), date(2025, 7, 15), date(2025, 4, 11), date(2025, 1, 15), date(2024, 10, 11),
               date(2024, 7, 12), date(2024, 4, 12), date(2024, 1, 12), date(2023, 10, 13)]
    w = W.expected_window("BLKX", reports, date(2026, 10, 12))
    assert w is not None and w.center == date(2026, 10, 9) and w.end >= date(2026, 10, 12)
    w = W.expected_window("BLKX", reports, date(2026, 10, 30))                 # the window closed with no filing: the following quarter
    assert w is not None and w.center.month == 1


def test_a_guidance_update_before_each_report_never_stands_in_for_the_report():
    # ABBV's Item 2.02 filings with per-share figures: an update early in the month, the report at its end
    abbv = [date(2026, 10, 5), date(2026, 7, 31), date(2026, 7, 6), date(2026, 4, 29), date(2026, 4, 3), date(2026, 2, 4), date(2026, 1, 7), date(2025, 10, 31),
            date(2025, 10, 3), date(2025, 7, 25), date(2025, 7, 7), date(2025, 4, 25), date(2025, 4, 4), date(2025, 1, 31), date(2025, 1, 6), date(2024, 10, 30), date(2024, 10, 4)]
    w = W.expected_window("ABBV", abbv, date(2026, 10, 13))
    assert w is not None and w.center == date(2026, 10, 30) and w.start <= date(2026, 10, 30) <= w.end
    # a company that reported today projects its following report, not today's
    jpm = [date(2026, 10, 13), date(2026, 7, 14), date(2026, 4, 14), date(2026, 1, 13), date(2025, 10, 14), date(2025, 7, 15), date(2025, 4, 11), date(2025, 1, 15), date(2024, 10, 11)]
    assert W.expected_window("JPM", jpm, date(2026, 10, 13)).center == date(2027, 1, 12)
