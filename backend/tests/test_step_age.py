"""Validate flags a nightly step that stopped succeeding."""
import pytest

from datetime import datetime, timedelta, timezone

from app.scripts.validate_data import ERROR, PASS, WARN, step_age_result

NOW = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).isoformat()


def test_step_age_levels():
    assert step_age_result({"A": _iso(0.5), "B": _iso(1.9)}, NOW).level == PASS
    warn = step_age_result({"A": _iso(0.5), "Analyst actions": _iso(2.5)}, NOW)
    assert warn.level == WARN and "Analyst actions" in warn.rows[0] and "2.5 days ago" in warn.rows[0]
    err = step_age_result({"A": _iso(0.5), "Analyst actions": _iso(4.2)}, NOW)
    assert err.level == ERROR and "4.2 days ago" in err.rows[0]


def test_step_that_never_succeeded_is_reported():
    out = step_age_result({"A": _iso(1), "New step": None}, NOW)
    assert out.level == WARN and any("never succeeded: New step" in r for r in out.rows)


def test_step_age_reads_every_nightly_step_but_itself():
    from app.scripts.refresh import STEPS
    labels = [label for label, _ in STEPS]
    assert "Analyst actions" in labels and "IV + RV snapshot (snapshot_iv)" in labels
    # check_step_age builds its dict from STEPS minus "Validate data" (asserting on the source keeps this honest)
    from pathlib import Path
    src = Path(__file__).resolve().parents[1].joinpath("app/scripts/validate_data.py").read_text()
    assert 'for label, _ in STEPS if label != "Validate data"' in src
    assert r"step:%\:last_success" in src


@pytest.mark.asyncio
async def test_check_step_age_runs_its_query_against_the_database():
    """The LIKE pattern contains ':last_success'; text() must not read that as a bind parameter."""
    from app.database import ScriptSessionLocal
    from app.scripts.validate_data import check_step_age

    async with ScriptSessionLocal() as session:
        out = await check_step_age(session)
    assert out.level in (PASS, WARN, ERROR)
