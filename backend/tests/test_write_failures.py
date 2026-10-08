"""A write that fails for any row fails the step and names the row; every loop-writing script with a per-row handler uses the helper."""
import pathlib

import pytest
import sqlalchemy.exc

from app.services.write_failures import WriteFailures, is_db_error

SCRIPTS = ["seed_release_eps", "check_release_eps", "compute_pe", "build_security_records", "scan_corporate_actions", "seed_dividends", "seed_splits",
           "refresh_profiles", "refresh_recommendations", "check_eps_basis"]


def test_database_errors_are_write_failures_and_fetch_errors_are_not():
    db = sqlalchemy.exc.DBAPIError("INSERT ...", {}, Exception("value too long for type character varying(40)"))
    assert is_db_error(db) and not is_db_error(ValueError("bad json")) and not is_db_error(TimeoutError())
    w = WriteFailures("Release EPS (8-K exhibits)")
    assert w.note("COST 2026-09-24", db) is True and w.note("MU", ValueError("x")) is False
    w.add("CSCO 2026-08-12", RuntimeError("commit refused"))
    assert w.rows[0].startswith("COST 2026-09-24: ") and len(w.rows) == 2
    assert w.exit_code(0) == 1 and WriteFailures("x").exit_code(0) == 0 and WriteFailures("x").exit_code(1) == 1


@pytest.mark.asyncio
async def test_finish_records_the_rows_and_returns_one(monkeypatch):
    recorded = {}
    import app.services.step_outcomes as SO
    async def fake(label, fields): recorded[label] = fields
    monkeypatch.setattr(SO, "record_step_fields", fake)
    w = WriteFailures("Trailing P/E")
    assert await w.finish(0) == 0 and recorded == {}
    w.add("BKNG", RuntimeError("x"))
    assert await w.finish(0) == 1 and recorded["Trailing P/E"]["write_failures"] == ["BKNG: x"]


def test_every_loop_writing_script_with_a_row_handler_uses_the_helper():
    root = pathlib.Path(__file__).resolve().parents[1] / "app" / "scripts"
    for name in SCRIPTS:
        src = (root / f"{name}.py").read_text()
        assert "WriteFailures(" in src and "WRITES.finish(" in src and ("WRITES.note(" in src or "WRITES.add(" in src), name

# shares the step_outcomes metadata key with the other files of this group: one xdist worker runs them (scripts/push_window.py runs pytest -n auto --dist loadgroup)
pytestmark = pytest.mark.xdist_group(name="step_outcomes")
