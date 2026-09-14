"""Ivy shadow model: calibrated logistic regression on earnings features.

Simple on purpose (10k rows). Trained nightly, predicts probability that
actual_5d > 0, with human-readable factor explanations.

Never writes to alert_picks. Shadow-only.
"""

from __future__ import annotations

import base64
import pickle
from dataclasses import dataclass, field
from datetime import date

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

# ── Feature spec ─────────────────────────────────────────────────────────────

FEATURE_COLS = [
    "momentum_20d",
    "beat_rate",
    "weighted_1d",
    "prior_avg_abs_5d",
    "prior_up_5d_rate",
    "prior_n",
    "analyst_net_90d",
    "median_1d_beat",
]

# Human-readable names for explanations
_COL_NAMES = {
    "momentum_20d": "20-day momentum",
    "beat_rate": "beat rate",
    "weighted_1d": "weighted 1d move",
    "prior_avg_abs_5d": "avg |5d move|",
    "prior_up_5d_rate": "prior up-5d rate",
    "prior_n": "prior event count",
    "analyst_net_90d": "analyst net 90d",
    "median_1d_beat": "median 1d on beat",
}

_COL_UNITS = {
    "momentum_20d": "%",
    "beat_rate": "%",
    "weighted_1d": "%",
    "prior_avg_abs_5d": "%",
    "prior_up_5d_rate": "",
    "prior_n": "",
    "analyst_net_90d": "",
    "median_1d_beat": "%",
}


@dataclass
class ShadowPrediction:
    probability_up_5d: float
    top_factors: list[str]


@dataclass
class TrainResult:
    model: ShadowModel
    feature_importance: list[tuple[str, float]]
    n_train: int
    n_positive: int


@dataclass
class ShadowModel:
    pipeline: Pipeline
    medians: dict[str, float]
    feature_cols: list[str] = field(default_factory=lambda: list(FEATURE_COLS))

    def serialize(self) -> str:
        """Serialize to base64 string for system_metadata storage."""
        return base64.b64encode(pickle.dumps(self)).decode("ascii")

    @staticmethod
    def deserialize(b64: str) -> ShadowModel:
        """Deserialize from base64 string."""
        return pickle.loads(base64.b64decode(b64))


# ── Feature extraction ───────────────────────────────────────────────────────

def _extract_row(row, medians: dict[str, float]) -> list[float]:
    """Extract feature vector from an EarningsFeature-like object.

    Null-safe: imputes with training median. Appends an is_null flag
    per column (doubles the feature count).
    """
    values = []
    for col in FEATURE_COLS:
        raw = getattr(row, col, None)
        if raw is not None:
            val = float(raw)
            values.append(val)
            values.append(0.0)  # is_null = False
        else:
            values.append(medians.get(col, 0.0))
            values.append(1.0)  # is_null = True
    return values


def _extract_row_from_dict(d: dict, medians: dict[str, float]) -> list[float]:
    """Extract feature vector from a plain dict."""
    values = []
    for col in FEATURE_COLS:
        raw = d.get(col)
        if raw is not None:
            values.append(float(raw))
            values.append(0.0)
        else:
            values.append(medians.get(col, 0.0))
            values.append(1.0)
    return values


def _compute_medians(rows: list) -> dict[str, float]:
    """Compute training medians for imputation."""
    col_vals: dict[str, list[float]] = {col: [] for col in FEATURE_COLS}
    for r in rows:
        for col in FEATURE_COLS:
            val = getattr(r, col, None)
            if val is not None:
                col_vals[col].append(float(val))
    medians = {}
    for col, vals in col_vals.items():
        medians[col] = float(np.median(vals)) if vals else 0.0
    return medians


# ── Train ────────────────────────────────────────────────────────────────────

def train(rows: list, cutoff_date: date) -> TrainResult:
    """Fit shadow model on events strictly before cutoff_date.

    Args:
        rows: list of EarningsFeature-like objects with FEATURE_COLS + actual_5d
        cutoff_date: train on events before this date

    Returns:
        TrainResult with fitted model, feature importance, and counts.
    """
    train_rows = [r for r in rows if r.event_date < cutoff_date and
                  getattr(r, "actual_5d", None) is not None]

    if len(train_rows) < 50:
        raise ValueError(f"Too few training rows ({len(train_rows)}), need >= 50")

    medians = _compute_medians(train_rows)

    X = np.array([_extract_row(r, medians) for r in train_rows])
    y = np.array([1 if float(r.actual_5d) > 0 else 0 for r in train_rows])

    # Logistic regression with L2, C tuned via internal CV
    base_lr = LogisticRegression(max_iter=2000, solver="lbfgs")
    # Calibrated with isotonic regression on 5-fold CV
    calibrated = CalibratedClassifierCV(base_lr, cv=5, method="isotonic")
    pipe = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", calibrated),
    ])
    pipe.fit(X, y)

    # Feature importance: standardized coefficients from a refitted plain LR
    # (the calibrated wrapper doesn't expose a single coef_ vector cleanly)
    plain_lr = Pipeline([
        ("scaler", StandardScaler()),
        ("clf", LogisticRegression(max_iter=2000, solver="lbfgs")),
    ])
    plain_lr.fit(X, y)
    coefs = plain_lr.named_steps["clf"].coef_[0]

    # Map back to original column names (skip is_null flags for importance)
    importance = []
    for i, col in enumerate(FEATURE_COLS):
        idx = i * 2  # each col has (value, is_null_flag)
        importance.append((col, round(float(coefs[idx]), 4)))
    importance.sort(key=lambda x: abs(x[1]), reverse=True)

    model = ShadowModel(pipeline=pipe, medians=medians)
    return TrainResult(
        model=model,
        feature_importance=importance,
        n_train=len(train_rows),
        n_positive=int(y.sum()),
    )


# ── Predict ──────────────────────────────────────────────────────────────────

def predict(model: ShadowModel, features) -> ShadowPrediction:
    """Predict probability_up_5d and top 3 factors.

    Args:
        features: an EarningsFeature-like object or dict with FEATURE_COLS

    Returns:
        ShadowPrediction with probability and factor phrases.
    """
    if isinstance(features, dict):
        x = np.array([_extract_row_from_dict(features, model.medians)])
    else:
        x = np.array([_extract_row(features, model.medians)])

    prob = float(model.pipeline.predict_proba(x)[0, 1])

    # Compute feature contributions for explanation
    # Use the scaler transform + raw feature values to explain
    factors = _explain_top_factors(model, features)

    return ShadowPrediction(
        probability_up_5d=round(prob, 4),
        top_factors=factors[:3],
    )


def _explain_top_factors(model: ShadowModel, features) -> list[str]:
    """Return human-readable factor explanations sorted by impact.

    Extracts raw values, computes standardized contribution using a
    refitted plain LR approximation (stored in the pipeline's scaler
    means/stds for direction only).
    """
    if isinstance(features, dict):
        raw_vals = {col: features.get(col) for col in FEATURE_COLS}
    else:
        raw_vals = {col: getattr(features, col, None) for col in FEATURE_COLS}

    # Build the full feature vector to get scaler-transformed values
    if isinstance(features, dict):
        x = np.array([_extract_row_from_dict(features, model.medians)])
    else:
        x = np.array([_extract_row(features, model.medians)])

    scaler = model.pipeline.named_steps["scaler"]
    x_scaled = scaler.transform(x)[0]

    # Get coefficients from the calibrated model's base estimators
    # Average across calibrated estimators for a single direction vector
    clf = model.pipeline.named_steps["clf"]
    coefs_list = []
    for est in clf.calibrated_classifiers_:
        coefs_list.append(est.estimator.coef_[0])
    avg_coefs = np.mean(coefs_list, axis=0)

    # Contribution = scaled_value * coefficient (for the real feature, not null flag)
    contributions = []
    for i, col in enumerate(FEATURE_COLS):
        idx = i * 2
        contrib = x_scaled[idx] * avg_coefs[idx]
        raw = raw_vals[col]
        contributions.append((col, contrib, raw))

    contributions.sort(key=lambda x: abs(x[1]), reverse=True)

    phrases = []
    for col, contrib, raw in contributions:
        name = _COL_NAMES.get(col, col)
        unit = _COL_UNITS.get(col, "")
        direction = "pushed up" if contrib > 0 else "pushed down"
        if raw is not None:
            val = float(raw)
            if unit == "%":
                phrases.append(f"{name} {val:+.0f}% {direction}")
            else:
                phrases.append(f"{name} {val:.0f} {direction}")
        else:
            phrases.append(f"{name} (missing) {direction}")
    return phrases
