"""A split after a quarter re-bases the frozen estimate; validate catches any row where it did not."""
from datetime import date
from decimal import Decimal

from app.models.enums import EarningsOutcome
from app.scripts.seed_historical_reactions import outcome_after_write, rebased_estimate
from app.scripts.validate_data import ERROR, PASS, estimate_split_basis_result
from app.services.split_basis import (
    factors_after, ratio_factor, rebase_factor, suffix_factors, wrong_basis_factor,
)

D = Decimal


def test_ratio_and_suffix_factors():
    assert ratio_factor("2:1") == 2.0 and ratio_factor("3:2") == 1.5 and ratio_factor("1:50") == 0.02
    assert suffix_factors([2.0, 2.0]) == [2.0, 4.0]          # latest split only, then both
    assert suffix_factors([]) == []
    assert suffix_factors([0.5]) == [2.0]                    # reverse split expressed as its inverse
    assert suffix_factors([37 / 35, 16 / 15]) == []          # spin-off ratios are not re-basings
    splits = [(date(2023, 3, 28), 2.0), (date(2026, 8, 11), 2.0)]
    assert factors_after(splits, date(2022, 2, 24)) == [2.0, 2.0]
    assert factors_after(splits, date(2025, 8, 7)) == [2.0]
    assert factors_after(splits, date(2026, 9, 1)) == []


def test_restated_actual_by_the_split_factor_is_a_rebasing():
    # MNST 2022-02-24: stored actual 0.30, Yahoo now reports 0.15 after the 2026 2:1
    assert rebase_factor(D("0.30"), D("0.15"), [2.0, 2.0]) == 2.0
    # APH 2022-04-27 after two 2:1 splits: 0.69 -> 0.1725 is the full product
    assert rebase_factor(D("0.69"), D("0.17"), [2.0, 2.0]) == 4.0
    # A genuine revision is not a split factor
    assert rebase_factor(D("0.56"), D("0.30"), [2.0]) is None
    assert rebase_factor(D("0.30"), D("0.30"), [2.0]) is None          # unchanged
    assert rebase_factor(D("0.30"), D("0.15"), []) is None             # no split after the quarter


def test_frozen_estimate_rebases_with_the_actual_and_outcome_follows():
    est = rebased_estimate(D("0.30"), 2.0)
    assert est == D("0.15")
    assert outcome_after_write(est, D("0.30"), {"eps_actual": D("0.15")}, frozen=True) == EarningsOutcome.MEET
    est = rebased_estimate(D("0.53"), 2.0)   # MNST 2026-05-07: 0.265 vs 0.29
    assert outcome_after_write(est, D("0.55"), {"eps_actual": D("0.29")}, frozen=True) == EarningsOutcome.BEAT


def test_wrong_basis_factor_flags_only_a_stale_estimate():
    assert wrong_basis_factor(D("0.30"), D("0.15"), [2.0]) == 2.0      # MNST 2022-02-24
    assert wrong_basis_factor(D("0.33"), D("0.19"), [2.0]) == 2.0      # MNST 2023-05-04, 1.74x
    assert wrong_basis_factor(D("0.34"), D("0.19"), [2.0, 2.0]) == 2.0  # APH 2022-07-27, latest split only
    assert wrong_basis_factor(D("0.17"), D("0.19"), [2.0]) is None      # same basis
    assert wrong_basis_factor(D("0.42"), D("0.59"), [1.5]) is None      # WRB: a real 40% beat, actual is never stale
    assert wrong_basis_factor(D("3.13"), D("2.97"), [37 / 35]) is None  # SPGI: spin-off ratio, ordinary surprise
    assert wrong_basis_factor(D("0.30"), D("0.15"), []) is None         # no split after


def test_validate_check_levels():
    rows = [
        ("MNST", date(2022, 2, 24), D("0.30"), D("0.15"), [2.0, 2.0]),
        ("MNST", date(2025, 8, 7), D("0.24"), D("0.25"), [2.0]),
        ("PNC", date(2021, 10, 15), D("3.61"), D("3.30"), []),
    ]
    out = estimate_split_basis_result(rows)
    assert out.level == ERROR and len(out.rows) == 1 and out.rows[0].startswith("MNST 2022-02-24")
    assert estimate_split_basis_result(rows[1:]).level == PASS
