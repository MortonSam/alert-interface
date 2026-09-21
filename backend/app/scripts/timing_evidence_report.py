"""Collect timing evidence for every earnings reaction. Report only: never writes to the DB.

Per earnings row, three signals about when the report reached the market:
  A  class from the Item 2.02 acceptance stamp read as true UTC
  B  class from the same stamp read as Eastern clock time (stamp mislabeled "Z")
  C  price: |opening gap| on the filing day vs the next session, counted only
     when the larger is at least twice the smaller and at least 1%

Per ticker, whether the raw acceptance clock shifts by an hour between daylight
saving seasons (true UTC) or stays fixed (Eastern mislabeled), plus two
reading-independent checks: EDGAR accepts filings 06:00-22:00 ET only, and a
filing accepted after 17:30 ET gets the next business day's filing date.

Usage:
    python -m app.scripts.timing_evidence_report --out /tmp/timing_evidence.json [--symbols A,B]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta

import numpy as np
import yfinance as yf
from sqlalchemy import select

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.enums import EventType
from app.models.historical_reaction import HistoricalReaction
from app.models.ticker import Ticker
from app.scripts.backfill_report_timing import (
    ET,
    ITEM_202_WINDOW_DAYS,
    _ciks_for,
    _has_earnings_item,
    classify_local,
)
from app.scripts.seed_historical_reactions import (
    LOOKBACK_YEARS,
    _build_date_cache,
    _fetch_price_history,
    _session_offset,
    _session_on_or_after,
    _zero_volume,
    load_reference_sessions,
)
from app.services.edgar_client import EdgarClient

GAP_RATIO = 2.0
GAP_MIN_PCT = 1.0
EDGAR_OPEN, EDGAR_CLOSE = time(6, 0), time(22, 0)
NEXT_DAY_CUTOFF = time(17, 30)


def _parse(at: str) -> tuple[datetime, datetime] | None:
    """(stamp read as true UTC -> ET, stamp read as ET clock), both naive ET."""
    try:
        utc = datetime.fromisoformat(at.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return utc.astimezone(ET).replace(tzinfo=None), utc.replace(tzinfo=None)


def _is_dst(d: date) -> bool:
    return bool(datetime(d.year, d.month, d.day, 12, tzinfo=ET).dst())


def _gap(hist, dates, sessions, day: date) -> float | None:
    """|open(day) / close(prior session) - 1| in percent; None unless both bars exist and traded."""
    prior = _session_offset(sessions, day, -1)
    if prior is None:
        return None
    i, j = np.flatnonzero(dates == day), np.flatnonzero(dates == prior)
    if i.size == 0 or j.size == 0:
        return None
    if _zero_volume(hist["Volume"].iloc[int(i[0])]) or _zero_volume(hist["Volume"].iloc[int(j[0])]):
        return None
    base = float(hist["Close"].iloc[int(j[0])])
    return abs(float(hist["Open"].iloc[int(i[0])]) / base - 1) * 100 if base else None


def price_signal(hist, dates, sessions, filing_session: date, event_session: date) -> tuple[str, float | None, float | None]:
    """Signal C expressed relative to the stored event date."""
    g_f = _gap(hist, dates, sessions, filing_session)
    nxt = _session_offset(sessions, filing_session, 1)
    g_n = _gap(hist, dates, sessions, nxt) if nxt is not None else None
    if g_f is None or g_n is None:
        return "none", g_f, g_n
    hi, lo = max(g_f, g_n), min(g_f, g_n)
    if hi < GAP_MIN_PCT or hi < GAP_RATIO * lo:
        return "none", g_f, g_n
    priced_pre_open = g_f > g_n  # news was in the filing-day open
    offset = int(np.searchsorted(sessions, filing_session) - np.searchsorted(sessions, event_session))
    if offset == 0:
        return ("bmo" if priced_pre_open else "amc"), g_f, g_n
    if offset == 1 and priced_pre_open:
        return "amc", g_f, g_n      # after the event-day close, before the next open
    if offset == -1 and not priced_pre_open:
        return "bmo", g_f, g_n      # after the prior close, before the event-day open
    return "off", g_f, g_n          # priced on a session the stored event date cannot explain


def _fetch_prices(symbol: str):
    lookback = date.today() - timedelta(days=LOOKBACK_YEARS * 366)
    try:
        return symbol, _fetch_price_history(yf.Ticker(symbol), lookback)
    except Exception:
        return symbol, None


def ticker_clock_stats(records: list[dict], since: date) -> dict:
    summer, winter = [], []
    impossible_utc = impossible_et = late_utc = late_et = n = 0
    agents: dict[str, int] = defaultdict(int)
    for r in records:
        if not _has_earnings_item(r["items"]):
            continue
        try:
            fd = date.fromisoformat(r["filing_date"])
        except ValueError:
            continue
        parsed = _parse(r["acceptance"])
        if fd < since or parsed is None:
            continue
        as_utc, as_et = parsed
        n += 1
        agents[r["accession"][:10]] += 1
        raw_minutes = as_et.hour * 60 + as_et.minute
        (summer if _is_dst(fd) else winter).append(raw_minutes)
        impossible_utc += not (EDGAR_OPEN <= as_utc.time() <= EDGAR_CLOSE)
        impossible_et += not (EDGAR_OPEN <= as_et.time() <= EDGAR_CLOSE)
        # accepted after 17:30 ET -> filing date should be a later day
        late_utc += (as_utc.time() > NEXT_DAY_CUTOFF) != (fd > as_utc.date())
        late_et += (as_et.time() > NEXT_DAY_CUTOFF) != (fd > as_et.date())
    shift = None
    if len(summer) >= 3 and len(winter) >= 3:
        shift = statistics.median(winter) - statistics.median(summer)
    return {
        "n_202": n, "n_summer": len(summer), "n_winter": len(winter),
        "median_raw_summer": statistics.median(summer) if summer else None,
        "median_raw_winter": statistics.median(winter) if winter else None,
        "winter_minus_summer_min": shift,
        "impossible_if_utc": impossible_utc, "impossible_if_et": impossible_et,
        "filing_date_conflict_if_utc": late_utc, "filing_date_conflict_if_et": late_et,
        "agents": dict(agents),
    }


async def _run(out_path: str, only: list[str] | None) -> int:
    sessions = load_reference_sessions()
    since = date.today() - timedelta(days=LOOKBACK_YEARS * 366)

    async with AsyncSessionLocal() as session:
        tickers = {t.id: t.symbol for t in (await session.execute(
            select(Ticker).where(Ticker.is_active.is_(True)))).scalars().all()}
        by_sym: dict[str, list] = defaultdict(list)
        for tid, d, timing in (await session.execute(
            select(HistoricalReaction.ticker_id, HistoricalReaction.event_date, HistoricalReaction.report_timing)
            .where(HistoricalReaction.event_type == EventType.EARNINGS)
            .order_by(HistoricalReaction.event_date)
        )).all():
            sym = tickers.get(tid)
            if sym and (not only or sym in only):
                by_sym[sym].append((d, (timing or "unknown").lower()))

    symbols = sorted(by_sym)
    print(f"Collecting evidence for {sum(len(v) for v in by_sym.values())} earnings rows, {len(symbols)} tickers", flush=True)

    with ThreadPoolExecutor(4) as pool:
        prices = dict(pool.map(_fetch_prices, symbols))

    rows_out: list[dict] = []
    tickers_out: dict[str, dict] = {}
    edgar = EdgarClient()
    try:
        for n, sym in enumerate(symbols):
            if n % 50 == 0:
                print(f"  [{n}/{len(symbols)}] {sym}", flush=True)
            records: list[dict] = []
            ciks: list[str] = []
            try:
                ciks = await _ciks_for(sym, edgar)
                for cik in ciks:
                    records.extend(await edgar.get_all_8k_records(cik))
                    await asyncio.sleep(0.12)
            except Exception as exc:
                tickers_out[sym] = {"error": str(exc)}
                continue
            stats = ticker_clock_stats(records, since)
            stats["ciks"] = ciks
            dated = []
            for r in records:
                try:
                    dated.append((date.fromisoformat(r["filing_date"]), r))
                except ValueError:
                    pass
            stats["first_8k"] = min((d for d, _ in dated), default=None)
            stats["first_8k"] = stats["first_8k"].isoformat() if stats["first_8k"] else None
            tickers_out[sym] = stats

            hist = prices.get(sym)
            dates = _build_date_cache(hist) if hist is not None and not hist.empty else None

            for event_date, stored in by_sym[sym]:
                cands = [
                    (fd, r) for fd, r in dated
                    if _has_earnings_item(r["items"]) and abs((fd - event_date).days) <= ITEM_202_WINDOW_DAYS
                ]
                rec = {"symbol": sym, "event_date": event_date.isoformat(), "stored": stored,
                       "A": "none", "B": "none", "C": "none"}
                filing_day = event_date
                if cands:
                    fd, r = min(cands, key=lambda c: (abs((c[0] - event_date).days), c[1]["acceptance"]))
                    parsed = _parse(r["acceptance"])
                    if parsed:
                        as_utc, as_et = parsed
                        rec.update({
                            "filing_date": fd.isoformat(), "raw": r["acceptance"], "items": r["items"],
                            "agent": r["accession"][:10],
                            "A": classify_local(as_utc, event_date), "A_clock": as_utc.strftime("%m-%d %H:%M"),
                            "B": classify_local(as_et, event_date), "B_clock": as_et.strftime("%m-%d %H:%M"),
                        })
                        filing_day = fd
                if dates is not None:
                    f_sess = _session_on_or_after(sessions, filing_day)
                    e_sess = _session_on_or_after(sessions, event_date)
                    if f_sess is not None and e_sess is not None:
                        c, g_f, g_n = price_signal(hist, dates, sessions, f_sess, e_sess)
                        rec.update({"C": c,
                                    "gap_filing_day": round(g_f, 3) if g_f is not None else None,
                                    "gap_next_day": round(g_n, 3) if g_n is not None else None})
                rows_out.append(rec)
    finally:
        await edgar.close()

    with open(out_path, "w") as fh:
        json.dump({"rows": rows_out, "tickers": tickers_out}, fh)
    print(f"Wrote {len(rows_out)} rows, {len(tickers_out)} tickers to {out_path}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols", default=None)
    a = ap.parse_args()
    sys.exit(asyncio.run(_run(a.out, [s.strip().upper() for s in a.symbols.split(",")] if a.symbols else None)))
