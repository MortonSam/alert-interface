"""The desk knows when the latest Auto-pick run failed or never happened."""
import json
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.nightly_run import auto_pick_status, expected_run_at

T = lambda h, m=0: datetime(2026, 9, 23, h, m, tzinfo=timezone.utc)  # noqa: E731


def test_expected_run_is_this_morning_after_the_grace_else_yesterday():
    assert expected_run_at(T(7, 30)) == T(6)
    assert expected_run_at(T(6, 20)) == datetime(2026, 9, 22, 6, tzinfo=timezone.utc)   # still inside the grace
    assert expected_run_at(T(2)) == datetime(2026, 9, 22, 6, tzinfo=timezone.utc)


def test_status_from_step_outcomes():
    failed = {"Auto-pick": {"exit": 1, "seconds": 12.3, "at": "2026-09-23T06:16:18+00:00",
                            "stderr_head": "Traceback (most recent call last):", "stderr_tail": "X: invalid input syntax for type json"}}
    s = auto_pick_status(failed, now=T(15))
    assert s.failed and not s.stale and s.exit == 1 and s.error == "X: invalid input syntax for type json"
    # the exception line is the LAST line of the tail, not the whole tail
    multi = {"Auto-pick": {"exit": 1, "at": "2026-09-23T06:16:18+00:00",
                           "stderr_tail": "  File x, line 1\n    self._handle_exception(error)\nsqlalchemy.exc.DBAPIError: boom"}}
    assert auto_pick_status(multi, now=T(15)).error == "sqlalchemy.exc.DBAPIError: boom"
    ok = {"Auto-pick": {"exit": 0, "seconds": 40.0, "at": "2026-09-23T06:16:18+00:00"}}
    s = auto_pick_status(ok, now=T(15))
    assert s.ok and s.error is None and not s.stale
    # a clean run from the night before is stale once this morning's run should have finished
    s = auto_pick_status(ok, now=datetime(2026, 9, 24, 9, tzinfo=timezone.utc))
    assert s.stale and s.failed and s.exit == 0
    # head is used when no tail was recorded; never recorded counts as failed and stale
    only_head = {"Auto-pick": {"exit": -1, "at": "2026-09-23T06:16:18+00:00", "stderr_head": "Traceback"}}
    assert auto_pick_status(only_head, now=T(15)).error == "traceback recorded, exception line not kept"   # never the head
    assert auto_pick_status({"Auto-pick": {"exit": 1, "at": "2026-09-23T06:16:18+00:00"}}, now=T(15)).error is None
    s = auto_pick_status({}, now=T(15))
    assert s.failed and s.stale and s.at is None and s.exit is None


@pytest.mark.asyncio
async def test_activity_read_carries_the_run_status(monkeypatch):
    import app.routers.thesis as thesis_module
    outcomes = {"Auto-pick": {"exit": 1, "seconds": 12.3, "at": "2026-09-23T06:16:18+00:00",
                              "stderr_head": "Traceback (most recent call last):",
                              "stderr_tail": "    raise translated_error from error\nX: invalid input syntax for type json"}}

    async def fake_get_value(session, key):
        return json.dumps(outcomes) if key == "step_outcomes" else None
    monkeypatch.setattr("app.services.system_metadata_service.get_value", fake_get_value)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/api/v1/theses/ivy-activity")).json()
    assert body["last_run_exit"] == 1 and body["last_run_failed"] is True
    assert body["last_run_error"] == "X: invalid input syntax for type json"
    assert body["last_run_at"] == "2026-09-23T06:16:18+00:00"
