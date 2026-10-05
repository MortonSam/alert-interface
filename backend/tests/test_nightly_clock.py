"""The nightly runs on the New York clock (02:30 America/New_York). A boot refresh never satisfies a slot; the desk reads the same clock."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import app.services.nightly_clock as clock
import app.services.nightly_run as nightly_run
import app.startup as startup
from app.services.nightly_clock import latest_slot, nightly_due, slot_key
from app.services.nightly_run import expected_run_at

NY = ZoneInfo("America/New_York")


def T(d: int, h: int, m: int = 0) -> datetime:
    return datetime(2026, 9, d, h, m, tzinfo=timezone.utc)


def NYT(d: int, h: int, m: int = 0) -> datetime:
    return datetime(2026, 9, d, h, m, tzinfo=NY)


def test_the_slot_is_the_latest_0230_new_york():
    assert latest_slot(T(29, 6, 35)) == NYT(29, 2, 30)           # 02:35 EDT
    assert latest_slot(T(29, 6, 25)) == NYT(28, 2, 30)           # 02:25 EDT: yesterday's slot
    assert slot_key(latest_slot(T(29, 6, 35))) == "2026-09-29"
    # the same local time in winter, a different UTC
    assert latest_slot(datetime(2026, 12, 10, 7, 35, tzinfo=timezone.utc)) == datetime(2026, 12, 10, 2, 30, tzinfo=NY)
    assert latest_slot(datetime(2026, 12, 10, 7, 25, tzinfo=timezone.utc)) == datetime(2026, 12, 9, 2, 30, tzinfo=NY)


def test_a_boot_refresh_at_1451z_does_not_suppress_that_nights_run():
    boot_refresh = "2026-09-28T14:51:29.830168+00:00"
    assert startup.nightly_refresh_due(T(29, 6, 35), last_slot_done="2026-09-28", last_refreshed_raw=boot_refresh)
    assert startup.nightly_refresh_due(T(29, 6, 35), last_slot_done=None, last_refreshed_raw=boot_refresh)
    # the slot the loop ran is done; nothing else counts
    assert not startup.nightly_refresh_due(T(29, 6, 35), last_slot_done="2026-09-29", last_refreshed_raw=None)
    assert not nightly_due(T(29, 6, 25), "2026-09-28")   # before the slot: yesterday's is the latest and it ran
    assert nightly_due(T(30, 6, 30), "2026-09-29")


def test_the_loop_and_the_desk_read_one_clock():
    assert startup.NIGHTLY_LOCAL_TIME is clock.NIGHTLY_LOCAL_TIME and startup.NIGHTLY_CLOCK is clock.NIGHTLY_CLOCK
    assert nightly_run.NIGHTLY_GRACE is clock.NIGHTLY_GRACE
    assert not hasattr(clock, "NIGHTLY_RUN_UTC_HOUR")
    now = T(29, 9)
    assert expected_run_at(now) == latest_slot(now - clock.NIGHTLY_GRACE) == NYT(29, 2, 30)
    # inside the grace the desk still expects yesterday's run, not today's unfinished one
    assert expected_run_at(NYT(29, 2, 30) + clock.NIGHTLY_GRACE - timedelta(minutes=1)) == NYT(28, 2, 30)


def test_a_boot_refresh_marks_no_slot_and_the_nightly_passes_its_slot_to_the_runner():
    import inspect
    src = inspect.getsource(startup._background_refresh)
    assert "if nightly_slot:" in src and "LAST_NIGHTLY_SLOT_KEY" in src
    assert "functools.partial(pipeline.main, slot=nightly_slot)" in src
    src_lifespan = inspect.getsource(startup.lifespan)
    assert "_background_refresh()" in src_lifespan   # the boot path passes no slot
