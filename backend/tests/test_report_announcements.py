"""A company announcement of a results date is recognised from wire copy and 8-K text, and nothing else."""
from datetime import date

from app.services.report_announcements import edgar_ir_8ks, find_announced_date, from_news, issuer_forms, names_issuer

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


# ── The announcing entity must be the issuer (production dry run, 2026-09-30) ────────────────────────────

GM_FINANCIAL = {"datetime": 1789000000, "headline": "GM Financial to Release Third Quarter 2026 Operating Results",
                "summary": "GM Financial will release its third quarter 2026 operating results on Tuesday, October 20, 2026."}
GPC_RELEASE = {"datetime": 1789000000, "headline": "Genuine Parts Company to Report Third Quarter 2026 Results on October 20, 2026",
               "summary": "Genuine Parts Company will report its third quarter 2026 results on Tuesday, October 20, 2026, before the market opens."}


def test_gm_financials_release_is_not_general_motors_and_genuine_parts_release_is_genuine_parts():
    assert names_issuer(GM_FINANCIAL["headline"], "General Motors Company") is False
    assert from_news([GM_FINANCIAL], TODAY, issuer="General Motors Company") is None
    assert from_news([GM_FINANCIAL], TODAY) is not None, "without the issuer the date rule alone would have taken it"
    assert names_issuer(GPC_RELEASE["headline"], "Genuine Parts Company") is True
    hit = from_news([GPC_RELEASE], TODAY, issuer="Genuine Parts Company")
    assert hit is not None and hit.day == date(2026, 10, 20)
    assert hit.evidence.endswith("Genuine Parts Company to Report Third Quarter 2026 Results on October 20, 2026")


def test_the_issuer_may_be_named_in_full_by_its_legal_short_form_or_a_distinctive_first_word():
    assert issuer_forms("General Motors Company") == ["general motors company", "general motors"]        # "General" is too generic
    assert issuer_forms("Verizon Communications Inc.") == ["verizon communications inc", "verizon communications", "verizon"]
    assert issuer_forms("Kimco Realty Corporation (HC)") == ["kimco realty corporation", "kimco realty", "kimco"]
    assert issuer_forms("JPMorgan Chase & Co.") == ["jpmorgan chase co", "jpmorgan chase", "jpmorgan"]
    accepted = [
        ("JPMorganChase to Host Third-Quarter 2026 Earnings Call", "JPMorgan Chase & Co."),
        ("Bristol Myers Squibb to Report Results for Third Quarter 2026 on October 29, 2026", "Bristol-Myers Squibb Company"),
        ("Kimco Realty\u00ae Invites You to Join Its Third Quarter Earnings Conference Call", "Kimco Realty Corporation (HC)"),
        ("Halliburton Third Quarter 2026 Earnings Conference Call", "Halliburton Company"),
        ("Verizon to report third-quarter earnings October 26, 2026", "Verizon Communications Inc."),
        ("T-Mobile to Host Q3 2026 Earnings Call on October 28, 2026", "T-Mobile US, Inc."),
        ("Citizens Financial Group Announces Third Quarter 2026 Earnings Conference Call Details", "Citizens Financial Group, Inc."),
        ("M&T Bank Corporation Announces Third Quarter 2026 Earnings Release", "M&T Bank Corporation"),
        ("D.R. Horton, Inc. to Release 2026 Fourth Quarter Earnings on October 29, 2026", "D.R. Horton, Inc."),
        ("SLB Announces Date for Third-Quarter 2026 Results Conference Call", "SLB N.V."),
        ("UnitedHealth Group Announces Earnings Release Date", "UnitedHealth Group Incorporated"),
    ]
    for headline, name in accepted:
        assert names_issuer(headline, name), (headline, name)
    rejected = [
        ("GM Financial to Release Third Quarter 2026 Operating Results", "General Motors Company"),
        ("General Motors Financial Company to Release Third Quarter Results", "General Motors Company"),   # subsidiary on the parent's name
        ("Quest Software to Report Third Quarter Results", "Quest Diagnostics Incorporated"),               # another company
        ("Comcast Foundation Announces Grants", "Comcast Corporation"),
        ("Conagra Brands to Release Fiscal 2027 First Quarter Earnings on September 30, 2026", "General Motors Company"),
        ("General Electric to Report Third Quarter Results", "General Motors Company"),
        ("Verizons to report", "Verizon Communications Inc."),
    ]
    for headline, name in rejected:
        assert not names_issuer(headline, name), (headline, name)


def test_the_calendar_step_passes_each_tickers_stored_name_to_the_matcher():
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1] / "app" / "scripts" / "refresh_earnings_calendar.py").read_text()
    assert "names = {t.symbol: t.name for t in tickers if t.name}" in src
    assert "hit = from_news(news, today, names.get(sym))" in src
    assert "fetch_announcements(finnhub, edgar, near, today, announce_budget_s, names)" in src
