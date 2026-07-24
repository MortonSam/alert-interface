"""Data-refresh orchestrator.

Runs each seed/validate step in order, records last_refreshed_at on success,
and exits non-zero if any step fails or validation reports errors.

Usage
-----
    python -m app.scripts.refresh
    make refresh
"""
from __future__ import annotations

import asyncio
import subprocess
import sys
from datetime import datetime, timezone

from app.database import AsyncSessionLocal
from app.services.system_metadata_service import set_value

# ── Steps ─────────────────────────────────────────────────────────────────────

STEPS: list[tuple[str, list[str]]] = [
    ("Ticker data (seed_sp500)",        ["python", "-m", "app.scripts.seed_sp500"]),
    ("Macro calendar (seed_macro)",     ["python", "-m", "app.scripts.seed_macro"]),
    ("Historical reactions (--all)",    ["python", "-m", "app.scripts.seed_historical_reactions", "--all"]),
    ("FOMC reactions",                  ["python", "-m", "app.scripts.seed_fomc_reactions"]),
    ("Dividend calendar",              ["python", "-m", "app.scripts.seed_dividends"]),
    ("Split history",                  ["python", "-m", "app.scripts.seed_splits"]),
    ("Analyst actions",                ["python", "-m", "app.scripts.seed_analyst_actions"]),
    ("Analyst reaction stats",         ["python", "-m", "app.scripts.compute_analyst_reactions"]),
    ("IV + RV snapshot (snapshot_iv)",  ["python", "-m", "app.scripts.snapshot_iv"]),
    ("RV rank precompute",              ["python", "-m", "app.scripts.compute_rv_ranks"]),
    ("Close expired alert picks",      ["python", "-m", "app.scripts.close_alert_picks"]),
    ("Validate data",                   ["python", "-m", "app.scripts.validate_data"]),
]

WIDTH = 42


def _record_step_success(label: str) -> None:
    """Write step:<label>:last_success to system_metadata."""
    import asyncio as _aio
    async def _write():
        now_iso = datetime.now(timezone.utc).isoformat()
        async with AsyncSessionLocal() as session:
            await set_value(session, f"step:{label}:last_success", now_iso)
            await session.commit()
    try:
        _aio.run(_write())
    except Exception:
        pass  # metadata write failure must not crash the pipeline


def _run_step(label: str, cmd: list[str]) -> bool:
    """Run a subprocess step, streaming its output. Returns True on success."""
    print(f"\n{'─' * 60}")
    print(f"  STEP: {label}")
    print(f"{'─' * 60}")
    result = subprocess.run(cmd, check=False)
    ok = result.returncode == 0
    status = "PASS" if ok else "FAIL"
    print(f"\n  [{status}] {label} (exit {result.returncode})")
    if ok:
        _record_step_success(label)
    return ok


async def _record_refresh() -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    async with AsyncSessionLocal() as session:
        await set_value(session, "last_refreshed_at", now_iso)
        await session.commit()
    print(f"\n  Recorded last_refreshed_at = {now_iso}")


def main() -> int:
    print(f"\n{'=' * 60}")
    print("  DATA REFRESH PIPELINE")
    print(f"  Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'=' * 60}")

    results: list[tuple[str, bool]] = []
    for label, cmd in STEPS:
        ok = _run_step(label, cmd)
        results.append((label, ok))

    # ── Summary ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("  SUMMARY")
    print(f"{'─' * 60}")
    all_passed = True
    for label, ok in results:
        icon = "PASS" if ok else "FAIL"
        print(f"  [{icon}]  {label}")
        if not ok:
            all_passed = False

    print(f"{'=' * 60}\n")

    if all_passed:
        try:
            asyncio.run(_record_refresh())
        except RuntimeError:
            # When called from startup.py's run_in_executor, asyncio.run()
            # can't create a nested event loop.  startup.py writes the
            # sentinel itself on exit_code == 0.
            pass
        print("\n  Refresh complete.\n")
        return 0
    else:
        print("\n  Refresh FAILED. last_refreshed_at not updated.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
