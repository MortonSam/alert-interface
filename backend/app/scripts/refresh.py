"""Data-refresh orchestrator.

Runs each seed/validate step in order, records last_refreshed_at on success,
and exits non-zero if any step fails or validation reports errors.

Usage
-----
    python -m app.scripts.refresh
    make refresh
"""
from __future__ import annotations
from app.services.redact import redact

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
    ("Security records (Intrinio)",           ["python", "-m", "app.scripts.build_security_records", "--write"]),
    ("Price bars shadow (Intrinio)",          ["python", "-m", "app.scripts.shadow_price_bars"]),
    ("Refresh earnings calendar (Finnhub)",   ["python", "-m", "app.scripts.refresh_earnings_calendar"]),
    ("EPS actuals (Finnhub)",          ["python", "-m", "app.scripts.seed_eps_actuals"]),
    # GAAP diluted EPS from the earnings release for quarters XBRL does not hold yet, then checked against XBRL once filed
    ("Release EPS (8-K exhibits)",     ["python", "-m", "app.scripts.seed_release_eps", "--due", "--write"]),
    ("Release EPS vs XBRL",            ["python", "-m", "app.scripts.check_release_eps"]),
    # after the price bars and the release figures: price over the four latest reported quarters, per ticker and per sector
    # completed spin-offs, mergers and share-exchange acquisitions from new 8-K Item 2.01 filings, before the P/E judges its windows
    ("Corporate actions (8-K Item 2.01)", ["python", "-m", "app.scripts.scan_corporate_actions", "--recent=45", "--write"]),
    ("Trailing P/E",                   ["python", "-m", "app.scripts.compute_pe", "--write"]),
    ("Analyst recommendations (Finnhub)",    ["python", "-m", "app.scripts.refresh_recommendations"]),
    ("Discover news (Finnhub)",              ["python", "-m", "app.scripts.refresh_news"]),
    ("Macro calendar (seed_macro)",           ["python", "-m", "app.scripts.seed_macro"]),
    # RV rank runs before every reaction step: its data_error verdict is the price-history
    # exclusion list the reaction steps and every reader apply, so they act on tonight's verdict.
    ("RV rank precompute",              ["python", "-m", "app.scripts.compute_rv_ranks"]),
    ("Historical reactions (--all)",    ["python", "-m", "app.scripts.seed_historical_reactions", "--all"]),
    ("Missed reports (catch_up_reports)", ["python", "-m", "app.scripts.catch_up_reports"]),
    ("EPS basis check (check_eps_basis)", ["python", "-m", "app.scripts.check_eps_basis", "--incremental"]),
    ("FOMC reactions",                  ["python", "-m", "app.scripts.seed_fomc_reactions"]),
    ("Dividend calendar",              ["python", "-m", "app.scripts.seed_dividends"]),
    ("Split history",                  ["python", "-m", "app.scripts.seed_splits"]),
    ("Reclassify spin-offs",           ["python", "-m", "app.scripts.reclassify_spin_offs", "--write"]),
    ("Analyst actions",                ["python", "-m", "app.scripts.seed_analyst_actions"]),
    ("Analyst reaction stats",         ["python", "-m", "app.scripts.compute_analyst_reactions"]),
    # rows still without a price source, and windows touching a session the calendar corrected, from the stored bars
    ("Recompute reactions (Intrinio)", ["python", "-m", "app.scripts.recompute_reactions_intrinio", "--nightly"]),
    ("Sector peer snapshot",            ["python", "-m", "app.scripts.compute_sector_peers"]),
    ("Magnitude trend snapshot",        ["python", "-m", "app.scripts.compute_magnitude_trends"]),
    # RV ranks first: snapshot_iv reads realized vol from the rv_snapshots row written here.
    ("IV + RV snapshot (snapshot_iv)",  ["python", "-m", "app.scripts.snapshot_iv"]),
    ("Build earnings features",         ["python", "-m", "app.scripts.build_features"]),
    ("Auto-pick",                      ["python", "-m", "app.scripts.auto_pick"]),
    ("Shadow eval",                    ["python", "-m", "app.scripts.shadow_eval"]),
    ("Close expired alert picks",      ["python", "-m", "app.scripts.close_alert_picks"]),
    # Scheduled at 03:05 America/New_York by the script itself (it waits when reached early); shadow only, no reader switches.
    ("Options chains (Intrinio)",      ["python", "-m", "app.scripts.shadow_option_chains"]),
    ("ATM IV (solver)",                ["python", "-m", "app.scripts.solve_atm_iv"]),
    # every ticker's newest chain from each source against the official close (services/options_source); before the warmed reads
    ("Chain parity (both sources)",    ["python", "-m", "app.scripts.check_chain_parity"]),
    # The warm fills the options-read cache for tonight's chain date; validate's options_read_coverage judges
    # that cache, so validate runs last (before, every chain-roll day reported 0/512 and then the warm filled it).
    ("Warm options reads",               ["python", "-m", "app.scripts.warm_options_reads"]),
    ("Validate data",                   ["python", "-m", "app.scripts.validate_data"]),
]

STEP_TIMEOUT_SECONDS = 600  # 10 minutes default

STEP_TIMEOUTS: dict[str, int] = {
    "Refresh profiles (Finnhub)": 300,
    "Security records (Intrinio)": 600,          # one Intrinio request per active ticker at 4/s
    "Price bars shadow (Intrinio)": 1800,        # one request per record per night; the first run writes five years
    "Refresh earnings calendar (Finnhub)": 1200,  # Finnhub once, Yahoo per ticker (420s budget), announcements (240s budget), EDGAR 2.02 checks
    "Analyst recommendations (Finnhub)": 300,
    "Discover news (Finnhub)": 1800,                # two Finnhub calls per ticker at 40 a minute, about 25 minutes
    "Historical reactions (--all)": 1800,
    "Missed reports (catch_up_reports)": 600,     # one Finnhub call, a few EDGAR calls, re-seed of a few tickers
    "EPS basis check (check_eps_basis)": 900,     # TIME_BUDGET_SECONDS 600 + EDGAR slack
    "FOMC reactions": 900,
    "Analyst actions": 1200,
    "Build earnings features": 1200,
    "Auto-pick": 600,
    "Shadow eval": 600,
    "Options chains (Intrinio)": 3 * 3600 + 1800,   # may wait up to MAX_WAIT_SECONDS for 03:05 New York, then ~2 requests per ticker
    "Recompute reactions (Intrinio)": 900,          # the first production night recomputes every row; afterwards only new rows and corrected windows
    "Chain parity (both sources)": 1200,             # two chains and the close per ticker, read from the database
    "ATM IV (solver)": 1200,                        # batched: ~60 round trips for 510 tickers; the backstop covers a slow database link
    "Warm options reads": 3600,
}


def _record_step_success(label: str) -> None:
    """Write step:<label>:last_success to system_metadata."""
    try:
        now_iso = datetime.now(timezone.utc).isoformat()
        _db_upsert(f"step:{label}:last_success", now_iso)
    except Exception as exc:
        print(f"  [WARN] Failed to write step stamp for {label}: {redact(exc)}")


STDERR_EXCERPT_LINES = 3


def _stderr_excerpt(stderr_text: str | None) -> tuple[str | None, str | None]:
    """(head, tail): the first and last STDERR_EXCERPT_LINES non-empty lines of a step's stderr.

    A Python traceback puts the exception class and message on its last
    line, so the tail is what names a failure; the head says where it began.
    The tail is None when the head already holds every line.
    """
    if not stderr_text:
        return None, None
    lines = [redact(l) for l in stderr_text.strip().splitlines() if l.strip()]
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
        elif "stderr_head" in existing:
            del existing["stderr_head"]      # nor an older run's head (Auto-pick kept Oct 6's FDX traceback head through clean runs)
        if stderr_tail:
            existing["stderr_tail"] = stderr_tail
        elif "stderr_tail" in existing:
            del existing["stderr_tail"]      # a short or clean run must not keep an older run's tail
        outcomes[label] = existing
        _db_upsert("step_outcomes", json.dumps(outcomes))
    except Exception as exc:
        print(f"  [WARN] Failed to write step outcome for {label}: {redact(exc)}")


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
        _alert_step_failure(label, -1, elapsed, stderr_tail or stderr_head)
        return False
    elapsed = time.monotonic() - t0
    ok = result.returncode == 0
    status = "PASS" if ok else "FAIL"
    print(f"\n  [{status}] {label} (exit {result.returncode}, {elapsed:.0f}s)")
    _record_step_outcome(label, exit_code=result.returncode, seconds=elapsed,
                         stderr_head=stderr_head, stderr_tail=stderr_tail)
    if ok:
        _record_step_success(label)
    else:
        _alert_step_failure(label, result.returncode, elapsed, stderr_tail or stderr_head)
    return ok


def _alert_step_failure(label: str, exit_code: int, seconds: float, tail: str | None) -> None:
    """One ntfy message per failed or timed-out step (services/notify)."""
    try:
        from app.services.notify import PRIORITY_HIGH, notify_sync, step_failure_message
        title, body = step_failure_message(label, exit_code, seconds, tail)
        notify_sync(title, body, PRIORITY_HIGH, ("warning",))
    except Exception as exc:
        print(f"  [WARN] could not send the step-failure alert: {redact(exc)}")


def _record_run(fields: dict) -> None:
    """Merge the run's own fields into step_outcomes under RUN_LABEL."""
    try:
        raw = _db_get("step_outcomes")
        outcomes = json.loads(raw) if raw else {}
        entry = dict(outcomes.get(RUN_LABEL) or {})
        entry.update(fields)
        outcomes[RUN_LABEL] = entry
        _db_upsert("step_outcomes", json.dumps(outcomes))
    except Exception as exc:
        print(f"  [WARN] could not record the run: {redact(exc)}")


def _record_refresh() -> None:
    now_iso = datetime.now(timezone.utc).isoformat()
    _db_upsert("last_refreshed_at", now_iso)
    print(f"\n  Recorded last_refreshed_at = {now_iso}")


JUDGE_STEPS = {"Validate data"}      # validate judges the data; it is not a data step, and its errors are reported on their own


def should_record_refresh(results: list[tuple[str, bool]]) -> bool:
    """last_refreshed_at is written only when every data step (every step but the judges) exited 0."""
    return all(ok for label, ok in results if label not in JUDGE_STEPS)


def digest_fields(results: list[tuple[str, bool]], outcomes: dict, now: datetime) -> tuple[str, str]:
    """The morning digest's title and body from this run's results and the stored outcomes."""
    from app.services.dataset_freshness import courier_summary
    from app.services.notify import digest_message
    failed = [label for label, ok in results if not ok]
    validate = outcomes.get("Validate data") or {}
    figures = validate.get("figures") or {}
    closer = outcomes.get("Close expired alert picks") or {}
    calendar = outcomes.get("Refresh earnings calendar (Finnhub)") or {}
    from app.services.notify import feed_spotcheck_active
    feed_confs = calendar.get("feed_confirmations") if feed_spotcheck_active(calendar.get("feed_spotcheck_started"), now.date()) else None
    release = outcomes.get("Release EPS (8-K exhibits)") or {}
    return digest_message(now.strftime("%Y-%m-%d"), sum(1 for _, ok in results if ok), len(results), failed, validate,
                          figures.get("chain_coverage_pct"), courier_summary(outcomes, now), closer.get("auto_voided") or None, feed_confs or None,
                          release.get("yoy_warnings") or None, validate.get("hidden") or None, release.get("disagreements") or None)


RUN_LABEL = "Nightly run"                  # the pseudo-step whose outcome tells the story of the run itself


def slot_progress_key(slot: str) -> str:
    return f"slot_progress:{slot}"


def steps_to_run(steps: list[tuple[str, list[str]]], done: dict) -> list[tuple[str, list[str]]]:
    """Pure: the steps a resumed run still has to do, from the first one the slot has no completion stamp for.
    A step after an incomplete one runs even if it has a stamp, so the order of effects holds."""
    out = []
    pending = False
    for label, cmd in steps:
        if pending or label not in done:
            pending = True
            out.append((label, cmd))
    return out


def main(slot: str | None = None) -> int:
    """Run the pipeline. With a slot (the loop's nightly), each step's completion is stamped under the slot, a run
    that a restart interrupted resumes from the first incomplete step, and the interruption is logged in the outcome."""
    print(f"\n{'=' * 60}")
    print("  DATA REFRESH PIPELINE")
    print(f"  Started: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}" + (f"  slot {slot}" if slot else "  (boot refresh, no slot)"))
    print(f"{'=' * 60}")

    done: dict = {}
    if slot:
        try:
            done = json.loads(_db_get(slot_progress_key(slot)) or "{}")
        except (TypeError, ValueError):
            done = {}
    todo = steps_to_run(STEPS, done) if slot else list(STEPS)
    todo_labels = {label for label, _ in todo}
    results: list[tuple[str, bool]] = [(label, True) for label, _ in STEPS if label not in todo_labels]   # done before the restart
    run_fields = {"slot": slot, "started_at": datetime.now(timezone.utc).isoformat(), "steps_total": len(STEPS), "steps_skipped_done": len(STEPS) - len(todo)}
    if slot and done:
        run_fields.update({"interrupted": True, "resumed_at": run_fields["started_at"], "resumed_from": todo[0][0] if todo else None,
                           "note": "a process restart (a deploy, or a crash) cut the previous run; resumed from the first incomplete step"})
        print(f"  Resuming slot {slot}: {len(done)} step(s) already done, resuming from {todo[0][0] if todo else 'nothing'}")
    _record_run(run_fields)
    for label, cmd in todo:
        ok = _run_step(label, cmd)
        results.append((label, ok))
        if slot and ok:
            done[label] = datetime.now(timezone.utc).isoformat()
            try:
                _db_upsert(slot_progress_key(slot), json.dumps(done))
            except Exception as exc:
                print(f"  [WARN] could not stamp {label} for slot {slot}: {redact(exc)}")
    by_label = dict(results)
    results = [(label, by_label.get(label, True)) for label, _ in STEPS]

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

    # last_refreshed_at means "every data step exited 0 tonight"; per-dataset ages live in /health (dataset_freshness).
    try:
        if should_record_refresh(results):
            _record_refresh()
        else:
            print("\n  last_refreshed_at not written: a data step failed (see /health datasets and step_outcomes)")
    except Exception:
        pass

    # the morning digest
    try:
        from app.services.notify import notify_sync
        raw = _db_get("step_outcomes")
        title, body = digest_fields(results, json.loads(raw) if raw else {}, datetime.now(timezone.utc))
        print(f"  {title}: {body}")
        notify_sync(title, body, tags=("sunrise",))
    except Exception as exc:
        print(f"  [WARN] could not send the digest: {redact(exc)}")

    _record_run({"finished_at": datetime.now(timezone.utc).isoformat(), "all_passed": all_passed, "interrupted": False})
    if all_passed:
        print("\n  Refresh complete.\n")
        return 0
    else:
        print("\n  Refresh completed with failures (see above). last_refreshed_at updated.\n")
        return 1


if __name__ == "__main__":
    sys.exit(main(next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--slot=")), None)))
