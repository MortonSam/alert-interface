"""Run the v3 reaction-window cutover pipeline.

Steps:
  0. Backfill report timing (Finnhub + EDGAR)
  1. Reseed all historical reactions (v3)
  2. Recompute sector peer snapshots
  3. Recompute magnitude trend snapshots
  4. Rebuild earnings features
  5. Shadow eval (Ivy retrain)
  6. Warm options reads

Usage
-----
    # Run backfill only, review coverage:
    nohup python -m app.scripts.run_v3_cutover --backfill-only > /tmp/v3_cutover.log 2>&1 &
    tail -f /tmp/v3_cutover.log

    # After reviewing, run full cutover from step 1:
    nohup python -m app.scripts.run_v3_cutover --step 1 > /tmp/v3_cutover.log 2>&1 &
    tail -f /tmp/v3_cutover.log

    # Full run:
    python -m app.scripts.run_v3_cutover
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime, timezone

STEPS: list[tuple[str, list[str], int | None]] = [
    # (label, command, timeout_seconds or None for no timeout)
    ("Backfill report timing",   ["python", "-m", "app.scripts.backfill_report_timing"], 1800),
    ("Reseed all (v3)",          ["python", "-m", "app.scripts.seed_historical_reactions", "--all", "--force"], None),
    ("Sector peer snapshot",     ["python", "-m", "app.scripts.compute_sector_peers"], 1800),
    ("Magnitude trend snapshot", ["python", "-m", "app.scripts.compute_magnitude_trends"], 1800),
    ("Build features",           ["python", "-m", "app.scripts.build_features"], 1800),
    ("Shadow eval (Ivy retrain)",["python", "-m", "app.scripts.shadow_eval"], 1800),
    ("Warm options reads",       ["python", "-m", "app.scripts.warm_options_reads"], 1800),
]

LOG_FILE = "/tmp/v3_cutover.log"


def _run_step(idx: int, label: str, cmd: list[str], timeout: int | None) -> bool:
    """Run a subprocess, streaming output. Returns True on success."""
    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
    header = f"\n{'=' * 60}\n[{ts}] Step {idx}: {label}\n{'=' * 60}\n"
    print(header, flush=True)

    try:
        result = subprocess.run(
            cmd,
            timeout=timeout,
            # Stream to parent stdout/stderr (which is tee'd to log by nohup)
        )
        if result.returncode != 0:
            print(f"\nERROR: Step {idx} ({label}) failed with exit code {result.returncode}", flush=True)
            return False
        print(f"\nStep {idx} ({label}) completed successfully.", flush=True)
        return True
    except subprocess.TimeoutExpired:
        print(f"\nERROR: Step {idx} ({label}) timed out after {timeout}s", flush=True)
        return False
    except Exception as exc:
        print(f"\nERROR: Step {idx} ({label}) raised {exc!r}", flush=True)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Run v3 reaction-window cutover pipeline")
    parser.add_argument("--step", type=int, default=0, metavar="N",
                        help="Start from step N (0-indexed, default 0)")
    parser.add_argument("--backfill-only", action="store_true",
                        help="Run only step 0 (backfill report timing) and exit")
    args = parser.parse_args()

    start_step = args.step
    end_step = 1 if args.backfill_only else len(STEPS)

    print(f"v3 cutover pipeline", flush=True)
    print(f"  Steps: {start_step} to {end_step - 1}", flush=True)
    print(f"  Log: {LOG_FILE}", flush=True)
    start_time = time.monotonic()

    for idx in range(start_step, end_step):
        if idx >= len(STEPS):
            break
        label, cmd, timeout = STEPS[idx]
        ok = _run_step(idx, label, cmd, timeout)
        if not ok:
            elapsed = time.monotonic() - start_time
            print(f"\nPipeline FAILED at step {idx} after {elapsed:.0f}s", flush=True)
            return 1

    elapsed = time.monotonic() - start_time
    print(f"\n{'=' * 60}", flush=True)
    print(f"Pipeline completed in {elapsed:.0f}s", flush=True)
    print(f"{'=' * 60}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
