"""Block 2 (2026-10-20): the release revenue reader took a segment's or a subsidiary's line for the company's revenue (2,045 of the
2,182 growth disagreements of 2026-10-19). One worked example per cause, from each release's own text."""
from app.scripts.compute_growth import _rank
from app.services.growth import parse_release_revenue, revenue_agrees

# A (Agilent) 2026-08-26: a segment's sentence comes first; the consolidated statement states the company's
AGILENT = ("Life Sciences and Diagnostics Markets Group The group reported third-quarter revenue of $746 million, growth of 11% over a year ago. "
           "CONDENSED CONSOLIDATED STATEMENTS OF OPERATIONS (In millions, except per share data) (Unaudited) PRELIMINARY Three Months Ended "
           "Nine Months Ended July 31, July 31, 2026 2025 2026 2025 Net revenue $ 1,878 $ 1,738 $ 5,511 $ 5,087 Costs and expenses: Cost of "
           "products and services 836 850 2,533 2,434")
# EXC 2026-07-30: a consolidating statement, one column per subsidiary; the company is the last
EXELON = ("Consolidating Statements of Operations (unaudited) (in millions) ComEd PECO BGE PHI Other (a) Exelon Three Months Ended June 30, 2026 "
          "Operating revenues $ 1,985 $ 1,062 $ 1,218 $ 1,712 $ (10) $ 5,967 Operating expenses Purchased power and fuel 579 389 545 698 — 2,211")
# CMCSA 2026-07-23: a segment table's "Total Revenue" before the statement
COMCAST = ("Connectivity & Platforms (in millions) 2Q26 2Q25 Change Total Revenue $17,124 $17,839 (4.0 %) Adjusted EBITDA $7,890 $8,012 "
           "Condensed Consolidated Statements of Income (Unaudited) Three Months Ended Six Months Ended (in millions, except per share data) "
           "June 30, June 30, 2026 2025 2026 2025 Revenue $29,940 $30,313 $61,396 $60,199 Costs and expenses Programming and production 8,389")
# PG 2026-07-29: the fiscal year's table before the fourth quarter's, no statement in the exhibit
PG = ("Fiscal Year ($ billions, except EPS) GAAP 2026 2025 % Change Non-GAAP* 2026 2025 % Change Net Sales $87.0 $84.3 +3% Organic Sales n/a "
      "n/a +1% Diluted EPS $6.62 $6.51 +2% Fourth Quarter ($ billions, except EPS) GAAP 2026 2025 % Change Non-GAAP* 2026 2025 % Change Net "
      "Sales $21.2 $20.9 +2% Organic Sales n/a n/a —% Diluted EPS $1.26 $1.48 (15)%")
# GS 2025 Q4: the quarter's sentence, then the year's
GS_Q4 = ("The Goldman Sachs Group, Inc. (NYSE: GS) today reported net revenues of $ 13.45 billion and net earnings of $ 4.39 billion for the "
         "fourth quarter ended December 31, 2025. Net revenues were $ 58.28 billion and net earnings were $ 17.18 billion for the year ended "
         "December 31, 2025.")


def test_the_consolidated_statement_outranks_a_segments_sentence():
    r = parse_release_revenue(AGILENT)
    assert (r["raw"], r["scale"]) == ("1,878", "millions") and "consolidated statement" in r["how"]
    assert revenue_agrees(1.878e9, r)


def test_a_consolidating_statement_reads_its_consolidated_column():
    r = parse_release_revenue(EXELON)
    assert r["raw"] == "5,967" and "consolidated column" in r["how"]


def test_a_segment_table_before_the_statement_is_never_read():
    r = parse_release_revenue(COMCAST)
    assert r["raw"] == "$29,940".strip("$") or r["raw"] == "29,940"
    assert revenue_agrees(2.994e10, r)


def test_the_years_table_is_never_the_quarters():
    r = parse_release_revenue(PG)
    assert (r["raw"], r["scale"]) == ("21.2", "billions")
    assert revenue_agrees(2.12e10, r)


def test_a_sentence_about_the_year_is_never_the_quarters():
    r = parse_release_revenue(GS_Q4)
    assert r["raw"] == "13.45" and r["how"] == "revenue sentence"


def test_one_unit_of_the_last_digit_agrees_and_two_do_not():
    assert revenue_agrees(5.2854e9, {"raw": "5,286", "number": 5286.0, "scale": "millions"})      # BSX: rounded differently
    assert not revenue_agrees(5.2835e9, {"raw": "5,286", "number": 5286.0, "scale": "millions"})


def test_when_two_exhibits_read_the_statement_outranks_a_sentence_which_outranks_a_table():
    assert _rank({"how": "net revenue, consolidated statement"}) < _rank({"how": "revenue sentence"}) < _rank({"how": "total revenue"})
