#!/usr/bin/env python3
"""Exit non-zero inside the no-push window: 16:00 to 16:45 America/New_York on weekdays, when the chain courier is
loading production and a deploy would cut it off. Run before every git push:

    python3 scripts/push_window.py && git push origin main

Pure check in `in_window(now)`; the module's main reads the clock. Tested in scripts/test_push_window.py.
"""
from __future__ import annotations

import sys
from datetime import datetime, time
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/New_York")
WINDOW_START = time(16, 0)
WINDOW_END = time(16, 45)        # inclusive


def in_window(now: datetime) -> bool:
    """True when `now` (any zone; naive is read as New York) falls in the weekday no-push window."""
    local = now.astimezone(ZONE) if now.tzinfo else now.replace(tzinfo=ZONE)
    return local.weekday() < 5 and WINDOW_START <= local.time() <= WINDOW_END


def main() -> int:
    now = datetime.now(ZONE)
    if in_window(now):
        print(f"no push: {now:%a %H:%M} New York is inside the {WINDOW_START:%H:%M}-{WINDOW_END:%H:%M} courier window", file=sys.stderr)
        return 1
    print(f"push window open: {now:%a %H:%M} New York")
    return 0


if __name__ == "__main__":
    sys.exit(main())
