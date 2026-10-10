"""Auto-pick evaluates every candidate, then exits 1 if any raised, naming them."""
import sys
from datetime import date

import pytest

import app.scripts.auto_pick as ap

# writes today's alert_pick_evaluations rows (a real _run with a failing candidate), which the ledger reads compare
# (test_reviewer_key): the same group, so the two never run at once
pytestmark = pytest.mark.xdist_group(name="shared_rows")


@pytest.mark.asyncio
async def test_finish_exits_1_and_names_the_failed_symbols(capsys):
    failures = [
        {"symbol": "BAD", "error": "RuntimeError: boom", "traceback": "Traceback (most recent call last):\n  ...\nRuntimeError: boom"},
        {"symbol": "WORSE", "error": "KeyError: 'x'", "traceback": "Traceback (most recent call last):\n  ...\nKeyError: 'x'"},
    ]
    assert await ap.finish(failures, dry_run=True) == 1
    err = capsys.readouterr().err
    assert "2 candidate(s) raised: BAD, WORSE" in err
    assert "Traceback" in err
    assert err.rstrip().splitlines()[-1] == "KeyError: 'x' [WORSE]"   # the desk prints the last stderr line
    assert await ap.finish([], dry_run=True) == 0


@pytest.mark.asyncio
async def test_a_raising_candidate_does_not_stop_the_others(monkeypatch, capsys):
    seen: list[str] = []

    async def fake_fresh(session, sym):
        return True, date(2026, 9, 28)

    async def fake_pick(sym, session, source, dry_run):
        seen.append(sym)
        if sym == "BAD":
            raise RuntimeError("boom")
        return {"outcome": "vol_gate", "leans": [], "pick_id": None, "note": None}

    monkeypatch.setattr(ap, "_check_chain_freshness", fake_fresh)
    monkeypatch.setattr(ap, "compute_alert_pick", fake_pick)

    recorded: dict = {}

    async def fake_record(label, fields):
        recorded[label] = fields
    monkeypatch.setattr(ap, "record_step_fields", fake_record)

    # candidates come from the DB in _run; drive the loop body through a fake session-less run
    class Row:
        def __init__(self, s):
            self.symbol, self.next_earnings = s, date(2026, 10, 1)

    async def fake_candidates(*a, **k):
        return [Row("GOOD"), Row("BAD"), Row("ALSO_GOOD")]
    monkeypatch.setattr(ap, "_load_candidates", fake_candidates)
    monkeypatch.setattr(ap, "_open_count", (lambda *a, **k: _zero()))

    code = await ap._run(dry_run=False)
    assert seen == ["GOOD", "BAD", "ALSO_GOOD"], "the run finished the other candidates"
    assert code == 1
    assert recorded["Auto-pick"]["failed_symbols"] == ["BAD"]
    assert "RuntimeError: boom [BAD]" in capsys.readouterr().err


async def _zero():
    return 0
