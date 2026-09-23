"""Data-refresh orchestrator.

Runs each seed/validate step in order, records last_refreshed_at on success,
and exits non-zero if any step fails or validation reports errors.

Usage
-----
    python -m app.scripts.refresh
    make refresh
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone

import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.config import settings

# ── Sync bookkeeping engine (one connection per write, no pool) ──────────────

_sync_engine = create_engine(settings.database_url_sync, poolclass=NullPool)


def _db_upsert(key: str, value: str) -> None:
    """Synchronous upsert mirroring set_value's SQL semantics."""
    now = datetime.now(timezone.utc)
    stmt = sa.text(
        "INSERT INTO system_metadata (key, value, updated_at) "
        "VALUES (:key, :value, :now) "
        "ON CONFLICT (key) DO UPDATE SET value = :value, updated_at = :now"
    )
    with _sync_engine.connect() as conn:
        conn.execute(stmt, {"key": key, "value": value, "now": now})
        conn.commit()


def _db_get(key: str) -> str | None:
    """Synchronous get mirroring get_value's SQL semantics."""
    stmt = sa.text("SELECT value FROM system_metadata WHERE key = :key")
    with _sync_engine.connect() as conn:
        row = conn.execute(stmt, {"key": key}).first()
    return row[0] if row else None


# ── Steps ─────────────────────────────────────────────────────────────────────

STEPS: list[tuple[str, list[str]]] = [
    ("Ticker data (seed_sp500)",              ["python", "-m", "app.scripts.seed_sp500"]),
    ("Refresh profiles (Finnhub)",            ["python", "-m", "app.scripts.refresh_profiles"]),
    ("Refresh earnings calendar (Finnhub)",   ["python", "-m", "app.scripts.refresh_earnings_calendar"]),
    ("Analyst recommendations (Finnhub)",    ["python", "-m", "app.scripts.refresh_recommendations"]),
    ("Macro calendar (seed_macro)",           ["python", "-m", "app.scripts.seed_macro"]),
    # RV rank runs before every reaction step: its data_error verdict is the price-history
    # exclusion list the reaction steps and every reader apply, so they act on tonight's verdict.
    ("RV rank precompute",              ["python", "-m", "app.scripts.compute_rv_ranks"]),
    ("Historical reactions (--all)",    ["python", "-m", "app.scripts.seed_historical_reactions", "--all"]),
    ("EPS basis check (check_eps_basis)", ["python", "-m", "app.scripts.check_eps_basis", "--incremental"]),
    ("FOMC reactions",                  ["python", "-m", "app.scripts.seed_fomc_reactions"]),
    ("Dividend calendar",              ["python", "-m", "app.scripts.seed_dividends"]),
    ("Split history",                  ["python", "-m", "app.scripts.seed_splits"]),
    ("Analyst actions",                ["python", "-m", "app.scripts.seed_analyst_actions"]),
    ("Analyst reaction stats",         ["python", "-m", "app.scripts.compute_analyst_reactions"]),
    ("Sector peer snapshot",            ["python", "-m", "app.scripts.compute_sector_peers"]),
    ("Magnitude trend snapshot",        ["python", "-m", "app.scripts.compute_magnitude_trends"]),
    # RV ranks first: snapshot_iv reads realized vol from the rv_snapshots row written here.
    ("IV + RV snapshot (snapshot_iv)",  ["python", "-m", "app.scripts.snapshot_iv"]),
    ("Build earnings features",         ["python", "-m", "app.scripts.build_features"]),
    ("Auto-pick",                      ["python", "-m", "app.scripts.auto_pick"]),
    ("Shadow eval",                    ["python", "-m", "app.scripts.shadow_eval"]),
    ("Close expired alert picks",      ["python", "-m", "app.scripts.close_alert_picks"]),
    ("Validate data",                   ["python", "-m", "app.scripts.validate_data"]),
    ("Warm options reads",               ["python", "-m", "app.scripts.warm_options_reads"]),
]

STEP_TIMEOUT_SECONDS = 600  # 10 minutes default

STEP_TIMEOUTS: dict[str, int] = {
    "Refresh profiles (Finnhub)": 300,
    "Refresh earnings calendar (Finnhub)": 300,
    "Analyst recommendations (Finnhub)": 300,
    "Historical reactions (--all)": 1800,
    "EPS basis check (check_eps_basis)": 900,     # TIME_BUDGET_SECONDS 600 + EDGAR slack
    "FOMC reactions": 900,
    "Analyst actions": 1200,
    "Build earnings features": 1200,
    "Auto-pick": 600,
    "Shadow eval": 600,
    "Warm options reads": 3600,
}


def _record_step_success(label: str) -> None:
    """Write step:<label>:last_success to system_metadata."""
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        _db_upsert(f"step:{label}:last_success", now_iso)
    except Exception as exc:
        print(f"  [WARN] Failed to write step stamp for {label}: {exc}")


STDERR_EXCERPT_LINES = 3


def _stderr_excerpt(stderr_text: str | None) -> tuple[str | None, str | None]:
    """(head, tail): the first and last STDERR_EXCERPT_LINES non-empty lines of a step's stderr.

    A Python traceback puts the exception class and message on its last
    line, so the tail is what names a failure; the head says where it began.
    The tail is None when the head already holds every line.
    """
    if not stderr_text:
        return None, None
    lines = [l for l in stderr_text.strip().splitlines() if l.strip()]
    if not lines:
        return None, None
    head = "\n".join(lines[:STDERR_EXCERPT_LINES])
    tail = "\n".join(lines[-STDERR_EXCERPT_LINES:]) if len(lines) > STDERR_EXCERPT_LINES else None
    return head, tail


def _record_step_outcome(label: str, exit_code: int, seconds: float,
                         stderr_head: str | None = None,
                         stderr_tail: str | None = None) -> None:
    """Append this step's outcome to the durable step_outcomes JSON blob.

    Merges with any existing fields for this label so that scripts which
    write their own extended outcome (e.g. warm_options_reads) keep those
    fields intact. /health returns the blob as step_outcomes, so stderr_head
    and stderr_tail are readable without the Railway log.
    """
    try:
        raw = _db_get("step_outcomes")
        outcomes = json.loads(raw) if raw else {}
        existing = outcomes.get(label, {})
        existing.update({
            "exit": exit_code,
            "seconds": round(seconds, 1),
            "at": datetime.now(timezone.utc).isoformat(),
        })
        if stderr_head:
            existing["stderr_head"] = stderr_head
        if stderr_tail:
            existing["stderr_tail"] = stderr_tail
        elif "stderr_tail" in existing:
            del existing["stderr_tail"]      # a short or clean run must not keep an older run's tail
        outcomes[label] = existing
        _db_upsert("step_outcomes", json.dumps(outcomes))
    except Exception as exc:
        print(f"  [WARN] Failed to write step outcome for {label}: {exc}")


def _step_env() -> dict[str, str]:
    """Subprocess environment with tqdm progress bars disabled."""
    env = os.environ.copy()
    env["TQDM_DISABLE"] = "1"
    return env


def _run_step(label: str, cmd: list[str]) -> bool:
    """Run a subprocess step, streaming stdout and capturing stderr.

    Returns True on success.  The first and last 3 lines of stderr are stored
    in step_outcomes (stderr_head / stderr_tail) for post-mortem diagnosis:
    the tail carries a traceback's exception line.
    """
    timeout = STEP_TIMEOUTS.get(label, STEP_TIMEOUT_SECONDS)
    print(f"\n{'─' * 60}")
    print(f"  STEP: {label}")
    print(f"{'─' * 60}")
    t0 = time.monotonic()
    stderr_head: str | None = None
    stderr_tail: str | None = None
    try:
        result = subprocess.run(
            cmd, check=False, timeout=timeout,
            env=_step_env(), stderr=subprocess.PIPE,
        )
        if result.stderr:
            stderr_text = result.stderr.decode(errors="replace")
            # Print stderr so it's visible in logs
            sys.stderr.write(stderr_text)
            stderr_head, stderr_tail = _stderr_excerpt(stderr_text)
    except subprocess.TimeoutExpired as exc:
        elapsed = time.monotonic() - t0
        print(f"\n  [FAIL] {label} (killed after {timeout}s timeout)")
        if exc.stderr:
            stderr_head, stderr_tail = _stderr_excerpt(exc.stderr.decode(errors="replace"))
        _record_step_outcome(label, exit_code=-1, seconds=elapsed,
                             stderr_head=stderr_head, stderr_tail=stderr_tail)
        return False
    elapsed = time.monotonic() - t0
    ok = result.returncode == 0
    status = "PASS" if ok else "FAIL"
    print(f"\n  [{status}] {label} (exit {result.returncode}, {elapsed:.0f}s)")
    _record_step_outcome(label, exit_code=result.returncode, seconds=elapsed,
                         stderr_head=stderr_head, stderr_tail=stderr_tail)
    if ok:
        _record_step_success(label)
    return ok


def _record_refresh() -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    _db_upsert("last_refreshed_at", now_iso)
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

    # Write last_refreshed_at when the pipeline runs to completion,
    # regardless of individual step results.  step_health tracks per-step truth.
    try:
        _record_refresh()
    except Exception:
        pass

    if all_passed:
        print("\n  Refresh complete.\n")
        return 0
    else:
        print("\n  Refresh completed with failures (see above). last_refreshed_at updated.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
