"""Beat and miss counts that state their coverage, and an outcome that needs a reported figure.

Two rules (2026-10-12):
  1. No earnings event carries a beat or miss label without a stored EPS actual: served_outcome() turns such a row's label into
     NO_REPORTED_FIGURE ("no reported figure"), whatever the stored outcome says.
  2. Every "X of N" beat count travels with how many of the N quarters had both an estimate and an actual (quarters_with_data) and
     how many did not (quarters_without_data), so the page can read "beat 0 of 1 with data; 19 quarters have no estimate data" instead
     of "0 of 20". coverage() is the one place that counts.
"""
from __future__ import annotations

from app.models.enums import EarningsOutcome

NO_REPORTED_FIGURE = "no_reported_figure"      # the served outcome of a row without an EPS actual


def served_outcome(outcome, eps_actual) -> str:
    """Pure: the outcome a visitor may see for a reaction row: beat, miss or meet only with a stored actual; otherwise the
    stored value when it is unknown, else NO_REPORTED_FIGURE."""
    value = outcome.value if isinstance(outcome, EarningsOutcome) else (outcome or EarningsOutcome.UNKNOWN.value)
    if value in (EarningsOutcome.BEAT.value, EarningsOutcome.MISS.value, EarningsOutcome.MEET.value) and eps_actual is None:
        return NO_REPORTED_FIGURE
    return value


def has_data(row) -> bool:
    """Pure: the quarter has both an estimate and an actual stored."""
    return getattr(row, "eps_actual", None) is not None and getattr(row, "eps_estimate", None) is not None


def coverage(rows) -> dict:
    """Pure: {total, with_data, without_data, beats, misses, meets} over reaction rows, counting a beat or miss only where the quarter
    has both figures."""
    total = len(rows)
    with_data = [r for r in rows if has_data(r)]
    beats = sum(1 for r in with_data if (r.outcome.value if isinstance(r.outcome, EarningsOutcome) else r.outcome) == "beat")
    misses = sum(1 for r in with_data if (r.outcome.value if isinstance(r.outcome, EarningsOutcome) else r.outcome) == "miss")
    meets = sum(1 for r in with_data if (r.outcome.value if isinstance(r.outcome, EarningsOutcome) else r.outcome) == "meet")
    return {"total": total, "with_data": len(with_data), "without_data": total - len(with_data), "beats": beats, "misses": misses, "meets": meets}
