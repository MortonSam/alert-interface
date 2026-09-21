"""Audit stored reactions whose window crosses a gap in the ticker's price history.

Report only: never writes. For every active ticker, fetch history once, compare
its bars to SPY's sessions, and list each stored reaction row (earnings, FOMC,
analyst) whose 1d/3d/5d window includes a session the ticker has no bar for, or
a zero-volume bar. Stored values are printed beside what the session-validated
computation gives now.

Usage:
    python -m app.scripts.audit_reaction_windows [TICKER ...]
"""
from __future__ import annotations

import asyncio
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import numpy as np
import yfinance as yf
from sqlalchemy import text

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.scripts.compute_analyst_reactions import _compute_pre_market
from app.scripts.seed_historical_reactions import (
    LOOKBACK_YEARS,
    _build_date_cache,
    _compute,
    _compute_v3,
    _fetch_price_history,
    _session_on_or_after,
    _zero_volume,
    load_reference_sessions,
)

FETCH_WORKERS = 4


def _fetch(symbol: str):
    lookback = date.today() - timedelta(days=LOOKBACK_YEARS * 366)
    try:
        return symbol, _fetch_price_history(yf.Ticker(symbol), lookback), None
    except Exception as exc:  # report and move on; this is an audit
        return symbol, None, str(exc)


def window_sessions(sessions: np.ndarray, event_type: str, timing: str, event_date: date) -> list[date]:
    """Every session a stored move depends on, base bar through the 5d bar."""
    t = _session_on_or_after(sessions, event_date)
    if t is None:
        return []
    pos = int(np.searchsorted(sessions, t))
    if event_type == "earnings":
        lo, hi = (pos - 1, pos + 4) if timing == "bmo" else (pos, pos + 5)
    elif event_type == "fomc":
        lo, hi = pos, pos + 5
    else:  # analyst_action: baseline is T-1, 5d bar is first session >= event_date + 4d
        t4 = _session_on_or_after(sessions, event_date + timedelta(days=4))
        lo, hi = pos - 1, int(np.searchsorted(sessions, t4)) if t4 is not None else pos
    return [sessions[i] for i in range(max(lo, 0), min(hi, len(sessions) - 1) + 1)]


def _fmt(v) -> str:
    return "NULL" if v is None else f"{float(v):+.4f}"


async def _run(only: list[str]) -> int:
    sessions = load_reference_sessions()
    last_session = sessions[-1]

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(text("""
            SELECT t.symbol, hr.event_type::text AS event_type, hr.event_date, hr.report_timing,
                   hr.pct_change_1d, hr.pct_change_3d, hr.pct_change_5d
            FROM historical_reactions hr
            JOIN tickers t ON t.id = hr.ticker_id
            WHERE t.is_active
              AND hr.event_type IN ('earnings', 'fomc', 'analyst_action')
              AND (hr.pct_change_1d IS NOT NULL OR hr.pct_change_3d IS NOT NULL OR hr.pct_change_5d IS NOT NULL)
            ORDER BY t.symbol, hr.event_date, hr.event_type
        """))).all()

    by_symbol: dict[str, list] = {}
    for r in rows:
        if not only or r.symbol in only:
            by_symbol.setdefault(r.symbol, []).append(r)

    print(f"Reference calendar: SPY, {len(sessions)} sessions {sessions[0]}..{last_session}")
    print(f"Auditing {sum(len(v) for v in by_symbol.values())} stored reaction rows with values "
          f"across {len(by_symbol)} tickers\n")

    flagged: list[str] = []
    per_ticker: dict[str, int] = {}
    per_type: dict[str, int] = {}
    changed = 0
    fetch_failed: list[str] = []
    gap_tickers: dict[str, str] = {}

    with ThreadPoolExecutor(FETCH_WORKERS) as pool:
        for symbol, hist, err in pool.map(_fetch, sorted(by_symbol)):
            if hist is None or hist.empty:
                fetch_failed.append(f"{symbol}: {err or 'empty history'}")
                continue
            dates = _build_date_cache(hist)
            have = set(dates)
            zero = {d for d, v in zip(dates, hist["Volume"]) if _zero_volume(v)}
            in_span = [s for s in sessions if dates[0] <= s <= dates[-1]]
            missing = [s for s in in_span if s not in have]
            tail = [s for s in sessions if s > dates[-1]]
            if missing or zero or len(tail) > 2:
                gap_tickers[symbol] = (f"bars={len(dates)} {dates[0]}..{dates[-1]} missing_inside={len(missing)} "
                                       f"zero_volume_bars={len(zero)} sessions_after_last_bar={len(tail)}")

            for r in by_symbol[symbol]:
                timing = (r.report_timing or "unknown").lower()
                win = window_sessions(sessions, r.event_type, timing, r.event_date)
                bad_missing = [d for d in win if d not in have]
                bad_zero = [d for d in win if d in zero]
                if not bad_missing and not bad_zero:
                    continue

                if r.event_type == "earnings":
                    fixed = _compute_v3(hist, dates, r.event_date, timing, sessions)
                elif r.event_type == "fomc":
                    fixed = _compute(hist, dates, r.event_date, sessions)
                else:
                    fixed = _compute_pre_market(hist, dates, r.event_date, sessions)
                f1 = fixed.get("pct_change_1d") if fixed else None
                f3 = fixed.get("pct_change_3d") if fixed else None
                f5 = fixed.get("pct_change_5d") if fixed else None

                def differs(stored, new) -> bool:
                    if stored is None and new is None:
                        return False
                    if stored is None or new is None:
                        return True
                    return abs(float(stored) - float(new)) > 0.0001

                is_changed = differs(r.pct_change_1d, f1) or differs(r.pct_change_5d, f5) or (
                    r.event_type != "analyst_action" and differs(r.pct_change_3d, f3))
                changed += is_changed
                per_ticker[symbol] = per_ticker.get(symbol, 0) + 1
                per_type[r.event_type] = per_type.get(r.event_type, 0) + 1
                why = []
                if bad_missing:
                    why.append("missing " + ",".join(d.isoformat()[5:] for d in bad_missing[:4])
                               + ("…" if len(bad_missing) > 4 else ""))
                if bad_zero:
                    why.append("zero-vol " + ",".join(d.isoformat()[5:] for d in bad_zero[:4]))
                flagged.append(
                    f"{symbol:<6} {r.event_type:<14} {r.event_date} {timing:<7} "
                    f"stored 1d={_fmt(r.pct_change_1d)} 3d={_fmt(r.pct_change_3d)} 5d={_fmt(r.pct_change_5d)} | "
                    f"fixed 1d={_fmt(f1)} 3d={_fmt(f3)} 5d={_fmt(f5)} | {'; '.join(why)}"
                    + ("" if is_changed else "  [values unchanged]")
                )

    print("── Summary ──")
    print(f"rows whose window crosses a missing session or zero-volume bar: {len(flagged)}")
    print(f"  of which the fixed computation changes a value: {changed}")
    print(f"  by event type: {per_type}")
    print(f"  by ticker: {dict(sorted(per_ticker.items(), key=lambda kv: -kv[1]))}")
    print(f"tickers with any gap in fetched history: {len(gap_tickers)}")
    for sym, desc in sorted(gap_tickers.items()):
        print(f"  {sym}: {desc}")
    if fetch_failed:
        print(f"fetch failures ({len(fetch_failed)}): " + "; ".join(fetch_failed[:10]))
    print("\n── Flagged rows ──")
    for line in flagged:
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run([a.upper() for a in sys.argv[1:]])))
