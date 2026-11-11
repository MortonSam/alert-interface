"""The release revenue reader against the releases where it read a line for the company's revenue (Sam, 2026-11-10: AJG "111",
BAC "11.2"). Each fixture is the exhibit's text as the reader gets it; each figure is the filing's (XBRL) revenue for the quarter."""
from pathlib import Path

import pytest

from app.services.growth import parse_release_revenue, revenue_agrees

DIR = Path(__file__).parent / "fixtures" / "releases_revenue"

# the filing's revenue, and what the reader took before: a sub-line whose label ends in "revenue", a segment's sentence, a change
AGREE = {"BAC": (29_958e6, "11.6"), "DRI": (3_200.3e6, "571.5"), "EQIX": (2_571e6, "2,442"), "ERIE": (1_069.917e6, "197,562"),
         "HII": (3_537e6, "1,100"), "IVZ": (1_873.2e6, "1,381.7"), "J": (4_076.41e6, "2,087,098"), "NEM": (6_363e6, "5,317"),
         "PPG": (4_353e6, "1,055"), "REGN": (5_115.8e6, "3,000.5"), "STT": (4_004e6, "332"), "TMUS": (23_584e6, "16.3"),
         "UNP": (7_197e6, "6,813"), "USB": (7_970e6, "440"), "VZ": (34_313e6, "5,116")}
# a release whose only revenue lines are parts ("Discount revenue", "Service revenues", "Gross fee revenues"): no reading beats a wrong one
REFUSE = {"AXP": "10,169", "CPRT": "969,544", "MAR": "1,522"}


@pytest.mark.parametrize("sym", sorted(AGREE))
def test_the_company_revenue_is_read_and_agrees_with_the_filing(sym):
    xbrl, before = AGREE[sym]
    r = parse_release_revenue((DIR / f"{sym}.txt").read_text())
    assert r and revenue_agrees(xbrl, r), (sym, r and r["raw"], r and r["how"])
    assert r["raw"] != before


@pytest.mark.parametrize("sym", sorted(REFUSE))
def test_a_line_of_revenue_is_never_read_as_the_total(sym):
    r = parse_release_revenue((DIR / f"{sym}.txt").read_text())
    assert r is None or r["raw"] != REFUSE[sym]


# the forms the other 385 stocks' releases use, which the row-start and sentence rules must keep reading: a column heading's last
# word before the first row, a heading that repeats the label, a longer label, a company sentence before a segment's
STILL_READ = {
    "HCA": (19_513e6, "Fourth Quarter Unaudited (Dollars in millions, except per share amounts) 2025 2024 Amount Ratio Amount Ratio Revenues $ 19,513 100.0 % $ 18,285 100.0 % Salaries and benefits 8,405"),
    "AOS": (912.5e6, "Fourth Quarter (in millions, except per share amounts) Q4 2025 Q4 2024 % Change YoY Net sales $912.5 $912.4 — Net earnings $125.4 $109.6"),
    "WDC": (3_747e6, "Q4FY26 Financial Highlights ($ in millions, except per share amounts) GAAP Q4FY26 Q3FY26 Q4FY25 Q/Q Y/Y Revenue $3,747 $3,337 $2,605 +12% +44% Gross Margin"),
    "PM": (11_192e6, "(in millions) Variance Favorable / (Unfavorable) 2026 2025 Change Total Price Volume / Mix / Other Cost Acq. / Divest. Currency Net Revenues 11,192 10,140 10.4% 1,052 689 81"),
    "CEG": (11_122e6, "(in millions) Three Months Ended March 31, 2026 Three Months Ended March 31, 2025 GAAP (a) Non-GAAP Adjustments GAAP (a) Non-GAAP Adjustments Operating revenues $ 11,122 $ (1,111) (b),(c),(d) $ 6,788 $ 12"),
    "IDXX": (1_090_579e3, "Condensed Consolidated Statements of Income (in thousands) Three Months Ended Twelve Months Ended December 31, December 31, December 31, December 31, 2025 2024 2025 2024 Revenue: Revenue $ 1,090,579 $ 954,288 $ 4,303,702 $ 3,897,504"),
    "TSCO": (3_898_320e3, "Condensed Consolidated Statements of Income (in thousands) Fourth Quarter Ended Fiscal Year Ended December 27, 2025 December 28, 2024 December 27, 2025 December 28, 2024 % of % of % of % of Net Net Net Net Sales Sales Sales Sales Net sales $ 3,898,320 100.00% $ 3,773,531 100.00% $ 15,520,000 100.00% $ 14,883,231 100.00%"),
    "KO": (11_822e6, "Condensed Consolidated Statements of Income (In millions except per share data) Three Months Ended December 31, 2025 December 31, 2024 % Change Net Operating Revenues $ 11,822 $ 11,544 2 Cost of goods sold 4,651 4,601"),
    "LYB": (7_197e6, "Millions of U.S. dollars (except share data) Three Months Ended March 31 2026 December 31 2025 March 31 2025 Sales and other operating revenues $7,197 $7,091 $7,677 Net income (loss) 12 5 177"),
    "UAL": (15_396e6, "Fourth-Quarter Financial Results • Capacity up 6.5% compared to fourth-quarter 2024. • Total operating revenue of $15.4 billion, up 4.8% compared to fourth-quarter 2024."),
    "HWM": (2_313e6, "Consolidated Results Howmet Aerospace reported first quarter 2026 revenue of $2.31 billion, up 19% year over year. Engine Structures reported revenue of $294 million, a decrease of 2% year over year."),
    "UNH": (112_032e6, "UnitedHealth Group Reports Second Quarter 2026 Results • Second Quarter 2026 Revenues of $112.0 Billion; Earnings from Operations of $5.2 Billion. UnitedHealthcare serves consumers and reported revenues of $86.0 billion and earnings from operations of $2.1 billion."),
    "C": (21_596e6, "Citigroup Inc. today reported net income for the first quarter 2025 of $4.1 billion, or $1.96 per diluted share, on revenues of $21.6 billion. Banking (on a reported basis) revenues of $1.4 billion decreased 12%."),
    "LLY": (19_292e6, "Fourth-Quarter Reported Results In Q4 2025, worldwide revenue was $19.3 billion, an increase of 43% compared with Q4 2024. U.S. revenue was $4.1 billion, an increase of 9%."),
}


@pytest.mark.parametrize("sym", sorted(STILL_READ))
def test_the_forms_other_releases_use_are_still_read(sym):
    xbrl, text = STILL_READ[sym]
    r = parse_release_revenue(text)
    assert r and revenue_agrees(xbrl, r), (sym, r and r["raw"], r and r["how"])
