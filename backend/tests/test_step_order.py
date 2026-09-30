"""The nightly's order where a step judges another's work."""
from app.scripts.refresh import STEPS


def test_validate_runs_after_the_warm_and_last():
    """validate's options_read_coverage counts tonight's options reads; the warm writes them. Before, on every
    chain-roll day validate reported 0/512 and errored, then the warm filled the cache."""
    labels = [label for label, _ in STEPS]
    assert labels.index("Warm options reads") < labels.index("Validate data")
    assert labels[-2:] == ["Warm options reads", "Validate data"]
    assert labels.index("Close expired alert picks") < labels.index("Validate data")   # pick_lifecycle judges the closer
