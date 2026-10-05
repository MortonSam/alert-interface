"""Reported EPS on the earnings event, the night of the report.

Pure rules for scripts/seed_eps_actuals and the briefing: which events are due, how a vendor row matches an event,
what may be written (a stored value is never overwritten unless it was null), and beat or miss against the estimate.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from app.services.trading_calendar import last_session_before, sessions_after

LOOKBACK_SESSIONS = 10        # events this many sessions back are asked for their EPS each night
MATCH_DAYS = 1                # a vendor row within this many calendar days of the event date is the same report
STALE_SESSIONS = 2            # a reported event with this many completed sessions since it (today excluded) and no EPS actual is a validate WARN
SOURCES = ("finnhub", "yfinance")


def sessions_back(today: date, n: int) -> date:
    """The session `n` sessions before today (today itself if a session counts as 0)."""
    d = today
    for _ in range(n):
        d = last_session_before(d)
    return d


def match_row(event_date: date, rows: dict[date, tuple[float | None, float | None]]) -> tuple[float | None, float | None] | None:
    """The vendor's (actual, estimate) for the event: the exact date first, else the nearest within MATCH_DAYS."""
    if event_date in rows:
        return rows[event_date]
    near = [(abs((d - event_date).days), d) for d in rows if abs((d - event_date).days) <= MATCH_DAYS]
    if not near:
        return None
    return rows[min(near)[1]]


def fill_plan(stored_actual, stored_estimate, actual: float | None, estimate: float | None, source: str, now: datetime) -> dict:
    """The columns to write: only the ones that are null now and that the vendor answered. Empty when nothing changes."""
    out: dict = {}
    if stored_actual is None and actual is not None:
        out["eps_actual"] = actual
    if stored_estimate is None and estimate is not None:
        out["eps_estimate"] = estimate
    if out:
        out["eps_source"] = source
        out["eps_fetched_at"] = now
    return out


def eps_outcome(actual: float | None, estimate: float | None) -> str | None:
    """beat, miss or meet against the estimate; None without both numbers."""
    if actual is None or estimate is None:
        return None
    if actual > estimate:
        return "beat"
    if actual < estimate:
        return "miss"
    return "meet"


def is_stale(event_date: date, today: date, actual) -> bool:
    """A reported event older than STALE_SESSIONS sessions with no EPS actual."""
    return actual is None and event_date <= today and sessions_after(event_date, today) >= STALE_SESSIONS
