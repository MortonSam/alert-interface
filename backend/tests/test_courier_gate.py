"""The courier starts at 16:05 New York whatever the Mac's zone: launchd fires every 5 minutes, 13:00-18:55 local on weekdays, and
courier_gate starts the run only on a New York trading day between 16:05 and 16:45 New York, once per New York day."""
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.scripts.courier_gate import LAST_START, START, decide

NY = ZoneInfo("America/New_York")
PLIST = Path(__file__).resolve().parents[1] / "ops" / "courier" / "com.alertinterface.chaincourier.plist"


def launchd_fires(day: date, zone: str) -> list[datetime]:
    """Every fire the plist schedules on `day` in the Mac's zone `zone` (launchd reads Hour and Minute as local time)."""
    text = PLIST.read_text()
    out = []
    wd = day.isoweekday()
    for w, h, m in re.findall(r"<key>Weekday</key><integer>(\d)</integer><key>Hour</key><integer>(\d+)</integer><key>Minute</key><integer>(\d+)</integer>", text):
        if int(w) == wd % 7 or (wd == 7 and int(w) == 0):
            out.append(datetime(day.year, day.month, day.day, int(h), int(m), tzinfo=ZoneInfo(zone)))
    return sorted(out)


def replay(day: date, zone: str, fail_first: int = 0) -> list[datetime]:
    """The New York times the courier would start, firing every scheduled time in order with the gate's state carried along; the
    first `fail_first` runs push nothing (production unreachable), which clears the day."""
    last, starts, fails = None, [], fail_first
    for fire in launchd_fires(day, zone):
        start, _ = decide(fire, last, trading_day=lambda d: d.weekday() < 5)
        if start:
            starts.append(fire.astimezone(NY))
            last = fire.astimezone(NY).date().isoformat()
            if fails:
                fails -= 1
                last = None
    return starts


def test_mountain_central_eastern_and_pacific_clocks_all_start_at_16_05_new_york_once():
    friday = date(2026, 10, 9)
    for zone in ("America/Denver", "America/Chicago", "America/New_York", "America/Los_Angeles"):
        starts = replay(friday, zone)
        assert [s.strftime("%H:%M") for s in starts] == ["16:05"], (zone, starts)
    assert replay(date(2026, 10, 10), "America/Denver") == []                     # Saturday: launchd does not fire
    assert len(PLIST.read_text().split("<key>Weekday</key>")) - 1 == 5 * 6 * 12


def test_a_run_that_could_not_reach_production_retries_until_16_45_and_never_later():
    starts = replay(date(2026, 10, 9), "America/Denver", fail_first=2)
    assert [s.strftime("%H:%M") for s in starts] == ["16:05", "16:10", "16:15"]
    starts = replay(date(2026, 10, 9), "America/Denver", fail_first=99)
    assert starts[-1].strftime("%H:%M") == "16:45" and len(starts) == 9


def test_the_window_and_the_trading_calendar():
    t = lambda h, m, d=9: datetime(2026, 10, d, h, m, tzinfo=NY)
    assert decide(t(16, 4), None)[0] is False and decide(t(16, 5), None)[0] is True and decide(t(16, 45), None)[0] is True
    assert decide(t(16, 46), None) == (False, "16:46 New York is after 16:45: no start this late")
    assert decide(t(16, 10), "2026-10-09") == (False, "the 2026-10-09 run has already started")
    assert decide(datetime(2026, 11, 26, 16, 5, tzinfo=NY), None)[0] is False      # Thanksgiving: not a trading day
    assert (START.hour, START.minute, LAST_START.hour, LAST_START.minute) == (16, 5, 16, 45)
