"""Pre-generate research notes on a hosted backend for demo readiness.

Hits the hosted API over HTTP — does NOT touch the local DB.  Designed to
be re-run the week before a pitch: idempotent, skips fresh notes, and
prints a spend-tracking summary.

CLI
---
    ADMIN_TOKEN=xxx python -m app.scripts.pregen_notes --base-url https://your-app.up.railway.app
    ADMIN_TOKEN=xxx python -m app.scripts.pregen_notes --base-url https://your-app.up.railway.app --tickers AAPL,NVDA
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import httpx

# ── Marquee tickers (edit this list before each pitch) ───────────────────────

MARQUEE_TICKERS = [
    "AAPL", "NVDA", "MSFT", "AMZN", "META", "GOOGL", "TSLA",
    "JPM", "COST", "WMT", "PANW", "NFLX", "AMD", "AVGO", "LLY",
]

# ── Constants ────────────────────────────────────────────────────────────────

GENERATE_TIMEOUT = 180.0  # seconds; generation can take >60s
READ_TIMEOUT = 15.0
INTER_TICKER_DELAY = 3.0  # be kind to the hosted backend
MAX_RETRIES = 1
POLL_INTERVAL = 5.0       # seconds between status polls
MAX_POLLS = 40            # 40 × 5s = 200s max wait


# ── Helpers ──────────────────────────────────────────────────────────────────

def _headers(token: str) -> dict[str, str]:
    return {"Content-Type": "application/json", "X-Admin-Token": token}


def _parse_ts(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


def _age_hours(ts: datetime | None) -> float | None:
    if ts is None:
        return None
    delta = datetime.now(timezone.utc) - ts.replace(tzinfo=timezone.utc)
    return delta.total_seconds() / 3600


def _fetch_existing(client: httpx.Client, base: str, symbol: str) -> dict | None:
    """GET the stored note. Returns parsed JSON or None if 404."""
    r = client.get(f"{base}/api/v1/research-notes", params={"symbol": symbol},
                   timeout=READ_TIMEOUT)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()


def _trigger_generate(client: httpx.Client, base: str, symbol: str, token: str) -> dict:
    """POST to trigger generation. Returns the placeholder note JSON."""
    r = client.post(
        f"{base}/api/v1/research-notes/generate",
        json={"symbol": symbol},
        headers=_headers(token),
        timeout=GENERATE_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()


def _poll_until_done(client: httpx.Client, base: str, symbol: str) -> dict | None:
    """Poll the read endpoint until status is terminal or we time out."""
    for _ in range(MAX_POLLS):
        time.sleep(POLL_INTERVAL)
        note = _fetch_existing(client, base, symbol)
        if note is None:
            return None
        if note.get("status") in ("complete", "failed"):
            return note
    return _fetch_existing(client, base, symbol)


# ── Per-ticker processing ───────────────────────────────────────────────────

def process_ticker(
    client: httpx.Client,
    base: str,
    token: str,
    symbol: str,
    max_age_hours: float,
) -> dict:
    """Process one ticker. Returns a result dict for the summary table."""
    t0 = time.monotonic()
    result = {
        "symbol": symbol,
        "action": "failed",
        "status": "—",
        "elapsed": 0.0,
        "note_ts": "—",
        "verified": False,
    }

    try:
        # Check for existing fresh note
        existing = _fetch_existing(client, base, symbol)
        if existing and existing.get("status") == "complete":
            updated = _parse_ts(existing.get("updated_at"))
            age = _age_hours(updated)
            if age is not None and age < max_age_hours:
                result["action"] = "skipped-fresh"
                result["status"] = existing.get("status", "—")
                result["note_ts"] = (updated.strftime("%Y-%m-%d %H:%M") if updated else "—")
                result["verified"] = existing.get("verification") is not None
                result["elapsed"] = time.monotonic() - t0
                return result

        # Trigger generation
        _trigger_generate(client, base, symbol, token)

        # Poll until complete
        note = _poll_until_done(client, base, symbol)
        if note is None:
            result["action"] = "failed"
            result["status"] = "404 after generate"
            result["elapsed"] = time.monotonic() - t0
            return result

        result["status"] = note.get("status", "—")

        if note.get("status") != "complete":
            result["action"] = "failed"
            result["elapsed"] = time.monotonic() - t0
            return result

        # Verify round-trip: fetch again via the public read path
        readback = _fetch_existing(client, base, symbol)
        if readback and readback.get("status") == "complete":
            result["action"] = "generated"
            updated = _parse_ts(readback.get("updated_at"))
            result["note_ts"] = (updated.strftime("%Y-%m-%d %H:%M") if updated else "—")
            result["verified"] = readback.get("verification") is not None
        else:
            result["action"] = "failed"
            result["status"] = "readback failed"

    except httpx.HTTPStatusError as exc:
        result["action"] = "failed"
        result["status"] = f"HTTP {exc.response.status_code}"
    except Exception as exc:
        result["action"] = "failed"
        result["status"] = str(exc)[:40]

    result["elapsed"] = time.monotonic() - t0
    return result


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pre-generate research notes on hosted backend for demo readiness"
    )
    parser.add_argument("--base-url", required=True,
                        help="Hosted backend URL (e.g. https://your-app.up.railway.app)")
    parser.add_argument("--tickers", default=None,
                        help="Comma-separated ticker list (default: marquee list)")
    parser.add_argument("--max-age-hours", type=float, default=72.0,
                        help="Skip notes fresher than N hours (default: 72)")
    args = parser.parse_args()

    token = os.environ.get("ADMIN_TOKEN", "")
    if not token:
        print("ERROR: ADMIN_TOKEN env var is required.", file=sys.stderr)
        return 1

    base = args.base_url.rstrip("/")
    tickers = [s.strip().upper() for s in args.tickers.split(",")] if args.tickers else MARQUEE_TICKERS

    print(f"Pre-generating research notes on {base}")
    print(f"Tickers: {', '.join(tickers)}")
    print(f"Max age: {args.max_age_hours}h (fresher notes will be skipped)")
    print(f"{'─' * 70}")

    results: list[dict] = []
    client = httpx.Client()

    for i, symbol in enumerate(tickers):
        print(f"\n[{i + 1}/{len(tickers)}] {symbol} ...", end=" ", flush=True)

        result = process_ticker(client, base, token, symbol, args.max_age_hours)

        # One retry on failure
        if result["action"] == "failed":
            print("retrying ...", end=" ", flush=True)
            time.sleep(INTER_TICKER_DELAY)
            result = process_ticker(client, base, token, symbol, args.max_age_hours)

        print(f"{result['action']} ({result['elapsed']:.1f}s)")
        results.append(result)

        if i < len(tickers) - 1:
            time.sleep(INTER_TICKER_DELAY)

    client.close()

    # Summary table
    generated = sum(1 for r in results if r["action"] == "generated")
    skipped = sum(1 for r in results if r["action"] == "skipped-fresh")
    failed = sum(1 for r in results if r["action"] == "failed")

    print(f"\n{'═' * 70}")
    print(f"  {'Ticker':<8} {'Action':<16} {'Status':<12} {'Verified':<10} {'Time':>6}  {'Note Timestamp'}")
    print(f"  {'─' * 8} {'─' * 16} {'─' * 12} {'─' * 10} {'─' * 6}  {'─' * 16}")
    for r in results:
        ver = "✓" if r["verified"] else "—"
        print(f"  {r['symbol']:<8} {r['action']:<16} {r['status']:<12} {ver:<10} {r['elapsed']:>5.1f}s  {r['note_ts']}")

    print(f"{'═' * 70}")
    print(f"  Generated: {generated}  |  Skipped (fresh): {skipped}  |  Failed: {failed}")
    print(f"  Generations performed: {generated}  (spend proxy)")
    print(f"{'═' * 70}")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
