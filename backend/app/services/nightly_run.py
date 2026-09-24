"""Whether the latest nightly Auto-pick run completed, from step_outcomes.

step_outcomes["Auto-pick"] holds exit, seconds, at, and on failure the first
and last stderr lines (refresh.py). The desk shows a worksheet only from rows
Auto-pick wrote, so when the latest run failed or never happened, the page
must say so rather than present the previous night's worksheet as current.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

AUTO_PICK_STEP = "Auto-pick"
NIGHTLY_RUN_UTC_HOUR = 6      # the Railway cron starts the nightly at 06:00Z
NIGHTLY_GRACE = timedelta(hours=1)   # Auto-pick sits ~16 min into the run; allow slow nights


@dataclass(frozen=True)
class RunStatus:
    at: str | None          # ISO UTC of the latest Auto-pick outcome
    exit: int | None        # its exit code (-1 = killed at the step timeout)
    error: str | None       # stderr tail when present, else head
    stale: bool             # older than the latest expected run
    failed: bool            # exit is not 0, or stale, or never recorded

    @property
    def ok(self) -> bool:
        return not self.failed


def expected_run_at(now: datetime) -> datetime:
    """The most recent nightly start that should have completed by `now`."""
    today_run = now.replace(hour=NIGHTLY_RUN_UTC_HOUR, minute=0, second=0, microsecond=0)
    return today_run if now >= today_run + NIGHTLY_GRACE else today_run - timedelta(days=1)


def auto_pick_status(step_outcomes: dict | None, now: datetime | None = None) -> RunStatus:
    now = now or datetime.now(timezone.utc)
    entry = (step_outcomes or {}).get(AUTO_PICK_STEP) or {}
    at = entry.get("at")
    exit_code = entry.get("exit")
    error = entry.get("stderr_tail") or entry.get("stderr_head")
    try:
        at_dt = datetime.fromisoformat(at) if at else None
    except ValueError:
        at_dt = None
    stale = at_dt is None or at_dt < expected_run_at(now)
    failed = stale or exit_code != 0
    return RunStatus(at=at, exit=exit_code, error=error, stale=stale, failed=failed)
