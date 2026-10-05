"""The nightly runs on the New York clock, and every reader of "did the nightly run" reads this clock.

The refresh loop starts the nightly at NIGHTLY_LOCAL_TIME on NIGHTLY_CLOCK every day (02:30 New York, so the Options
chains step's own 03:05 wait is short). A boot refresh (startup.py, after a deploy) refreshes the data but never
satisfies a nightly slot: the slot is marked done only by a run the loop started for it, and a run the loop resumes
after a restart continues the same slot (refresh.py keeps per-step completion for it). The Ivy desk's "did last
night's run happen" check reads the same time and the same grace, so the page and the scheduler cannot disagree.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

NIGHTLY_CLOCK = "America/New_York"
NIGHTLY_LOCAL_TIME = time(2, 30)          # never a UTC time: the market's day ends on the New York clock
NIGHTLY_GRACE = timedelta(hours=2)        # Auto-pick sits ~45 min into the run; allow a slow night
LAST_NIGHTLY_SLOT_KEY = "last_nightly_slot"   # system_metadata: the slot date the loop last completed


def latest_slot(now: datetime) -> datetime:
    """The most recent NIGHTLY_LOCAL_TIME on the New York clock at or before `now`, as an aware datetime."""
    local = now.astimezone(ZoneInfo(NIGHTLY_CLOCK))
    today_slot = local.replace(hour=NIGHTLY_LOCAL_TIME.hour, minute=NIGHTLY_LOCAL_TIME.minute, second=0, microsecond=0)
    return today_slot if local >= today_slot else today_slot - timedelta(days=1)


def slot_key(slot: datetime) -> str:
    """The slot's New York date."""
    return slot.astimezone(ZoneInfo(NIGHTLY_CLOCK)).date().isoformat()


def nightly_due(now: datetime, last_slot_done: str | None) -> bool:
    """True when the latest slot has not been run by the loop. Independent of any other refresh."""
    return slot_key(latest_slot(now)) != last_slot_done


def slot_local_label() -> str:
    return NIGHTLY_LOCAL_TIME.strftime("%H:%M")


def slot_utc_today(now: datetime | None = None) -> str:
    """Today's slot expressed in UTC, for logs that compare with UTC stamps ("06:30Z" in summer, "07:30Z" in winter)."""
    slot = latest_slot(now or datetime.now(timezone.utc))
    return slot.astimezone(timezone.utc).strftime("%H:%MZ")
