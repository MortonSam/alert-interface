#!/usr/bin/env python3
"""Dead-man alert for the nightly: pages the phone when the morning digest has not arrived two hours after the 02:30 New York start.

Runs on Sam's Mac under launchd (com.alertinterface.deadman.plist, every 30 minutes from 04:30 to 06:00 New York, expressed in the
Mac's own clock by the plist; the script judges on the New York clock). It reads production's /health, finds the "Nightly run"
record in step_outcomes, and alerts through the same ntfy topic the digest uses when, at or after NIGHTLY_START + LATE_AFTER, no run
for today's New York date has finished. One alert per day (a state file). Nothing on Railway is involved, which is the point: a
backend that never starts its nightly cannot report that it did not.

Env file (never committed): ~/.alert-interface/deadman.env with NTFY_TOPIC=<topic> and optionally NTFY_SERVER, HEALTH_URL.

    python3 check_digest.py            # the launchd command
    python3 check_digest.py --dry-run  # print the verdict, send nothing
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

CLOCK = ZoneInfo("America/New_York")
NIGHTLY_START = dtime(2, 30)            # services/nightly_clock NIGHTLY_LOCAL_TIME
LATE_AFTER = timedelta(hours=2)         # the digest is late this long after the start
HEALTH_URL = "https://alertinterface.com/api/v1/health"
STATE = Path.home() / ".alert-interface" / "deadman.state"
ENV = Path.home() / ".alert-interface" / "deadman.env"


def load_env(path: Path = ENV) -> dict[str, str]:
    out: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def digest_late(health: dict | None, now: datetime) -> tuple[bool, str]:
    """Pure: (late, why). Late when now (New York) is past the start plus LATE_AFTER and no nightly run for today's New York
    date has a finished_at. /health unreadable counts as late (a dead backend is what this alert is for)."""
    local = now.astimezone(CLOCK)
    today = local.date()
    deadline = datetime.combine(today, NIGHTLY_START, tzinfo=CLOCK) + LATE_AFTER
    if local < deadline:
        return False, f"before the {deadline.strftime('%H:%M')} New York deadline"
    if not health:
        return True, "/health could not be read"
    run = (health.get("step_outcomes") or {}).get("Nightly run") or {}
    if run.get("slot") == today.isoformat() and run.get("finished_at"):
        return False, f"the {today} run finished at {run['finished_at']}"
    if run.get("slot") == today.isoformat() and run.get("started_at"):
        return True, f"the {today} run started at {run['started_at']} and has not finished"
    return True, f"no nightly run for {today} (last recorded slot {run.get('slot')})"


def fetch_health(url: str) -> dict | None:
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def already_alerted(today: date) -> bool:
    return STATE.exists() and STATE.read_text().strip() == today.isoformat()


def send(topic: str, server: str, title: str, body: str) -> bool:
    req = urllib.request.Request(f"{server.rstrip('/')}/{topic}", data=body.encode(), headers={"Title": title, "Priority": "high", "Tags": "rotating_light"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return 200 <= r.status < 300


def main(argv: list[str]) -> int:
    env = load_env()
    now = datetime.now(tz=CLOCK)
    health = fetch_health(env.get("HEALTH_URL", HEALTH_URL))
    late, why = digest_late(health, now)
    print(f"{now:%Y-%m-%d %H:%M} New York: {'LATE' if late else 'ok'}: {why}")
    if not late or "--dry-run" in argv:
        return 0
    if already_alerted(now.date()):
        print("already alerted today")
        return 0
    topic = env.get("NTFY_TOPIC")
    if not topic:
        print("no NTFY_TOPIC in", ENV)
        return 1
    send(topic, env.get("NTFY_SERVER", "https://ntfy.sh"), "Nightly digest is late", f"{why}. Check Railway and /health.")
    STATE.write_text(now.date().isoformat())
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
