#!/usr/bin/env python3
"""After a push: Railway's running deployment must be the commit just pushed, or this fails loudly.

    python3 scripts/deploy_check.py SHA              # waits up to WAIT_S for Railway's running commit to be SHA
    python3 scripts/deploy_check.py SHA --wait=60

On 2026-10-20 two pushes to main (f77172a, then an empty 55aeb08) started no Railway deployment at all: Vercel deployed, the
backend kept running e236e6d, and nothing said so. The gate (push_window.py) runs this after every push. It reads the service's
active deployment and its latest deployment through the Railway CLI, every POLL_S seconds, and exits 0 only when the running
commit is the pushed one; a deployment of it that failed, or none started within NO_START_S, or still another commit at the end,
exits 1 with a message that names both commits. Pure parts (`verdict`, `running_commit`, `latest_for`) are tested in
scripts/test_deploy_check.py.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time

SERVICE = "alert-interface"
WAIT_S = 15 * 60          # a Railway build and deploy takes about 3 minutes
POLL_S = 30
NO_START_S = 5 * 60       # no deployment of the pushed commit by then: Railway was never triggered
IN_PROGRESS = ("QUEUED", "INITIALIZING", "BUILDING", "DEPLOYING", "WAITING")
FAILED = ("FAILED", "CRASHED")


def running_commit(status: dict, service: str = SERVICE) -> str | None:
    """Pure: the commit of the service's active deployment in `railway status --json`."""
    for env in (status.get("environments") or {}).get("edges") or []:
        for si in ((env.get("node") or {}).get("serviceInstances") or {}).get("edges") or []:
            n = si.get("node") or {}
            if n.get("serviceName") != service:
                continue
            for d in n.get("activeDeployments") or []:
                sha = (d.get("meta") or {}).get("commitHash")
                if sha:
                    return sha
    return None


def latest_for(deployments: list[dict], sha: str) -> dict | None:
    """Pure: the newest deployment of `sha` in `railway deployment list --json` (newest first), or None."""
    return next((d for d in deployments if ((d.get("meta") or {}).get("commitHash") or "").startswith(sha)), None)


def verdict(sha: str, running: str | None, mine: dict | None, waited_s: float) -> tuple[str, str]:
    """Pure: ("ok" | "wait" | "fail", message)."""
    if running and running.startswith(sha):
        return "ok", f"deploy check: Railway is running {running[:8]}, the commit just pushed"
    have = f"Railway is still running {running[:8] if running else 'an unknown commit'}, not the pushed {sha[:8]}"
    if mine and mine.get("status") in FAILED:
        return "fail", f"DEPLOY CHECK FAILED: the deployment of {sha[:8]} ended {mine['status']}; {have}"
    if mine is None and waited_s >= NO_START_S:
        return "fail", f"DEPLOY CHECK FAILED: Railway started no deployment of {sha[:8]} in {NO_START_S // 60} minutes; {have}"
    if waited_s >= WAIT_S:
        return "fail", f"DEPLOY CHECK FAILED: {have} after {WAIT_S // 60} minutes" + (f" (its deployment is {mine.get('status')})" if mine else "")
    return "wait", have + (f"; its deployment is {mine.get('status')}" if mine else "; no deployment of it yet")


def _railway(args: list[str]):
    out = subprocess.run(["railway", *args], capture_output=True, text=True, timeout=60)
    return json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else None


def main(argv: list[str]) -> int:
    global WAIT_S
    sha = next((a for a in argv if not a.startswith("--")), None)
    if not sha:
        print("usage: deploy_check.py SHA [--wait=SECONDS]", file=sys.stderr)
        return 2
    WAIT_S = int(next((a.split("=", 1)[1] for a in argv if a.startswith("--wait=")), WAIT_S))
    t0 = time.time()
    while True:
        try:
            status = _railway(["status", "--json"]) or {}
            deployments = _railway(["deployment", "list", "--service", SERVICE, "--json"]) or []
        except (subprocess.SubprocessError, ValueError, OSError) as exc:
            status, deployments = {}, []
            print(f"deploy check: Railway unreadable ({type(exc).__name__}), retrying", flush=True)
        state, msg = verdict(sha, running_commit(status), latest_for(deployments, sha), time.time() - t0)
        if state == "ok":
            print(msg, flush=True)
            return 0
        if state == "fail":
            bar = "!" * 100
            print(f"\n{bar}\n{msg}\n{bar}\n", file=sys.stderr, flush=True)
            return 1
        print(f"deploy check: {msg}", flush=True)
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
