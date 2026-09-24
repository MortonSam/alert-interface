"""Every outcome the nightly evaluation writes has a category and a label."""
import re
from pathlib import Path

from app.services.ivy_outcomes import ERROR, HOLDING, IVY_OUTCOMES, PASSED, PICKED, REFUSED, count_by_category, outcome_category

APP = Path(__file__).resolve().parents[1] / "app"


def test_every_outcome_written_by_the_code_is_in_the_map():
    written = set()
    for rel in ("scripts/auto_pick.py", "routers/thesis.py"):
        written |= set(re.findall(r'outcome\s*==?\s*"([a-z_]+)"', (APP / rel).read_text()))
    assert written, "found no outcome strings; the scan is broken"
    assert written <= set(IVY_OUTCOMES), written - set(IVY_OUTCOMES)


def test_categories_split_a_night_five_ways():
    counts = count_by_category(["picked", "vol_gate", "no_fresh_chain", "momentum_gate", "momentum_gate",
                                "cap_reached", "open_pick_exists", "error", "something_unknown"])
    assert counts == {PICKED: 1, REFUSED: 2, PASSED: 3, HOLDING: 1, ERROR: 2}   # unknown outcomes count as errors, not as passes
    assert sum(counts.values()) == 9
    assert outcome_category("open_pick_exists") == HOLDING              # evaluated, not doubled up: neither refused nor passed


def test_refused_means_the_setup_was_there():
    assert outcome_category("vol_gate") == REFUSED
    assert outcome_category("momentum_gate") == PASSED
    assert outcome_category("insufficient_history") == PASSED
    assert outcome_category(None) == ERROR


def test_verdict_text_uses_the_rule_constants():
    src = (APP / "scripts" / "auto_pick.py").read_text()
    assert "(needs {MIN_PRIOR_N})" in src and "needs 8" not in src
    assert "needs <= -10%" not in src


def test_holding_verdict_names_the_open_pick_date_and_implied_reason_never_claims_a_failure_that_did_not_happen():
    from app.scripts.auto_pick import NOT_PRICED_NO_CHAIN, _build_verdict, implied_reason
    assert _build_verdict({"outcome": "open_pick_exists", "existing_since": "2026-09-18"}, {"implied_pct": 4.1}) == "Holding, open pick since 2026-09-18"
    # not priced: the evaluation never reached pricing
    assert implied_reason("no_fresh_chain", None) == NOT_PRICED_NO_CHAIN
    assert implied_reason("open_pick_exists", {"gate_reason": "no fresh options chain for X", "implied_pct": None}) == NOT_PRICED_NO_CHAIN
    assert implied_reason("no_features", None) == "not priced: no data for this name"
    assert implied_reason("error", None) == "not priced: evaluation stopped before pricing"
    # priced and failed: the only case that may say so
    assert implied_reason("vol_gate", {"gate_reason": "options pricing 6.1%, history says 3.2%", "implied_pct": None}).startswith("options could not be priced")
    src = (APP / "scripts" / "auto_pick.py").read_text()
    assert 'fields["implied_reason"] = implied_reason(' in src


def test_legacy_rows_are_classified_by_the_same_rule_as_new_rows():
    from app.services.ivy_outcomes import NOT_PRICED_UNRECORDED, implied_reason_for_display, worksheet_verdict
    # a row stored before the holding verdict and implied_reason existed
    assert worksheet_verdict("open_pick_exists", "Passed, open pick exists", "2026-09-18") == "Holding, open pick since 2026-09-18"
    assert worksheet_verdict("open_pick_exists", "Passed, open pick exists", None) == "Holding, open pick"
    assert worksheet_verdict("vol_gate", "Refused, options pricing 6.1%, history says 3.2%", None) == "Refused, options pricing 6.1%, history says 3.2%"
    assert implied_reason_for_display(None, None) == NOT_PRICED_UNRECORDED          # never "options could not be priced"
    assert implied_reason_for_display(None, "not priced: no current options data") == "not priced: no current options data"
    assert implied_reason_for_display(4.1, None) is None
    src = (APP / "routers" / "thesis.py").read_text()
    assert "verdict=worksheet_verdict(r.outcome, r.verdict, pick_since)" in src
    assert "implied_reason=implied_reason_for_display(implied, r.implied_reason)" in src


def test_categories_partition_any_row_set():
    import random
    codes = list(IVY_OUTCOMES) + ["unknown_code", None]
    rng = random.Random(7)
    for n in (0, 1, 6, 41):
        outcomes = [rng.choice(codes) for _ in range(n)]
        counts = count_by_category(outcomes)
        assert sum(counts.values()) == n                       # picked + refused + passed + holding + error == evaluated
