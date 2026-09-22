"""A split after a quarter re-bases the frozen estimate; validate catches any row where it did not."""
from datetime import date
from decimal import Decimal

from app.models.enums import EarningsOutcome
from app.scripts.seed_historical_reactions import outcome_after_write, rebased_estimate
from app.scripts.validate_data import ERROR, PASS, estimate_split_basis_result
from app.services.split_basis import (
    anchored_factor, candidates, find_anchors, nearer_to_rebased, ratio_factor, rebase_factor,
    splits_after, stale_factor, wrong_basis_factor,
)

D = Decimal
S23, S26 = date(2023, 3, 28), date(2026, 8, 11)          # MNST 2:1 splits
A24, A26 = date(2024, 6, 12), date(2026, 9, 3)           # APH 2:1 splits
MNST = [(S23, 2.0), (S26, 2.0)]
APH = [(A24, 2.0), (A26, 2.0)]


def test_ratio_and_candidates():
    assert ratio_factor("2:1") == 2.0 and ratio_factor("3:2") == 1.5 and ratio_factor("1:50") == 0.02
    assert candidates(MNST) == [(2.0, S26), (4.0, S23)]     # latest split only, then both
    assert candidates([]) == []
    assert candidates([(S26, 0.5)]) == [(2.0, S26)]         # reverse split expressed as its inverse
    assert candidates([(S23, 37 / 35), (S26, 16 / 15)]) == []   # spin-off ratios are not re-basings
    assert splits_after(MNST, date(2022, 2, 24)) == MNST
    assert splits_after(MNST, date(2025, 8, 7)) == [(S26, 2.0)]
    assert splits_after(MNST, date(2026, 9, 1)) == []


def test_restated_actual_by_the_split_factor_is_a_rebasing():
    c = candidates(MNST)
    assert rebase_factor(D("0.30"), D("0.15"), c) == (2.0, S26)   # MNST 2022-02-24 after the 2026 2:1
    assert rebase_factor(D("0.69"), D("0.17"), c) == (4.0, S23)   # both splits at once
    assert rebase_factor(D("0.56"), D("0.30"), c) is None          # a genuine revision
    assert rebase_factor(D("0.30"), D("0.30"), c) is None          # unchanged
    assert rebase_factor(D("0.30"), D("0.15"), []) is None         # no split after the quarter


def test_frozen_estimate_rebases_with_the_actual_and_outcome_follows():
    est = rebased_estimate(D("0.30"), 2.0)
    assert est == D("0.15")
    assert outcome_after_write(est, D("0.30"), {"eps_actual": D("0.15")}, frozen=True) == EarningsOutcome.MEET
    est = rebased_estimate(D("0.53"), 2.0)   # MNST 2026-05-07: 0.265 vs 0.29
    assert outcome_after_write(est, D("0.55"), {"eps_actual": D("0.29")}, frozen=True) == EarningsOutcome.BEAT


def test_wrong_basis_factor_flags_only_a_stale_estimate_within_the_band():
    c = candidates([(S26, 2.0)])
    assert wrong_basis_factor(D("0.30"), D("0.15"), c) == (2.0, S26)      # MNST 2022-02-24
    assert wrong_basis_factor(D("0.33"), D("0.19"), c) == (2.0, S26)      # MNST 2023-05-04, 1.74x
    assert wrong_basis_factor(D("0.17"), D("0.19"), c) is None            # same basis
    assert wrong_basis_factor(D("0.52"), D("0.32"), c) is None            # APH 2025-04-23: 1.63x, outside the band
    assert wrong_basis_factor(D("0.42"), D("0.59"), candidates([(S26, 1.5)])) is None   # WRB: a real 40% beat
    assert wrong_basis_factor(D("3.13"), D("2.97"), candidates([(S26, 37 / 35)])) is None  # SPGI spin-off ratio


def test_anchors_extend_the_rebasing_to_rows_nearer_the_stale_basis():
    # APH: the two 2022 rows anchor (factor 2, split 2026-09-03); 2025 rows sit outside the band
    rows = [
        (date(2022, 4, 27), D("0.31"), D("0.17"), None),
        (date(2022, 7, 27), D("0.34"), D("0.19"), None),
        (date(2025, 4, 23), D("0.52"), D("0.32"), None),
        (date(2025, 7, 23), D("0.67"), D("0.41"), None),
        (date(2026, 1, 21), D("0.20"), D("0.21"), None),
    ]
    anchors = find_anchors(rows, APH)
    assert anchors == {(2.0, A26)}
    assert nearer_to_rebased(D("0.52"), D("0.32"), 2.0) is True     # 0.52 is nearer 0.64 than 0.32
    assert anchored_factor(D("0.52"), D("0.32"), date(2025, 4, 23), anchors) == (2.0, A26)
    assert anchored_factor(D("0.67"), D("0.41"), date(2025, 7, 23), anchors) == (2.0, A26)
    assert anchored_factor(D("0.20"), D("0.21"), date(2026, 1, 21), anchors) is None   # same basis
    assert anchored_factor(D("0.52"), D("0.32"), date(2026, 9, 10), anchors) is None   # after the split
    assert anchored_factor(D("0.52"), D("0.32"), date(2025, 4, 23), set()) is None     # no anchor, no extension
    # a restated actual anchors too
    assert find_anchors([(date(2022, 2, 24), D("0.15"), D("0.30"), D("0.15"))], MNST) == {(2.0, S26)}
    assert rebased_estimate(D("0.52"), 2.0) == D("0.26")   # -> beat against 0.32


def test_validate_check_levels():
    anchors = {(2.0, A26)}
    c = candidates(APH)
    rows = [
        ("APH", date(2022, 4, 27), D("0.31"), D("0.17"), c, anchors),
        ("APH", date(2025, 4, 23), D("0.52"), D("0.32"), c, anchors),
        ("APH", date(2026, 1, 21), D("0.20"), D("0.21"), c, anchors),
        ("PNC", date(2021, 10, 15), D("3.61"), D("3.30"), [], set()),
    ]
    out = estimate_split_basis_result(rows)
    assert out.level == ERROR and [r[:14] for r in out.rows] == ["APH 2022-04-27", "APH 2025-04-23"]
    assert "split 2026-09-03" in out.rows[1]
    assert estimate_split_basis_result(rows[2:]).level == PASS
    assert stale_factor(D("0.52"), D("0.32"), date(2025, 4, 23), c, set()) is None
