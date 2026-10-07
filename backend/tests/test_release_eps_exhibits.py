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


def test_the_fixture_set_is_the_production_run():
    assert len(ROWS) == 26 and sum(1 for r in ROWS if r[4] == "") == 1


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
