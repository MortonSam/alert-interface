"""The nightly runs on a clock, and every reader of "did the nightly run" reads this clock.

The refresh loop starts the nightly at NIGHTLY_RUN_UTC_HOUR every day. A boot
refresh (startup.py, after a deploy) refreshes the data but never satisfies a
nightly slot: the slot is marked done only by a run the loop started for it.
The Ivy desk's "did last night's run happen" check reads the same hour and the
same grace, so the page and the scheduler cannot disagree.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

NIGHTLY_RUN_UTC_HOUR = 6                 # 06:00Z, 02:00 ET in summer, 01:00 ET in winter
NIGHTLY_GRACE = timedelta(hours=2)       # Auto-pick sits ~45 min into the run; allow a slow night
LAST_NIGHTLY_SLOT_KEY = "last_nightly_slot"   # system_metadata: the slot date the loop last completed


def latest_slot(now: datetime) -> datetime:
    """The most recent NIGHTLY_RUN_UTC_HOUR at or before `now` (UTC)."""
    now = now.astimezone(timezone.utc)
    today_slot = now.replace(hour=NIGHTLY_RUN_UTC_HOUR, minute=0, second=0, microsecond=0)
    return today_slot if now >= today_slot else today_slot - timedelta(days=1)


def slot_key(slot: datetime) -> str:
    return slot.astimezone(timezone.utc).date().isoformat()


def nightly_due(now: datetime, last_slot_done: str | None) -> bool:
    """True when the latest slot has not been run by the loop. Independent of any other refresh."""
    return slot_key(latest_slot(now)) != last_slot_done
