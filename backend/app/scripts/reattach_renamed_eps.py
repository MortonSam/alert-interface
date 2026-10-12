"""Reattach EPS history to a renamed ticker. VMRK (Equity Residential until 2026-10-05, renamed by Intrinio's record) keeps its 20
reaction rows but none of their EPS estimates or actuals: the nightly actuals seeder reads Finnhub's earnings calendar, which never
lists the renamed symbol's past quarters, and the reactions table carries whatever the events held when the quarter was seeded.
Finnhub's earnings-surprises endpoint does answer for the new symbol (quarters by period end), and yfinance answers for both symbols
by report date; both are read here, the new symbol first, and matched to the stored earnings events.

Dry run by default: prints each renamed ticker's rows before and after, and what each event would receive and from where.
--write fills events.eps_estimate / eps_actual, copies them to the matching reaction rows and sets their outcome from
services/eps_actuals.eps_outcome, then bumps nothing else (the reaction's moves are unchanged).

    python -m app.scripts.reattach_renamed_eps              # every ticker in ticker_aliases, dry run
    python -m app.scripts.reattach_renamed_eps VMRK --write
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.eps_actuals import eps_outcome, fill_plan, match_row
from app.services.finnhub_client import FinnhubClient
from app.services.redact import redact

PERIOD_TO_REPORT_DAYS = (14, 75)     # a report lands this long after its quarter end


def _num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def surprises_by_period(rows: list[dict]) -> dict[date, tuple[float | None, float | None]]:
    """Pure: Finnhub's surprises {period end: (actual, estimate)}."""
    out = {}
    for r in rows:
        try:
            out[date.fromisoformat(str(r.get("period"))[:10])] = (_num(r.get("actual")), _num(r.get("estimate")))
        except ValueError:
            continue
    return out


def match_period(event_date: date, by_period: dict) -> tuple[float | None, float | None] | None:
    """Pure: the surprise whose quarter ended PERIOD_TO_REPORT_DAYS before the report."""
    lo, hi = PERIOD_TO_REPORT_DAYS
    hits = [(pe, v) for pe, v in by_period.items() if lo <= (event_date - pe).days <= hi]
    return min(hits, key=lambda x: event_date - x[0])[1] if hits else None


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    only = {a.upper() for a in argv if not a.startswith("--")}
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    async with ScriptSessionLocal() as s:
        aliases = (await s.execute(text("SELECT old_symbol, symbol, renamed_on FROM ticker_aliases ORDER BY renamed_on"))).all()
        targets = [(o, n) for o, n, _ in aliases if not only or n in only]
        if not targets:
            print("no renamed ticker to reattach"); return 0
        client = FinnhubClient()
        try:
            for old, new in targets:
                evs = (await s.execute(text("""SELECT e.id, e.event_date, e.eps_actual, e.eps_estimate FROM events e JOIN tickers t ON t.id = e.ticker_id
                    WHERE t.symbol = :s AND e.event_type = 'earnings' AND e.event_date <= CURRENT_DATE ORDER BY e.event_date"""), {"s": new})).all()
                rx = (await s.execute(text("""SELECT count(*), count(eps_actual), count(eps_estimate) FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id
                    WHERE t.symbol = :s AND hr.event_type = 'earnings'"""), {"s": new})).one()
                print(f"\n{new} (was {old}): {len(evs)} earnings event(s); reaction rows {rx[0]}, with actual {rx[1]}, with estimate {rx[2]}")
                try:
                    by_period = surprises_by_period(await client.get_earnings_surprises(new))
                except Exception as exc:
                    print(f"  Finnhub surprises failed for {new}: {redact(exc)[:100]}"); by_period = {}
                from app.scripts.seed_eps_actuals import yfinance_rows
                yf = {}
                for sym in (new, old):
                    try:
                        yf.update({d: v for d, v in (await asyncio.to_thread(yfinance_rows, sym)).items() if d not in yf})
                    except Exception as exc:
                        print(f"  yfinance failed for {sym}: {redact(exc)[:100]}")
                plans = []
                # one report per quarter: when two stored events sit in a period's window (a leftover estimate beside the real date),
                # only the event nearest the quarter end takes the figure
                nearest_by_period: dict = {}
                for _, d, _, _ in evs:
                    hit = [(pe, v) for pe, v in by_period.items() if PERIOD_TO_REPORT_DAYS[0] <= (d - pe).days <= PERIOD_TO_REPORT_DAYS[1]]
                    if hit:
                        pe = min(hit, key=lambda x: d - x[0])[0]
                        if pe not in nearest_by_period or d < nearest_by_period[pe]:
                            nearest_by_period[pe] = d
                for ev_id, d, actual, estimate in evs:
                    got, source = match_period(d, by_period), "finnhub surprises"
                    if got is not None and d not in nearest_by_period.values():
                        got = None                      # another event is the quarter's report date
                    if got is None or got[0] is None:
                        alt = match_row(d, yf)
                        if alt is not None and (got is None or alt[0] is not None):
                            got, source = alt, "yfinance"
                    if got is None:
                        continue
                    plan = fill_plan(actual, estimate, got[0], got[1], source, now)
                    if plan:
                        plans.append((ev_id, d, plan, source))
                        print(f"  {d}: {', '.join(f'{k}={v}' for k, v in plan.items() if k in ('eps_actual', 'eps_estimate'))} from {source}")
                filled = sum(1 for _, _, p, _ in plans if "eps_actual" in p)
                print(f"  would fill {filled} actual(s) on {len(plans)} event(s); reaction rows after: with actual {rx[1] + filled}")
                if write:
                    for ev_id, d, plan, _ in plans:
                        cols = {k: v for k, v in plan.items() if k in ("eps_actual", "eps_estimate")}
                        if not cols:
                            continue
                        await s.execute(text("UPDATE events SET " + ", ".join(f"{k} = :{k}" for k in cols) + " WHERE id = :id"), {**cols, "id": ev_id})
                        a = (await s.execute(text("SELECT eps_actual, eps_estimate FROM events WHERE id = :id"), {"id": ev_id})).one()
                        outcome = eps_outcome(float(a[0]) if a[0] is not None else None, float(a[1]) if a[1] is not None else None)
                        await s.execute(text("""UPDATE historical_reactions hr SET eps_actual = :a, eps_estimate = :e, outcome = COALESCE(CAST(:o AS earnings_outcome_enum), outcome)
                            FROM tickers t WHERE t.id = hr.ticker_id AND t.symbol = :s AND hr.event_type = 'earnings' AND abs(hr.event_date - :d) <= 2"""),
                                        {"a": a[0], "e": a[1], "o": outcome, "s": new, "d": d})
                    await s.commit()
                    print(f"  written {len(plans)} event(s) and their reaction rows")
        finally:
            await client.close()
    print("\n" + ("written" if write else "dry run: nothing written (add --write)"))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
