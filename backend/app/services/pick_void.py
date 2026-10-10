"""The void standard, applied automatically. Ivy's rule enters a pick ENTRY_MIN_SESSIONS to ENTRY_MAX_SESSIONS sessions
before the report. Once the company a pick targeted has actually reported, the closer counts the sessions from the
pick's entry to that report; a pick whose report fell outside the window is voided with the standard reason, winners
and losers alike, kept in the ledger with the reason visible and outside the record.

    void_verdict(pick_day, exit_date, actual_report) -> (sessions_after_entry, inside_window, targeted_day)
    standard_reason(company, sessions, actual, target)
    auto_void(session, today) -> [labels]            # the closer calls this each run; nothing is deleted
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import text

from app.services.ivy_v2 import EXIT_TRADING_DAYS
from app.services.trading_calendar import last_session_before, sessions_after

ENTRY_MIN_SESSIONS = 1       # the rule picks a name reporting one to five sessions after entry (ivy_v2.CANDIDATE_WINDOW_DAYS, seven calendar days)
ENTRY_MAX_SESSIONS = 5
REPORT_SEARCH_DAYS = 75      # how far past the entry an actual report is looked for


def targeted_day(exit_date: date | None) -> date | None:
    """The report day a v2 pick was built on: its exit is EXIT_TRADING_DAYS sessions after the report."""
    if exit_date is None:
        return None
    d = exit_date
    for _ in range(EXIT_TRADING_DAYS):
        d = last_session_before(d)
    return d


def sessions_from_entry(pick_day: date, actual: date) -> int:
    """Sessions from the pick's entry day to the actual report day: a report the next session counts 1; one the same day or before, 0 or less."""
    if actual <= pick_day:
        return -(sessions_after(actual, pick_day) + 1) if actual < pick_day else 0        # symmetric with the forward count
    return sessions_after(pick_day, actual) + 1


def void_verdict(pick_day: date, exit_date: date | None, actual: date) -> tuple[int, bool, date | None]:
    n = sessions_from_entry(pick_day, actual)
    return n, ENTRY_MIN_SESSIONS <= n <= ENTRY_MAX_SESSIONS, targeted_day(exit_date)


def standard_reason(company: str, sessions: int, actual: date, target: date | None) -> str:
    tgt = target.strftime("%b %-d, %Y") if target else "an unrecorded day"
    return (f"Report came {sessions} sessions after entry, the rule allows {ENTRY_MIN_SESSIONS} to {ENTRY_MAX_SESSIONS}; "
            f"{company} reported {actual.strftime('%b %-d, %Y')}, not the targeted {tgt}")


PRICE_FIELDS = ("closed_at", "close_price", "option_pnl_dollars", "option_pnl_pct")     # cleared on void: a void pick is priced by nothing


async def auto_void(session, today: date | None = None) -> list[str]:
    """Void every v2 pick (open or closed) whose company has reported outside the entry window. A pick already void is
    skipped and reported as "already void"; its reason and time are never rewritten. A void pick is priced by nothing: voiding
    clears its close and option P&L fields, and any void pick still carrying one has it cleared here (validate's pick_void
    check holds the invariant). Returns labels for the step outcome and the digest. Deletes nothing."""
    today = today or date.today()
    cleared = (await session.execute(text(f"UPDATE alert_picks SET {', '.join(f'{c} = NULL' for c in PRICE_FIELDS)} WHERE status = 'void' AND ({' OR '.join(f'{c} IS NOT NULL' for c in PRICE_FIELDS)})"))).rowcount
    if cleared:
        print(f"[void] cleared the price fields of {cleared} already-void pick(s)")
    picks = (await session.execute(text("""
        SELECT p.id, p.symbol, p.generated_at, p.exit_date, p.status, t.id AS tid, t.name
        FROM alert_picks p JOIN tickers t ON t.symbol = p.symbol
        WHERE p.status IN ('open', 'closed', 'void') AND p.exit_date IS NOT NULL ORDER BY p.generated_at"""))).all()
    out: list[str] = []
    for p in picks:
        pick_day = p.generated_at.date()
        # the first report the company actually made after entry: a reported EPS, a reaction row, or a company-confirmed past date
        actual = (await session.execute(text("""
            SELECT e.event_date FROM events e WHERE e.ticker_id = :t AND e.event_type = 'earnings'
              AND e.event_date BETWEEN :a AND :b AND e.event_date <= :today
              AND (e.eps_actual IS NOT NULL OR e.is_confirmed
                   OR EXISTS (SELECT 1 FROM historical_reactions hr WHERE hr.ticker_id = e.ticker_id AND hr.event_type = 'earnings' AND hr.event_date = e.event_date))
            ORDER BY e.event_date LIMIT 1"""), {"t": p.tid, "a": pick_day - timedelta(days=3), "b": pick_day + timedelta(days=REPORT_SEARCH_DAYS), "today": today})).scalar()
        if actual is None:
            continue
        n, inside, target = void_verdict(pick_day, p.exit_date, actual)
        if inside:
            continue
        if p.status == "void":                       # already void, by hand or by an earlier run: its reason and time are never rewritten
            out.append(f"{p.symbol} picked {pick_day.isoformat()}: already void")
            continue
        from app.services.briefing import short_name
        reason = standard_reason(short_name(p.name, p.symbol) or p.symbol, n, actual, target)
        await session.execute(text(f"UPDATE alert_picks SET status = 'void', void_reason = :r, voided_at = :at, {', '.join(f'{c} = NULL' for c in PRICE_FIELDS)} WHERE id = :i"),
                              {"r": reason, "at": datetime.now(timezone.utc), "i": p.id})
        out.append(f"{p.symbol} picked {pick_day.isoformat()} ({p.status}): {reason}")
    return out
