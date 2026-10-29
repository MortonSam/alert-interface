"""A stuck earnings-reactions count raises a warning (Sam, 2026-10-29: the count sat at 10,000 while every report since Oct 21
waited, and nothing said so).

The nightly reaction step records the stored count of earnings reactions with a first-day move each night (record_count, under
COUNT_KEY). Validate's reaction_count_moving warns in the morning digest when that count is the same now as before the last
STUCK_SESSIONS trading sessions while at least STUCK_MIN_REPORTS S&P 500 companies reported in those sessions.
"""
from __future__ import annotations

import json
from datetime import date

from sqlalchemy import text

from app.services.dates import fmt_day

COUNT_KEY = "earnings_reaction_counts"
STUCK_SESSIONS = 3
STUCK_MIN_REPORTS = 5
KEEP_DAYS = 40

COUNT_SQL = "SELECT count(*) FROM historical_reactions WHERE event_type = 'earnings' AND pct_change_1d IS NOT NULL"


async def record_count(session, today: date) -> int:
    """Store tonight's count under today's date (the last KEEP_DAYS nights kept). Returns the count."""
    n = int((await session.execute(text(COUNT_SQL))).scalar() or 0)
    raw = (await session.execute(text("SELECT value FROM system_metadata WHERE key = :k"), {"k": COUNT_KEY})).scalar()
    counts = json.loads(raw) if raw else {}
    counts[today.isoformat()] = n
    counts = dict(sorted(counts.items())[-KEEP_DAYS:])
    await session.execute(text("""INSERT INTO system_metadata (key, value, updated_at) VALUES (:k, :v, now())
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"""), {"k": COUNT_KEY, "v": json.dumps(counts)})
    await session.commit()
    return n


def stuck_window(counts: dict[str, int], sessions: list[date]) -> tuple[date, date, int, int] | None:
    """Pure: (first session, last session, count before them, count now) over the last STUCK_SESSIONS sessions, or None when the
    history is too short. The count before is the latest one recorded on or before the first session's date (a nightly records the
    sessions before it); the count now is the latest recorded."""
    if len(sessions) < STUCK_SESSIONS or not counts:
        return None
    window = sorted(sessions)[-STUCK_SESSIONS:]
    days = sorted((date.fromisoformat(k), v) for k, v in counts.items())
    before = [v for d, v in days if d <= window[0]]
    if not before:
        return None
    return window[0], window[-1], before[-1], days[-1][1]


def verdict(window: tuple[date, date, int, int] | None, reports: int) -> tuple[bool, str]:
    """Pure: (stuck, detail)."""
    if window is None:
        return False, "not enough nightly counts recorded yet"
    first, last, before, now = window
    span = f"{fmt_day(first)} to {fmt_day(last)}"
    if before == now and reports >= STUCK_MIN_REPORTS:
        return True, (f"the earnings reactions count has stayed at {now:,} over the last {STUCK_SESSIONS} trading sessions "
                      f"({span}) while {reports} S&P 500 companies reported")
    return False, f"count {before:,} before {span}, {now:,} now; {reports} S&P 500 report(s) in those sessions"
