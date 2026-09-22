"""The one-line blurbs on discover cards. One template per fact, built from the
same values the card's chips are built from (rv_rank_label for the RV word,
the vol regime the chip shows, the conditional earnings stats).
"""
from __future__ import annotations

from app.services.basis_exclusion import excluded_note
from app.thresholds import PRICED_IN_PARTIALLY, rv_rank_label

MIN_QUARTERS = 4

VOL_REGIME_WORDS = {"iv_rich": "IV rich", "iv_cheap": "IV cheap", None: "IV in line with realized"}


def earnings_blurb(cond: dict | None) -> str | None:
    """Reporting-soon card. Facts in priority order: beats that sold off, a high beat rate, the typical move."""
    if not cond or cond["total"] < MIN_QUARTERS:
        return None
    total, beats, sold_off = cond["total"], cond["beat_count"], cond["bbd_count"]
    note = excluded_note(cond.get("basis_excluded", 0))
    excl = f" ({note})" if note else ""

    if beats >= 4 and sold_off >= 2:
        pct = round(sold_off / beats * 100)
        if pct >= PRICED_IN_PARTIALLY:      # the same cutoff the priced-in label uses
            return f"Beat {beats} of {total}; the stock fell after {pct}% of those beats{excl}"

    if beats >= 3 and beats / total >= 0.75 and cond.get("avg_1d_on_beat") is not None:
        avg = cond["avg_1d_on_beat"]
        return f"Beat {beats} of {total}, averaging {avg:+.1f}% on the 1-day reaction to a beat{excl}"

    if cond.get("avg_abs_1d") is not None:
        return f"Earnings move averages ±{cond['avg_abs_1d']:.1f}% over {total} quarters"

    return None


def volatility_blurb(spread_pp: float | None, vol_regime: str | None, rv_rank: float | None) -> str | None:
    """Unusually-active card. The regime word is the chip's; the tier word is rv_rank_label's."""
    if rv_rank is None:
        return None
    tier = rv_rank_label(rv_rank)
    rank_part = f"RV rank {rv_rank:.0f}, {tier.label}" if tier else f"RV rank {rv_rank:.0f}"
    if spread_pp is None:
        return rank_part
    return f"{VOL_REGIME_WORDS.get(vol_regime, VOL_REGIME_WORDS[None])} at {spread_pp:+.0f}pp vs realized · {rank_part}"


def reaction_blurb(pct_1d: float | None, outcome: str, cond: dict | None) -> str | None:
    """Just-reported card: the realized 1-day move against this name's typical one."""
    if pct_1d is None or not cond or cond["total"] < MIN_QUARTERS or cond.get("avg_abs_1d") is None:
        return None
    typical = cond.get("avg_1d_on_beat" if outcome == "beat" else "avg_1d_on_miss") if outcome in ("beat", "miss") else None
    if typical is not None:
        return f"Moved {pct_1d:+.1f}% on the 1-day reaction; its typical {outcome} moves {typical:+.1f}%"
    return f"Moved {pct_1d:+.1f}% on the 1-day reaction; its typical earnings move is \u00b1{cond['avg_abs_1d']:.1f}%"
