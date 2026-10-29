"""Which of a report's longer reaction windows are not yet available (Sam, 2026-10-29).

A report's first-day move is stored by the nightly after its first full session closes; its 3- and 5-day moves stay empty until
their sessions close and a later night fills them in on the same row (scripts/seed_historical_reactions). An empty longer window
on a report that recent is "not yet available": every reader shows it that way and none counts it as zero. After
WINDOW_FILL_DAYS an empty window is simply not on file (no bar for that session).
"""
from __future__ import annotations

from datetime import date

WINDOW_FILL_DAYS = 14          # calendar days: five sessions after a report, holidays included, always end inside this
NOT_YET = "not yet available"


def pending_windows(event_date: date | None, pct_1d, pct_3d, pct_5d, today: date) -> list[str]:
    """Pure: the windows ("3d", "5d") still to come for a report whose first-day move is stored."""
    if event_date is None or pct_1d is None or (today - event_date).days > WINDOW_FILL_DAYS:
        return []
    return [k for k, v in (("3d", pct_3d), ("5d", pct_5d)) if v is None]
