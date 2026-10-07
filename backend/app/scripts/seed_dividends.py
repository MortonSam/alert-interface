"""Seed ex-dividend dates from Intrinio's price adjustments into the events table.

By default the dates come from the stored shadow bars (price_bars_shadow.dividend, one query, no requests): a bar
with a cash dividend is an ex-dividend date, and the amount stored is that cash per share (metadata.dividend_amount,
basis per_share). The nightly reads the last WINDOW_DAYS; --full reads Intrinio's adjustments endpoint by security
record (current and predecessors) for all history. Rows are inserted once per (ticker, date); existing rows are
never rewritten.

Intrinio's price adjustments are past adjustments only, and this plan has no dividends endpoint, so the declared
next ex-dividend date (a date, not a price) keeps its yfinance source: the named exception in CLAUDE.md beside the
earnings calendar. Its amount is the declared per-payment dividend: the last payment on the stored Intrinio bars first, yfinance's
lastDividendValue when the bars hold none; never the annualized dividendRate.

CLI
---
    python -m app.scripts.seed_dividends                # nightly: the last WINDOW_DAYS from the stored bars
    python -m app.scripts.seed_dividends --full         # every stored bar, then the adjustments endpoint for every record
    python -m app.scripts.seed_dividends --limit 5
"""
from __future__ import annotations
from app.services.redact import redact

import argparse
import asyncio
import sys
from datetime import date, timedelta

from sqlalchemy import select, text

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.enums import DataSource, EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.services.corporate_actions import dividends_from_adjustments
from app.services.intrinio_client import IntrinioClient

WINDOW_DAYS = 14          # the nightly looks this far back on the bars; the ex-date is on the bar, so a few days of slack is plenty
DIVIDEND_BASIS = "per_share"
FORWARD_BASIS_INTRINIO = "last_payment_intrinio"   # the last per-payment dividend on the stored Intrinio bars
FORWARD_BASIS_YFINANCE = "last_payment_yfinance"   # yfinance's lastDividendValue (the last declared payment) when the bars hold none
PER_PAYMENT_BASES = ("per_share", FORWARD_BASIS_INTRINIO, FORWARD_BASIS_YFINANCE)   # amounts a page may call a per-share dividend
FORWARD_BASIS_UNKNOWN = "unknown"                 # a stored forward date whose amount no source confirms: the date stays, the amount is shown from nothing
FORWARD_BASIS = FORWARD_BASIS_YFINANCE
FORWARD_BATCH = 5
FORWARD_BATCH_SLEEP = 2.0


def _fetch_forward_sync(symbol: str) -> dict | None:
    """The declared next ex-dividend date from yfinance (the named exception: a date, not a price), with the annual rate."""
    import yfinance as yf
    from datetime import datetime, timezone
    try:
        info = yf.Ticker(symbol).info
    except Exception:
        return None
    ex_ts = info.get("exDividendDate")
    if ex_ts is None:
        return None
    try:
        ex_date = datetime.fromtimestamp(ex_ts, tz=timezone.utc).date()
    except (TypeError, ValueError, OSError):
        return None
    if ex_date < date.today():
        return None                     # a past date is Intrinio's to record, from the bars
    last = info.get("lastDividendValue")          # the last declared payment per share, never dividendRate (the annualized figure)
    return {"ex_date": ex_date, "last_payment": float(last) if last else None}


async def last_paid_from_bars(session, symbol: str) -> float | None:
    """The most recent per-payment dividend Intrinio recorded on the stored bars; None when the bars hold none."""
    return await session.scalar(select(text("dividend")).select_from(text("price_bars_shadow"))
                                .where(text("symbol = :s AND dividend > 0")).order_by(text("date DESC")).limit(1).params(s=symbol))


async def retire_stale_forward_rows(session, ticker: Ticker, declared_date: date | None, paid: float | None, today: date | None = None) -> dict[str, int]:
    """Future ex-dividend rows of this ticker that carry an amount with no per-payment basis and no declaration: the writer before
    2026-10-05 stored yfinance's annualized dividendRate with no basis, and the nightly only corrected a row on the date yfinance
    still reports, so a row on a date it no longer reports kept the annual rate (PCAR 2026-11-11 1.40 beside the declared 11-10
    0.35). One on another date than the declared one is dropped (the declared date supersedes it); one on the declared date, or
    any when no date is declared, is re-based to the last payment on the stored bars, or loses its amount and reads basis unknown.
    Returns {dropped, rebased, unpriced}."""
    today = today or date.today()
    out = {"dropped": 0, "rebased": 0, "unpriced": 0}
    rows = (await session.execute(select(Event).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EX_DIVIDEND, Event.event_date >= today))).scalars().all()
    for e in rows:
        meta = e.metadata_ or {}
        if meta.get("basis") in PER_PAYMENT_BASES or meta.get("declared") or meta.get("dividend_amount") is None:
            continue
        if declared_date is not None and e.event_date != declared_date:
            await session.delete(e)
            out["dropped"] += 1
        elif paid:
            e.metadata_ = {**meta, "dividend_amount": float(paid), "basis": FORWARD_BASIS_INTRINIO}
            out["rebased"] += 1
        else:
            e.metadata_ = {**{k: v for k, v in meta.items() if k != "dividend_amount"}, "basis": FORWARD_BASIS_UNKNOWN}
            out["unpriced"] += 1
    return out


async def dividends_from_bars(symbols: list[str], since: date | None) -> dict[str, list[dict]]:
    """{symbol: [{date, amount}]} from every stored bar with a cash dividend on or after `since`, one query."""
    more = " AND date >= :since" if since else ""
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(text(f"SELECT symbol, date, dividend FROM price_bars_shadow WHERE dividend <> 0 AND symbol = ANY(:s){more} ORDER BY symbol, date"),
                                {"s": symbols, **({"since": since} if since else {})})).all()
    by: dict[str, list] = {}
    for r in rows:
        by.setdefault(r.symbol, []).append(r)
    return {sym: dividends_from_adjustments(rs) for sym, rs in by.items()}


async def dividends_from_api(symbol: str, client: IntrinioClient) -> list[dict]:
    async with AsyncSessionLocal() as s:
        ids = (await s.execute(text("SELECT intrinio_security_id FROM security_records WHERE symbol = :s AND intrinio_security_id IS NOT NULL ORDER BY valid_from"),
                               {"s": symbol})).scalars().all()
    out: dict[date, dict] = {}
    for sid in ids:
        for dv in dividends_from_adjustments(await client.price_adjustments(sid)):
            out.setdefault(dv["date"], dv)
    return [out[d] for d in sorted(out)]


async def _upsert_dividend_event(session, ticker: Ticker, ex_date: date, dividend_amount: float | None,
                                 source: DataSource = DataSource.INTRINIO, basis: str = DIVIDEND_BASIS) -> bool:
    """Insert the ex-dividend date if not already present. Returns True if inserted."""
    existing = (await session.execute(select(Event).where(Event.ticker_id == ticker.id, Event.event_date == ex_date, Event.event_type == EventType.EX_DIVIDEND))).scalars().first()
    if existing is not None:
        # a stored forward amount that is not a per-payment figure (the old annual rate, or no basis) is corrected in place
        if basis in PER_PAYMENT_BASES and dividend_amount is not None and (existing.metadata_ or {}).get("basis") not in PER_PAYMENT_BASES:
            existing.metadata_ = {**(existing.metadata_ or {}), "dividend_amount": dividend_amount, "basis": basis}
        return False
    meta = {"basis": basis}
    if dividend_amount is not None:
        meta["dividend_amount"] = dividend_amount
    session.add(Event(ticker_id=ticker.id, event_type=EventType.EX_DIVIDEND, event_date=ex_date, title=f"{ticker.symbol} Ex-Dividend",
                      source=source, is_confirmed=True, metadata_=meta))
    return True


async def main() -> int:
    parser = argparse.ArgumentParser(description="Seed ex-dividend dates from Intrinio's price adjustments")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--full", action="store_true", help="every stored bar, then the adjustments endpoint by security record")
    parser.add_argument("--no-forward", action="store_true", help="skip the yfinance pass for the declared next ex-date")
    parser.add_argument("--symbols", default=None, help="comma-separated symbols to run alone (a targeted repair of their forward rows)")
    args = parser.parse_args()

    async with AsyncSessionLocal() as session:
        tickers = list((await session.execute(select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol))).scalars().all())
    if args.symbols:
        wanted = {x.strip().upper() for x in args.symbols.split(",") if x.strip()}
        tickers = [t for t in tickers if t.symbol in wanted]
    if args.limit:
        tickers = tickers[:args.limit]
    since = None if args.full else date.today() - timedelta(days=WINDOW_DAYS)
    print(f"Dividend calendar (stored shadow bars{' then the adjustments endpoint' if args.full else f', last {WINDOW_DAYS} days'}): {len(tickers)} ticker(s)", flush=True)

    inserted = 0
    requests = 0
    failed: list[str] = []
    found = await dividends_from_bars([t.symbol for t in tickers], since)
    client = IntrinioClient() if args.full else None
    try:
        for t in tickers:
            try:
                divs = {d["date"]: d for d in found.get(t.symbol, [])}
                if args.full:
                    for d in await dividends_from_api(t.symbol, client):
                        divs.setdefault(d["date"], d)
                if not divs:
                    continue
                async with AsyncSessionLocal() as session:
                    n = 0
                    for d in sorted(divs):
                        n += await _upsert_dividend_event(session, t, d, divs[d]["amount"])
                    await session.commit()
                inserted += n
            except Exception as exc:
                failed.append(f"{t.symbol}: {redact(exc)[:80]}")
    finally:
        if client is not None:
            requests = client.request_count
            await client.close()
    print(f"  {inserted} ex-dividend date(s) inserted from Intrinio, {len(failed)} failed, {requests} request(s)")
    for f in failed[:10]:
        print("   ", f)
    # the declared next ex-date: yfinance, the named exception (a date, not a price)
    forward = 0
    forward_failed = 0
    stale = {"dropped": 0, "rebased": 0, "unpriced": 0}
    if not args.no_forward:
        loop = asyncio.get_event_loop()
        for i in range(0, len(tickers), FORWARD_BATCH):
            batch = tickers[i:i + FORWARD_BATCH]
            infos = await asyncio.gather(*(loop.run_in_executor(None, _fetch_forward_sync, t.symbol) for t in batch), return_exceptions=True)
            async with AsyncSessionLocal() as session:
                for t, info in zip(batch, infos):
                    if isinstance(info, Exception):
                        forward_failed += 1
                        continue
                    paid = await last_paid_from_bars(session, t.symbol)
                    if info:
                        amount, basis = (float(paid), FORWARD_BASIS_INTRINIO) if paid else (info["last_payment"], FORWARD_BASIS_YFINANCE)
                        forward += await _upsert_dividend_event(session, t, info["ex_date"], amount, DataSource.YFINANCE, basis)
                    # rows the pre-2026-10-05 writer left with the annual rate and no basis are retired every night, declared date or not
                    for k, v in (await retire_stale_forward_rows(session, t, info["ex_date"] if info else None, float(paid) if paid else None)).items():
                        stale[k] += v
                await session.commit()
            if i + FORWARD_BATCH < len(tickers):
                await asyncio.sleep(FORWARD_BATCH_SLEEP)
        print(f"  {forward} forward ex-dividend date(s) inserted from yfinance, {forward_failed} failed; stale forward rows: {stale['dropped']} dropped "
              f"(superseded by the declared date), {stale['rebased']} re-based to the last payment on the bars, {stale['unpriced']} left without an amount")
    return 1 if len(failed) + forward_failed > 10 else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
