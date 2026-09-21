"""Remove duplicate earnings reactions (one report stored under two dates).

For each pair of earnings rows for one ticker within WINDOW_DAYS:
  - eps_estimate and eps_actual identical on both rows -> one report.
      The SEC acceptance time (earnings_report_timing.acceptance_datetime)
      decides the true row: accepted before 09:30 ET on date X -> X with bmo;
      accepted at or after 16:00 ET on X -> X with amc. Keep the row dated X,
      stamp it with that timing, delete the other. recompute_null_reactions
      fills the moves afterwards. When the two rows carry different acceptance
      times, the earliest one is the release.
      Fallback (no acceptance time, or accepted during market hours): keep the
      row with pct values; if neither has pct values, keep the row with known
      timing (bmo/amc).
  - EPS differs, or the rule does not pick a single row -> print, change nothing,
    unless the row is listed in MANUAL_DELETES (resolved by hand, with a reason).

Dry run by default.

Usage:
    python -m app.scripts.dedupe_earnings_reactions            # dry run
    python -m app.scripts.dedupe_earnings_reactions --write    # apply
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, time

from sqlalchemy import text

from app.database import ScriptSessionLocal as AsyncSessionLocal

WINDOW_DAYS = 45
KNOWN_TIMINGS = {"bmo", "amc"}
# Pairs whose EPS differs, resolved by hand against the reported figure.
# (symbol, event_date of the row to delete) -> reason
MANUAL_DELETES: dict[tuple[str, date], str] = {
    ("COST", date(2022, 10, 5)): "monthly sales release; 2022-09-22 matches reported Q4 EPS 4.20",
    ("DD", date(2023, 8, 3)): "2023-08-02 matches reported EPS 0.85",
    ("TMUS", date(2022, 2, 1)): "2022-02-02 matches reported EPS 0.34",
    ("TMUS", date(2024, 4, 26)): "2024-04-25 matches reported EPS 2.00",
}
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def _has_pct(r) -> bool:
    return r["pct_1d"] is not None or r["pct_3d"] is not None or r["pct_5d"] is not None


def _timing(r) -> str:
    t = r["timing"]
    return (getattr(t, "value", t) or "unknown").lower()


def _fmt(r) -> str:
    acc = f"{r['accepted_et']:%Y-%m-%d %H:%M} ET" if r["accepted_et"] else "none"
    return (f"{r['event_date']} ({_timing(r)}, {'pct' if _has_pct(r) else 'null'}, "
            f"eps={r['eps_estimate']}/{r['eps_actual']}, accepted={acc})")


def _fill_note(keep: dict, stamp: str | None) -> str:
    if _has_pct(keep):
        return ""
    if (stamp or _timing(keep)) in KNOWN_TIMINGS:
        return "  [kept row has no pct, recompute_null_reactions will fill]"
    return "  [kept row has no pct and unknown timing, stays NULL]"


def true_row_from_acceptance(accepted_et: datetime | None) -> tuple[date, str] | None:
    """Map an acceptance time (naive, US Eastern) to (true event date, timing)."""
    if accepted_et is None:
        return None
    if accepted_et.time() < MARKET_OPEN:
        return accepted_et.date(), "bmo"
    if accepted_et.time() >= MARKET_CLOSE:
        return accepted_et.date(), "amc"
    return None


def _fallback(a: dict, b: dict) -> tuple[dict | None, dict | None, str]:
    pa, pb = _has_pct(a), _has_pct(b)
    if pa != pb:
        keep, drop = (a, b) if pa else (b, a)
        return keep, drop, "keep the row with pct values"
    if pa and pb:
        return None, None, "NO CHANGE: both rows have pct values"
    ka, kb = _timing(a) in KNOWN_TIMINGS, _timing(b) in KNOWN_TIMINGS
    if ka != kb:
        keep, drop = (a, b) if ka else (b, a)
        return keep, drop, "neither has pct, keep the row with known timing"
    return None, None, (
        "NO CHANGE: neither has pct, "
        + ("both timings known" if ka else "neither timing known")
    )


def decide(a: dict, b: dict) -> tuple[dict | None, dict | None, str | None, str]:
    """Return (keep, delete, timing_to_stamp, reason). keep/delete None = no change."""
    if a["eps_estimate"] is None or a["eps_actual"] is None:
        return None, None, None, "NO CHANGE: EPS missing on first row, cannot prove one report"
    if (a["eps_estimate"], a["eps_actual"]) != (b["eps_estimate"], b["eps_actual"]):
        return None, None, None, "NO CHANGE: EPS differs"

    accepted = sorted({x["accepted_et"] for x in (a, b) if x["accepted_et"] is not None})
    if accepted:
        note = " (earliest of two acceptance times)" if len(accepted) > 1 else ""
        truth = true_row_from_acceptance(accepted[0])
        if truth is None:
            keep, drop, why = _fallback(a, b)
            return keep, drop, None, f"accepted during market hours{note}, fallback: {why}"
        true_date, timing = truth
        for keep, drop in ((a, b), (b, a)):
            if keep["event_date"] == true_date:
                return keep, drop, timing, f"accepted {accepted[0]:%Y-%m-%d %H:%M} ET{note} -> {true_date} {timing}"
        return None, None, None, f"NO CHANGE: acceptance implies {true_date} {timing}, which is neither row"

    keep, drop, why = _fallback(a, b)
    return keep, drop, None, f"no acceptance time, fallback: {why}"


async def _stamp_timing(session, keep: dict, drop: dict, timing: str) -> None:
    """Make the kept row and its timing record agree with the acceptance-derived timing."""
    await session.execute(
        text("UPDATE historical_reactions SET report_timing = :t WHERE id = :id"),
        {"t": timing, "id": keep["id"]},
    )
    accepted = keep["accepted_utc"] or drop["accepted_utc"]
    await session.execute(text("""
        INSERT INTO earnings_report_timing (id, ticker_id, event_date, timing, source, acceptance_datetime)
        VALUES (gen_random_uuid(), :tid, :d, :t, 'edgar', :acc)
        ON CONFLICT (ticker_id, event_date)
        DO UPDATE SET timing = :t, source = 'edgar', acceptance_datetime = :acc
    """), {"tid": keep["ticker_id"], "d": keep["event_date"], "t": timing, "acc": accepted})


async def _run(write: bool) -> int:
    async with AsyncSessionLocal() as session:
        pairs = (await session.execute(text("""
            SELECT t.symbol, hr1.id AS id1, hr2.id AS id2
            FROM historical_reactions hr1
            JOIN historical_reactions hr2
              ON hr1.ticker_id = hr2.ticker_id
             AND hr1.event_type = 'earnings' AND hr2.event_type = 'earnings'
             AND hr2.event_date > hr1.event_date
             AND hr2.event_date - hr1.event_date <= :win
            JOIN tickers t ON t.id = hr1.ticker_id
            ORDER BY t.symbol, hr1.event_date, hr2.event_date
        """), {"win": WINDOW_DAYS})).all()

        print(f"{len(pairs)} pair(s) of earnings rows within {WINDOW_DAYS} days (write={write})\n")

        deleted_ids: set = set()
        n_delete = n_nochange = 0
        for p in pairs:
            if p.id1 in deleted_ids or p.id2 in deleted_ids:
                print(f"{p.symbol}  pair skipped, one row already deleted by an earlier decision")
                continue
            rows = {
                r.id: dict(r._mapping) for r in (await session.execute(text("""
                    SELECT hr.id, hr.ticker_id, hr.event_date, hr.report_timing AS timing,
                           hr.eps_estimate, hr.eps_actual,
                           hr.pct_change_1d AS pct_1d, hr.pct_change_3d AS pct_3d,
                           hr.pct_change_5d AS pct_5d,
                           ert.acceptance_datetime AT TIME ZONE 'America/New_York' AS accepted_et,
                           ert.acceptance_datetime AS accepted_utc
                    FROM historical_reactions hr
                    LEFT JOIN earnings_report_timing ert
                      ON ert.ticker_id = hr.ticker_id AND ert.event_date = hr.event_date
                    WHERE hr.id IN (:a, :b)
                """), {"a": p.id1, "b": p.id2})).all()
            }
            a, b = rows[p.id1], rows[p.id2]
            manual = [r for r in (a, b) if (p.symbol, r["event_date"]) in MANUAL_DELETES]
            if len(manual) == 1:
                drop = manual[0]
                keep = b if drop is a else a
                stamp = None
                reason = "MANUAL: " + MANUAL_DELETES[(p.symbol, drop["event_date"])]
            else:
                keep, drop, stamp, reason = decide(a, b)
            print(f"{p.symbol}  {_fmt(a)} <-> {_fmt(b)}")
            if keep is None:
                print(f"    {reason}")
                n_nochange += 1
                continue
            restamp = stamp is not None and _timing(keep) != stamp
            print(
                f"    KEEP {keep['event_date']}  DELETE {drop['event_date']}  ({reason})"
                + (f"  [timing {_timing(keep)} -> {stamp}]" if restamp else "")
                + _fill_note(keep, stamp)
            )
            n_delete += 1
            deleted_ids.add(drop["id"])
            if write:
                await session.execute(
                    text("DELETE FROM historical_reactions WHERE id = :id"), {"id": drop["id"]}
                )
                if restamp:
                    await _stamp_timing(session, keep, drop, stamp)

        if write:
            await session.commit()

    verb = "deleted" if write else "would delete"
    print(f"\nSummary: {n_delete} row(s) {verb}, {n_nochange} pair(s) left unchanged")
    if not write and n_delete:
        print("Dry run. Re-run with --write to apply.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Dedupe earnings reactions stored under two dates")
    ap.add_argument("--write", action="store_true", help="apply deletions (default: dry run)")
    return asyncio.run(_run(ap.parse_args().write))


if __name__ == "__main__":
    sys.exit(main())
