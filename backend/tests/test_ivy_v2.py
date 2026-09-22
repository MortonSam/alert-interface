"""Unit tests for ivy_v2 gate math.

Tests use mock objects to avoid needing a real DB connection.
All tests target the deterministic gate logic, not the AI narration.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.services.ivy_v2 import (
    IV_PREMIUM_CAP,
    LiveFeatures,
    MIN_PRIOR_N,
    MOMENTUM_CUTOFF,
    V2Result,
    compute_expected_move,
    compute_expected_move_live,
    decide,
)


# ── Fake EarningsFeature for testing ─────────────────────────────────────────

@dataclass
class FakeFeature:
    """Minimal stand-in for EarningsFeature with the fields decide() reads."""
    symbol: str = "TEST"
    event_date: date = date(2025, 1, 15)
    momentum_20d: Decimal | None = Decimal("-20.0")
    prior_n: int | None = 10
    prior_avg_abs_5d: Decimal | None = Decimal("5.0")
    prior_up_5d_rate: Decimal | None = Decimal("0.58")
    beat_rate: Decimal | None = Decimal("65.0")
    actual_5d: Decimal | None = Decimal("3.5")


def _make_feature(**overrides) -> FakeFeature:
    return FakeFeature(**overrides)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _run(coro):
    """Run an async coroutine on a private loop: decide() gets a mocked db, so no pooled connection is involved."""
    return asyncio.run(coro)


def _decide_with_mocked_chain(
    feature,
    implied_move: float | None = 3.0,
    has_fresh_chain: bool = True,
    all_features: list | None = None,
) -> V2Result:
    """Call decide() with compute_implied_move mocked out."""
    mock_db = AsyncMock()
    with patch("app.services.ivy_v2.compute_implied_move", new_callable=AsyncMock) as mock_cim:
        mock_cim.return_value = (implied_move, has_fresh_chain)
        return _run(decide(
            features=feature,
            db=mock_db,
            symbol=feature.symbol,
            event_date=feature.event_date,
            all_features=all_features,
            ai_client=None,
        ))


# ══════════════════════════════════════════════════════════════════════════════
# Volatility gate tests
# ══════════════════════════════════════════════════════════════════════════════

class TestVolatilityGate:

    def test_no_fresh_chain_refuses(self):
        """No fresh chain → refuse with descriptive reason."""
        feat = _make_feature()
        result = _decide_with_mocked_chain(feat, implied_move=None, has_fresh_chain=False)
        assert result.pick is False
        assert result.gate_passed is False
        assert "no fresh options chain" in result.skip_reason
        assert "TEST" in result.skip_reason

    def test_implied_exceeds_cap_refuses(self):
        """implied_move > 1.2 × expected_move → refuse."""
        feat = _make_feature(prior_avg_abs_5d=Decimal("5.0"))  # expected = 5.0
        # implied = 7.0 → 7.0 > 1.2 * 5.0 = 6.0 → refuse
        result = _decide_with_mocked_chain(feat, implied_move=7.0, has_fresh_chain=True)
        assert result.pick is False
        assert result.gate_passed is False
        assert "options pricing" in result.skip_reason
        assert "history says" in result.skip_reason

    def test_implied_within_cap_passes(self):
        """implied_move ≤ 1.2 × expected_move → pass vol gate."""
        feat = _make_feature(prior_avg_abs_5d=Decimal("5.0"))
        # implied = 5.5 → 5.5 ≤ 6.0 → pass
        result = _decide_with_mocked_chain(feat, implied_move=5.5, has_fresh_chain=True)
        # Should pass vol gate (may still pick=True if other gates pass)
        assert result.pick is True
        assert "options pricing" not in (result.skip_reason or "")

    def test_implied_exactly_at_cap_passes(self):
        """implied_move == 1.2 × expected_move → pass (not strictly greater)."""
        feat = _make_feature(prior_avg_abs_5d=Decimal("5.0"))
        # implied = 6.0 → 6.0 > 6.0 is False → pass
        result = _decide_with_mocked_chain(feat, implied_move=6.0, has_fresh_chain=True)
        assert "options pricing" not in (result.skip_reason or "")


# ══════════════════════════════════════════════════════════════════════════════
# History gate tests
# ══════════════════════════════════════════════════════════════════════════════

class TestHistoryGate:

    def test_insufficient_prior_n_skips(self):
        """prior_n < MIN_PRIOR_N → skip."""
        feat = _make_feature(prior_n=5)  # MIN_PRIOR_N is 8
        result = _decide_with_mocked_chain(feat)
        assert result.pick is False
        assert "insufficient history" in result.skip_reason
        assert "5 events" in result.skip_reason

    def test_none_prior_n_skips(self):
        """prior_n is None → skip."""
        feat = _make_feature(prior_n=None)
        result = _decide_with_mocked_chain(feat)
        assert result.pick is False
        assert "insufficient history" in result.skip_reason

    def test_sufficient_prior_n_passes(self):
        """prior_n >= MIN_PRIOR_N → pass history gate."""
        feat = _make_feature(prior_n=8)
        result = _decide_with_mocked_chain(feat)
        assert "insufficient history" not in (result.skip_reason or "")


# ══════════════════════════════════════════════════════════════════════════════
# Momentum qualifying tests
# ══════════════════════════════════════════════════════════════════════════════

class TestMomentumGate:

    def test_momentum_below_cutoff_qualifies(self):
        """momentum_20d ≤ -10% → qualifies."""
        feat = _make_feature(momentum_20d=Decimal("-20.0"))
        result = _decide_with_mocked_chain(feat)
        assert result.pick is True
        assert result.direction == "bullish"

    def test_momentum_at_cutoff_qualifies(self):
        """momentum_20d == -10% → qualifies (≤ not <)."""
        feat = _make_feature(momentum_20d=Decimal("-10.0"))
        result = _decide_with_mocked_chain(feat)
        assert result.pick is True
        assert result.direction == "bullish"

    def test_momentum_above_cutoff_skips(self):
        """momentum_20d > -10% → skip."""
        feat = _make_feature(momentum_20d=Decimal("-5.0"))
        result = _decide_with_mocked_chain(feat)
        assert result.pick is False
        assert "momentum" in result.skip_reason
        assert "cutoff" in result.skip_reason

    def test_no_momentum_data_skips(self):
        """momentum_20d is None → skip."""
        feat = _make_feature(momentum_20d=None)
        result = _decide_with_mocked_chain(feat)
        assert result.pick is False
        assert "no momentum data" in result.skip_reason


# ══════════════════════════════════════════════════════════════════════════════
# compute_expected_move tests
# ══════════════════════════════════════════════════════════════════════════════

class TestComputeExpectedMove:

    def test_returns_prior_avg_abs_5d_when_enough_data(self):
        feat = _make_feature(prior_n=10, prior_avg_abs_5d=Decimal("4.5"))
        result = compute_expected_move(feat)
        assert result == 4.5

    def test_returns_none_when_insufficient_data(self):
        feat = _make_feature(prior_n=5, prior_avg_abs_5d=Decimal("4.5"))
        result = compute_expected_move(feat)
        assert result is None

    def test_returns_none_when_prior_n_is_none(self):
        feat = _make_feature(prior_n=None, prior_avg_abs_5d=Decimal("4.5"))
        result = compute_expected_move(feat)
        assert result is None

    def test_returns_none_when_avg_is_none(self):
        feat = _make_feature(prior_n=10, prior_avg_abs_5d=None)
        result = compute_expected_move(feat)
        assert result is None


# ══════════════════════════════════════════════════════════════════════════════
# Full gate pipeline tests
# ══════════════════════════════════════════════════════════════════════════════

class TestGatePipeline:

    def test_all_gates_pass_returns_bullish_with_receipt(self):
        """Full qualifying event → pick=True, direction=bullish, receipt populated."""
        feat = _make_feature(
            momentum_20d=Decimal("-20.0"),
            prior_n=10,
            prior_avg_abs_5d=Decimal("5.0"),
        )
        result = _decide_with_mocked_chain(feat, implied_move=4.0, has_fresh_chain=True)
        assert result.pick is True
        assert result.direction == "bullish"
        assert result.gate_passed is True
        assert result.skip_reason is None
        assert result.receipt["gate_reason"] is None
        assert result.receipt["reasoning"] is not None
        assert "TEST" in result.receipt["reasoning"]

    def test_vol_gate_checked_before_history(self):
        """Vol gate fires before history gate, even if prior_n is also bad."""
        feat = _make_feature(prior_n=3, momentum_20d=Decimal("-20.0"))
        result = _decide_with_mocked_chain(feat, implied_move=None, has_fresh_chain=False)
        assert "no fresh options chain" in result.skip_reason
        # Should NOT mention "insufficient history" — vol gate comes first
        assert "insufficient history" not in result.skip_reason

    def test_direction_always_bullish(self):
        """v2 only produces bullish picks, never bearish."""
        feat = _make_feature(momentum_20d=Decimal("-25.0"))
        result = _decide_with_mocked_chain(feat)
        assert result.direction == "bullish"


# ══════════════════════════════════════════════════════════════════════════════
# LiveFeatures tests
# ══════════════════════════════════════════════════════════════════════════════

def _make_live(**overrides) -> LiveFeatures:
    defaults = dict(
        symbol="TEST",
        event_date=date(2026, 9, 20),
        momentum_20d=-15.0,
        prior_n=12,
        prior_avg_abs_5d=5.0,
        prior_up_5d_rate=0.58,
        beat_rate=65.0,
    )
    defaults.update(overrides)
    return LiveFeatures(**defaults)


class TestLiveFeatures:

    def test_decide_accepts_live_features(self):
        """decide() works with LiveFeatures (not just EarningsFeature)."""
        live = _make_live()
        result = _decide_with_mocked_chain(live, implied_move=4.0, has_fresh_chain=True)
        assert result.pick is True
        assert result.direction == "bullish"

    def test_live_momentum_above_cutoff_skips(self):
        live = _make_live(momentum_20d=-5.0)
        result = _decide_with_mocked_chain(live, implied_move=4.0, has_fresh_chain=True)
        assert result.pick is False
        assert "momentum" in result.skip_reason

    def test_live_insufficient_prior_n_skips(self):
        live = _make_live(prior_n=3)
        result = _decide_with_mocked_chain(live, implied_move=4.0, has_fresh_chain=True)
        assert result.pick is False
        assert "insufficient history" in result.skip_reason

    def test_compute_expected_move_live(self):
        live = _make_live(prior_n=10, prior_avg_abs_5d=4.5)
        assert compute_expected_move_live(live) == 4.5

    def test_compute_expected_move_live_insufficient(self):
        live = _make_live(prior_n=5, prior_avg_abs_5d=4.5)
        assert compute_expected_move_live(live) is None
