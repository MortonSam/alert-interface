"""
Single source of truth for all interpretive-label thresholds.

Every label shown on the frontend that derives from a numeric value
must be computed here. The backend sends { label, rule } so the
frontend never owns threshold logic.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class LabeledValue:
    label: str
    rule: str


# ── RV rank ───────────────────────────────────────────────────────────────────

RV_RANK_EXTREME = 90
RV_RANK_ELEVATED = 70
RV_RANK_NORMAL = 25


def rv_rank_label(rank: float | None) -> LabeledValue | None:
    if rank is None:
        return None
    if rank >= RV_RANK_EXTREME:
        return LabeledValue("extreme", f"rank {RV_RANK_EXTREME} or above")
    if rank >= RV_RANK_ELEVATED:
        return LabeledValue("elevated", f"rank {RV_RANK_ELEVATED} to {RV_RANK_EXTREME - 1}")
    if rank >= RV_RANK_NORMAL:
        return LabeledValue("normal", f"rank {RV_RANK_NORMAL} to {RV_RANK_ELEVATED - 1}")
    return LabeledValue("quiet", f"rank below {RV_RANK_NORMAL}")


# ── IV-RV spread ─────────────────────────────────────────────────────────────

SPREAD_RICH_PP = 10
SPREAD_CHEAP_PP = -10


def spread_label(spread_pp: float | None) -> LabeledValue | None:
    if spread_pp is None:
        return None
    if spread_pp > SPREAD_RICH_PP:
        return LabeledValue("options rich", f"implied vol {SPREAD_RICH_PP}+ points above realized")
    if spread_pp < SPREAD_CHEAP_PP:
        return LabeledValue("options cheap", f"implied vol {abs(SPREAD_CHEAP_PP)}+ points below realized")
    return LabeledValue("in line", "implied and realized vol within 10 points")


# ── IV-RV spread for discover (vol regime) ───────────────────────────────────
# Discover page uses wider asymmetric bands for badge assignment.

DISCOVER_IV_RICH_PP = 8
DISCOVER_IV_CHEAP_PP = -4


def vol_regime_label(spread_pp: float | None) -> LabeledValue | None:
    """Label used by the discover page vol-regime badges."""
    if spread_pp is None:
        return None
    if spread_pp > DISCOVER_IV_RICH_PP:
        return LabeledValue("IV rich", f"implied vol {DISCOVER_IV_RICH_PP}+ points above realized")
    if spread_pp < DISCOVER_IV_CHEAP_PP:
        return LabeledValue("IV cheap", f"implied vol {abs(DISCOVER_IV_CHEAP_PP)}+ points below realized")
    return None  # no badge


# ── Put/call ratio ───────────────────────────────────────────────────────────

PC_PUT_HEAVY = 1.2
PC_CALL_HEAVY = 0.7


def put_call_label(ratio: float | None) -> LabeledValue | None:
    if ratio is None:
        return None
    if ratio > PC_PUT_HEAVY:
        return LabeledValue("put-heavy", f"ratio above {PC_PUT_HEAVY}")
    if ratio < PC_CALL_HEAVY:
        return LabeledValue("call-heavy", f"ratio below {PC_CALL_HEAVY}")
    return LabeledValue("balanced", f"ratio between {PC_CALL_HEAVY} and {PC_PUT_HEAVY}")


# ── Priced-in (beat-but-dropped rate) ────────────────────────────────────────

PRICED_IN_LARGELY = 50
PRICED_IN_PARTIALLY = 25


def priced_in_label(drop_rate_pct: float | None) -> LabeledValue | None:
    if drop_rate_pct is None:
        return None
    if drop_rate_pct >= PRICED_IN_LARGELY:
        return LabeledValue(
            "beats appear largely priced in",
            f"stock dropped after {PRICED_IN_LARGELY}%+ of beats",
        )
    if drop_rate_pct >= PRICED_IN_PARTIALLY:
        return LabeledValue(
            "beats partially priced in",
            f"stock dropped after {PRICED_IN_PARTIALLY}-{PRICED_IN_LARGELY - 1}% of beats",
        )
    return LabeledValue(
        "beats tend to drive the stock higher",
        f"stock dropped after fewer than {PRICED_IN_PARTIALLY}% of beats",
    )


# ── Magnitude trend ─────────────────────────────────────────────────────────

MAGNITUDE_INCREASE_THRESHOLD = 0.20
MAGNITUDE_DECREASE_THRESHOLD = -0.20


def magnitude_trend_label(trend: str | None) -> LabeledValue | None:
    """Label from the already-computed trend string."""
    if trend is None:
        return None
    pct = int(abs(MAGNITUDE_INCREASE_THRESHOLD) * 100)
    if trend == "increasing":
        return LabeledValue("heating up", f"recent moves {pct}%+ larger than prior")
    if trend == "decreasing":
        return LabeledValue("cooling", f"recent moves {pct}%+ smaller than prior")
    return LabeledValue("stable", f"recent and prior moves within {pct}%")


# ── Discover unusually-active tier ───────────────────────────────────────────

DISCOVER_EXTREME_RV = 93
DISCOVER_ELEVATED_RV = 85  # retrieval filter


def discover_rv_tier(rv_rank: float) -> LabeledValue:
    if rv_rank >= DISCOVER_EXTREME_RV:
        return LabeledValue("extreme", f"RV rank {DISCOVER_EXTREME_RV}+")
    return LabeledValue("elevated", f"RV rank {DISCOVER_ELEVATED_RV} to {DISCOVER_EXTREME_RV - 1}")
