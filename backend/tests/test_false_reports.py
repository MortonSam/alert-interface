"""An earnings report is stored only on evidence of one: an Item 2.02 8-K counts when an exhibit states per-share results
(Tesla's deliveries release does not), one release cannot confirm two dates, and validate errors on a confirmed past report with
neither an EPS actual nor a reaction row."""
from datetime import date, timedelta

import pytest
from sqlalchemy import text

from app.database import AsyncSessionLocal
from app.scripts.validate_data import ERROR, PASS, check_reports_have_evidence
from app.services.earnings_calendar import same_release_stale
from app.services.earnings_release import is_results_release, says_results_not_final, states_per_share_results
from app.services.edgar_client import document_names

pytestmark = pytest.mark.xdist_group(name="false_reports")

DELIVERIES = ("Tesla Vehicle Production & Deliveries and Date for Financial Results & Webcast for Third Quarter 2026. In the third quarter, "
              "we produced over 470,000 vehicles and delivered over 497,000 vehicles. Tesla will post its financial results for the third "
              "quarter of 2026 after market close on Wednesday, October 21, 2026.")
EARNINGS = "Net income attributable to common stockholders was $1.17 billion, or $0.33 per diluted share, for the second quarter."
NO_PER_SHARE = ("Targa Resources Corp. today reported second quarter 2026 results. Net income attributable to Targa Resources Corp. was $765 "
                "million. The Company declared a quarterly cash dividend of $1.25 per common share.")


def test_per_share_results_decide_an_item_202_filing():
    assert not states_per_share_results(DELIVERIES)
    assert states_per_share_results(EARNINGS)
    assert states_per_share_results("Adjusted EPS of $2.10 compared with revenue of $4.2 billion")
    assert states_per_share_results("FFO per diluted share was $1.12")
    assert not states_per_share_results("repurchased shares at a weighted average per share price of $259.93")   # no results word near


ABBV_2026_10_05 = ("Item 2.02 Results of Operations and Financial Condition Reported GAAP earnings and adjusted non-GAAP earnings for the third "
                   "quarter of 2026 are expected to include acquired IPR&D and milestones expense of $216 million on a pre-tax basis, representing an "
                   "unfavorable impact of $0.11 to both GAAP diluted earnings per share and adjusted non-GAAP diluted earnings per share. Results for the "
                   "quarter ended September 30, 2026 have not been finalized and are subject to our financial statement closing procedures.")
REGN_2026_10_06 = ("Item 2.02. Results of Operations and Financial Condition. Regeneron currently expects that its financial results calculated in "
                   "accordance with U.S. generally accepted accounting principles and its non-GAAP financial results for the third quarter 2026 will "
                   "include an acquired in-process research and development charge of approximately $22 million on a pre-tax basis. The acquired IPR&D "
                   "charge is expected to negatively impact each of GAAP and non-GAAP net income per diluted share for the third quarter 2026 by "
                   "approximately $0.18. Regeneron\u2019s results for the third quarter 2026 have not been finalized and are subject to Regeneron\u2019s "
                   "financial statement closing procedures.")


def test_an_item_202_filing_whose_results_are_not_final_is_never_a_report():
    # AbbVie's and Regeneron's acquired IPR&D notices state per-share figures, yet say the quarter's results are not final
    for cover in (ABBV_2026_10_05, REGN_2026_10_06):
        assert states_per_share_results(cover) and says_results_not_final(cover)
        assert not is_results_release([cover])
        assert not is_results_release([cover, EARNINGS])          # the guidance exhibit beside the cover does not make it a release
    assert is_results_release(["AbbVie issued a press release announcing its financial results for the quarter ended September 30, 2026.", EARNINGS])
    assert not says_results_not_final(EARNINGS)
    assert not says_results_not_final("as if the Merger had been completed on September 27, 2025. The allocation has not been finalized.")
    assert not is_results_release([DELIVERIES])


# validate's five phantom reports (2026-10-27): Item 2.02 8-Ks with per-share figures that are not the quarter's results
KMB_2026_10_15 = ("Exhibit 99.1 Kimberly-Clark Announces Preliminary Third Quarter 2026 Results and Provides Full Year 2026 Outlook Consistent with "
                  "Previous Expectations Final Third Quarter and Nine Months results to be Released November 5, 2026. Adjusted Earnings per Share "
                  "from Continuing Operations to grow high single digits on a constant-currency basis.")
PRU_2026_10_15 = ("Item 7.01 Regulation FD Disclosure. Prudential Financial, Inc. (the \u201cCompany\u201d) is furnishing this Current Report to "
                  "disclose (1) certain preliminary financial information regarding the quarter ended September 30, 2026. Net income per share "
                  "is expected to be reduced by $0.40.")
UDR_2026_10_21 = ("Item 2.02 Results of Operations and Financial Condition. On October 21, 2026, UDR, Inc. (the \u201cCompany\u201d) issued a press "
                  "release announcing its preliminary financial results for the quarter ended September 30, 2026. Net income per diluted share was $0.12.")
EMR_2026_10_13 = ("Item 2.02 Results of Operations and Financial Condition (Dollars in millions, except per share amounts) On October 13, 2026, "
                  "Emerson Electric Co. announced that, effective for the fiscal year ended September 30, 2026, it has elected to change its method "
                  "of accounting for actuarial gains and losses. Diluted earnings per share common stockholders: Earnings from continuing operations $1.08.")
COR_2026_10_21 = ("Cencora now expects adjusted diluted earnings per share (EPS) to be at least $17.90. The updated financial expectations are based "
                  "on information available as of today and other developments that may arise between the date of the news release and the time "
                  "financial results for the full-year 2026 are finalized.")
GD_RESULTS = ("Exhibit 99.1 General Dynamics Reports Third-Quarter 2016 Results. Net earnings were $844 million, $2.62 per diluted share. "
              + "x" * 1200 + " EXHIBIT G PRELIMINARY FINANCIAL INFORMATION - (UNAUDITED) DOLLARS IN MILLIONS EXCEPT PER SHARE AMOUNTS")


def test_a_preliminary_or_recast_filing_is_never_a_report():
    for text in (KMB_2026_10_15, PRU_2026_10_15, UDR_2026_10_21, EMR_2026_10_13, COR_2026_10_21):
        assert states_per_share_results(text), text[:60]
        assert not is_results_release([text]), text[:60]
        assert not is_results_release([text, EARNINGS]), text[:60]
    assert is_results_release([GD_RESULTS])                 # "preliminary" in its tables, past the headline: still the results


def test_every_exhibit_keeps_releases_whose_names_start_with_r():
    names = ["0001-index.html", "0001-index-headers.html", "R1.htm", "R12.htm", "gehc-20260729.htm", "release2q26earnings.htm",
             "rf-2026630xexhibit991.htm", "logo.jpg"]
    assert document_names(names, every_exhibit=True) == ["gehc-20260729.htm", "release2q26earnings.htm", "rf-2026630xexhibit991.htm"]
    assert "release2q26earnings.htm" not in document_names(names)      # the default filter, kept for the other readers, drops it


def test_one_release_cannot_confirm_two_dates():
    ev = "press release via Finnhub news 2026-09-29: Ares Management Corporation Schedules Earnings Release and Conference Call"
    note = "confirmed: press release via Finnhub news 2026-09-29: Ares Management Corporation Schedule"
    assert same_release_stale(date(2026, 9, 30), note, date(2026, 10, 29), ev, [])
    assert not same_release_stale(date(2026, 10, 29), note, date(2026, 10, 29), ev, [])            # the date it confirms
    assert not same_release_stale(date(2026, 9, 30), note, date(2026, 10, 29), ev, [date(2026, 9, 30)])   # a reaction row stands on it
    assert not same_release_stale(date(2026, 9, 30), "confirmed: Finnhub and Yahoo Finance agree", date(2026, 10, 29), ev, [])


@pytest.mark.asyncio
async def test_validate_errors_on_a_confirmed_past_report_with_no_evidence():
    day = date.today() - timedelta(days=9)
    async with AsyncSessionLocal() as s:
        tid = (await s.execute(text("SELECT id FROM tickers WHERE symbol = 'TSLA'"))).scalar()
        await s.execute(text("DELETE FROM events WHERE ticker_id = :t AND event_type = 'earnings' AND event_date = :d"), {"t": tid, "d": day})
        await s.execute(text("""INSERT INTO events (id, ticker_id, event_type, event_date, title, source, is_confirmed, confirmation_note, metadata, created_at, updated_at)
            VALUES (gen_random_uuid(), :t, 'earnings', :d, 'TSLA Earnings', 'edgar', true, 'reported per EDGAR (8-K Item 2.02)', '{}', now(), now())"""), {"t": tid, "d": day})
        await s.commit()
        try:
            r = await check_reports_have_evidence(s)
            assert r.level == ERROR and any(row.startswith(f"TSLA  reported {day}") for row in r.rows)
        finally:
            await s.execute(text("DELETE FROM events WHERE ticker_id = :t AND event_type = 'earnings' AND event_date = :d"), {"t": tid, "d": day})
            await s.commit()


def test_a_past_report_on_an_8k_alone_is_removed_once_the_company_confirms_the_real_date():
    from app.services.earnings_calendar import edgar_only_report_superseded
    note = "reported on 2026-10-15 per EDGAR (8-K Item 2.02)"
    d = date(2026, 10, 15)
    assert edgar_only_report_superseded(d, note, [], [], [date(2026, 11, 5)]) == date(2026, 11, 5)          # KMB: preliminary figures, real report Nov 5
    assert edgar_only_report_superseded(d, note, [date(2026, 10, 15)], [], [date(2026, 11, 5)]) is None     # a reaction row stands on it
    assert edgar_only_report_superseded(d, note, [], [date(2026, 10, 16)], [date(2026, 11, 5)]) is None     # an EPS actual says it was the report
    assert edgar_only_report_superseded(d, note, [], [], [date(2027, 1, 20)]) is None                       # the next quarter's date, not this report's
    assert edgar_only_report_superseded(d, "reported on 2026-10-15 per Finnhub (actual EPS)", [], [], [date(2026, 11, 5)]) is None
    assert edgar_only_report_superseded(d, "confirmed: press release", [], [], [date(2026, 11, 5)]) is None
