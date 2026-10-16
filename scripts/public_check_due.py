"""Whether the scheduled public-pages check runs now (.github/workflows/public-pages-check.yml), and the one ntfy alarm it sends.

The check renders every public route of production as an anonymous visitor (frontend/scripts/public-pages-check.mjs). It runs
  after every deploy: a commit status of success from Vercel or Railway on a commit that main contains;
  after every nightly: an hourly schedule reads production's /health and runs once a refresh has finished within the last
    NIGHTLY_LOOKBACK_MINUTES and none is in progress;
  by hand: workflow_dispatch, always.

usage: python3 scripts/public_check_due.py due <event_name> <event.json> <health.json or ->   prints run=true|false and reason=...
       python3 scripts/public_check_due.py alarm <check output file> <run url>                  sends one ntfy message (NTFY_TOPIC)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Optional

NIGHTLY_LOOKBACK_MINUTES = 60      # the schedule fires hourly, so each finished refresh is checked once
DEPLOY_CONTEXTS = ("Vercel", "enchanting-cooperation - alert-interface")   # the frontend and backend deploy statuses on GitHub
ALARM_LINES = 12                   # failing lines quoted in the alarm; the run's log holds the rest
TIMEOUT_SECONDS = 15


def _ts(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    t = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def due(event_name: str, event: dict, health: Optional[dict], now: datetime) -> tuple[bool, str]:
    """Pure: (run, reason)."""
    if event_name == "workflow_dispatch":
        return True, "run by hand"
    if event_name == "status":
        ctx, state = event.get("context", ""), event.get("state")
        on_main = any(b.get("name") == "main" for b in event.get("branches") or [])
        if state == "success" and on_main and ctx in DEPLOY_CONTEXTS:
            return True, f"deploy finished: {ctx} on {str(event.get('sha', ''))[:7]}"
        return False, f"status {ctx or '?'} {state or '?'}" + ("" if on_main else ", not on main")
    if event_name == "schedule":
        if health is None:
            return False, "production /health unreadable; the next hour retries"
        if health.get("refresh_in_progress") or health.get("refresh_started_at"):
            return False, "a refresh is in progress"
        last = _ts(health.get("last_refreshed_at"))
        if last and timedelta(0) <= now - last <= timedelta(minutes=NIGHTLY_LOOKBACK_MINUTES):
            return True, f"refresh finished {last:%Y-%m-%d %H:%M} UTC"
        return False, "no refresh finished in the last hour"
    return False, f"event {event_name} is not a trigger"


def alarm_text(output: str, run_url: str) -> tuple[str, str]:
    """Pure: (title, body) of the one alarm for a failing run."""
    lines = output.splitlines()
    fails = [ln for ln in lines if ln.startswith("FAIL") or ln.startswith("  ")]
    summary = next((ln for ln in reversed(lines) if "failing; patterns" in ln), "the check did not finish")
    n = sum(1 for ln in lines if ln.startswith("FAIL"))
    title = f"Public pages check: {n} route(s) failing" if n else "Public pages check did not finish"
    body = "\n".join(fails[:ALARM_LINES] + ([f"... {len(fails) - ALARM_LINES} more"] if len(fails) > ALARM_LINES else [])
                     + [summary.split(";")[0], run_url])
    return title, body


def send(title: str, body: str) -> bool:
    topic = os.environ.get("NTFY_TOPIC", "").strip()
    if not topic:
        print("NTFY_TOPIC is not set: no alarm sent", file=sys.stderr)
        return False
    server = (os.environ.get("NTFY_SERVER") or "https://ntfy.sh").rstrip("/")
    req = urllib.request.Request(f"{server}/{topic}", data=body.encode(), method="POST",
                                 headers={"Title": title, "Priority": "high", "Tags": "warning"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as r:
        return 200 <= r.status < 300


def main(argv: list[str]) -> int:
    if argv[:1] == ["due"]:
        event_name, event_path, health_path = argv[1:4]
        event = json.load(open(event_path)) if os.path.exists(event_path) else {}
        health = None
        if health_path != "-" and os.path.exists(health_path):
            try:
                health = json.load(open(health_path))
            except ValueError:
                health = None
        run, reason = due(event_name, event, health, datetime.now(timezone.utc))
        print(f"run={'true' if run else 'false'}\nreason={reason}")
        return 0
    if argv[:1] == ["alarm"]:
        title, body = alarm_text(open(argv[1]).read() if os.path.exists(argv[1]) else "", argv[2])
        print(f"{title}\n{body}")
        return 0 if send(title, body) else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
