"""Unit tests for ivy_shadow: predict shape, null handling, serialization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from app.services.ivy_shadow import (
    FEATURE_COLS,
    ShadowModel,
    ShadowPrediction,
    predict,
    train,
)


@dataclass
class FakeFeatureRow:
    """Minimal stand-in for EarningsFeature."""
    event_date: date = date(2024, 6, 15)
    actual_5d: float | None = 2.0
    momentum_20d: float | None = -12.0
    beat_rate: float | None = 65.0
    weighted_1d: float | None = 0.3
    prior_avg_abs_5d: float | None = 5.0
    prior_up_5d_rate: float | None = 0.55
    prior_n: int | None = 12
    analyst_net_90d: int | None = 1
    median_1d_beat: float | None = 2.0


def _make_rows(n: int = 200) -> list[FakeFeatureRow]:
    """Generate n synthetic rows spanning multiple dates."""
    rows = []
    for i in range(n):
        d = date(2022, 1, 1 + (i % 28))
        month = 1 + (i // 28) % 12
        year = 2022 + i // 336
        try:
            d = date(year, month, 1 + (i % 28))
        except ValueError:
            d = date(year, month, 1)
        rows.append(FakeFeatureRow(
            event_date=d,
            actual_5d=((i % 7) - 3.0),  # mix of positive and negative
            momentum_20d=-15.0 + (i % 30),
            beat_rate=50.0 + (i % 40),
            weighted_1d=-0.5 + (i % 10) * 0.2,
            prior_avg_abs_5d=3.0 + (i % 5),
            prior_up_5d_rate=0.4 + (i % 4) * 0.05,
            prior_n=5 + (i % 20),
            analyst_net_90d=(i % 5) - 2,
            median_1d_beat=1.0 + (i % 3),
        ))
    return rows


class TestTrainPredict:

    def test_train_returns_model(self):
        rows = _make_rows(200)
        tr = train(rows, cutoff_date=date(2025, 1, 1))
        assert tr.model is not None
        assert tr.n_train > 0
        assert len(tr.feature_importance) == len(FEATURE_COLS)

    def test_predict_shape(self):
        rows = _make_rows(200)
        tr = train(rows, cutoff_date=date(2025, 1, 1))
        pred = predict(tr.model, rows[0])
        assert isinstance(pred, ShadowPrediction)
        assert 0.0 <= pred.probability_up_5d <= 1.0
        assert len(pred.top_factors) == 3
        assert all(isinstance(f, str) for f in pred.top_factors)

    def test_predict_with_dict(self):
        rows = _make_rows(200)
        tr = train(rows, cutoff_date=date(2025, 1, 1))
        d = {
            "momentum_20d": -14.0,
            "beat_rate": 60.0,
            "weighted_1d": 0.5,
            "prior_avg_abs_5d": 4.0,
            "prior_up_5d_rate": 0.55,
            "prior_n": 10,
            "analyst_net_90d": 0,
            "median_1d_beat": 1.5,
        }
        pred = predict(tr.model, d)
        assert 0.0 <= pred.probability_up_5d <= 1.0
        assert len(pred.top_factors) == 3


class TestNullHandling:

    def test_all_nulls_predict(self):
        """Predict should work even with all features null."""
        rows = _make_rows(200)
        tr = train(rows, cutoff_date=date(2025, 1, 1))
        null_row = FakeFeatureRow(
            event_date=date(2025, 6, 1),
            actual_5d=None,
            momentum_20d=None,
            beat_rate=None,
            weighted_1d=None,
            prior_avg_abs_5d=None,
            prior_up_5d_rate=None,
            prior_n=None,
            analyst_net_90d=None,
            median_1d_beat=None,
        )
        pred = predict(tr.model, null_row)
        assert 0.0 <= pred.probability_up_5d <= 1.0
        # Should mention "(missing)" in factors
        assert any("missing" in f for f in pred.top_factors)

    def test_partial_nulls_predict(self):
        """Predict works with some null features."""
        rows = _make_rows(200)
        tr = train(rows, cutoff_date=date(2025, 1, 1))
        partial = FakeFeatureRow(
            event_date=date(2025, 6, 1),
            actual_5d=1.0,
            momentum_20d=-10.0,
            beat_rate=None,
            weighted_1d=0.5,
            prior_avg_abs_5d=None,
            prior_up_5d_rate=0.6,
            prior_n=12,
            analyst_net_90d=None,
            median_1d_beat=2.0,
        )
        pred = predict(tr.model, partial)
        assert 0.0 <= pred.probability_up_5d <= 1.0

    def test_null_dict_predict(self):
        rows = _make_rows(200)
        tr = train(rows, cutoff_date=date(2025, 1, 1))
        d = {col: None for col in FEATURE_COLS}
        pred = predict(tr.model, d)
        assert 0.0 <= pred.probability_up_5d <= 1.0


class TestSerialization:

    def test_roundtrip(self):
        rows = _make_rows(200)
        tr = train(rows, cutoff_date=date(2025, 1, 1))
        b64 = tr.model.serialize()
        restored = ShadowModel.deserialize(b64)
        pred_orig = predict(tr.model, rows[0])
        pred_restored = predict(restored, rows[0])
        assert abs(pred_orig.probability_up_5d - pred_restored.probability_up_5d) < 1e-6

    def test_too_few_rows_raises(self):
        rows = _make_rows(30)
        with pytest.raises(ValueError, match="Too few"):
            train(rows, cutoff_date=date(2025, 1, 1))
