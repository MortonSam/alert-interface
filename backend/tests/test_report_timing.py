"""The report-timing rule, on the real cases that shaped it."""
from datetime import date

from app.services.report_timing import (
    EASTERN_CLOCK_TICKERS,
    PATTERN_MIN_DECISIVE,
    Filing,
    acceptance_bucket,
    classify,
    parse_acceptance,
    select_filing,
    ticker_pattern,
)


def _filing(raw: str, filing_date: date, earnings: bool = True) -> Filing:
    return Filing(filing_date, parse_acceptance(raw), earnings)


def test_schw_files_after_the_close_but_reports_pre_market():
    # 8-K accepted 16:17 ET every quarter; price shows the news in that day's open.
    d = date(2024, 10, 15)
    f = _filing("2024-10-15T20:17:00.000Z", d)
    out = classify("SCHW", d, f, pattern="bmo", stored_timing="amc")
    assert (out.timing, out.source) == ("bmo", "accepted_post_close_pattern_bmo")
    # The same filing on a ticker without a pre-market pattern is after-close.
    assert classify("AAPL", d, f, pattern="amc").timing == "amc"
    assert classify("XYZ", d, f, pattern="mixed").timing == "amc"


def test_ttwo_stamp_is_eastern_clock_time():
    assert "TTWO" in EASTERN_CLOCK_TICKERS
    d = date(2025, 2, 6)
    f = _filing("2025-02-06T16:11:34.000Z", d)     # raw clock 16:11, no seasonal shift
    assert acceptance_bucket("TTWO", f.acceptance, d) == "post_close"
    assert classify("TTWO", d, f, pattern="amc", stored_timing="bmo").timing == "amc"
    # Read as true UTC (any other ticker) the same stamp is 11:11 ET, intraday.
    assert acceptance_bucket("OTHER", f.acceptance, d) == "intraday"


def test_dri_pre_open_acceptance_is_bmo_whatever_was_stored():
    d = date(2024, 9, 19)
    f = _filing("2024-09-19T11:05:00.000Z", d)     # 07:05 ET
    out = classify("DRI", d, f, pattern="bmo", stored_timing="amc")
    assert (out.timing, out.source) == ("bmo", "accepted_pre_open")


def test_adbe_2021_12_16_pre_open_filing_beats_an_after_close_pattern():
    # ADBE normally reports after the close; this quarter the 8-K was accepted 08:06 ET.
    d = date(2021, 12, 16)
    f = _filing("2021-12-16T13:06:00.000Z", d)
    out = classify("ADBE", d, f, pattern="amc", stored_timing="bmo")
    assert (out.timing, out.source) == ("bmo", "accepted_pre_open")


def test_mixed_pattern_ticker_follows_the_acceptance_bound_only():
    assert ticker_pattern(["bmo"] * 5 + ["amc"] * 5).pattern == "mixed"
    d = date(2025, 4, 24)
    after = _filing("2025-04-24T20:04:00.000Z", d)   # 16:04 ET
    before = _filing("2025-04-24T11:00:00.000Z", d)  # 07:00 ET
    assert classify("TMUS", d, after, pattern="mixed").timing == "amc"
    assert classify("TMUS", d, before, pattern="mixed").timing == "bmo"
    # No filing and no pattern to lean on: unknown, even if something was stored.
    assert classify("TMUS", d, None, pattern="mixed", stored_timing="amc").timing == "unknown"


def test_intraday_acceptance_on_an_after_close_ticker_is_a_contradiction():
    d = date(2023, 5, 17)
    f = _filing("2023-05-17T17:30:00.000Z", d)     # 13:30 ET
    out = classify("AMC_CO", d, f, pattern="amc", stored_timing="amc")
    assert out.timing == "unknown"
    assert out.source == "contradiction_intraday_vs_amc_pattern"
    # On a pre-market or mixed ticker the same filing uses the bmo window.
    assert classify("DHI", d, f, pattern="bmo").timing == "bmo"
    assert classify("MIX", d, f, pattern="mixed").source == "accepted_intraday"


def test_prior_evening_and_next_morning_filings():
    d = date(2024, 2, 2)
    assert acceptance_bucket("X", parse_acceptance("2024-02-01T22:30:00.000Z"), d) == "pre_open"    # 17:30 ET on T-1
    assert acceptance_bucket("X", parse_acceptance("2024-02-03T11:35:00.000Z"), d) == "post_close"  # 06:35 ET on T+1
    assert acceptance_bucket("X", parse_acceptance("2024-02-05T11:35:00.000Z"), d) == "far"
    assert classify("X", d, _filing("2024-02-05T11:35:00.000Z", date(2024, 2, 5)), "bmo").timing == "unknown"


def test_pattern_thresholds():
    assert ticker_pattern(["bmo"] * 8 + ["amc"] * 2).pattern == "bmo"          # 80%
    assert ticker_pattern(["bmo"] * 7 + ["amc"] * 3).pattern == "mixed"        # 70%
    assert ticker_pattern(["amc"] * 9 + ["bmo"]).pattern == "amc"
    assert ticker_pattern(["bmo"] * (PATTERN_MIN_DECISIVE - 1)).pattern == "mixed"  # too few rows
    assert ticker_pattern(["none", "off"]).decisive_rows == 0


def test_select_filing_prefers_item_202_and_flags_the_fallback():
    d = date(2025, 1, 15)
    filings = [
        ("2025-01-15", "2025-01-15T21:30:00.000Z", "8.01"),          # unrelated 8-K, after close
        ("2025-01-15", "2025-01-15T11:44:00.000Z", "2.02,9.01"),     # earnings, 06:44 ET
    ]
    chosen = select_filing(filings, d)
    assert chosen.is_earnings_item and chosen.acceptance.hour == 11
    fallback = select_filing([filings[0]], d)
    assert fallback is not None and not fallback.is_earnings_item
    assert classify("BLK", d, fallback, "mixed").source == "accepted_post_close_any8k"
    assert select_filing([], d) is None
