"""Expected report windows against the 92 company-confirmed report dates stored on 2026-10-13, recomputed from the stored filing
verdicts with today pinned to 2026-10-13. Sam's pass mark (90 contained, HAL, KIM, KKR, CL, EMR, FERG and FDX each in) is not met:
FDX changed its reporting calendar after the FedEx Freight spin-off, FDXF has no history, MSCI and TSN moved a week, JPM and UNH
reported on the day, and CL, EMR and FERG have no company-confirmed date stored. This holds the chosen version's score (v3, 82 of 92) as a floor."""
from datetime import date

import pytest

from app.scripts import score_report_windows as S
from app.services import report_windows as W

pytestmark = pytest.mark.xdist_group(name="report_window_fixture")


def test_the_score_counts_containment_and_the_named_tickers():
    confirmed = {"HAL": date(2026, 10, 20), "FDX": date(2026, 10, 28), "AAA": date(2026, 11, 2)}
    r = S.score(confirmed, {"HAL": {"start": "2026-10-19", "end": "2026-10-21"}, "FDX": {"start": "2026-12-14", "end": "2026-12-19"}, "AAA": None})
    assert (r["contained"], r["total"]) == (1, 3) and r["named"]["HAL"] is True and r["named"]["FDX"] is False and r["named"]["CL"] is None
    assert not r["passed"]


def test_a_report_two_years_after_one_on_the_same_date_is_on_cadence():
    # HAL: Q3 2024 unfiled under 2.02, a stray filing on 2024-11-07; Q3 2025 still projects Q3 2026
    hal = [date.fromisoformat(d) for d in "2026-07-21 2026-04-21 2026-01-21 2025-10-21 2025-07-22 2025-04-22 2025-01-22 2024-11-07 2024-07-19 2024-04-23 2024-01-23 2023-10-24".split()]
    w = W.expected_window("HAL", hal, date(2026, 10, 13))
    assert w.start <= date(2026, 10, 20) <= w.end and w.computation_version == W.WINDOW_VERSION == 3


@pytest.mark.asyncio
async def test_the_fixture_score_stays_at_the_best_version():
    confirmed = S.load_fixture()
    windows = await S.verdict_windows(sorted(confirmed), S.FIXTURE_DAY)
    if sum(w is not None for w in windows.values()) < 80:
        pytest.skip("the database holds no stored filing verdicts for the fixture's tickers")
    r = S.score(confirmed, windows)
    assert r["total"] == 92 and r["contained"] >= 82, r["misses"]
    assert all(r["named"][s] for s in ("HAL", "KIM", "KKR"))
