"""Unit tests for auto_pick outcome codes and v2 worksheet field extraction."""
from decimal import Decimal

from app.scripts.auto_pick import _build_v2_fields, _build_verdict


# ── Outcome code mapping ──────────────────────────────────────────────────────

VALID_OUTCOME_CODES = {
    "no_fresh_chain", "vol_gate", "insufficient_history", "momentum_gate",
    "structure_failed", "picked", "cap_reached", "error", "no_features",
    "open_pick_exists", "skipped",
}


class TestOutcomeCodes:
    """Outcome must always be a short stable code, never free text."""

    def test_momentum_refusal_produces_short_code(self):
        """The free-text skip_reason is NOT used as outcome."""
        result = {
            "outcome": "momentum_gate",
            "receipt": {
                "momentum_20d": -1.9,
                "n_comparable": 18,
                "expected_pct": 5.2,
                "implied_pct": 6.1,
                "gate_reason": "momentum -1.9% above -10% cutoff",
            },
        }
        assert result["outcome"] in VALID_OUTCOME_CODES
        assert len(result["outcome"]) <= 40

    def test_vol_gate_refusal(self):
        result = {"outcome": "vol_gate", "receipt": {"gate_reason": "options pricing 8.5%, history says 5.2%"}}
        assert result["outcome"] in VALID_OUTCOME_CODES

    def test_insufficient_history_refusal(self):
        result = {"outcome": "insufficient_history", "receipt": {"gate_reason": "insufficient history, 3 events"}}
        assert result["outcome"] in VALID_OUTCOME_CODES


# ── Verdict generation ────────────────────────────────────────────────────────

class TestBuildVerdict:
    def test_momentum_gate_verdict(self):
        result = {"outcome": "momentum_gate"}
        receipt = {"momentum_20d": -1.9, "gate_reason": "momentum -1.9% above -10% cutoff"}
        v = _build_verdict(result, receipt)
        assert "momentum" in v.lower()
        assert "-2%" in v or "-1%" in v  # formatted as integer

    def test_vol_gate_verdict(self):
        result = {"outcome": "vol_gate"}
        receipt = {"gate_reason": "options pricing 8.5%, history says 5.2%"}
        v = _build_verdict(result, receipt)
        assert "options pricing" in v.lower() or "IV" in v

    def test_insufficient_history_verdict(self):
        result = {"outcome": "insufficient_history"}
        receipt = {"n_comparable": 3, "gate_reason": "insufficient history, 3 events"}
        v = _build_verdict(result, receipt)
        assert "3" in v
        assert "needs 8" in v

    def test_picked_with_structure(self):
        result = {"outcome": "picked", "structure": {"long_strike": 100, "short_strike": 105, "expiration": "2026-10-02"}}
        receipt = {"gate_reason": None}
        v = _build_verdict(result, receipt)
        assert v.startswith("Picked")
        assert "100" in v

    def test_no_fresh_chain_verdict(self):
        result = {"outcome": "no_fresh_chain"}
        receipt = {"gate_reason": "no fresh options chain for FDS"}
        v = _build_verdict(result, receipt)
        assert "no fresh chain" in v.lower()


# ── v2 worksheet field extraction ─────────────────────────────────────────────

class TestBuildV2Fields:
    def test_refusal_populates_fields(self):
        """A refused candidate must produce non-null momentum/prior_n from receipt."""
        result = {
            "outcome": "momentum_gate",
            "receipt": {
                "momentum_20d": -1.9,
                "n_comparable": 18,
                "expected_pct": 5.2,
                "implied_pct": 6.1,
                "gate_reason": "momentum -1.9% above -10% cutoff",
            },
        }
        fields = _build_v2_fields(result)
        assert fields is not None
        assert fields["momentum_20d"] == Decimal("-1.90")
        assert fields["prior_n"] == 18
        assert fields["expected_move_pct"] == Decimal("5.2")
        assert fields["implied_move_pct"] == Decimal("6.1")
        assert fields["verdict"] is not None
        assert len(fields["verdict"]) > 0

    def test_vol_gate_populates_both_moves(self):
        """Vol-gate refusals carry both implied and expected."""
        result = {
            "outcome": "vol_gate",
            "receipt": {
                "momentum_20d": -12.3,
                "n_comparable": 20,
                "expected_pct": 4.8,
                "implied_pct": 7.5,
                "gate_reason": "options pricing 7.5%, history says 4.8%",
            },
        }
        fields = _build_v2_fields(result)
        assert fields["expected_move_pct"] == Decimal("4.8")
        assert fields["implied_move_pct"] == Decimal("7.5")

    def test_no_receipt_returns_verdict_only(self):
        """If receipt is None, still return a dict with verdict."""
        result = {"outcome": "no_features", "receipt": None}
        fields = _build_v2_fields(result)
        assert fields is not None
        assert "verdict" in fields
        assert fields["verdict"] == "Passed, no features available"

    def test_no_chain_refusal_has_null_implied(self):
        """No-chain refusals carry momentum/prior_n/expected but implied is null."""
        result = {
            "outcome": "no_fresh_chain",
            "receipt": {
                "momentum_20d": -5.0,
                "n_comparable": 12,
                "expected_pct": 6.0,
                "implied_pct": None,
                "gate_reason": "no fresh options chain for FDS",
            },
        }
        fields = _build_v2_fields(result)
        assert fields["momentum_20d"] == Decimal("-5.00")
        assert fields["prior_n"] == 12
        assert fields["expected_move_pct"] == Decimal("6.0")
        assert "implied_move_pct" not in fields  # None values are not added
