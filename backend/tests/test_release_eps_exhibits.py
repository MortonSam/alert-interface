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


def test_plausibility_guard():
    assert V.implausible(397.0, 95.0, 2.22) is not None and "25%" in V.implausible(397.0, 95.0, 2.22)
    assert V.implausible(429.7, 150.0, 1.06) is not None
    assert V.implausible(0.74, 95.0, 2.22) is None                                       # a third of last year's quarter is fine
    assert "10.0x" in (V.implausible(32.87, 1063.96, 2.83) or "") or V.implausible(32.87, 1063.96, 2.83) is not None   # Micron: 11.6x the year-ago quarter
    assert V.implausible(32.87, 1063.96, None) is None                                   # no year-ago quarter: only the price test
    assert V.implausible(-0.35, 180.0, 0.36) is None                                     # a loss against a profit is not compared
    assert V.implausible(1.21, None, 1.06) is None
