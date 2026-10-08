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
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

ZONE = ZoneInfo("America/New_York")
WINDOW_START = time(16, 0)
WINDOW_END = time(16, 45)        # inclusive
ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"
DEV_PORT = 3000

STEPS: list[tuple[str, list[str], Path]] = [
    ("backend tests", ["docker", "compose", "exec", "-T", "backend", "python", "-m", "pytest", "tests", "-q"], ROOT),
    ("frontend tests", ["npx", "vitest", "run"], FRONTEND),
    ("frontend build", ["npm", "run", "build"], FRONTEND),
]
PUSH = ["git", "push", "origin", "main"]


def in_window(now: datetime) -> bool:
    """True when `now` (any zone; naive is read as New York) falls in the weekday no-push window."""
    local = now.astimezone(ZONE) if now.tzinfo else now.replace(tzinfo=ZONE)
    return local.weekday() < 5 and WINDOW_START <= local.time() <= WINDOW_END


def steps_for(frontend_only: bool) -> list[tuple[str, list[str], Path]]:
    """The gate's steps: all three, or only the frontend ones when the push carries frontend changes alone."""
    return [s for s in STEPS if not frontend_only or s[0].startswith("frontend")]


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
    if "--check-only" in argv:
        return 0
    frontend_only = "--frontend-only" in argv
    if frontend_only:
        print("frontend-only lane: the backend suite is skipped (the change touches frontend/ alone)")
    results: list[tuple[str, int]] = []
    for name, cmd, cwd in steps_for(frontend_only):
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
        results.append((name, code))
        if code != 0:
            break
    ok, why = gate(results)
    print(f"\n{why}", file=sys.stderr if not ok else sys.stdout, flush=True)
    if not ok:
        return 1
    return _run(PUSH, ROOT)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
