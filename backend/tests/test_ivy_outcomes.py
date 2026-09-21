"""Every outcome the nightly evaluation writes has a category and a label."""
import re
from pathlib import Path

from app.services.ivy_outcomes import ERROR, IVY_OUTCOMES, PASSED, PICKED, REFUSED, count_by_category, outcome_category

APP = Path(__file__).resolve().parents[1] / "app"


def test_every_outcome_written_by_the_code_is_in_the_map():
    written = set()
    for rel in ("scripts/auto_pick.py", "routers/thesis.py"):
        written |= set(re.findall(r'outcome\s*==?\s*"([a-z_]+)"', (APP / rel).read_text()))
    assert written, "found no outcome strings; the scan is broken"
    assert written <= set(IVY_OUTCOMES), written - set(IVY_OUTCOMES)


def test_categories_split_a_night_four_ways():
    counts = count_by_category(["picked", "vol_gate", "no_fresh_chain", "momentum_gate", "momentum_gate",
                                "cap_reached", "error", "something_unknown"])
    assert counts == {PICKED: 1, REFUSED: 2, PASSED: 3, ERROR: 2}     # unknown outcomes count as errors, not as passes
    assert sum(counts.values()) == 8


def test_refused_means_the_setup_was_there():
    assert outcome_category("vol_gate") == REFUSED
    assert outcome_category("momentum_gate") == PASSED
    assert outcome_category("insufficient_history") == PASSED
    assert outcome_category(None) == ERROR


def test_verdict_text_uses_the_rule_constants():
    src = (APP / "scripts" / "auto_pick.py").read_text()
    assert "(needs {MIN_PRIOR_N})" in src and "needs 8" not in src
    assert "needs <= -10%" not in src
