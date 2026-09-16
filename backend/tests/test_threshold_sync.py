"""
Drift guard: asserts that frontend/src/lib/thresholds.ts matches
backend/app/thresholds.py for every shared constant.

Fails CI if they diverge.
"""

import re
from pathlib import Path

import pytest

import app.thresholds as T

# Path to the frontend mirror file.
# From tests/ -> backend/ -> repo root -> frontend/
_HERE = Path(__file__).resolve()
FRONTEND_TS = _HERE.parents[2] / "frontend" / "src" / "lib" / "thresholds.ts"

# Constants that must match between backend and frontend
EXPECTED = {
    "RV_RANK_EXTREME": T.RV_RANK_EXTREME,
    "RV_RANK_ELEVATED": T.RV_RANK_ELEVATED,
    "RV_RANK_NORMAL": T.RV_RANK_NORMAL,
    "SPREAD_RICH_PP": T.SPREAD_RICH_PP,
    "SPREAD_CHEAP_PP": T.SPREAD_CHEAP_PP,
    "DISCOVER_IV_RICH_PP": T.DISCOVER_IV_RICH_PP,
    "DISCOVER_IV_CHEAP_PP": T.DISCOVER_IV_CHEAP_PP,
    "PC_PUT_HEAVY": T.PC_PUT_HEAVY,
    "PC_CALL_HEAVY": T.PC_CALL_HEAVY,
    "PRICED_IN_LARGELY": T.PRICED_IN_LARGELY,
    "PRICED_IN_PARTIALLY": T.PRICED_IN_PARTIALLY,
    "MAGNITUDE_INCREASE_THRESHOLD": T.MAGNITUDE_INCREASE_THRESHOLD,
    "MAGNITUDE_DECREASE_THRESHOLD": T.MAGNITUDE_DECREASE_THRESHOLD,
    "DISCOVER_EXTREME_RV": T.DISCOVER_EXTREME_RV,
    "DISCOVER_ELEVATED_RV": T.DISCOVER_ELEVATED_RV,
}


def _parse_ts_constants(text: str) -> dict[str, float]:
    """Extract `export const NAME = VALUE;` from TypeScript source."""
    out: dict[str, float] = {}
    for m in re.finditer(r"export\s+const\s+(\w+)\s*=\s*(-?[\d.]+)", text):
        out[m.group(1)] = float(m.group(2))
    return out


def test_frontend_thresholds_match_backend():
    if not FRONTEND_TS.exists():
        pytest.skip(f"Frontend thresholds file not found at {FRONTEND_TS} (running in Docker?)")
    ts_values = _parse_ts_constants(FRONTEND_TS.read_text())

    missing = set(EXPECTED) - set(ts_values)
    assert not missing, f"Constants missing from frontend thresholds.ts: {missing}"

    mismatched = {
        k: (EXPECTED[k], ts_values[k])
        for k in EXPECTED
        if ts_values.get(k) != EXPECTED[k]
    }
    assert not mismatched, f"Threshold drift detected: {mismatched}"
