"""The realized-volatility rank compares a stock with its own past year. After a spin-off, merger, share-exchange acquisition or
rename-merge the company is not the one the year describes (CTVA's RV rank of 100 after the Vylor spin-off compared the new
company with the pre-spin year), so the rank is held on Discover, the strip and Ask Ivy, with the action as the reason, until
CLEAN_SESSIONS_NEEDED sessions have passed since it.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text

from app.services.trading_calendar import is_trading_day
from app.services.valuation import ACTION_VERBS

CLEAN_SESSIONS_NEEDED = 252


def sessions_cutoff(today: date, sessions: int = CLEAN_SESSIONS_NEEDED) -> date:
    """Pure: the date `sessions` trading days before `today`; an action on or after it holds the rank."""
    d, n = today, 0
    while n < sessions:
        d -= timedelta(days=1)
        if is_trading_day(d):
            n += 1
    return d


def hold_reason(kind: str, name: str | None, day: date) -> str:
    """Pure: "Spun off Vylor on Oct 1, 2026; 252 clean sessions after it are needed"."""
    from app.services.briefing import fmt_date
    verb = ACTION_VERBS.get(kind, "Had a corporate action ({kind}) on {date}").format(name=name or "a business", date=fmt_date(day), kind=kind)
    return f"{verb}; {CLEAN_SESSIONS_NEEDED} clean sessions after it are needed"


def hold_phrase(kind: str, name: str | None, day: date) -> str:
    """Pure: "Spun off Vylor on Oct 1": the action in words with a short date, for the Discover tape."""
    short = f"{day.strftime('%b')} {day.day}"
    return ACTION_VERBS.get(kind, "Had a corporate action on {date}").format(name=name or "a business", date=short, kind=kind)


async def rank_holds(db, symbols: list[str], today: date | None = None) -> dict[str, str]:
    """{symbol: reason} for the tickers with a recorded action inside the last CLEAN_SESSIONS_NEEDED sessions (the newest action)."""
    return {sym: hold_reason(a["kind"], a["name"], a["date"]) for sym, a in (await rank_hold_actions(db, symbols, today)).items()}


async def rank_hold_actions(db, symbols: list[str], today: date | None = None) -> dict[str, dict]:
    """{symbol: {kind, name, date}}: the newest recorded action inside the last CLEAN_SESSIONS_NEEDED sessions, which holds the rank."""
    if not symbols:
        return {}
    today = today or date.today()
    cutoff = sessions_cutoff(today)
    rows = (await db.execute(text("""
        SELECT t.symbol, e.event_date, COALESCE(e.metadata->>'corporate_action', 'spin_off') AS kind, e.metadata->>'counterparty' AS name
        FROM events e JOIN tickers t ON t.id = e.ticker_id
        WHERE t.symbol = ANY(:s) AND e.event_date >= :c AND e.event_date <= :t
          AND (e.event_type = 'spin_off' OR (e.event_type = 'other' AND e.metadata ? 'corporate_action'))
        UNION ALL
        SELECT symbol, renamed_on, 'rename_merge', old_symbol FROM ticker_aliases WHERE symbol = ANY(:s) AND renamed_on >= :c AND renamed_on <= :t
        ORDER BY 2"""), {"s": list(symbols), "c": cutoff, "t": today})).all()
    from app.services.valuation import drop_renames_explained
    by_sym: dict[str, list[dict]] = {}
    for sym, day, kind, name in rows:
        by_sym.setdefault(sym, []).append({"kind": kind, "date": day, "name": name})
    out: dict[str, dict] = {}
    for sym, acts in by_sym.items():
        kept = sorted(drop_renames_explained(acts), key=lambda a: a["date"])      # a rename explained by a recorded deal defers to it
        if kept:
            out[sym] = kept[-1]
    return out
