"""The RV extreme-return guard tells a real crash from a bad split adjustment.

A |log return| above the threshold is data_error only when the session's volume
is below VOLUME_SPIKE_MULTIPLE x the trailing median and no split or dividend is
recorded for that date.
"""
from datetime import date

import numpy as np
import pandas as pd

from app.services.rv_math import (
    VOLUME_SPIKE_MULTIPLE,
    _RETURN_THRESHOLD,
    compute_rv_metrics,
    extreme_return_is_real,
)

N = 320
CRASH_POS = 300


def _series(crash: bool, crash_volume_multiple: float | None = None):
    idx = pd.bdate_range("2025-01-01", periods=N)
    rng = np.random.default_rng(7)
    closes = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.01, N))), index=idx)
    volumes = pd.Series(np.full(N, 1_000_000.0), index=idx)
    if crash:
        closes.iloc[CRASH_POS:] *= 0.6  # -40%: |log return| 0.51 > threshold
        if crash_volume_multiple is not None:
            volumes.iloc[CRASH_POS] = 1_000_000.0 * crash_volume_multiple
    return closes, volumes, idx[CRASH_POS].date()


def test_no_extreme_return_is_ok_without_volumes():
    closes, _, _ = _series(crash=False)
    assert compute_rv_metrics(closes)["status"] == "ok"


def test_crash_without_volumes_or_actions_is_data_error():
    closes, _, _ = _series(crash=True)
    assert compute_rv_metrics(closes)["status"] == "data_error"


def test_crash_on_normal_volume_is_data_error():
    closes, volumes, _ = _series(crash=True, crash_volume_multiple=2.0)
    assert compute_rv_metrics(closes, volumes=volumes, action_dates=set())["status"] == "data_error"


def test_crash_on_volume_spike_is_a_real_move():
    closes, volumes, _ = _series(crash=True, crash_volume_multiple=VOLUME_SPIKE_MULTIPLE)
    out = compute_rv_metrics(closes, volumes=volumes, action_dates=set())
    assert out["status"] == "ok"
    assert out["rv_20d"] is not None and out["rv_rank"] is not None


def test_crash_on_a_recorded_action_date_is_a_real_move():
    closes, volumes, crash_day = _series(crash=True, crash_volume_multiple=1.0)
    assert compute_rv_metrics(closes, volumes=volumes, action_dates={crash_day})["status"] == "ok"
    other_day = date(2020, 1, 1)
    assert compute_rv_metrics(closes, volumes=volumes, action_dates={other_day})["status"] == "data_error"


def test_extreme_return_is_real_uses_trailing_median_not_the_spike_itself():
    idx = pd.bdate_range("2025-01-01", periods=80)
    volumes = pd.Series(np.full(80, 100.0), index=idx)
    volumes.iloc[70] = 499.0   # just under 5x
    assert extreme_return_is_real(idx[70].date(), volumes, set()) is False
    volumes.iloc[70] = 500.0
    assert extreme_return_is_real(idx[70].date(), volumes, set()) is True
    assert extreme_return_is_real(date(2030, 1, 1), volumes, set()) is False   # not in index


def test_threshold_is_a_50_percent_move():
    assert abs(_RETURN_THRESHOLD - np.log(1.5)) < 1e-3
