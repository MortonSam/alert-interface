"""A company announcement of a results date is recognised from wire copy and 8-K text, and nothing else."""
from datetime import date

from app.services.report_announcements import edgar_ir_8ks, find_announced_date, from_news

TODAY = date(2026, 9, 29)
NKE_RELEASE = ("NIKE, Inc. to Announce First Quarter Fiscal 2027 Results. BEAVERTON, Ore.--(BUSINESS WIRE)--Aug 28, 2026-- "
               "NIKE, Inc. (NYSE: NKE) plans to release its first quarter fiscal 2027 financial results on Thursday, "
               "October 1, 2026, after the market closes. Following the news release, management will host a conference call.")


def test_nke_press_release_names_oct_1_after_the_close():
    hit = find_announced_date(NKE_RELEASE, date(2026, 8, 28), "press release via Finnhub news 2026-08-28")
    assert hit is not None and hit.day == date(2026, 10, 1) and hit.timing == "amc"
    assert hit.evidence == "press release via Finnhub news 2026-08-28"


def test_a_date_without_a_results_sentence_is_not_an_announcement():
    assert find_announced_date("NIKE named a new director on September 15, 2026.", TODAY, "x") is None
    assert find_announced_date("Results were released on June 30, 2026.", TODAY, "x") is None    # past
    assert find_announced_date("The company will report results on March 3, 2027.", TODAY, "x") is None   # beyond the horizon


def test_news_items_are_scanned_newest_first_with_their_publish_date_in_the_evidence():
    items = [{"datetime": 1787000000, "headline": "NIKE, Inc. to Announce First Quarter Fiscal 2027 Results",
              "summary": "NIKE, Inc. plans to release its first quarter fiscal 2027 financial results on Thursday, October 1, 2026, after the market closes."},
             {"datetime": 1786000000, "headline": "Nike names new CFO", "summary": "no date here"}]
    hit = from_news(items, TODAY)
    assert hit is not None and hit.day == date(2026, 10, 1)
    assert hit.evidence.startswith("press release via Finnhub news 2026-08-") and "NIKE, Inc. to Announce" in hit.evidence


def test_ir_8ks_are_items_701_or_801_in_the_window():
    records = [{"filing_date": "2026-09-16", "items": "5.02,7.01,9.01", "accession": "a"},
               {"filing_date": "2026-09-10", "items": "5.02,5.07,9.01", "accession": "b"},
               {"filing_date": "2026-07-01", "items": "8.01", "accession": "c"}]
    assert [r["accession"] for r in edgar_ir_8ks(records, TODAY)] == ["a"]
