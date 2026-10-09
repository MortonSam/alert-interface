#!/usr/bin/env python3
"""The push gate. Run instead of `git push`:

    python3 scripts/push_window.py              # checks, then pushes origin main
    python3 scripts/push_window.py --check-only # the courier-window check alone, no tests, no push

In order, each read by its exit code directly (never through a pipe): the no-push window (16:00 to 16:45 America/New_York on
weekdays, when the chain courier is loading production), the full backend suite in the backend container, the full frontend
suite, the frontend production build with the dev server stopped before it and restarted after it, and only then git push.
Any non-zero exit stops the gate and nothing is pushed. Pure parts (`in_window`, `gate`) are tested in scripts/test_push_window.py.
"""
from __future__ import annotations

import os
import subprocess
import time as clock          # `time` the name is datetime.time (WINDOW_START)
import sys
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/New_York")
WINDOW_START = time(16, 0)
WINDOW_END = time(16, 45)        # inclusive
ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DEV_PORT = 3000

# The backend suite runs on alertdb_test, a copy of the dev database rebuilt for every run (tests never share a database with the
# container's refresh loop), in parallel with pytest-xdist; files that share rows carry an xdist_group mark and run on one worker.
TEST_DB = "alertdb_test"
TEST_DB_ASYNC = f"postgresql+asyncpg://alert:alert@db:5432/{TEST_DB}"
TEST_DB_SYNC = f"postgresql://alert:alert@db:5432/{TEST_DB}"
STEPS: list[tuple[str, list[str], Path]] = [
    ("backend tests", ["docker", "compose", "exec", "-T", "-e", f"DATABASE_URL={TEST_DB_ASYNC}", "-e", f"DATABASE_URL_SYNC={TEST_DB_SYNC}",
                       "backend", "python", "-m", "pytest", "tests", "-q", "-n", "auto", "--dist", "loadgroup"], ROOT),
    ("frontend tests", ["npx", "vitest", "run"], FRONTEND),
    ("frontend build", ["npm", "run", "build"], FRONTEND),
]
REBUILD_TEST_DB = ["docker", "compose", "exec", "-T", "db", "sh", "-c",
                   f"set -o pipefail; psql -q -U alert -d postgres -c 'drop database if exists {TEST_DB}' && psql -q -U alert -d postgres -c 'create database {TEST_DB}' "
                   f"&& pg_dump -U alert alertdb | psql -q -U alert {TEST_DB}"]
BACKEND_LOG = Path("/tmp/push_backend_tests.log")
PUSH = ["git", "push", "origin", "main"]


def lane_for(changed: list[str], argv: list[str]) -> str:
    """Pure: "frontend" when every file the push carries is under frontend/ (or --frontend-only is given), else "full"; --full forces full."""
    if "--full" in argv:
        return "full"
    if "--frontend-only" in argv:
        return "frontend"
    if changed and all(f.startswith("frontend/") for f in changed):
        return "frontend"
    return "full"


def steps_for(lane: str) -> list[tuple[str, list[str], Path]]:
    """The gate's steps: the frontend lane runs the frontend tests and build; the full lane adds the backend suite."""
    return [s for s in STEPS if lane == "full" or s[0].startswith("frontend")]


def changed_files() -> list[str] | None:
    """The files the push would carry (origin/main..HEAD), or None when the upstream ref cannot be read (then the lane is full)."""
    out = subprocess.run(["git", "diff", "--name-only", "origin/main...HEAD"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        return None
    return [line for line in out.stdout.splitlines() if line.strip()]


HEALTH_URL = "https://alertinterface.com/api/v1/health"
NIGHTLY_START = time(2, 30)          # app/services/nightly_clock.NIGHTLY_LOCAL_TIME, New York
NIGHTLY_MAX_HOURS = 6                # a run marked in progress longer than this is a dead marker, not a running nightly
NIGHTLY_LEAD_MINUTES = 15            # no push this close before the nightly starts: the deploy would restart the backend as it begins
RECHECK_MINUTES = 15


def nightly_block(health: dict | None, now: datetime) -> str | None:
    """Pure: why a push must wait for the production nightly, or None. `health` is production's /health (None when unreadable)."""
    local = now.astimezone(ZONE)
    start_today = local.replace(hour=NIGHTLY_START.hour, minute=NIGHTLY_START.minute, second=0, microsecond=0)
    if timedelta(0) < start_today - local <= timedelta(minutes=NIGHTLY_LEAD_MINUTES):
        return (f"no push: the production nightly starts at {NIGHTLY_START:%H:%M} New York and a deploy now would restart the backend as it "
                f"begins; retry after {start_today:%H:%M} once /health shows it running, or after it finishes")
    if health is None:
        return f"no push: production /health is unreadable, so whether the nightly is running is unknown; retry in {RECHECK_MINUTES} minutes (or pass --nightly-unknown-ok if production is down)"
    started_raw = health.get("refresh_started_at")
    if started_raw:
        try:
            started = datetime.fromisoformat(started_raw)
        except ValueError:
            started = None
        if started is not None:
            age = now - started
            if age < timedelta(hours=NIGHTLY_MAX_HOURS):
                latest = (started + timedelta(hours=NIGHTLY_MAX_HOURS)).astimezone(ZONE)
                return (f"no push: the production nightly has been running since {started.astimezone(ZONE):%H:%M} New York ({int(age.total_seconds() // 60)} min); "
                        f"retry in {RECHECK_MINUTES} minutes, and by {latest:%H:%M} at the latest it has finished or its marker has expired")
    elif health.get("refresh_in_progress"):
        return f"no push: production /health reports the nightly in progress; retry in {RECHECK_MINUTES} minutes"
    return None


def read_health(url: str = HEALTH_URL) -> dict | None:
    """Production's /health, or None when it cannot be read."""
    import json as _json
    import urllib.request
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "push_window"}), timeout=20) as r:
            return _json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def nightly_check(argv: list[str]) -> str | None:
    """The live check: None when a push may go now."""
    why = nightly_block(read_health(), datetime.now(timezone.utc))
    if why and "--nightly-unknown-ok" in argv and why.startswith("no push: production /health is unreadable"):
        return None
    return why


def in_window(now: datetime) -> bool:
    """True when `now` (any zone; naive is read as New York) falls in the weekday no-push window."""
    local = now.astimezone(ZONE) if now.tzinfo else now.replace(tzinfo=ZONE)
    return local.weekday() < 5 and WINDOW_START <= local.time() <= WINDOW_END


def gate(results: list[tuple[str, int]]) -> tuple[bool, str]:
    """Pure: (may push, why) from (step, exit code) pairs: every step must have exited 0."""
    failed = [f"{name} (exit {code})" for name, code in results if code != 0]
    if failed:
        return False, "no push: " + ", ".join(failed)
    return True, "all checks passed: " + ", ".join(name for name, _ in results)


def _run(cmd: list[str], cwd: Path) -> int:
    """A step's exit code, output passed straight through (no pipe, no shell)."""
    print(f"\n$ {' '.join(cmd)}   (in {cwd.relative_to(ROOT) if cwd != ROOT else '.'})", flush=True)
    return subprocess.run(cmd, cwd=cwd).returncode


def _dev_server_pids() -> list[int]:
    out = subprocess.run(["lsof", "-nP", f"-iTCP:{DEV_PORT}", "-sTCP:LISTEN", "-t"], capture_output=True, text=True).stdout.split()
    return [int(p) for p in out if p.isdigit()]


def _stop_dev_server() -> bool:
    pids = _dev_server_pids()
    for pid in pids:
        subprocess.run(["kill", str(pid)])
    return bool(pids)


def _start_dev_server() -> None:
    log = open("/tmp/next-dev.log", "ab")
    subprocess.Popen(["npm", "run", "dev"], cwd=FRONTEND, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)


def main(argv: list[str]) -> int:
    now = datetime.now(ZONE)
    if in_window(now):
        print(f"no push: {now:%a %H:%M} New York is inside the {WINDOW_START:%H:%M}-{WINDOW_END:%H:%M} courier window", file=sys.stderr)
        return 1
    print(f"push window open: {now:%a %H:%M} New York")
    why = nightly_check(argv)
    if why:
        print(why, file=sys.stderr)
        return 1
    print("production nightly: not running")
    if "--check-only" in argv:
        return 0
    changed = changed_files()
    lane = lane_for(changed or [], argv) if changed is not None else "full"
    print(f"{lane} lane: " + ("the push carries frontend/ changes only; the backend suite is skipped" if lane == "frontend"
                             else "backend suite on a fresh copy of the dev database, in parallel with the frontend tests and build"))
    started = clock.monotonic()
    timings: list[tuple[str, float]] = []
    results: list[tuple[str, int]] = []
    backend: subprocess.Popen | None = None
    backend_started = 0.0
    if lane == "full":
        t0 = clock.monotonic()
        code = _run(REBUILD_TEST_DB, ROOT)
        timings.append(("rebuild test db", clock.monotonic() - t0))
        results.append(("rebuild test db", code))
        if code == 0:
            cmd = next(c for n, c, _ in STEPS if n == "backend tests")
            print(f"\n$ {' '.join(cmd)}   (in ., background, output to {BACKEND_LOG})", flush=True)
            backend_started = clock.monotonic()
            backend = subprocess.Popen(cmd, cwd=ROOT, stdout=open(BACKEND_LOG, "wb"), stderr=subprocess.STDOUT)
    if all(code == 0 for _, code in results):
        for name, cmd, cwd in steps_for("frontend"):
            t0 = clock.monotonic()
            if name == "frontend build":
                was_running = _stop_dev_server()      # the build and the dev server share .next
                try:
                    code = _run(cmd, cwd)
                finally:
                    if was_running:
                        _start_dev_server()
                        print("dev server restarted", flush=True)
            else:
                code = _run(cmd, cwd)
            timings.append((name, clock.monotonic() - t0))
            results.append((name, code))
            if code != 0:
                break
    if backend is not None:
        code = backend.wait()                      # the exit code, read from the process, never through a pipe
        timings.append(("backend tests", clock.monotonic() - backend_started))
        results.append(("backend tests", code))
        tail = BACKEND_LOG.read_text(errors="replace").splitlines()[-40:]
        print("\n--- backend tests (last 40 lines of " + str(BACKEND_LOG) + ") ---\n" + "\n".join(tail), flush=True)
    print("\ntimings: " + ", ".join(f"{n} {t:.0f}s" for n, t in timings) + f"; total {clock.monotonic() - started:.0f}s", flush=True)
    ok, why = gate(results)
    print(f"\n{why}", file=sys.stderr if not ok else sys.stdout, flush=True)
    if not ok:
        return 1
    why = nightly_check(argv)              # checked again: the gate takes minutes and the nightly may have started meanwhile
    if why:
        print(why, file=sys.stderr)
        return 1
    return _run(PUSH, ROOT)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
