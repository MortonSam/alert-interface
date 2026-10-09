"""Whether the chain courier starts now. launchd fires run_courier.sh every 5 minutes on weekdays between 13:00 and 19:00 in the
Mac's own zone (Mountain, Central, Eastern or Pacific all cover 16:05 New York); this gate starts the run only on a New York
trading day, at or after 16:05 and no later than 16:45 New York, and only once per New York day. Independent of the Mac's zone.

Usage (from run_courier.sh):
    python3 -m app.scripts.courier_gate check --state FILE [--now 2026-10-09T20:05:00+00:00]   exit 0: start; exit 3: skip
    python3 -m app.scripts.courier_gate mark  --state FILE [--now ...]     the New York day's run has started
    python3 -m app.scripts.courier_gate clear --state FILE                 the run pushed nothing (production unreachable): may retry
Standard library only, plus the trading calendar when pandas is importable (else weekdays only).
"""
from __future__ import annotations

import sys
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

NEW_YORK = ZoneInfo("America/New_York")
START = time(16, 5)            # the capture starts after the 16:00 close (the Intrinio shadow judges captures at or after 16:00)
LAST_START = time(16, 45)      # never start later: the run takes about 30 minutes and must land before the backend's nightly reads it
SKIP = 3


def _trading_day(d: date) -> bool:
    try:
        from app.services.trading_calendar import is_trading_day
        return is_trading_day(d)
    except Exception:
        return d.weekday() < 5


def decide(now: datetime, last_run: str | None, trading_day=_trading_day) -> tuple[bool, str]:
    """Pure: (start, why). `now` is any aware time; `last_run` is the New York date (ISO) a run last started, or None."""
    ny = now.astimezone(NEW_YORK)
    day = ny.date()
    if not trading_day(day):
        return False, f"{day} is not a New York trading day"
    if ny.time() < START:
        return False, f"{ny:%H:%M} New York is before {START:%H:%M}"
    if ny.time() > LAST_START:
        return False, f"{ny:%H:%M} New York is after {LAST_START:%H:%M}: no start this late"
    if last_run == day.isoformat():
        return False, f"the {day} run has already started"
    return True, f"start: {ny:%Y-%m-%d %H:%M} New York"


def _now(argv: list[str]) -> datetime:
    raw = next((argv[i + 1] for i, a in enumerate(argv) if a == "--now" and i + 1 < len(argv)), None)
    return datetime.fromisoformat(raw) if raw else datetime.now(timezone.utc)


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "check"
    state = Path(next(argv[i + 1] for i, a in enumerate(argv) if a == "--state"))
    if cmd == "mark":
        state.write_text(_now(argv).astimezone(NEW_YORK).date().isoformat())
        return 0
    if cmd == "clear":
        state.unlink(missing_ok=True)
        return 0
    last = state.read_text().strip() if state.exists() else None
    start, why = decide(_now(argv), last)
    print(why)
    return 0 if start else SKIP


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
