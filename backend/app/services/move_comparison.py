"""What the options price against what the stock usually does, in one rule every page uses.

    compare_moves(implied_pct, typical_pct) -> "more than usual" | "less than usual" | "about its usual"
    comparison_sentence(implied_pct, typical_pct, chain_date) -> the Discover line, chain date as the receipt

implied_pct and typical_pct are percent units (6.0 means 6.0%). MORE_RATIO and LESS_RATIO are the only thresholds.
"""
from __future__ import annotations

from datetime import date

MORE_RATIO = 1.2       # implied over typical above this reads "more than usual"
LESS_RATIO = 0.8       # below this, "less than usual"
MIN_REPORTS = 8        # fewest stored reports behind a typical move


def compare_moves(implied_pct: float, typical_pct: float) -> str:
    if typical_pct <= 0:
        return "about its usual"
    ratio = round(implied_pct / typical_pct, 4)       # 4.8 over 4.0 is 1.2 exactly, not a hair above it
    if ratio > MORE_RATIO:
        return "more than usual"
    if ratio < LESS_RATIO:
        return "less than usual"
    return "about its usual"


def comparison_sentence(implied_pct: float, typical_pct: float, chain_date: date) -> str:
    """"Options price a ±6.0% move; it has moved ±4.0% on a typical report, more than usual (chain Oct 5, 2026).\""""
    return (f"Options price a ±{implied_pct:.1f}% move; it has moved ±{typical_pct:.1f}% on a typical report, "
            f"{compare_moves(implied_pct, typical_pct)} (chain {chain_date.strftime('%b %-d, %Y')}).")
