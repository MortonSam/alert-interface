"""What the options price against what the stock usually does, in one rule every page uses.

    compare_moves(implied_pct, typical_pct) -> "more than usual" | "less than usual" | "about its usual"
    report_verdict(report_pct, typical_pct, reports) -> the comparison of the report-only move (services/report_move), or None
    report_sentence(report_pct, typical_pct, comparison, chain_date) -> the one sentence both the ticker page and Discover show

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


# the report-only move (services/report_move): both surfaces say these words, the ticker page's verdict and Discover's line
COMPARISON_WORDS = {
    "more than usual": "more than",
    "less than usual": "less than",
    "about its usual": "about the same as",
}
REPORT_MOVE_ABSENT = {
    "no_pre_expiration": "The options don't separate a report move, because no expiration ends before the report.",
    "not_separated": "The options don't separate a report move, because the expiration after the report is priced no higher than the one before it.",
    "no_chain": "No options prices from the last session cover the report, so there is no report move.",
    "mixed_dates": "The two expirations around the report were priced on different days, so there is no report move.",
    "no_iv": "The options prices around the report could not be read as a volatility, so there is no report move.",
}


def report_verdict(report_pct: float | None, typical_pct: float | None, reports: int) -> str | None:
    """The comparison words for a report-only move against the typical first-day move, or None when either is missing or the
    typical move stands on fewer than MIN_REPORTS reports. Percent units in."""
    if report_pct is None or not typical_pct or typical_pct <= 0 or reports < MIN_REPORTS:
        return None
    return compare_moves(round(report_pct, 1), round(typical_pct, 1))


def report_sentence(report_pct: float, typical_pct: float | None, comparison: str | None, chain_date: date) -> str:
    """The sentence, e.g. "Options price a move of about 6.0% from the report itself, more than the 4.0% it has moved on a typical
    report (options from Oct 5, 2026)." With no comparison it states the report move alone."""
    day = chain_date.strftime('%b %-d, %Y')
    if comparison is None or typical_pct is None:
        return f"Options price a move of about {report_pct:.1f}% from the report itself (options from {day})."
    return (f"Options price a move of about {report_pct:.1f}% from the report itself, {COMPARISON_WORDS[comparison]} the "
            f"{typical_pct:.1f}% it has moved on a typical report (options from {day}).")
