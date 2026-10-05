"""Nightly, right after the earnings calendar refresh: reported EPS and the estimate onto each earnings event of the
last LOOKBACK_SESSIONS sessions, from Finnhub's earnings calendar (one call for the range), Yahoo's earnings_dates
as the second source where Finnhub has nothing. A value already stored is never overwritten unless it was null.

    python -m app.scripts.seed_eps_actuals
    python -m app.scripts.seed_eps_actuals --since 2026-09-01     # a one-time backfill of older events validate warns about
"""
from __future__ import annotations

import asyncio
import math
import sys
from datetime import date, datetime, timezone

from sqlalchemy import select, text

from app.database import ScriptSessionLocal
from app.models.enums import EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.services.eps_actuals import LOOKBACK_SESSIONS, fill_plan, match_row, sessions_back
from app.services.finnhub_client import FinnhubClient
from app.services.step_outcomes import record_step_fields

STEP_LABEL = "EPS actuals (Finnhub)"


def _num(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def finnhub_rows(entries: list[dict]) -> dict[str, dict[date, tuple[float | None, float | None]]]:
    """{symbol: {date: (actual, estimate)}} from the calendar payload; rows without an actual are kept for their estimate."""
    out: dict[str, dict[date, tuple[float | None, float | None]]] = {}
    for e in entries or []:
        try:
            d = date.fromisoformat(str(e.get("date"))[:10])
        except (TypeError, ValueError):
            continue
        sym = (e.get("symbol") or "").upper()
        if sym:
            out.setdefault(sym, {})[d] = (_num(e.get("epsActual")), _num(e.get("epsEstimate")))
    return out


def yfinance_rows(symbol: str) -> dict[date, tuple[float | None, float | None]]:
    """Sync: {date: (reported EPS, estimate)} from Yahoo's earnings_dates; empty when nothing came back."""
    try:
        import yfinance as yf
        df = yf.Ticker(symbol).get_earnings_dates(limit=12)
    except Exception:
        return {}
    out: dict[date, tuple[float | None, float | None]] = {}
    if df is None or df.empty:
        return out
    for ts, row in df.iterrows():
        try:
            out[ts.date()] = (_num(row.get("Reported EPS")), _num(row.get("EPS Estimate")))
        except Exception:
            continue
    return out


def since_arg(argv: list[str]) -> date | None:
    """--since YYYY-MM-DD, else None (the nightly's LOOKBACK_SESSIONS window)."""
    for i, a in enumerate(argv):
        if a.startswith("--since="):
            return date.fromisoformat(a.split("=", 1)[1])
        if a == "--since" and i + 1 < len(argv):
            return date.fromisoformat(argv[i + 1])
    return None


async def run(today: date | None = None, since: date | None = None) -> int:
    today = today or date.today()
    start = since or sessions_back(today, LOOKBACK_SESSIONS)
    now = datetime.now(timezone.utc)
    async with ScriptSessionLocal() as s:
        events = (await s.execute(
            select(Event, Ticker.symbol).join(Ticker, Ticker.id == Event.ticker_id)
            .where(Event.event_type == EventType.EARNINGS, Event.event_date >= start, Event.event_date <= today, Ticker.is_active)
            .order_by(Event.event_date))).all()
        due = [(e, sym) for e, sym in events if e.eps_actual is None or e.eps_estimate is None]
        print(f"{STEP_LABEL}: {len(events)} earnings event(s) since {start}, {len(due)} still missing EPS", flush=True)
        filled: dict[str, list[str]] = {"finnhub": [], "yfinance": []}
        missing: list[str] = []
        error: str | None = None
        by_symbol: dict[str, dict[date, tuple]] = {}
        if due:
            client = FinnhubClient()
            try:
                from datetime import timedelta
                cursor = start
                entries: list[dict] = []
                while cursor <= today:
                    stop = min(cursor + timedelta(days=89), today)
                    payload = await client.get_earnings_calendar(cursor.isoformat(), stop.isoformat())
                    entries += payload.get("earningsCalendar") or []
                    cursor = stop + timedelta(days=1)
                by_symbol = finnhub_rows(entries)
            except Exception as exc:
                error = f"finnhub calendar: {exc}"
                print(f"  [WARN] {error}", flush=True)
            finally:
                await client.close()
        yf_cache: dict[str, dict] = {}
        for e, sym in due:
            got = match_row(e.event_date, by_symbol.get(sym, {}))
            source = "finnhub"
            if got is None or got[0] is None:
                if sym not in yf_cache:
                    yf_cache[sym] = await asyncio.to_thread(yfinance_rows, sym)
                alt = match_row(e.event_date, yf_cache[sym])
                if alt is not None and (got is None or alt[0] is not None):
                    got, source = alt, "yfinance"
            if got is None:
                missing.append(f"{sym} {e.event_date.isoformat()}")
                continue
            plan = fill_plan(e.eps_actual, e.eps_estimate, got[0], got[1], source, now)
            if not plan:
                missing.append(f"{sym} {e.event_date.isoformat()}")
                continue
            for k, v in plan.items():
                setattr(e, k, v)
            filled[source].append(f"{sym} {e.event_date.isoformat()}")
            print(f"  {sym} {e.event_date}: {plan.get('eps_actual', 'kept')} vs {plan.get('eps_estimate', 'kept')} ({source})", flush=True)
        await s.commit()
    await record_step_fields(STEP_LABEL, {"since": start.isoformat(), "events": len(events), "due": len(due), "filled_finnhub": filled["finnhub"],
                                          "filled_yfinance": filled["yfinance"], "still_missing": missing[:60], "error": error})
    return 1 if error and not (filled["finnhub"] or filled["yfinance"]) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(since=since_arg(sys.argv[1:]))))
