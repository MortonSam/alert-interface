"""Hotfix 2026-10-20: a report is matched only to the quarter it announces. With the new quarter not on file, the 120-day reach took
the previous quarter (JPM's Oct 13 report showed Q2's $7.70; PLD's Oct 15 report Q2's FFO $1.70)."""
from datetime import date

import pytest

from app.services.eps_year_ago import load_quarters, quarter_for_report, year_ago_pairs

JPM = [(date(2025, 9, 30), 5.07), (date(2025, 12, 31), 4.64), (date(2026, 3, 31), 5.94), (date(2026, 6, 30), 7.70)]


def test_a_report_never_takes_the_previous_quarter():
    assert quarter_for_report(year_ago_pairs(JPM), date(2026, 10, 13)) is None              # Jun 30 is 105 days before Oct 13
    assert quarter_for_report(year_ago_pairs(JPM), date(2026, 7, 14))["eps"] == 7.70
    assert quarter_for_report(year_ago_pairs(JPM + [(date(2026, 9, 30), 5.57)]), date(2026, 10, 13))["eps"] == 5.57


class _Db:
    def __init__(self, xbrl, release):
        self.calls = [xbrl, release]

    async def execute(self, *_a, **_k):
        rows = self.calls.pop(0)

        class R:
            def all(self_inner):
                return rows
        return R()


@pytest.mark.asyncio
async def test_a_quarter_xbrl_lacks_comes_from_its_agreed_release():
    from types import SimpleNamespace as N
    db = _Db([N(period_end=d, eps=v) for d, v in JPM], [N(period_end=date(2026, 9, 30), diluted_eps_gaap=5.57), N(period_end=date(2026, 6, 30), diluted_eps_gaap=7.71)])
    q = await load_quarters(db, "JPM")
    assert q[-1] == (date(2026, 9, 30), 5.57) and dict(q)[date(2026, 6, 30)] == 7.70        # XBRL wins where it has the quarter
    pair = quarter_for_report(year_ago_pairs(q), date(2026, 10, 13))
    assert pair["eps"] == 5.57 and pair["year_ago_eps"] == 5.07
