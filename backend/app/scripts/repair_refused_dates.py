"""Swap a wrongly dated earnings row for the date the seeder refused, when the SEC supports it.

For each refused_earnings_dates row: read the blocking row's stored 8-K
acceptance time; if it supports the refused date and not the blocking one
(refusal_evidence.support == "refused"), then with --write: fetch the ticker's
Yahoo earnings entries and price history, compute the reaction for the refused
date, delete the blocking row (and its derived eps_basis_checks / earnings_features
rows), insert the refused date's row through upsert_reaction, and clear the
refusal. Never swaps on "both", "neither" or "no_acceptance". Report by default.

Usage (inside the backend container or via railway run):
    python -m app.scripts.repair_refused_dates            # report only
    python -m app.scripts.repair_refused_dates --write    # apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from sqlalchemy import delete, select, text

from app.database import ScriptSessionLocal as AsyncSessionLocal
from app.models.earnings_feature import EarningsFeature
from app.models.enums import EventType
from app.models.eps_basis_check import EpsBasisCheck
from app.models.historical_reaction import HistoricalReaction
from app.models.refused_earnings_date import RefusedEarningsDate
from app.models.ticker import Ticker
from app.scripts.seed_historical_reactions import (
    _build_date_cache, _compute_outcome, _compute_v3, _fetch_ticker_data_sync,
    load_reference_sessions, upsert_reaction,
)
from app.services.refusal_evidence import SUPPORTS_REFUSED, blocking_row_acceptance, describe, support

REFUSALS_SQL = text("""
    SELECT r.id, r.ticker_id, t.symbol, r.refused_date, r.blocking_row_date, r.source, r.times_seen
    FROM refused_earnings_dates r JOIN tickers t ON t.id = r.ticker_id
    ORDER BY t.symbol, r.refused_date
""")


async def _swap(session, ticker: Ticker, refused: date, blocking: date, loop) -> str:
    """Replace the blocking row with the refused date's row. Returns a one-line result."""
    entries, hist = await loop.run_in_executor(None, _fetch_ticker_data_sync, ticker.symbol)
    entry = next(((d, est, act) for d, est, act in entries if d == refused), None)
    if entry is None:
        return f"skipped: Yahoo no longer lists {refused} for {ticker.symbol}"
    if hist.empty:
        return "skipped: no price history"
    timing = await session.scalar(text(
        "SELECT timing FROM earnings_report_timing WHERE ticker_id = :t AND event_date = :d"
    ), {"t": ticker.id, "d": refused}) or "unknown"
    data = _compute_v3(hist, _build_date_cache(hist), refused, timing, load_reference_sessions())
    if data is None:
        return f"skipped: no price bars around {refused}"
    _, est, act = entry
    data["eps_estimate"], data["eps_actual"] = est, act
    data["outcome"] = _compute_outcome(est, act)
    data["report_timing"] = timing

    for model in (HistoricalReaction, EpsBasisCheck, EarningsFeature):
        cond = [model.ticker_id == ticker.id, model.event_date == blocking]
        if model is HistoricalReaction:
            cond.append(HistoricalReaction.event_type == EventType.EARNINGS)
        await session.execute(delete(model).where(*cond))
    created = await upsert_reaction(session, ticker, refused, data)
    if created is None:
        return "failed: the refused date is still blocked after deleting the row"
    await session.execute(delete(RefusedEarningsDate).where(
        RefusedEarningsDate.ticker_id == ticker.id, RefusedEarningsDate.refused_date == refused))
    return f"swapped: {blocking} row deleted, {refused} row inserted ({data['outcome'].value}, timing {timing})"


async def repair(write: bool) -> int:
    loop = asyncio.get_running_loop()
    swappable = 0
    async with AsyncSessionLocal() as session:
        rows = (await session.execute(REFUSALS_SQL)).all()
        print(f"{len(rows)} refusal(s) on record")
        for r in rows:
            acc = await blocking_row_acceptance(session, r.ticker_id, r.blocking_row_date)
            verdict = support(r.symbol, acc, r.refused_date, r.blocking_row_date)
            acc_s = acc.isoformat(timespec="minutes") if acc else "none"
            line = (f"  {r.symbol:6s} {r.source} offered {r.refused_date}, blocked by {r.blocking_row_date} "
                    f"(seen {r.times_seen}x, 8-K accepted {acc_s}): {describe(verdict)}")
            if verdict != SUPPORTS_REFUSED:
                print(line + " -> no swap")
                continue
            swappable += 1
            if not write:
                print(line + " -> would swap")
                continue
            ticker = await session.scalar(select(Ticker).where(Ticker.id == r.ticker_id))
            try:
                result = await _swap(session, ticker, r.refused_date, r.blocking_row_date, loop)
                await session.commit()
            except Exception as exc:
                await session.rollback()
                result = f"failed: {exc}"
            print(line + f" -> {result}")
    print(f"{swappable} swappable with SEC evidence" + ("" if write else "; pass --write to apply"))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="Apply the swaps (default: report only)")
    args = parser.parse_args()
    return asyncio.run(repair(args.write))


if __name__ == "__main__":
    sys.exit(main())
