"""The release parser against the full exhibit text it sees in production: the 25 reads from the 2026-10-07 production dry run
(stored under tests/fixtures/releases with their report dates and accessions in INDEX.txt) read to their exact GAAP diluted EPS,
and HPE stays unread. A snippet can hide what a whole exhibit shows (GIS's net earnings in millions once read as EPS)."""
from datetime import date
from pathlib import Path

import pytest

from app.services import valuation as V

FIXTURES = Path(__file__).parent / "fixtures" / "releases"
ROWS = [line.split("|") for line in (FIXTURES / "INDEX.txt").read_text().splitlines() if line.strip()]


@pytest.mark.parametrize("sym,report_date,accession,name,want", ROWS, ids=[r[0] for r in ROWS])
def test_full_exhibit_reads_its_gaap_diluted_eps(sym, report_date, accession, name, want):
    hit = V.parse_release_eps((FIXTURES / f"{sym}.txt").read_text(), date.fromisoformat(report_date))
    if want == "":
        assert hit is None, (sym, hit)
    else:
        assert hit is not None and hit["eps"] == float(want), (sym, hit and (hit["eps"], hit["how"], hit["evidence"][:120]))


def test_the_fixture_set_is_the_production_runs():
    """The 2026-10-07 dry run's 25 reads and HPE unread, plus the four misreads of the second dry run (CRL, SMCI, CAH, FRT) and
    Dominion, whose release states a continuing-operations row beside the total row."""
    assert len(ROWS) == 31 and sum(1 for r in ROWS if r[4] == "") == 1


def test_the_four_misreads_and_the_rules_behind_them():
    assert V.parse_release_eps("Reports second-quarter revenue of $1.00 billion, GAAP loss per share of $(0.03), and non-GAAP earnings per share of $3.02.")["eps"] == -0.03
    smci = "• Diluted net income per common share of $1.62 versus $0.72 in Q3'26. Non-GAAP net income attributable to common stockholders for fiscal year 2026 was $2.5 billion, or $3.63 per diluted share."
    assert V.parse_release_eps(smci)["eps"] == 1.62
    assert V.parse_release_eps("Non-GAAP net income for fiscal year 2026 was $2.5 billion, or $3.63 per diluted share, versus $1.3 billion.") is None   # non-GAAP and annual
    assert V.parse_release_eps("Net income for fiscal year 2026 was $2.2 billion, or $3.26 per diluted share, versus $1.0 billion.") is None            # annual
    cah = "Fiscal year 2026 revenues were $254.2 billion, a 14% increase. GAAP operating earnings were $2.6 billion and GAAP diluted EPS was $7.23."
    assert V.parse_release_eps(cah) is None                                                                                                  # the paragraph is the year's
    assert V.parse_release_eps("Fourth quarter revenue increased 6% to $63.7 billion and GAAP diluted earnings per share (EPS) increased 70% to $1.70. " + cah)["eps"] == 1.70
    frt = "Nareit FFO was $162.8 million, or $1.88 per diluted share, for the second quarter of 2026. Net income available for common shareholders was $83.7 million and earnings per diluted share was $0.97 versus $153.9 million."
    assert V.parse_release_eps(frt)["eps"] == 0.97
    assert V.parse_release_eps("Core FFO per diluted share of $1.88 for the quarter.") is None
    d = "Reported Income (loss) per common share from continuing operations - diluted $ 0.37 $ 0.88 Reported Income (loss) per common share - diluted $ 0.37 $ 0.88 Average shares"
    hit = V.parse_release_eps(d)
    assert hit["eps"] == 0.37 and "from continuing" not in hit["evidence"]
    assert V.parse_release_eps("Reported Income (loss) per common share from continuing operations - diluted $ 0.37 $ 0.88 Average shares") is None   # continuing only: unread
    # a quarter sentence that also names the year is not refused as annual; the first GAAP figure is the quarter's
    assert V.parse_release_eps("For the fourth quarter and fiscal year ended June 30, 2026, GAAP net income was $500 million, or $1.25 per diluted share.")["eps"] == 1.25
    assert V.is_annual_figure("Fiscal year 2026 revenues were $254.2 billion. GAAP diluted EPS was $7.23.", 65, 90) is True
    acn = "Effective tax rate 27.3 % 30.1 % Diluted earnings per share (2) $ 3.29 $ 2.25 $ 0.78 $ 3.03 Year Ended August 31, 2026 As Reported (GAAP)"
    assert V.parse_release_eps(acn)["eps"] == 3.29                                                                                     # the next table's header follows the row
    assert V.parse_release_eps("HIGHLIGHTS • Generates reported EPS of $3.32 and comparable EPS of $3.74 • Beer Business")["eps"] == 3.32   # STZ: the comparable figure is named on purpose


def test_plausibility_guard_refuses_on_price_and_adjusted_eps_and_notes_year_over_year():
    assert V.implausible(397.0, 95.0, 2.22) is not None and "25%" in V.implausible(397.0, 95.0, 2.22)        # a net income in millions read as EPS
    assert V.implausible(429.7, 150.0, 1.06) is not None
    assert V.implausible(0.74, 95.0, 0.86) is None                                       # GIS: GAAP near adjusted
    assert "5.9x the stored adjusted EPS" in V.implausible(12.5, 400.0, 2.11)             # five times the adjusted figure for the same report: refused
    assert V.implausible(0.30, 400.0, 2.11) is not None                                  # under a fifth of it likewise
    assert V.implausible(32.87, 1063.96, 33.42) is None                                  # Micron: GAAP 32.87 beside adjusted 33.42 is fine
    assert V.implausible(32.87, 1063.96, None) is None                                   # no adjusted figure stored: only the price test
    assert V.implausible(-0.35, 180.0, 0.36) is None                                     # a loss against a profit is not compared (PANW)
    assert V.implausible(1.21, None, 1.06) is None
    # year over year is a warning for the digest, never a refusal: Micron's 11.6x was real
    assert V.year_over_year_note(32.87, 2.83) == "+32.87 is 11.6x the same quarter a year earlier (+2.83)"
    assert V.year_over_year_note(0.74, 2.22) is None and V.year_over_year_note(32.87, None) is None and V.year_over_year_note(-0.35, 0.36) is None
    from app.services.notify import digest_message
    body = digest_message("2026-10-08", 30, 30, [], None, 90.0, None, None, None, ["MU 2026-09-30: +32.87 is 11.6x the same quarter a year earlier (+2.83)"])[1]
    assert "release EPS year-over-year warning(s) (1), stored, check by hand: MU 2026-09-30: +32.87 is 11.6x" in body
    assert "year-over-year" not in digest_message("2026-10-08", 30, 30, [], None, 90.0, None)[1]


def test_every_reading_label_fits_the_column():
    """release_eps.how is 64 characters wide; the longest label is "net income per share row, basic then diluted" (44)."""
    import re
    src = (Path(V.__file__)).read_text()
    labels = re.findall(r'\(_[A-Z_0-9]+, "([^"]+)", \d+\)', src) + ["highlights sentence"]
    assert labels and max(len(x) for x in labels) <= 64, max(labels, key=len)
