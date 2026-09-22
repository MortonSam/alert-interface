"""Outcome is derived from the EPS values a row will hold after every write, never frozen on its own."""
from decimal import Decimal

from app.models.enums import EarningsOutcome
from app.scripts.seed_historical_reactions import FROZEN_KEYS, outcome_after_write

D = Decimal


def test_revised_actual_on_a_frozen_row_re_derives_outcome():
    # TTWO 2025-02-06: stored estimate 0.56 frozen, Yahoo revises the actual to -0.71
    out = outcome_after_write(stored_estimate=D("0.56"), stored_actual=D("0.30"),
                              data={"eps_estimate": D("0.10"), "eps_actual": D("-0.71")}, frozen=True)
    assert out == EarningsOutcome.MISS


def test_frozen_row_keeps_stored_estimate_even_if_a_new_one_arrives():
    out = outcome_after_write(stored_estimate=D("1.00"), stored_actual=D("1.10"),
                              data={"eps_estimate": D("2.00"), "eps_actual": D("1.10")}, frozen=True)
    assert out == EarningsOutcome.BEAT   # 1.10 vs the stored 1.00, not the incoming 2.00


def test_unfrozen_row_uses_incoming_values():
    out = outcome_after_write(stored_estimate=None, stored_actual=None,
                              data={"eps_estimate": D("1.00"), "eps_actual": D("0.90")}, frozen=False)
    assert out == EarningsOutcome.MISS
    out = outcome_after_write(stored_estimate=D("1.00"), stored_actual=None,
                              data={"eps_estimate": D("1.20")}, frozen=False)
    assert out == EarningsOutcome.UNKNOWN   # no actual anywhere


def test_missing_incoming_actual_falls_back_to_stored():
    out = outcome_after_write(stored_estimate=D("1.00"), stored_actual=D("1.00"),
                              data={"pct_change_1d": D("2.0")}, frozen=True)
    assert out == EarningsOutcome.MEET


def test_outcome_is_not_a_frozen_key():
    assert "outcome" not in FROZEN_KEYS
    assert FROZEN_KEYS == {"eps_estimate", "revenue_estimate"}
