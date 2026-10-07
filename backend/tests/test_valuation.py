"""Trailing P/E from filings: the release parser on Micron's Sep 30, 2026 exhibit text, quarterly facts with the derived
fourth quarter, the freshness rule (the window must hold the latest reported quarter), the history summary with its
exclusions, the release-against-XBRL flag, and the checker's quarter match."""
from datetime import date

from app.scripts.check_release_eps import matching_quarter
from app.scripts.seed_release_eps import exhibit_text
from app.services import valuation as V

MU_RELEASE = ("MICRON TECHNOLOGY, INC. REPORTS RESULTS FOR THE FOURTH QUARTER AND FULL YEAR OF FISCAL 2026. Fiscal Q4 2026 highlights • Revenue of $54.23 billion "
              "versus $41.46 billion for the prior quarter • GAAP net income of $37.70 billion, or $32.87 per diluted share • Non-GAAP net income of $38.40 billion, "
              "or $33.42 per diluted share • Fiscal 2026 Highlights • GAAP net income of $84.97 billion, or $74.33 per diluted share • Non-GAAP net income of $86.76 billion, "
              "or $75.52 per diluted share. 4th Qtr. 3rd Qtr. 4th Qtr. Year Ended September 3, 2026 May 28, 2026 August 28, 2025 "
              "GAAP diluted earnings per share $ 32.87 $ 24.67 $ 2.83 $ 74.33 $ 7.59 Non-GAAP diluted earnings per share $ 33.42 $ 25.11 $ 3.03")
TABLE_ONLY = ("Results for the quarter ended June 30, 2026. Non-GAAP diluted earnings per share $ 2.10 $ 1.90 "
              "Diluted earnings per share $ 1.84 $ 1.62 Weighted average shares 1,000")


def test_release_parser_reads_the_quarters_gaap_figure_not_the_years_or_the_non_gaap_one():
    hit = V.parse_release_eps(MU_RELEASE, date(2026, 9, 30))
    assert hit["eps"] == 32.87 and hit["how"] == "highlights sentence" and hit["period_end"] == date(2026, 9, 3)
    assert "$32.87 per diluted share" in hit["evidence"]
    hit = V.parse_release_eps(TABLE_ONLY)
    assert hit["eps"] == 1.84 and hit["how"] == "diluted EPS row" and hit["period_end"] == date(2026, 6, 30)   # the non-GAAP row is skipped
    assert V.parse_release_eps("Revenue grew nicely. Adjusted diluted earnings per share $ 3.00") is None
    assert V.parse_release_eps("") is None


def q(end, eps, filed, start=None, form="10-Q"):
    return {"end": end, "start": start or (end.replace(month=end.month - 2) if end.month > 2 else end.replace(year=end.year - 1, month=end.month + 10)),
            "eps": eps, "filed": filed, "form": form, "derived": False, "source": "xbrl"}


MU_Q = [q(date(2025, 8, 28), 2.83, date(2025, 10, 3), form="10-K"), q(date(2025, 11, 27), 4.60, date(2025, 12, 18), start=date(2025, 8, 29)), q(date(2026, 2, 26), 12.07, date(2026, 3, 19)),
        q(date(2026, 5, 28), 24.67, date(2026, 6, 25))]


def test_eps_quarters_derives_the_fourth_quarter_from_the_annual_fact():
    facts = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [
        {"start": "2025-01-01", "end": "2025-03-31", "val": 1.0, "filed": "2025-05-01", "form": "10-Q"},
        {"start": "2025-04-01", "end": "2025-06-30", "val": 1.1, "filed": "2025-08-01", "form": "10-Q"},
        {"start": "2025-07-01", "end": "2025-09-30", "val": 1.2, "filed": "2025-11-01", "form": "10-Q"},
        {"start": "2025-01-01", "end": "2025-12-31", "val": 4.6, "filed": "2026-02-15", "form": "10-K"},
        {"start": "2025-01-01", "end": "2025-06-30", "val": 2.1, "filed": "2025-08-01", "form": "10-Q"},      # a six-month fact is neither
    ]}}}}}
    qs = V.eps_quarters(facts)
    assert [(x["end"].isoformat(), x["eps"], x["derived"]) for x in qs] == [("2025-03-31", 1.0, False), ("2025-06-30", 1.1, False), ("2025-09-30", 1.2, False), ("2025-12-31", 1.3, True)]


def test_the_window_must_hold_the_latest_reported_quarter():
    today = date(2026, 10, 7)
    four, why = V.fresh_window(MU_Q, date(2026, 9, 30), None, today)
    assert four is None and "release EPS is not stored" in why                                           # Sep 30 reported, XBRL through May 28
    four, why = V.fresh_window(MU_Q, date(2026, 9, 30), {"eps": 32.87, "period_end": date(2026, 9, 3), "accession": "0000723125-26-000018"}, today)
    assert [x["eps"] for x in four] == [4.60, 12.07, 24.67, 32.87] and four[-1]["source"] == "release" and why.startswith("three XBRL")
    assert V.pe(1063.96, four) == 14.34 and V.period_label(four) == "2025-08-29 to 2026-09-03"
    four, why = V.fresh_window(MU_Q, date(2026, 6, 25), None, today)                                   # the latest report is in XBRL already
    assert [x["eps"] for x in four] == [2.83, 4.60, 12.07, 24.67] and why.startswith("XBRL holds")
    assert V.fresh_window(MU_Q[:3], None, None, today) == (None, "fewer than four reported quarters in XBRL")


def test_history_reports_median_and_share_above_and_counts_exclusions():
    bars = [(date(2026, 7, 1), 100.0), (date(2026, 7, 2), 1000.0), (date(2026, 7, 3), 120.0), (date(2026, 7, 6), 110.0)]
    qs = [q(date(2025, 9, 30), 2.0, date(2025, 11, 1)), q(date(2025, 12, 31), 2.0, date(2026, 2, 1)), q(date(2026, 3, 31), 2.0, date(2026, 5, 1)), q(date(2026, 6, 30), 2.0, date(2026, 6, 30))]
    h = V.pe_history(bars, qs, current=13.0)
    assert h["sessions"] == 3 and h["excluded"] == 1                                                  # 1000/8 = 125 is excluded (EPS under 1% of price)
    assert h["median"] == 13.8 and h["share_above"] == 33 and "min" not in h and "max" not in h
    neg = [q(date(2025, 9, 30), -7.0, date(2025, 11, 1))] + qs[1:]
    assert V.pe_history(bars, neg, 10.0)["excluded"] == 4                                              # negative trailing EPS


def test_release_against_xbrl_and_the_checkers_match():
    assert V.release_difference(32.87, 32.87) == (0.0, False)
    assert V.release_difference(32.87, 32.99) == (-0.12, True)
    assert V.release_difference(1.84, 1.85) == (-0.01, False)
    later = MU_Q + [q(date(2026, 9, 3), 32.87, date(2026, 10, 20), form="10-K")]
    assert matching_quarter(later, date(2026, 9, 3), date(2026, 9, 30))["eps"] == 32.87
    assert matching_quarter(later, None, date(2026, 9, 30))["eps"] == 32.87                          # newest quarter before the report, filed after it
    assert matching_quarter(MU_Q, date(2026, 9, 3), date(2026, 9, 30)) is None                        # not filed yet
    assert exhibit_text([("form8k.htm", "x" * 600), ("a2026q4ex991-pressrelease.htm", "y" * 600)])[0] == "a2026q4ex991-pressrelease.htm"
