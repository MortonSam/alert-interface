"""Ivy's walkthrough and Compare, served from the stored nightly build (services/walkthrough, scripts/build_walkthroughs).

    GET /walkthrough/{symbol}                 the seven steps, the summary, and Compare's two choices
    GET /walkthrough/compare?a=MU&b=AAPL      both stocks' rows side by side, Ivy's sentence for the pair when one was verified
    GET /walkthrough-featured                 the home page's stock, chosen nightly by walkthrough_compare.FEATURED_RULE

GROWTH_ENABLED and PE_ENABLED apply here (gate), at serve time: while one is off its step is the honest in-review line, its
Compare row is blank and the summary marks it. Nothing here calls a model or fetches a price.
"""
from __future__ import annotations

import copy
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import is_admin
from app.config import settings
from app.database import get_db
from app.services import walkthrough as W

router = APIRouter(tags=["walkthrough"])


def gate(payload: dict, growth_on: bool, pe_on: bool) -> dict:
    """Pure: the payload as served: growth and the P/E replaced by their in-review line while their flag is off."""
    out = copy.deepcopy(payload)
    name = out["name"]
    for i, s in enumerate(out["steps"]):
        if s["key"] == "growth" and not growth_on:
            out["steps"][i] = W.step_growth(name, None, out.get("sector"), False)
        if s["key"] == "valuation" and not pe_on:
            out["steps"][i] = W.step_valuation(name, out.get("sector"), None, [], None, False)
    rows = out["compare"]["rows"]
    if not growth_on:
        rows["growth"] = None
    if not pe_on:
        rows["pe"] = None
    out["summary"] = W.summary(name, out["steps"])
    return out


async def _payload(db: AsyncSession, symbol: str) -> dict | None:
    row = (await db.execute(text("SELECT payload FROM ivy_walkthroughs WHERE symbol = :s"), {"s": symbol.upper()})).scalar()
    return gate(row, settings.growth_enabled, settings.pe_enabled) if row else None


@router.get("/walkthrough/compare")
async def compare(a: str = Query(..., max_length=10), b: str = Query(..., max_length=10), db: AsyncSession = Depends(get_db)) -> dict:
    pa, pb = await _payload(db, a), await _payload(db, b)
    if not pa or not pb:
        raise HTTPException(status_code=404, detail="No walkthrough for one of these stocks")
    story = (await db.execute(text("SELECT sentence FROM ivy_compare_stories WHERE symbol = :a AND other = :b"), {"a": pa["symbol"], "b": pb["symbol"]})).scalar()
    title, idea = W.COMPARE_IDEA
    return {"a": pa["compare"], "b": pb["compare"], "rows": [{"key": k, "label": label} for k, label in W.COMPARE_ROWS], "missing": W.COMPARE_MISSING,
            "story": story, "idea": {"concept": "comparing", "title": title, "text": idea}}


@router.get("/walkthrough/{symbol}")
async def walkthrough(symbol: str, db: AsyncSession = Depends(get_db), admin: bool = Depends(is_admin)) -> dict:
    from app.services.walkthrough_compare import RIVAL_RULE, rival_for, ruler_for
    p = await _payload(db, symbol)
    if not p:
        raise HTTPException(status_code=404, detail=f"No walkthrough for {symbol.upper()}")
    tickers = {r.symbol: dict(r._mapping) for r in (await db.execute(text(
        "SELECT symbol, name, sector, industry, market_cap, index_member FROM tickers WHERE is_active"))).all()}
    have = set((await db.execute(text("SELECT symbol FROM ivy_walkthroughs"))).scalars().all())
    rival = rival_for(p["symbol"], tickers, have)
    ruler = ruler_for(p["symbol"])
    from app.services.briefing import short_name
    choices = []
    if rival:
        choices.append({"kind": "rival", "symbol": rival["symbol"], "name": short_name(tickers[rival["symbol"]]["name"], rival["symbol"]), "basis": rival["basis"],
                        "rule": RIVAL_RULE})
    if ruler in have and ruler in tickers:
        choices.append({"kind": "ruler", "symbol": ruler, "name": short_name(tickers[ruler]["name"], ruler)})
    return {**p, "known_concept_line": W.KNOWN_CONCEPT_LINE, "compare_choices": choices, "ask_enabled": bool(settings.ask_ivy_enabled or admin)}


@router.get("/walkthrough-featured")
async def featured(db: AsyncSession = Depends(get_db)) -> dict:
    raw = (await db.execute(text("SELECT value, updated_at FROM system_metadata WHERE key = 'ivy_featured'"))).first()
    pick = json.loads(raw[0]) if raw and raw[0] else {}
    sym = pick.get("symbol")
    if not sym:
        return {"symbol": None, "name": None, "rule": pick.get("rule"), "date": pick.get("date")}
    name = (await db.execute(text("SELECT payload->>'name' FROM ivy_walkthroughs WHERE symbol = :s"), {"s": sym})).scalar()
    return {"symbol": sym if name else None, "name": name, "rule": pick.get("rule"), "date": pick.get("date"), "minutes": W.MINUTES}
