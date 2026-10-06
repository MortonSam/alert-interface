"""Picks made on a wrong report date. Dry run by default: lists the named picks with the report day they targeted, the
day the company actually reported or has confirmed, the sessions between the pick and the actual report, and the exit
date against the actual reaction window. --write voids one pick: status void, the reason kept and shown in the ledger,
excluded from the record's counts and P&L, never deleted, skipped by the closer.

    python -m app.scripts.void_pick                                        # FDX 2026-10-05, JBL 2026-09-16, NKE 2026-09-21, CCL 2026-09-21
    python -m app.scripts.void_pick --picks=FDX:2026-10-05,JBL:2026-09-16
    python -m app.scripts.void_pick --write --id <pick uuid> --reason "report date was a Yahoo estimate; FedEx confirmed Oct 28"
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.services.ivy_v2 import EXIT_TRADING_DAYS
from app.services.trading_calendar import last_session_before, nth_trading_day_after, sessions_after

DEFAULT_PICKS = "FDX:2026-10-05,JBL:2026-09-16,NKE:2026-09-21,CCL:2026-09-21"


def targeted_report_day(exit_date: date | None) -> date | None:
    """The report day a v2 pick was built on: its exit is EXIT_TRADING_DAYS sessions after the report."""
    if exit_date is None:
        return None
    d = exit_date
    for _ in range(EXIT_TRADING_DAYS):
        d = last_session_before(d)
    return d


def assess(pick_day: date, exit_date: date | None, actual: date | None) -> dict:
    """Pure: how a pick's dates compare with the report that really happened (or is confirmed)."""
    target = targeted_report_day(exit_date)
    out = {"targeted": target, "actual": actual, "sessions_pick_to_actual": None, "sessions_target_to_actual": None,
           "actual_window_end": None, "exit_vs_window": None}
    if actual:
        out["sessions_pick_to_actual"] = sessions_after(pick_day, actual) + (1 if actual > pick_day else 0)
        if target:
            out["sessions_target_to_actual"] = (sessions_after(target, actual) + 1) if actual > target else (-(sessions_after(actual, target) + 1) if actual < target else 0)
        end = nth_trading_day_after(actual, EXIT_TRADING_DAYS)
        out["actual_window_end"] = end
        if exit_date:
            out["exit_vs_window"] = ("inside the actual window" if actual <= exit_date <= end else
                                     "before the actual report" if exit_date < actual else "after the actual window")
    return out


async def run(argv: list[str]) -> int:
    write = "--write" in argv
    pick_id = next((a.split("=", 1)[1] for a in argv if a.startswith("--id=")), None) or (argv[argv.index("--id") + 1] if "--id" in argv else None)
    reason = next((a.split("=", 1)[1] for a in argv if a.startswith("--reason=")), None) or (argv[argv.index("--reason") + 1] if "--reason" in argv else None)
    spec = next((a.split("=", 1)[1] for a in argv if a.startswith("--picks=")), DEFAULT_PICKS)
    async with ScriptSessionLocal() as s:
        if write:
            if not pick_id or not reason:
                print("--write needs --id <uuid> and --reason \"...\"")
                return 2
            row = (await s.execute(text("SELECT symbol, status, generated_at FROM alert_picks WHERE id = :i"), {"i": pick_id})).first()
            if row is None:
                print(f"no pick {pick_id}"); return 2
            if row.status == "void":
                print(f"{row.symbol} {row.generated_at.date()} is already void"); return 0
            await s.execute(text("UPDATE alert_picks SET status = 'void', void_reason = :r, voided_at = :at WHERE id = :i"),
                            {"r": reason, "at": datetime.now(timezone.utc), "i": pick_id})
            await s.commit()
            print(f"voided {row.symbol} picked {row.generated_at.date()} (was {row.status}): {reason}")
            return 0
        print("dry run: nothing changes; --write --id <uuid> --reason \"...\" voids one pick")
        for item in spec.split(","):
            sym, day = item.strip().split(":")
            picks = (await s.execute(text("""
                SELECT p.id, p.symbol, p.generated_at, p.status, p.exit_date, p.expiration, p.void_reason, t.id AS tid
                FROM alert_picks p JOIN tickers t ON t.symbol = p.symbol WHERE p.symbol = :s AND p.generated_at::date = :d ORDER BY p.generated_at"""),
                {"s": sym.upper(), "d": date.fromisoformat(day)})).all()
            if not picks:
                print(f"  {sym} {day}: no pick"); continue
            for p in picks:
                pick_day = p.generated_at.date()
                evs = (await s.execute(text("""
                    SELECT event_date, is_confirmed, eps_actual IS NOT NULL AS reported, source::text FROM events
                    WHERE ticker_id = :t AND event_type = 'earnings' AND event_date BETWEEN :a AND :b ORDER BY event_date"""),
                    {"t": p.tid, "a": pick_day - timedelta(days=5), "b": pick_day + timedelta(days=75)})).all()
                hard = [e for e in evs if e.reported or e.is_confirmed]
                actual = hard[0].event_date if hard else None
                a = assess(pick_day, p.exit_date, actual)
                how = ("reported" if hard and hard[0].reported else "confirmed") if hard else "none held"
                print(f"  {p.symbol} picked {pick_day} [{p.status}] id {p.id}")
                print(f"     targeted report day {a['targeted']} | actual/confirmed {actual} ({how}{', ' + hard[0].source if hard else ''})")
                print(f"     sessions pick->actual {a['sessions_pick_to_actual']} | target->actual {a['sessions_target_to_actual']} | "
                      f"exit {p.exit_date} vs actual window {actual}..{a['actual_window_end']}: {a['exit_vs_window']}")
                if p.void_reason:
                    print(f"     already void: {p.void_reason}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(run(sys.argv[1:])))
