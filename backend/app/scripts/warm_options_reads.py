"""Warm the options-read cache for all active tickers.

Hits the running backend over HTTP with the admin token, triggering
generation for any ticker without a cached read for today.  Tickers
with a fresh cache hit are skipped automatically by the endpoint.

Uses claude-sonnet-4-6 (~$0.005/ticker).  509 tickers ≈ $2.70 total.

CLI
---
    ADMIN_TOKEN=xxx python -m app.scripts.warm_options_reads --base-url https://your-app.up.railway.app
    ADMIN_TOKEN=xxx python -m app.scripts.warm_options_reads --base-url https://your-app.up.railway.app --symbol MU
    ADMIN_TOKEN=xxx python -m app.scripts.warm_options_reads --base-url https://your-app.up.railway.app --limit 10
"""

from __future__ import annotations

import argparse
import os
import sys
import time

import httpx


TIMEOUT = 120.0          # single request timeout (generation can be slow)
INTER_TICKER_DELAY = 1.0 # seconds between requests


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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Warm the options-read cache for all active tickers"
    )
    parser.add_argument("--base-url", required=True,
                        help="Backend URL (e.g. https://your-app.up.railway.app)")
    parser.add_argument("--symbol", default=None,
                        help="Warm a single ticker (e.g. MU)")
    parser.add_argument("--limit", type=int, default=None, metavar="N",
                        help="Cap at N tickers (for testing)")
    args = parser.parse_args()

    token = os.environ.get("ADMIN_TOKEN", "")
    if not token:
        print("ERROR: ADMIN_TOKEN env var is required.", file=sys.stderr)
        return 1

    base = args.base_url.rstrip("/")
    client = httpx.Client()

    # Build ticker list
    if args.symbol:
        symbols = [args.symbol.upper()]
    else:
        print(f"Fetching active tickers from {base} ...", flush=True)
        symbols = _get_active_symbols(client, base)
        if args.limit:
            symbols = symbols[:args.limit]

    print(f"Warming options-read cache for {len(symbols)} tickers on {base}")
    print(f"{'─' * 70}", flush=True)

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
            print(f"  [{i+1}/{len(symbols)}] {sym:<6} generated  ({elapsed:.1f}s)", flush=True)
        elif tag == "cached":
            cached += 1
            print(f"  [{i+1}/{len(symbols)}] {sym:<6} cached     ({elapsed:.1f}s)", flush=True)
        elif tag == "failed":
            failed += 1
            failed_list.append(sym)
            print(f"  [{i+1}/{len(symbols)}] {sym:<6} FAILED     ({elapsed:.1f}s) {result['error']}", flush=True)
        else:
            print(f"  [{i+1}/{len(symbols)}] {sym:<6} {tag:<10} ({elapsed:.1f}s)", flush=True)

        if i < len(symbols) - 1:
            time.sleep(INTER_TICKER_DELAY)

    client.close()

    print(f"\n{'═' * 70}")
    print(f"  Generated: {generated}  |  Cached (skipped): {cached}  |  Failed: {failed}")
    if failed_list:
        print(f"  Failed: {', '.join(failed_list)}")
    print(f"{'═' * 70}")

    return 1 if failed > 10 else 0


if __name__ == "__main__":
    sys.exit(main())
