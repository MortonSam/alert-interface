"""The EPS basis check runs nightly after the earnings seeder, incrementally and within a budget."""
from collections import namedtuple
from decimal import Decimal

from app.scripts.check_eps_basis import TIME_BUDGET_SECONDS, needs_check
from app.scripts.refresh import STEPS, STEP_TIMEOUTS

Row = namedtuple("Row", "eps_actual checked_actual")


def test_incremental_selects_unchecked_and_changed_rows_only():
    assert needs_check(Row(Decimal("1.00"), None), incremental=True) is True          # never checked
    assert needs_check(Row(Decimal("1.05"), Decimal("1.00")), incremental=True) is True   # actual revised
    assert needs_check(Row(Decimal("1.00"), Decimal("1.00")), incremental=True) is False  # checked, unchanged
    assert needs_check(Row(Decimal("1.00"), Decimal("1.00")), incremental=False) is True  # full run


def test_step_runs_after_the_earnings_seeder_with_a_budget_inside_its_timeout():
    labels = [label for label, _ in STEPS]
    i = labels.index("Historical reactions (--all)")
    assert labels[i + 1] == "EPS basis check (check_eps_basis)"
    cmd = dict(STEPS)["EPS basis check (check_eps_basis)"]
    assert cmd[-1] == "--incremental"
    assert STEP_TIMEOUTS["EPS basis check (check_eps_basis)"] > TIME_BUDGET_SECONDS


def test_step_age_covers_the_new_step():
    # check_step_age builds its dict from STEPS, so the label is covered without a code change
    assert "EPS basis check (check_eps_basis)" in [label for label, _ in STEPS]
