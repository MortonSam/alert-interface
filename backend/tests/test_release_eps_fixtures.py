"""The release parser on exhibit text from the 2026-10-07 production dry run: the two misreads as failing fixtures (an adjustment
item, a prior-year comparison) and the seventeen correct reads as passing ones. Each fixture is the exhibit's text around the
figure, as the parser sees it."""
from datetime import date

import pytest

from app.services import valuation as V

HPE = ("llion to $14.8 billion. HPE estimates GAAP diluted net EPS to be in the range of $1.12 to $1.22 and non-GAAP diluted net EPS (1) to be in the range of $1.20 to $1.30. "
       "Fiscal 2026 fourth quarter non-GAAP diluted net EPS estimate excludes net after-tax adjustments of approximately $0.08 per diluted share, primarily related to "
       "amortization of intangible assets, stock-based compensation expense, acquisition, disposition and")
PANW = ("non-GAAP operating income of $768 million for the fiscal fourth quarter 2025. A reconciliation between GAAP and non-GAAP information is contained in the tables below. "
        "• GAAP net loss for the fiscal fourth quarter 2026 was $282 million, or ($0.35) per diluted share, compared with GAAP net income of $254 million, or $0.36 per "
        "diluted share, for the fiscal fourth quarter 2025. Non-GAAP net income for the fiscal fourth quarter 2")
PASSING = {
    "ACN": (3.29, "Effective tax rate 27.3 % 30.1 % 20.5 % 27.9 % Diluted earnings per share (2) $ 3.29 $ 2.25 $ 0.78 $ 3.03 Year Ended August 31, 2026 August 31, 2025 As Reported (GAAP) Business Optimization (1) Adjusted"),
    "ADBE": (4.62, "Basic net income per share $ 4.63 $ 4.18 $ 13.48 $ 12.28 Shares used to compute basic net income per share 395 423 403 429 Diluted net income per share $ 4.62 $ 4.18 $ 13.47 $ 12.26 Shares used to compute diluted net income per share 395 424"),
    "AVGO": (2.68, "• GAAP operating income of $16.0 billion for the third quarter; Non-GAAP operating income of $20.1 billion for the third quarter • GAAP diluted EPS of $2.68 for the third quarter; Non-GAAP diluted EPS of $3.32 for the third quarter • Cash from operations of $14.2 billion for"),
    "CASY": (7.37, "Earnings Three Months Ended July 31, 2026 2025 Net income (in thousands) $ 273,720 $ 215,355 Diluted earnings per share $ 7.37 $ 5.77 EBITDA (in thousands) $ 485,083 $ 414,270 For the quarter, net income, diluted EPS, and EBITDA increased compar"),
    "CCL": (1.40, "Net Income attributable to Carnival Corporation Ltd. $ 1,920 $ 1,852 $ 2,715 $ 2,338 Earnings Per Share Basic $ 1.41 $ 1.41 $ 1.97 $ 1.78 Diluted $ 1.40 $ 1.33 $ 1.96 $ 1.71 Weighted-Average Shares Outstanding - Basic 1,363 1,313 1,375 1,311"),
    "COST": (6.75, "*Excluding the impacts from changes in gasoline prices and foreign exchange. Net income for the fourth quarter was $2.998 billion, $6.75 per diluted share, compared to $2.610 billion, $5.87 per diluted share, last year. This year's fourth quarter was positively impacted by"),
    "CTAS": (1.36, "Net income $ 551,711 $ 491,140 12.3% Basic earnings per share $ 1.37 $ 1.21 13.2% Diluted earnings per share $ 1.36 $ 1.20 13.3% Basic weighted average common shares outstanding 400,137 403,292 Diluted weighted average common shares ou"),
    "DELL": (6.34, "Net income $ 4,133 $ 1,164 255% $ 7,571 $ 2,129 256% Earnings per share: Basic $ 6.41 $ 1.72 273% $ 11.70 $ 3.11 276% Diluted $ 6.34 $ 1.70 273% $ 11.58 $ 3.07 277% Weighted average shares: Basic 645 678 (5)% 647 685 (6)% Diluted 652 686 (5)%"),
    "GIS": (0.74, "Net earnings attributable to General Mills $ 397.0 $ 1,204.2 (67) % Earnings per share – basic $ 0.74 $ 2.22 (67) % Earnings per share – diluted $ 0.74 $ 2.22 (67) % Quarter Ended Comparisons as a % of net sales Aug. 30, 2026 Aug. 24, 2025"),
    "JBL": (3.76, "Fourth Quarter of Fiscal Year 2026 Highlights: • Net revenue: $10.6 billion • U.S. GAAP operating income: $602 million • U.S. GAAP diluted earnings per share: $3.76 • Core operating income (Non-GAAP): $675 million • Core diluted earnings per share (Non-GAAP): $4.40 Fiscal Year 2026 H"),
    "LEN": (1.19, "Net earnings attributable to Lennar $ 283,876 590,967 818,031 1,587,942 Basic and diluted average shares outstanding 237,756 255,601 240,990 259,540 Basic and diluted earnings per share $ 1.19 2.29 3.36 6.06 Supplemental information: Interest incurred (1) $ 63,173"),
    "LULU": (2.92, "Net income $ 329,223 $ 370,905 $ 524,271 $ 685,477 Basic earnings per share $ 2.92 $ 3.10 $ 4.59 $ 5.71 Diluted earnings per share $ 2.92 $ 3.10 $ 4.59 $ 5.70 Basic weighted-average shares outstanding 112,898 119,600 114,156 120,116 Diluted weighted-average"),
    "MDT": (1.14, "Net income attributable to Medtronic $ 1,470 $ 1,040 Basic earnings per share $ 1.15 $ 0.81 Diluted earnings per share $ 1.14 $ 0.81 Basic weighted average shares outstanding 1,279.8 1,281.6 Diluted weighted average shares outstanding 1,285.1 1,"),
    "MKC": (0.36, "Net income attributable to McCormick $ 97.6 (56.7) % $ 231.7 1.1 % Earnings per share - diluted $ 0.36 (57.1) % $ 0.86 1.2 % Third Quarter 2026 Results Net sales increased 17% in the third quarter compared to the year-ago"),
    "MU": (32.87, "Fiscal Q4 2026 Highlights • Revenue of $54.23 billion versus $41.46 billion for the prior quarter and $11.32 billion for the same period last year • GAAP net income of $37.70 billion, or $32.87 per diluted share • Non-GAAP net income of $38.40 billion, or $33.42 per diluted share • Operating cash flo"),
    "ORCL": (1.56, "NET INCOME AVAILABLE TO COMMON SHAREHOLDERS $ 4,679 $ 1,079 $ 5,758 $ 2,927 $ 1,356 $ 4,283 60% 34% 59% 34% DILUTED EARNINGS PER SHARE ATTRIBUTABLE TO COMMON SHAREHOLDERS $ 1.56 $ 1.92 $ 1.01 $ 1.47 55% 30% 54% 30% DILUTED WEIGHTED AVERAGE COMMON SHARES OUTSTANDING 3,000 — 3,000 2,909 — 2,909 3%"),
    "PAYX": (1.21, "Three months ended August 31, In millions, except per share amounts 2026 2025 Change Total revenue $ 1,630.5 $ 1,540.0 6 % Operating income $ 619.2 $ 541.9 14 % Adjusted operating income* $ 684.7 $ 626.7 9 % Diluted earnings per share $ 1.21 $ 1.06 14 % Adjusted diluted earnings per share* $ 1.34 $ 1.22 10 % 'Paychex delivered"),
}


def test_an_adjustment_item_is_never_the_quarters_eps():
    assert V.parse_release_eps(HPE, date(2026, 9, 2)) is None


def test_a_prior_year_comparison_is_never_taken_and_the_current_loss_is():
    hit = V.parse_release_eps(PANW, date(2026, 9, 1))
    assert hit is not None and hit["eps"] == -0.35, hit                         # the current period, a loss written "($0.35)"


@pytest.mark.parametrize("sym", sorted(PASSING))
def test_the_correct_reads_still_read(sym):
    eps, text = PASSING[sym]
    hit = V.parse_release_eps(text, date(2026, 9, 15))
    assert hit is not None and hit["eps"] == eps, (sym, hit)


# the second pass: releases the first patterns could not read, from the exhibits (passing when the figure is the quarter's total GAAP diluted EPS)
PASSING_2 = {
    "AZO": (56.05, "Net income for the quarter was $931.6 million compared to $837.0 million in the same period last year, while diluted earnings per share were $56.05 compared to last year at $48.71. For the fiscal year ended August 29, 2026, net sales were"),
    "AZO_row": (56.05, "Income tax expense 236,646 211,027 Net income $ 931,587 $ 836,951 Net income per share: Basic $ 57.17 $ 50.02 Diluted $ 56.05 $ 48.71 Weighted average shares outstanding: Basic 16,294 16,731 Diluted 16,620"),
    "D": (0.37, "Dominion Energy Announces Second-Quarter 2026 Results • Second-quarter 2026 GAAP net income of $0.37 per share; operating earnings (non-GAAP) of $0.79 per share • Company reaffirms its full-year 2026 operating earnings guidance"),
    "DOW": (0.99, "• GAAP earnings per share (EPS) was $0.99; operating EPS 1 was $1.44, compared to a loss of $0.42 in the year-ago period. Op. EPS excludes significant items"),
    "DOW_row": (0.99, "Per common share data: Earnings (loss) per common share - basic $ 0.99 $ (1.18) $ 0.25 $ (1.62) Earnings (loss) per common share - diluted $ 0.99 $ (1.18) $ 0.25 $ (1.62)"),
    "DRI": (2.04, "Diluted net earnings per share: Earnings from continuing operations $ 2.05 $ 2.19 Losses from discontinued operations (0.01) — Net earnings $ 2.04 $ 2.19 Average number of common shares outstanding"),
    "DUK": (1.38, "Duke Energy (NYSE: DUK) today announced second-quarter 2026 reported EPS of $1.38, prepared in accordance with Generally Accepted Accounting Principles (GAAP), and adjusted EPS of $1.43. This is compared to reported and adjusted EPS of $1.25 for the second quarter of 2025."),
    "ETR": (1.03, "Entergy Corporation (NYSE: ETR) reported second quarter 2026 earnings per share of $1.03 on an as-reported and an adjusted (non-GAAP) basis. At our investor day in June, we provided"),
    "EXC": (0.39, "EXELON REPORTS SECOND QUARTER 2026 RESULTS Earnings Release Highlights • GAAP net income of $0.39 per share and Adjusted (non-GAAP) operating earnings of $0.43 per share for the second quarter of 2026, in line with expectations"),
    "F": (-0.01, "Net Income / (Loss) Margin (%) (0.1) % (2.7) % (2.7) ppts 0.5 % 1.3 % 0.9 ppts EPS (Diluted) $ (0.01) $ (0.33) $ (0.32) $ 0.11 $ 0.30 $ 0.19 Non-GAAP Financial Measures Company Adj. Free Cash Flow"),
    "F_row": (-0.01, "Diluted shares 4,025 4,066 4,018 4,069 Earnings/(Loss) per share – diluted (GAAP) (a) $ (0.01) $ (0.33) $ 0.11 $ 0.30 Less: Net impact of special items"),
    "FE": (0.50, "FirstEnergy Corp. (NYSE: FE) today reported second quarter 2026 GAAP earnings of $288 million, or $0.50 per basic and diluted share, on revenue of $3.7 billion. This compares to second quarter of 2025 GAAP earnings of $268 million"),
    "HUM": (5.73, "• Reports 2Q26 earnings per share (EPS) of $5.73 on a GAAP basis, Adjusted EPS of $7.61; reports year to date (YTD) 2026 EPS of $15.55 on a GAAP basis"),
    "HUM_row": (5.73, "Impairment charges 21 32 21 32 Adjusted (non-GAAP) $1,248 $1,017 $2,918 $2,910 1 Diluted earnings per share (EPS) 2Q26 (a) 2Q25 (a) YTD 2026 (a) YTD 2025 (a) GAAP $5.73 $4.51 $15.55 $14.81 Amortization associated with"),
}
AMBIGUOUS = {
    # a basic figure stated as GAAP, no diluted figure in the row: not taken
    "ED": "Reported earnings per share (basic) and net income for common stock (GAAP basis) $0.83 $0.68 $308 $246 $3.37 $2.93 $1,232 $1,038 Loss and other impairments",
    # a continuing-operations figure in prose is not the whole GAAP diluted EPS
    "DRI_prose": "• Reported diluted net earnings per share from continuing operations were $2.05, an increase of 4.1% from last year's adjusted diluted net earnings per share from continuing operations",
    # guidance ranges
    "HUM_guidance": "Humana revises its GAAP EPS guidance for the year ending December 31, 2026 (FY 2026) to 'at least $6.52' from 'at least $8.36'",
}


@pytest.mark.parametrize("sym", sorted(PASSING_2))
def test_second_pass_reads(sym):
    eps, text = PASSING_2[sym]
    hit = V.parse_release_eps(text, date(2026, 8, 15))
    assert hit is not None and hit["eps"] == eps, (sym, hit)


@pytest.mark.parametrize("sym", sorted(AMBIGUOUS))
def test_second_pass_ambiguous_are_not_read(sym):
    assert V.parse_release_eps(AMBIGUOUS[sym], date(2026, 8, 15)) is None, sym
