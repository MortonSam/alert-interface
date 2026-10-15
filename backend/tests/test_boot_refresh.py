"""The boot refresh rule (startup.boot_refresh_decision) and the mark it reads (refresh.should_record_refresh). Pure, no database."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

import app.startup as startup
from app.scripts import refresh

Z = timezone.utc


def _steps(failed: tuple[str, ...] = ()) -> dict:
    return {label: {"ok": label not in failed, "seconds": 1.0} for label, _ in refresh.STEPS}


def test_the_key_check_does_not_hold_back_the_mark():
    # 2026-10-15: the nightly's only data-side failure was the key check at the usage limit; the mark stayed at Oct 14
    assert "AI key check" in [label for label, _ in refresh.STEPS]
    assert refresh.should_record_refresh([("AI key check", False), ("Ticker data (seed_sp500)", True), ("Validate data", False)])
    assert not refresh.should_record_refresh([("AI key check", True), ("Warm options reads", False)])


def test_last_successful_nightly_reads_slot_runs_whose_data_steps_passed():
    history = [
        {"slot": "2026-10-14", "finished_at": "2026-10-14T08:13:49+00:00", "steps": _steps(("Validate data",))},
        {"slot": "2026-10-15", "finished_at": "2026-10-15T07:56:42+00:00", "steps": _steps(("ATM IV (solver)",))},   # a data step failed
        {"slot": None, "finished_at": "2026-10-15T19:49:34+00:00", "steps": _steps()},                               # a boot run is not a nightly
        {"slot": "2026-10-16", "finished_at": "2026-10-16T08:00:00+00:00", "interrupted": True, "steps": _steps()},
    ]
    assert refresh.last_successful_nightly(json.dumps(history)) == datetime(2026, 10, 14, 8, 13, 49, tzinfo=Z)
    # the key check alone failing still counts as a successful nightly
    history.append({"slot": "2026-10-17", "finished_at": "2026-10-17T08:00:00+00:00", "steps": _steps(("AI key check", "Validate data"))})
    assert refresh.last_successful_nightly(json.dumps(history)) == datetime(2026, 10, 17, 8, 0, tzinfo=Z)
    assert refresh.last_successful_nightly(None) is None
    assert refresh.last_successful_nightly("not json") is None


def test_boot_runs_keep_their_own_history_entries():
    a = refresh.timings_history(None, {"slot": None, "started_at": "2026-10-15T14:07:00+00:00"})
    b = refresh.timings_history(json.dumps(a), {"slot": None, "started_at": "2026-10-15T18:20:28+00:00"})
    assert [r["started_at"] for r in b] == ["2026-10-15T14:07:00+00:00", "2026-10-15T18:20:28+00:00"]


def test_no_boot_refresh_within_30_hours_of_a_successful_nightly():
    now = datetime(2026, 10, 15, 18, 19, tzinfo=Z)
    stale = "2026-10-13T08:00:00+00:00"                     # the mark alone would start a run
    nightly = now - timedelta(hours=startup.SKIP_AFTER_SUCCESSFUL_NIGHTLY_HOURS) + timedelta(minutes=1)
    go, why = startup.boot_refresh_decision(now, stale, nightly, None)
    assert not go and "successful nightly" in why
    go, _ = startup.boot_refresh_decision(now, stale, nightly - timedelta(minutes=2), None)
    assert go


def test_no_boot_refresh_within_24_hours_of_any_run():
    # 2026-10-15: the 02:31 nightly failed a step; the 10:07 and 14:20 deploys each started a full run (Reads twice, ~$5)
    now = datetime(2026, 10, 15, 14, 7, tzinfo=Z)
    go, why = startup.boot_refresh_decision(now, "2026-10-14T08:13:49+00:00", None, datetime(2026, 10, 15, 6, 31, 47, tzinfo=Z))
    assert not go and "started" in why
    go, _ = startup.boot_refresh_decision(now, "2026-10-14T08:13:49+00:00", None, now - timedelta(hours=startup.SKIP_AFTER_ANY_RUN_HOURS, minutes=1))
    assert go


def test_the_mark_decides_when_no_recent_run():
    now = datetime(2026, 10, 15, 12, 0, tzinfo=Z)
    assert startup.boot_refresh_decision(now, None, None, None)[0]
    assert startup.boot_refresh_decision(now, "garbage", None, None)[0]
    assert startup.boot_refresh_decision(now, (now - timedelta(hours=25)).isoformat(), None, None)[0]
    assert not startup.boot_refresh_decision(now, (now - timedelta(hours=23)).isoformat(), None, None)[0]


def test_the_lifespan_uses_the_decision():
    import inspect
    src = inspect.getsource(startup.lifespan)
    assert "boot_refresh_decision(" in src and "_read_run_history()" in src
    assert "REFRESH_IF_OLDER_THAN_HOURS:" not in src            # the old inline age check is gone


def test_catch_up_refuses_while_running_and_within_24_hours_unless_forced():
    now = datetime(2026, 10, 15, 21, 0, tzinfo=Z)
    recent = now - timedelta(hours=3)
    assert startup.catch_up_decision(now, True, None, None, force=True) == (False, "a refresh is running in this process")
    ok, why = startup.catch_up_decision(now, False, (now - timedelta(hours=2)).isoformat(), None, force=True)
    assert not ok and "running since" in why                         # force never runs two pipelines at once
    ok, why = startup.catch_up_decision(now, False, "done", recent, force=False)
    assert not ok and "force=true" in why
    ok, why = startup.catch_up_decision(now, False, "done", recent, force=True)
    assert ok and "force=true" in why
    assert startup.catch_up_decision(now, False, (now - timedelta(hours=7)).isoformat(), now - timedelta(hours=25), force=False)[0]   # a dead marker


@pytest.mark.asyncio
async def test_the_catch_up_endpoint_needs_the_admin_token_and_starts_a_boot_style_run(monkeypatch):
    from httpx import ASGITransport, AsyncClient
    import app.auth as auth
    from app.main import app

    monkeypatch.setattr(auth.settings, "admin_token", "t")
    started, writes = [], []

    async def history():
        return None, datetime.now(Z) - timedelta(hours=2)

    async def sentinel():
        return None, "done"

    async def write(v):
        writes.append(v)

    async def fake_run(nightly_slot=None):
        started.append(nightly_slot)

    monkeypatch.setattr(startup, "_read_run_history", history)
    monkeypatch.setattr(startup, "_read_sentinel", sentinel)
    monkeypatch.setattr(startup, "_write_sentinel", write)
    monkeypatch.setattr(startup, "_background_refresh", fake_run)
    monkeypatch.setattr(startup, "_refresh_in_progress", False)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        assert (await c.post("/api/v1/admin/catch-up-refresh")).status_code == 401
        r = await c.post("/api/v1/admin/catch-up-refresh", headers={"X-Admin-Token": "t"})
        assert r.status_code == 409 and "force=true" in r.json()["detail"] and started == []
        r = await c.post("/api/v1/admin/catch-up-refresh?force=true", headers={"X-Admin-Token": "t"})
        assert r.status_code == 202 and r.json()["started"] is True
        await asyncio.sleep(0)
        assert started == [None] and len(writes) == 1          # no slot: recorded in nightly_timings like a boot run
        r = await c.post("/api/v1/admin/catch-up-refresh?force=true", headers={"X-Admin-Token": "t"})
        assert r.status_code == 409                            # this process now holds a run
