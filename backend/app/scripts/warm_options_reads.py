"""Warm the options-read cache for all active tickers.

Hits the running backend over HTTP with the admin token, triggering
generation for any ticker without a cached read for the current chain
snapshot date.  Tickers with a fresh cache hit are skipped automatically.

Uses claude-sonnet-4-6 (~$0.005/ticker).  509 tickers ~ $2.70 total.

This step must not fail the refresh pipeline.  Always exits 0;
records generated/cached/failed counts and estimated cost in
step_outcomes via system_metadata.  If zero reads are generated
despite active tickers, the outcome is recorded with reason and
exit -2 (soft failure visible in /health but not aborting refresh).

CLI
---
    ADMIN_TOKEN=xxx python -m app.scripts.warm_options_reads --base-url https://your-app.up.railway.app
    ADMIN_TOKEN=xxx python -m app.scripts.warm_options_reads --base-url https://your-app.up.railway.app --symbol MU
    ADMIN_TOKEN=xxx python -m app.scripts.warm_options_reads --base-url https://your-app.up.railway.app --limit 10
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import httpx
import sqlalchemy as sa
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app.config import settings

TIMEOUT = 120.0          # single request timeout (generation can be slow)
INTER_TICKER_DELAY = 1.0 # seconds between requests
COST_PER_GENERATION = 0.005  # estimated Sonnet cost per generated read

# Collects diagnostic messages throughout the run for inclusion in step_outcomes.
_diagnostics: list[str] = []


def _warm_one(
    client: httpx.Client,
    base: str,
    token: str,
    symbol: str,
) -> dict:
    """Hit the options-read endpoint for one ticker. Returns result dict."""
    t0 = time.monotonic()
    try:
        r = client.get(
            f"{base}/api/v1/tickers/options-read/{symbol}",
            headers={"X-Admin-Token": token},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        elapsed = time.monotonic() - t0
        cached = data.get("cached", False)
        model = data.get("model_used", "?")
        return {
            "symbol": symbol,
            "action": "cached" if cached else ("generated" if model != "none" else "skipped"),
            "model": model,
            "elapsed": elapsed,
            "error": None,
        }
    except Exception as exc:
        return {
            "symbol": symbol,
            "action": "failed",
            "model": None,
            "elapsed": time.monotonic() - t0,
            "error": str(exc)[:80],
        }


def _get_active_symbols(client: httpx.Client, base: str) -> list[str]:
    """Fetch active ticker symbols from the backend."""
    r = client.get(f"{base}/api/v1/tickers", params={"active_only": "true"}, timeout=30.0)
    r.raise_for_status()
    tickers = r.json()
    return sorted(t["symbol"] for t in tickers)


def _record_warm_outcome(generated: int, cached: int, failed: int,
                         failed_symbols: list[str], total: int,
                         elapsed: float, *,
                         reason: str | None = None) -> None:
    """Write warm outcome details to step_outcomes in system_metadata.

    exit codes in the outcome:
      0  = normal (some reads generated or all cached)
     -2  = soft failure (zero generated despite active tickers)
    """
    try:
        engine = create_engine(settings.database_url_sync, poolclass=NullPool)
        now = datetime.now(timezone.utc)

        # Read existing outcomes
        stmt = sa.text("SELECT value FROM system_metadata WHERE key = :key")
        with engine.connect() as conn:
            row = conn.execute(stmt, {"key": "step_outcomes"}).first()
        outcomes = json.loads(row[0]) if row else {}

        estimated_cost = round(generated * COST_PER_GENERATION, 2)
        soft_fail = (generated == 0 and total > 0) or reason is not None
        outcome: dict = {
            "exit": -2 if soft_fail else 0,
            "seconds": round(elapsed, 1),
            "at": now.isoformat(),
            "generated": generated,
            "cached": cached,
            "failed": failed,
            "failed_symbols": failed_symbols[:20],  # cap to avoid blob bloat
            "total": total,
            "estimated_cost_usd": estimated_cost,
        }
        if reason:
            outcome["reason"] = reason
        if _diagnostics:
            outcome["stderr"] = _diagnostics[:3]
        outcomes["Warm options reads"] = outcome

        upsert = sa.text(
            "INSERT INTO system_metadata (key, value, updated_at) "
            "VALUES (:key, :value, :now) "
            "ON CONFLICT (key) DO UPDATE SET value = :value, updated_at = :now"
        )
        with engine.connect() as conn:
            conn.execute(upsert, {
                "key": "step_outcomes",
                "value": json.dumps(outcomes),
                "now": now,
            })
            conn.commit()
        engine.dispose()
    except Exception as exc:
        print(f"  [WARN] Failed to write warm outcome: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Warm the options-read cache for all active tickers"
    )
    port = os.environ.get("PORT", "8000")
    parser.add_argument("--base-url", default=None,
                        help=f"Backend URL (default: WARM_BASE_URL env or http://localhost:$PORT [{port}])")
    parser.add_argument("--symbol", default=None,
                        help="Warm a single ticker (e.g. MU)")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Cap at N tickers (for testing)")
    args = parser.parse_args()

    token = os.environ.get("ADMIN_TOKEN", "")
    if not token:
        msg = "ADMIN_TOKEN env var is required"
        print(f"ERROR: {msg}.", file=sys.stderr)
        _diagnostics.append(msg)
        _record_warm_outcome(0, 0, 0, [], 0, 0.0, reason=msg)
        return 0  # never fail the pipeline

    base = (args.base_url or os.environ.get("WARM_BASE_URL", f"http://localhost:{port}")).rstrip("/")
    client = httpx.Client()

    # Build ticker list
    if args.symbol:
        symbols = [args.symbol.upper()]
    else:
        print(f"Fetching active tickers from {base} ...", flush=True)
        try:
            symbols = _get_active_symbols(client, base)
        except Exception as exc:
            msg = f"Could not fetch tickers from {base}: {exc}"
            print(f"  [WARN] {msg}")
            _diagnostics.append(msg)
            _record_warm_outcome(0, 0, 0, [], 0, 0.0, reason=msg)
            return 0  # never fail the pipeline
        if args.limit:
            symbols = symbols[:args.limit]

    total = len(symbols)
    print(f"Warming options-read cache for {total} tickers on {base}")
    print(f"{'─' * 70}", flush=True)

    t_start = time.monotonic()
    generated = 0
    cached = 0
    failed = 0
    failed_list: list[str] = []

    for i, sym in enumerate(symbols):
        result = _warm_one(client, base, token, sym)

        tag = result["action"]
        elapsed = result["elapsed"]

        if tag == "generated":
            generated += 1
            print(f"  [{i+1}/{total}] {sym:<6} generated  ({elapsed:.1f}s)", flush=True)
        elif tag == "cached":
            cached += 1
            print(f"  [{i+1}/{total}] {sym:<6} cached     ({elapsed:.1f}s)", flush=True)
        elif tag == "failed":
            failed += 1
            failed_list.append(sym)
            err_msg = result["error"] or "unknown"
            _diagnostics.append(f"{sym}: {err_msg}")
            print(f"  [{i+1}/{total}] {sym:<6} FAILED     ({elapsed:.1f}s) {err_msg}", flush=True)
        else:
            print(f"  [{i+1}/{total}] {sym:<6} {tag:<10} ({elapsed:.1f}s)", flush=True)

        if i < total - 1:
            time.sleep(INTER_TICKER_DELAY)

    client.close()
    total_elapsed = time.monotonic() - t_start
    estimated_cost = round(generated * COST_PER_GENERATION, 2)

    print(f"\n{'═' * 70}")
    print(f"  Generated: {generated}  |  Cached: {cached}  |  Failed: {failed}  |  Total: {total}")
    print(f"  Estimated Sonnet cost: ${estimated_cost:.2f}")
    if failed_list:
        print(f"  Failed: {', '.join(failed_list[:20])}")
    print(f"  Elapsed: {total_elapsed:.0f}s")
    print(f"{'═' * 70}")

    # Determine reason for zero-generation runs
    reason: str | None = None
    if generated == 0 and total > 0 and cached == 0:
        reason = f"Zero generated and zero cached across {total} tickers; likely connection or auth issue"
    elif generated == 0 and total > 0:
        reason = None  # all cached is normal, not a failure

    # Record detailed outcome in system_metadata
    _record_warm_outcome(generated, cached, failed, failed_list, total, total_elapsed,
                         reason=reason)

    return 0  # never fail the pipeline


if __name__ == "__main__":
    sys.exit(main())
