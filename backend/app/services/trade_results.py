"""Hypothetical trade results in My Trades (Sam, 2026-10-29). Every saved Build a Trade idea with an option leg is scored once its
expiration has passed, from stored prices only: what it cost when saved (the mid of each leg then, as stored), what it was worth at
expiration (each leg's intrinsic value at the stored official close on the expiration day, services/price_bars), the result in
dollars and percent, and how the stock actually moved from the day it was saved to expiration against the move options priced when
it was saved (priced_move_pct, the at-the-money straddle over the price on the stored chain, recorded at save).

Labeled "Hypothetical" everywhere; nothing here is money anyone spent, and no wording says buy or sell. A spread is the saved first
leg held and the second sold (services/pnl_math). RESULTS_VERSION is stored with each result, so a change to the scoring rescored
nothing silently.
"""
from __future__ import annotations

from datetime import date

from app.services.move_comparison import compare_moves
from app.services.pnl_math import compute_intrinsic_mids, pnl_percent

RESULTS_VERSION = 1


def score(*, option_type: str, strike: float, entry_premium: float, contracts: int, close_at_expiration: float, entry_price: float | None,
          strike2: float | None = None, entry_premium2: float | None = None, priced_move_pct: float | None = None,
          expiration: date, saved_on: date) -> dict:
    """Pure: one expired idea's result (dollars for the whole position, 100 shares a contract)."""
    mid1, mid2 = compute_intrinsic_mids(option_type, close_at_expiration, strike, strike2)
    spread = strike2 is not None and entry_premium2 is not None
    cost = entry_premium - (entry_premium2 if spread else 0.0)          # per share, as saved
    worth = mid1 - (mid2 if spread and mid2 is not None else 0.0)       # per share at expiration
    n = max(1, int(contracts or 1)) * 100
    out = {"version": RESULTS_VERSION, "expiration": expiration.isoformat(), "saved_on": saved_on.isoformat(),
           "close_at_expiration": round(close_at_expiration, 2), "paid_usd": round(cost * n, 2), "worth_usd": round(worth * n, 2),
           "result_usd": round((worth - cost) * n, 2), "result_pct": pnl_percent(worth - cost, cost), "ahead": worth > cost,
           "stock_move_pct": None, "priced_move_pct": priced_move_pct, "moved_vs_priced": None}
    if entry_price:
        move = round((close_at_expiration / entry_price - 1) * 100, 1)
        out["stock_move_pct"] = move
        if priced_move_pct:
            word = compare_moves(abs(move), float(priced_move_pct))          # the site's one rule for more, less or about the same
            out["moved_vs_priced"] = {"more than usual": "more", "less than usual": "less", "about its usual": "same"}[word]
    return out


def summary_line(results: list[dict]) -> str:
    """Pure: "6 hypothetical trades, 2 finished ahead" over the scored ideas."""
    n = len(results)
    ahead = sum(1 for r in results if r.get("ahead"))
    return f"{n} hypothetical trade{'' if n == 1 else 's'}, {ahead} finished ahead"


async def priced_move_now(db, symbol: str, expiration: date, today: date | None = None) -> tuple[float | None, date | None]:
    """What options price for the stock's move to `expiration`, from the stored chain for that expiration while it is fresh:
    (percent, the chain's date), or (None, None)."""
    from app.services import chain_store
    from app.services.implied_move import straddle_implied_move
    got = await chain_store.get_chain(db, symbol, expiration.isoformat())
    if not got or not got[1] or not chain_store.is_fresh(got[1], today=today or date.today()):
        return None, None
    chain, last_trade = got
    spot = chain.get("underlying_price")
    im = straddle_implied_move(chain.get("calls") or [], chain.get("puts") or [], float(spot)) if spot else None
    if im is None:
        return None, None
    return round(im.pct * 100, 1), date.fromisoformat(str(last_trade)[:10])


async def score_due(db, today: date | None = None) -> dict:
    """Score every expired idea with an option leg and no result yet, from the stored close on its expiration day. Returns counts."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.models.thesis import Thesis
    from app.services import price_bars
    today = today or date.today()
    rows = (await db.execute(select(Thesis).options(selectinload(Thesis.ticker)).where(
        Thesis.option_type.is_not(None), Thesis.option_expiration < today, Thesis.result.is_(None)))).scalars().all()
    scored = waiting = 0
    for t in rows:
        close = price_bars.close_on_date_sync(t.ticker.symbol, t.option_expiration.isoformat())
        if close is None or t.entry_premium is None or t.strike is None:
            waiting += 1
            continue
        t.result = score(option_type=t.option_type, strike=float(t.strike), entry_premium=float(t.entry_premium), contracts=t.contracts or 1,
                         close_at_expiration=float(close), entry_price=float(t.entry_price) if t.entry_price else None,
                         strike2=float(t.strike2) if t.strike2 is not None else None,
                         entry_premium2=float(t.entry_premium2) if t.entry_premium2 is not None else None,
                         priced_move_pct=float(t.priced_move_pct) if t.priced_move_pct is not None else None,
                         expiration=t.option_expiration, saved_on=t.created_at.date())
        scored += 1
    await db.commit()
    return {"scored": scored, "waiting_for_a_close": waiting}
