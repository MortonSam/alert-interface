"""The nightly runs on a clock. A boot refresh never satisfies a slot; the desk reads the same clock."""
from datetime import datetime, timedelta, timezone

import app.services.nightly_clock as clock
import app.services.nightly_run as nightly_run
import app.startup as startup
from app.services.nightly_clock import latest_slot, nightly_due, slot_key
from app.services.nightly_run import expected_run_at


def T(d: int, h: int, m: int = 0) -> datetime:
    return datetime(2026, 9, d, h, m, tzinfo=timezone.utc)


def test_the_slot_is_the_latest_0600z():
    assert latest_slot(T(29, 6, 5)) == T(29, 6)
    assert latest_slot(T(29, 5, 55)) == T(28, 6)
    assert slot_key(T(29, 6)) == "2026-09-29"


def test_a_boot_refresh_at_1451z_does_not_suppress_that_nights_run():
    boot_refresh = "2026-09-28T14:51:29.830168+00:00"
    assert startup.nightly_refresh_due(T(29, 6, 5), last_slot_done="2026-09-28", last_refreshed_raw=boot_refresh)
    assert startup.nightly_refresh_due(T(29, 6, 5), last_slot_done=None, last_refreshed_raw=boot_refresh)
    # the slot the loop ran is done; nothing else counts
    assert not startup.nightly_refresh_due(T(29, 6, 5), last_slot_done="2026-09-29", last_refreshed_raw=None)
    assert not nightly_due(T(29, 5, 55), "2026-09-28")   # before the slot: yesterday's is the latest and it ran
    assert nightly_due(T(30, 6, 0), "2026-09-29")


def test_the_loop_and_the_desk_read_one_clock():
    assert startup.NIGHTLY_RUN_UTC_HOUR is clock.NIGHTLY_RUN_UTC_HOUR
    assert nightly_run.NIGHTLY_RUN_UTC_HOUR is clock.NIGHTLY_RUN_UTC_HOUR
    assert nightly_run.NIGHTLY_GRACE is clock.NIGHTLY_GRACE
    now = T(29, 9)
    assert expected_run_at(now) == latest_slot(now - clock.NIGHTLY_GRACE) == T(29, 6)
    # inside the grace the desk still expects yesterday's run, not today's unfinished one
    assert expected_run_at(T(29, 6) + clock.NIGHTLY_GRACE - timedelta(minutes=1)) == T(28, 6)


def test_a_boot_refresh_marks_no_slot():
    import inspect
    src = inspect.getsource(startup._background_refresh)
    assert "if nightly_slot:" in src and "LAST_NIGHTLY_SLOT_KEY" in src
    src_lifespan = inspect.getsource(startup.lifespan)
    assert "_background_refresh()" in src_lifespan   # the boot path passes no slot
