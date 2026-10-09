"""Fail closed. When a validate check fails on a fact for a ticker, every surface that uses that fact for that ticker (the strip
question, the Overview clause, the Discover line, Ask Ivy's facts) is hidden until the check passes, and the morning digest lists what
was hidden. validate writes the holds at the end of each run (fact_holds, replaced whole); readers ask holds_for(db, symbol).

FACT_OF_CHECK names the fact each per-ticker check judges; a check's ERROR rows begin with the ticker symbol, which is how a hold
finds its ticker. A check that lists more rows than its cap holds only the listed tickers.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import text

FACTS = ("implied_move", "report_date", "dividend_amount", "release_eps", "pe", "typical_move", "sector_peer")

FACT_OF_CHECK: dict[str, str] = {
    "next_dividend_amount": "dividend_amount",
    "estimate_beside_confirmed": "report_date", "past_estimate_standing": "report_date", "duplicate_future_earnings": "report_date", "refused_earnings_dates": "report_date",
    "release_eps_checked": "release_eps",
    "pe_sanity": "pe", "pe_window_fresh": "pe",
    "sector_peer_avg_range": "sector_peer", "sector_peer_count_range": "sector_peer",
    "reaction_pct_range": "typical_move", "reactions_eps_bounds": "typical_move", "reactions_1d_equals_3d": "typical_move", "reactions_3d_equals_5d": "typical_move",
    "reactions_null_open_with_pct": "typical_move", "tickers_uniform_outcome": "typical_move", "outcome_matches_eps": "typical_move", "basis_mismatch_no_outcome": "typical_move",
    "iv_solver_band": "implied_move", "iv_vendor_band": "implied_move", "iv_history_out_of_band": "implied_move", "iv_history_price_drift": "implied_move",
}

# what each fact feeds, so a hold hides all of it (documentation for readers; the gating itself sits in each surface)
SURFACES: dict[str, tuple[str, ...]] = {
    "implied_move": ("strip: implied_big", "Overview: options clause", "Discover: options against typical", "Ask Ivy: implied move facts"),
    "report_date": ("strip: implied_big", "Overview: next report clause", "Discover: reporting-soon row", "Ask Ivy: next report facts"),
    "dividend_amount": ("strip: ex_dividend", "Ask Ivy: dividend facts"),
    "release_eps": ("strip: pe_compare when the window holds the release quarter", "Ask Ivy: P/E facts"),
    "pe": ("strip: pe_compare", "Ask Ivy: P/E facts"),
    "typical_move": ("strip: reaction_normal, implied_big, beat_fell, usual_move", "Overview: typical move", "Discover: insight and comparison", "Ask Ivy: move facts"),
    "sector_peer": ("sector peers endpoint: own and sector averages",),
}

_SYMBOL = re.compile(r"^([A-Z][A-Z0-9.-]{0,9})(?=[\s:])")


def symbol_of_row(row: str) -> str | None:
    """Pure: the ticker a check's row names, when the row starts with it."""
    m = _SYMBOL.match(row or "")
    return m.group(1) if m else None


def holds_from_results(results, symbols: set[str]) -> list[dict]:
    """Pure: [{symbol, fact, check, detail}] from the ERROR results of the mapped checks, one per (symbol, fact, check)."""
    out: dict[tuple[str, str, str], dict] = {}
    for r in results:
        fact = FACT_OF_CHECK.get(r.name)
        if fact is None or r.level != "error":
            continue
        for row in r.rows:
            sym = symbol_of_row(row)
            if sym and sym in symbols and (sym, fact, r.name) not in out:
                out[(sym, fact, r.name)] = {"symbol": sym, "fact": fact, "check": r.name, "detail": row[:300]}
    return sorted(out.values(), key=lambda h: (h["symbol"], h["fact"], h["check"]))


def hidden_lines(holds: list[dict]) -> list[str]:
    """Pure: "SYM: fact (check)" per hold, for the step outcome and the digest."""
    return [f"{h['symbol']}: {h['fact'].replace('_', ' ')} ({h['check']})" for h in holds]


async def replace_holds(session, holds: list[dict], now: datetime | None = None) -> None:
    """The table is the current run's verdict: every hold is replaced; a hold already present keeps its first `since`."""
    now = now or datetime.now(timezone.utc)
    existing = {(r[0], r[1], r[2]): r[3] for r in (await session.execute(text("SELECT symbol, fact, check_name, since FROM fact_holds"))).all()}
    await session.execute(text("DELETE FROM fact_holds"))
    for h in holds:
        await session.execute(text("INSERT INTO fact_holds (symbol, fact, check_name, detail, since) VALUES (:s, :f, :c, :d, :at)"),
                              {"s": h["symbol"], "f": h["fact"], "c": h["check"], "d": h["detail"], "at": existing.get((h["symbol"], h["fact"], h["check"]), now)})


async def holds_for(db, symbol: str) -> dict[str, list[str]]:
    """{fact: [checks]} currently holding this ticker's facts."""
    rows = (await db.execute(text("SELECT fact, check_name FROM fact_holds WHERE symbol = :s ORDER BY fact, check_name"), {"s": symbol})).all()
    out: dict[str, list[str]] = {}
    for fact, check in rows:
        out.setdefault(fact, []).append(check)
    from app.services.pending_deals import HELD_FACTS, HOLD_CHECK, deal_for
    if await deal_for(db, symbol):                       # a pending cash deal holds the move facts (services/pending_deals)
        for fact in HELD_FACTS:
            out.setdefault(fact, []).append(HOLD_CHECK)
    return out


async def holds_for_symbols(db, symbols: list[str]) -> dict[str, set[str]]:
    """{symbol: {facts}} for many tickers in one query."""
    if not symbols:
        return {}
    rows = (await db.execute(text("SELECT symbol, fact FROM fact_holds WHERE symbol = ANY(:s)"), {"s": list(symbols)})).all()
    out: dict[str, set[str]] = {}
    for sym, fact in rows:
        out.setdefault(sym, set()).add(fact)
    from app.services.pending_deals import HELD_FACTS, deals_for
    for sym in await deals_for(db, list(symbols)):
        out.setdefault(sym, set()).update(HELD_FACTS)
    return out
