"""Every outcome the nightly evaluation can record, and what kind of outcome it is.

One map, used by the verdict text, the activity endpoint's counts and (through
a test) the frontend's label map. "Passed" means the setup was not there;
"refused" means the setup was there and Ivy declined it; "holding" means she
already has an open pick on the name and does not double up (the name is
still fully evaluated).
"""
from __future__ import annotations

PICKED, REFUSED, PASSED, HOLDING, ERROR = "picked", "refused", "passed", "holding", "error"

IVY_OUTCOMES: dict[str, dict[str, str]] = {
    "picked":               {"category": PICKED,  "label": "Picked"},
    "vol_gate":             {"category": REFUSED, "label": "Refused: options too expensive for the edge"},
    "no_fresh_chain":       {"category": REFUSED, "label": "Refused: no current options data"},
    "structure_failed":     {"category": REFUSED, "label": "Refused: could not build the spread from the available strikes"},
    "momentum_gate":        {"category": PASSED,  "label": "Passed: no momentum setup"},
    "insufficient_history": {"category": PASSED,  "label": "Passed: not enough earnings history"},
    "no_features":          {"category": PASSED,  "label": "Passed: no data for this name"},
    "open_pick_exists":     {"category": HOLDING, "label": "Holding: already has an open pick in this name"},
    "cap_reached":          {"category": PASSED,  "label": "Passed: pick limit reached"},
    "mixed_evidence":       {"category": PASSED,  "label": "Passed: signals disagreed (earlier engine)"},
    "error":                {"category": ERROR,   "label": "Error during evaluation"},
}


def outcome_category(outcome: str | None) -> str:
    return IVY_OUTCOMES.get(outcome or "", {}).get("category", ERROR)


def count_by_category(outcomes: list[str | None]) -> dict[str, int]:
    counts = {PICKED: 0, REFUSED: 0, PASSED: 0, HOLDING: 0, ERROR: 0}
    for o in outcomes:
        counts[outcome_category(o)] += 1
    return counts


# ── Worksheet rows, old and new, rendered by one rule ────────────────────────
# Rows written before the holding verdict and implied_reason existed carry
# their old text ("Passed, open pick exists", no reason). The desk classifies
# every stored row by these functions, so the rule is the same on every night.

NOT_PRICED_UNRECORDED = "not priced: reason not recorded"


def worksheet_verdict(outcome: str | None, stored_verdict: str | None, pick_since: str | None) -> str | None:
    """The verdict to show. An open-pick row is always "Holding, open pick[ since <date>]"."""
    if outcome == "open_pick_exists":
        return f"Holding, open pick since {pick_since}" if pick_since else "Holding, open pick"
    return stored_verdict


def implied_reason_for_display(implied_move_pct: float | None, stored_reason: str | None) -> str | None:
    """The reason beside a null implied move; never a failure the evaluation did not record."""
    if implied_move_pct is not None:
        return None
    return stored_reason or NOT_PRICED_UNRECORDED
