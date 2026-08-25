"""Fetch options chains from a residential IP and push to the hosted backend.

yfinance works reliably from residential IPs but may return stale/empty
data from datacenter IPs (Yahoo rate-limits or blocks them).  This script
bridges the gap: run it from your laptop before drafting to ensure the
hosted backend has fresh chain data.

CLI
---
    ADMIN_TOKEN=xxx python -m app.scripts.chain_courier --base-url https://your-app.up.railway.app
    ADMIN_TOKEN=xxx python -m app.scripts.chain_courier --base-url https://your-app.up.railway.app --tickers AAPL,NKE,NVDA
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta

import httpx
import yfinance as yf

# ── Marquee tickers (edit before each pitch) ──────────────────────────────────

MARQUEE_TICKERS = [
    # Core holdings
    "AAPL", "NVDA", "MSFT", "AMZN", "META", "GOOGL", "TSLA",
    "JPM", "COST", "WMT", "PANW", "NFLX", "AMD", "AVGO", "LLY",
    # Earnings Aug-Oct 2026 (by market cap)
    "ORCL", "DELL", "MRVL", "PEP", "CRWD", "MDT", "ACN", "ADBE",
    "INTU", "CTAS", "SNPS", "HPE", "NKE", "ADSK", "CIEN", "WDAY",
    "PAYX", "A", "VEEV", "NTAP", "CCL", "JBL", "CASY", "CPRT",
    "WSM", "DG", "DLTR", "DRI", "STZ", "ULTA",
]

# ── Constants ─────────────────────────────────────────────────────────────────

POST_TIMEOUT = httpx.Timeout(connect=15.0, read=60.0, write=60.0, pool=15.0)
INTER_TICKER_DELAY = 2.0
RETRY_DELAY = 5.0
MIN_DAYS_OUT = 14  # pick expiration at least this many days out


# ── Helpers ───────────────────────────────────────────────────────────────────

def _headers(token: str) -> dict[str, str]:
    return {"Content-Type": "application/json", "X-Admin-Token": token}


def _parse_option_df(df) -> list[dict]:
    """Mirror of the backend _parse_option_df — keep shapes identical."""
    import pandas as pd

    rows = []
    for _, row in df.iterrows():
        iv_raw = row["impliedVolatility"]
        iv = None if pd.isna(iv_raw) else (float(iv_raw) if 0 < float(iv_raw) <= 3.0 else None)
        vol_raw = row["volume"]
        vol = None if pd.isna(vol_raw) else int(vol_raw)
        oi_raw = row["openInterest"]
        oi = None if pd.isna(oi_raw) else int(oi_raw)
        def _f(v): return None if pd.isna(v) else float(v)
        rows.append({
            "strike": float(row["strike"]),
            "bid": _f(row["bid"]), "ask": _f(row["ask"]),
            "lastPrice": _f(row["lastPrice"]),
            "volume": vol, "openInterest": oi, "impliedVolatility": iv,
        })
    return rows


def _fetch_chain(symbol: str, expiration: str) -> dict:
    """Fetch one chain with retry, matching backend get_option_chain shape."""
    import pandas as pd

    empty: dict = {"calls": [], "puts": [], "expiration": expiration, "chain_last_trade": None}
    for attempt in range(3):
        try:
            chain = yf.Ticker(symbol).option_chain(expiration)
            calls = _parse_option_df(chain.calls)
            puts = _parse_option_df(chain.puts)
            if calls or puts:
                chain_last_trade = None
                for df in (chain.calls, chain.puts):
                    if "lastTradeDate" in df.columns and not df.empty:
                        max_dt = df["lastTradeDate"].dropna().max()
                        if pd.notna(max_dt):
                            dt = pd.Timestamp(max_dt).date()
                            if chain_last_trade is None or dt > chain_last_trade:
                                chain_last_trade = dt
                return {
                    "calls": calls, "puts": puts, "expiration": expiration,
                    "chain_last_trade": chain_last_trade.isoformat() if chain_last_trade else None,
                }
        except Exception:
            pass
        if attempt < 2:
            time.sleep(1.5 * (attempt + 1))
    return empty


def _get_next_earnings(symbol: str, base_url: str) -> date | None:
    """Fetch next earnings date from our backend, fall back to yfinance calendar."""
    today = date.today()

    # Primary: our backend
    try:
        r = httpx.get(f"{base_url}/api/v1/tickers/by-symbol/{symbol}", timeout=10.0)
        if r.status_code == 200:
            ned = r.json().get("next_earnings_date")
            if ned:
                earnings_date = date.fromisoformat(ned)
                if earnings_date >= today:
                    return earnings_date
    except Exception:
        pass

    # Fallback: yfinance calendar
    try:
        cal = yf.Ticker(symbol).calendar
        if cal is not None:
            if isinstance(cal, dict):
                ed = cal.get("Earnings Date")
                if isinstance(ed, list) and ed:
                    ed = ed[0]
            else:
                ed = cal.iloc[0, 0] if hasattr(cal, "iloc") and cal.size > 0 else None
            if ed is not None:
                if isinstance(ed, date) and not isinstance(ed, datetime):
                    earnings_date = ed
                elif isinstance(ed, str):
                    earnings_date = date.fromisoformat(ed)
                elif hasattr(ed, "date"):
                    import pandas as pd
                    earnings_date = pd.Timestamp(ed).date()
                else:
                    return None
                if earnings_date >= today:
                    return earnings_date
    except Exception:
        pass

    return None


def _pick_expirations(symbol: str, base_url: str) -> tuple[list[str], str | None]:
    """Return (distinct expirations to fetch, next_earnings_str | None).

    Two targets:
      (a) base_exp  — nearest chain expiry ≥ today + 14 days
      (b) earn_exp  — nearest chain expiry ≥ next earnings + 14 days (if earnings known)
    Returns deduplicated list (1 or 2 items) and the earnings date string.
    """
    try:
        exps = list(yf.Ticker(symbol).options)
    except Exception:
        return [], None
    if not exps:
        return [], None

    today = date.today()
    base_cutoff = (today + timedelta(days=MIN_DAYS_OUT)).isoformat()
    base_exp = next((e for e in exps if e >= base_cutoff), exps[-1])

    earnings_str: str | None = None
    earn_exp: str | None = None
    earnings_date = _get_next_earnings(symbol, base_url)
    if earnings_date:
        earnings_str = earnings_date.isoformat()
        earn_cutoff = (earnings_date + timedelta(days=14)).isoformat()
        earn_exp = next((e for e in exps if e >= earn_cutoff), exps[-1])
        print(f"  {symbol} earnings={earnings_str} → earn_exp={earn_exp}")

    targets = [base_exp]
    if earn_exp and earn_exp != base_exp:
        targets.append(earn_exp)
    return targets, earnings_str


# ── Per-ticker processing ────────────────────────────────────────────────────

def process_ticker(
    client: httpx.Client,
    base: str,
    token: str,
    symbol: str,
) -> dict:
    """Fetch chain(s) locally and push to the hosted ingest endpoint.

    Computes two target expirations (base ≥ today+14d, earnings ≥ earnings+14d)
    and pushes a chain for each distinct one.
    """
    t0 = time.monotonic()
    result = {
        "symbol": symbol,
        "action": "failed",
        "strikes": 0,
        "chain_last_trade": "—",
        "base_exp": "—",
        "earn_exp": "—",
        "elapsed": 0.0,
    }

    try:
        target_exps, earnings_str = _pick_expirations(symbol, base)
        if not target_exps:
            result["action"] = "no-expirations"
            result["elapsed"] = time.monotonic() - t0
            return result

        result["base_exp"] = target_exps[0]
        if len(target_exps) > 1:
            result["earn_exp"] = target_exps[1]
        elif earnings_str:
            result["earn_exp"] = target_exps[0]  # coincides with base

        # ── After-hours guard (check once using first chain) ─────────────
        try:
            spot = yf.Ticker(symbol).fast_info["lastPrice"]
        except Exception:
            spot = None

        chains_to_push: list[dict] = []
        total_strikes = 0

        for exp in target_exps:
            chain = _fetch_chain(symbol, exp)
            quality = [c for c in chain.get("calls", [])
                       if (c.get("bid") or 0) > 0 or (c.get("ask") or 0) > 0]
            total_strikes += len(quality)
            if not chain.get("chain_last_trade"):
                result["chain_last_trade"] = "—"
            else:
                result["chain_last_trade"] = chain["chain_last_trade"]

            if not quality:
                continue

            # After-hours guard per chain
            if spot and spot > 0:
                near_atm = [c for c in chain.get("calls", [])
                            if abs(c["strike"] - spot) / spot <= 0.15]
                if near_atm:
                    zero_bids = sum(1 for c in near_atm if not c.get("bid"))
                    if zero_bids > len(near_atm) / 2:
                        result["action"] = "after-hours, skipped"
                        result["strikes"] = total_strikes
                        result["elapsed"] = time.monotonic() - t0
                        return result

            chains_to_push.append({
                "symbol": symbol,
                "expiration": exp,
                "calls": chain["calls"],
                "puts": chain["puts"],
                "chain_last_trade": chain.get("chain_last_trade"),
            })

        result["strikes"] = total_strikes
        if not chains_to_push:
            result["action"] = "empty-chain"
            result["elapsed"] = time.monotonic() - t0
            return result

        # Push all chains in one request
        payload = {"chains": chains_to_push}
        r = client.post(
            f"{base}/api/v1/admin/ingest-options-chains",
            json=payload,
            headers=_headers(token),
            timeout=POST_TIMEOUT,
        )
        r.raise_for_status()
        n = len(chains_to_push)
        result["action"] = f"pushed({n})" if n > 1 else "pushed"

    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:120] if exc.response else ""
        result["action"] = f"HTTP {exc.response.status_code}: {body}"[:60]
    except Exception as exc:
        result["action"] = str(exc)[:60]

    result["elapsed"] = time.monotonic() - t0
    return result


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch options chains locally and push to hosted backend"
    )
    parser.add_argument("--base-url", required=True,
                        help="Hosted backend URL (e.g. https://your-app.up.railway.app)")
    parser.add_argument("--tickers", default=None,
                        help="Comma-separated ticker list (default: marquee list)")
    args = parser.parse_args()

    token = os.environ.get("ADMIN_TOKEN", "")
    if not token:
        print("ERROR: ADMIN_TOKEN env var is required.", file=sys.stderr)
        return 1

    base = args.base_url.rstrip("/")
    tickers = [s.strip().upper() for s in args.tickers.split(",")] if args.tickers else MARQUEE_TICKERS

    print(f"Chain courier → {base}")
    print(f"Tickers: {', '.join(tickers)}")
    print(f"{'─' * 70}")

    results: list[dict] = []
    client = httpx.Client()

    for i, symbol in enumerate(tickers):
        print(f"[{i + 1}/{len(tickers)}] {symbol} ...", end=" ", flush=True)

        result = process_ticker(client, base, token, symbol)

        # One retry on transport / server errors
        non_retry = ("pushed", "empty-chain", "no-expirations", "after-hours, skipped")
        if result["action"] not in non_retry and not result["action"].startswith("pushed("):
            print(f"({result['action']}) retrying ...", end=" ", flush=True)
            time.sleep(RETRY_DELAY)
            result = process_ticker(client, base, token, symbol)

        print(f"{result['action']} ({result['strikes']} strikes, {result['elapsed']:.1f}s)")
        results.append(result)

        if i < len(tickers) - 1:
            time.sleep(INTER_TICKER_DELAY)

    client.close()

    # Summary table
    pushed = sum(1 for r in results if r["action"].startswith("pushed"))
    failed = sum(1 for r in results if not r["action"].startswith("pushed"))

    print(f"\n{'═' * 90}")
    print(f"  {'Ticker':<8} {'Action':<20} {'Strikes':>8} {'Base Exp':<12} {'Earn Exp':<12} {'Last Trade':<12} {'Time':>6}")
    print(f"  {'─' * 8} {'─' * 20} {'─' * 8} {'─' * 12} {'─' * 12} {'─' * 12} {'─' * 6}")
    for r in results:
        print(
            f"  {r['symbol']:<8} {r['action']:<20} {r['strikes']:>8} "
            f"{r.get('base_exp', '—'):<12} {r.get('earn_exp', '—'):<12} "
            f"{r['chain_last_trade']:<12} {r['elapsed']:>5.1f}s"
        )

    print(f"{'═' * 90}")
    print(f"  Pushed: {pushed}  |  Failed: {failed}")
    print(f"{'═' * 90}")

    return 1 if failed > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
