"""Block 2 (2026-10-20): the bank and insurer releases of Oct 13 to 16 that stored nothing, one worked example per cause, each from the
exhibit's own text (flattened as the readers read it)."""
from datetime import date

from app.services import release_reader as R
from app.services.valuation import clean_labels, current_column, parse_release_eps

# FAST 2026-10-14, the performance summary: the year to date comes before the quarter
FAST = ("PERFORMANCE SUMMARY Nine-month Period Three-month Period 2026 2025 Change 2026 2025 Change Net sales $ 7,051.9 6,173.1 14.2 % "
        "$ 2,463.3 2,133.3 15.5 % Net income $ 1,124.2 964.4 16.6 % $ 401.6 335.5 19.7 % Diluted net income per share $ 0.98 0.84 16.5 % "
        "$ 0.35 0.29 19.8 % Note – Daily sales rate (DSR) is defined as the total net sales for the period")
# STT 2026-10-14: the current quarter is the third column ("3Q25 2Q26 3Q26")
STT = ("Quarters % Change 3Q25 2Q26 3Q26 3Q26 vs. 2Q26 3Q26 vs. 3Q25 Net income available to common shareholders $ 802 $ 1,026 $ 1,030 "
       "Diluted earnings per share $2.78 $3.65 $3.69 1% 33% Return on average common equity 12.0 % 13.3 %")
# USB 2026-10-15: "3Q26 2Q26 3Q25", the current quarter first
USB = ("INCOME STATEMENT (b) 3Q26 2Q26 3Q25 Net interest income (taxable-equivalent basis) $4,490 $4,387 $4,251 Net income attributable to "
       "U.S. Bancorp $2,202 $2,177 $2,001 Diluted earnings per common share $1.34 $1.35 $1.22 Dividends declared per common share $.54 $.52 $.52")
# GS 2026-10-13: footnote numbers glued to the label
GS = ("3Q26 vs. 2Q26 vs. 3Q25 3Q26 YTD vs. 3Q25 YTD Net earnings to common $ 5,122 (20)% 33% $ 16,924 42% Diluted EPS1,2 $ 17.01 (19)% 39% "
      "$ 55.56 49% ROE2,3 18.7% (4.8)pp 4.5pp 20.7% 6.1pp")
# UNH 2026-10-13: a dot leader between the label and the figure
UNH = ("Three Months Ended September 30, Nine Months Ended September 30, 2026 2025 2026 2025 Net earnings attributable to UnitedHealth Group "
       "common shareholders ...... $4,110 $2,348 $15,874 $12,046 Diluted earnings per share attributable to UnitedHealth Group common "
       "shareholders (a) ...................................................................................................... $4.56 $2.59 $17.53 $13.27 "
       "Adjusted earnings per share")
# PGR 2026-10-14: a month-and-quarter release; the quarter's group is the second, the share count diluted
PGR = ("today reported the following results for the month and quarter ended September 30, 2026: September Quarter (millions, except per "
       "share amounts and ratios; unaudited) 2026 2025 Change 2026 2025 Change Net premiums written $ 7,255 $ 7,128 2 % $ 22,301 $ 21,384 4 % "
       "Net income $ 630 $ 305 107 % $ 2,542 $ 2,615 (3) % Per share available to common shareholders $ 1.08 $ 0.52 109 % $ 4.37 $ 4.45 (2) % "
       "Combined ratio 90.0 100.4 (10.4) pts. 88.7 89.5 (0.8) pts. Average diluted equivalent common shares 581.7 588.2 (1) % 582.2 588.2 (1) %")
# CFG 2026-10-16, the earnings presentation: a segment's contribution is not the company's EPS
CFG_SEGMENT = "Private Bank contribution to total CFG Diluted EPS $0.16 $0.15 $0.11 $0.10 $0.08 $s in billions"
# PLD 2026-10-15: a sentence that states the prior period after the figure
PLD = "Net earnings per diluted share was $0.86, compared with $0.82 for the same period in 2025."


def test_a_year_to_date_column_before_the_quarter_is_never_read():
    hit = parse_release_eps(FAST, date(2026, 10, 14))
    assert hit["eps"] == 0.35 and "column 3" in hit["how"]
    assert R.verify_quote(FAST, "Diluted net income per share $ 0.98 0.84 16.5 % $ 0.35 0.29 19.8 %", 0.35, None, 3) == []
    assert R.verify_quote(FAST, "Diluted net income per share $ 0.98 0.84 16.5 % $ 0.35 0.29 19.8 %", 0.98, None, 1) \
        == ["the heading names column 3 as the quarter's but column 1 was read"]


def test_quarter_label_headings_name_the_current_column():
    assert parse_release_eps(STT, date(2026, 10, 14))["eps"] == 3.69
    assert R.verify_quote(STT, "Diluted earnings per share $2.78 $3.65 $3.69 1% 33%", 3.69, None, 3) == []
    assert parse_release_eps(USB, date(2026, 10, 15))["eps"] == 1.34
    assert R.verify_quote(USB, "Diluted earnings per common share $1.34 $1.35 $1.22", 1.34, None, 1) == []      # was refused as prior-first
    assert current_column("Q2 2026 Q1 2026 Q2 2025 Diluted EPS", 3) == 0 and current_column("2026 2025 Diluted EPS", 2) is None


def test_footnote_marks_and_dot_leaders_in_labels():
    assert clean_labels("Diluted EPS1,2 $ 17.01") == "Diluted EPS $ 17.01"
    assert parse_release_eps(GS, date(2026, 10, 13))["eps"] == 17.01
    assert parse_release_eps(UNH, date(2026, 10, 13))["eps"] == 4.56
    assert R.verify_quote(GS, "Diluted EPS1,2 $ 17.01 (19)% 39% $ 55.56 49%", 17.01, None, 1) == []


def test_a_month_and_quarter_release_reads_the_quarter():
    hit = parse_release_eps(PGR, date(2026, 10, 14))
    assert hit["eps"] == 4.37 and "column 3" in hit["how"]
    assert parse_release_eps(PGR.replace("Average diluted equivalent common shares", "Average common shares"), date(2026, 10, 14)) is None


def test_a_segment_contribution_is_not_the_companys_eps():
    assert parse_release_eps(CFG_SEGMENT, date(2026, 10, 16)) is None


def test_a_sentence_with_its_prior_period_needs_no_column():
    assert R.verify_quote(PLD, PLD, 0.86) == []
    assert R.verify_quote(PLD, PLD, 0.82) != []


# GS 2026-10-13, the release (EX-99.1): a footnote number spaced after "(EPS)"
GS_RELEASE = ("NEW YORK, October 13, 2026 – The Goldman Sachs Group, Inc. (NYSE: GS) today reported net revenues of $ 18.68 billion and net earnings "
              "of $ 5.29 billion for the third quarter ended September 30, 2026. Diluted earnings per common share (EPS) 1 was $ 17.01 for the third "
              "quarter of 2026 compared with $ 12.25 for the third quarter of 2025 and $ 20.98 for the second quarter of 2026, and was $ 55.56 for the "
              "first nine months of 2026.")
# CARR 2026-07-28: the Diluted block's total line
CARR = ("Earnings per share Basic: Continuing operations $ 0.61 $ 0.71 $ 0.89 $ 1.18 Discontinued operations — (0.02) — (0.01) Net earnings (loss) "
        "$ 0.61 $ 0.69 $ 0.89 $ 1.17 Diluted: Continuing operations $ 0.60 $ 0.70 $ 0.88 $ 1.17 Discontinued operations — (0.02) — (0.02) Net "
        "earnings (loss) $ 0.60 $ 0.68 $ 0.88 $ 1.15 Weighted-average number of shares outstanding")


def test_a_spaced_footnote_after_eps_and_the_releases_own_quarter_end():
    hit = parse_release_eps(GS_RELEASE, date(2026, 10, 13))
    assert hit["eps"] == 17.01 and hit["period_end"] == date(2026, 9, 30)


def test_the_diluted_blocks_total_line_is_diluted_eps():
    assert R.in_diluted_block(CARR, "Net earnings (loss) $ 0.60 $ 0.68 $ 0.88 $ 1.15")
    assert not R.in_diluted_block(CARR, "Net earnings (loss) $ 0.61 $ 0.69 $ 0.89 $ 1.17")
    figure, note = R.decide({"eps": 0.60, "how": "diluted EPS block (colon), net earnings line"},
                            {"eps": 0.60, "quote": "Net earnings (loss) $ 0.60 $ 0.68 $ 0.88 $ 1.15", "columns": "Quarter ended June 30 2026 2025", "column": 1}, CARR)
    assert figure == 0.60, note


def test_a_month_and_quarter_row_in_a_diluted_share_table_stores_when_both_read_the_quarter():
    q = "Per share available to common shareholders $ 1.08 $ 0.52 109 % $ 4.37 $ 4.45 (2) %"
    assert R.in_diluted_share_table(PGR, q)
    figure, note = R.decide({"eps": 4.37, "how": "per share available row, diluted share count, column 3"},
                            {"eps": 4.37, "quote": q, "columns": "September Quarter 2026 2025 2026 2025", "column": 3}, PGR)
    assert figure == 4.37, note


def test_a_presentation_reads_after_the_release_when_neither_is_named_ex99():
    from app.scripts.seed_release_eps import exhibit_candidates
    deck = ("a3q26gsearningsresultspr.htm", "x" * 600 + " Third Quarter 2026 Earnings Results Presentation " + "y" * 9000)
    release = ("a3q26gsearningsresults.htm", "Third Quarter 2026 Earnings Results Media Relations " + "z" * 5000)
    assert [n for n, _ in exhibit_candidates([deck, release])] == ["a3q26gsearningsresults.htm", "a3q26gsearningsresultspr.htm"]


def test_a_figure_followed_by_for_the_quarter_is_the_quarters_after_a_nine_months_sentence():
    text = ("Net revenues were $ 56.24 billion and net earnings were $ 17.55 billion for the first nine months of 2026. " + GS_RELEASE.split("2026. ", 1)[1])
    hit = parse_release_eps("for the third quarter ended September 30, 2026. " + text, date(2026, 10, 13))
    assert hit["eps"] == 17.01 and hit["how"] == "EPS were sentence"


def test_a_share_class_is_never_a_merger_counterparty():
    from app.scripts.scan_corporate_actions import counterparty_name
    assert counterparty_name("Company Class B") is None                                   # CHTR, an older scan of 0001140361-26-033909
    assert counterparty_name("Charter Class C Common Stock") is None
    assert counterparty_name("Liberty Broadband Corporation and Cox Enterprises, Inc. (Cox Communications, LLC)") \
        == "Liberty Broadband Corporation and Cox Enterprises, Inc. (Cox Communications, LLC)"
