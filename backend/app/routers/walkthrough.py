"""Ivy's walkthrough and Compare, served from the stored nightly build (services/walkthrough, scripts/build_walkthroughs).

    GET /walkthrough/{symbol}                 the seven steps, the summary, and Compare's two choices
    GET /walkthrough/compare?a=MU&b=AAPL      both stocks' rows side by side, Ivy's sentence for the pair when one was verified
    GET /walkthrough-featured                 the home page's stock, chosen nightly by walkthrough_compare.FEATURED_RULE
    GET /ivy-page                             the /ivy page's live parts: quick picks, the seven ideas with an example step each, and
                                              the counts behind "why you can trust her", each with its own date

IVY_WALKTHROUGH_ENABLED (off in production until the wording is approved) hides all three from everyone but the admin token.
GROWTH_ENABLED and PE_ENABLED apply here (gate), at serve time: while one is off its step is the honest in-review line, its
Compare row is blank and the summary marks it. `entry` says whether a ticker page offers the walkthrough (at least
W.ENTRY_MIN_STEPS steps shown after the flags). Nothing here calls a model or fetches a price.
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


def gate(payload: dict, growth_on: bool, pe_on: bool, now=None) -> dict:
    """Pure: the payload as served: growth and the P/E replaced by their in-review line while their flag is off (a real estate
    trust's price to FFO is not a P/E and stays). Step 7's check never points at a figure the flags hide. Step 6's next Fed
    decision is the next one as of `now` (New York; the request's time by default), never one a stored build named that has passed."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    out = copy.deepcopy(payload)
    now = now or datetime.now(ZoneInfo("America/New_York"))
    for s in out["steps"]:
        if s["key"] == "upcoming":
            W.with_fed(s, W.next_fed_day(now))
    name = out["name"]
    reit = bool(out.get("reit"))
    noun = out.get("noun") or "sales"
    hidden = set()
    for i, s in enumerate(out["steps"]):
        if s["key"] == "growth" and not growth_on:
            out["steps"][i] = W.step_growth(name, None, out.get("sector"), False, noun=noun)
            hidden.add("growth")
        if s["key"] == "valuation" and not pe_on and not reit:
            out["steps"][i] = W.step_valuation(name, out.get("sector"), None, [], None, False)
            hidden.add("valuation")
    rows = out["compare"]["rows"]
    if "growth" in hidden:
        rows["growth"] = {}
    if "valuation" in hidden:
        rows["valuation"] = {}
    risks = next(s for s in out["steps"] if s["key"] == "risks")
    gone = {s.get("point") for s in payload["steps"] if s["key"] in hidden} - {None}
    if risks.get("check") and gone & set(risks["check"]["options"]):
        headings = {int(k): v for k, v in (risks.get("headings") or {}).items()}
        risks["check"] = W.risk_check(name, risks.get("risks") or [], headings, out["steps"], noun)
    out["summary"] = W.summary(name, out["steps"])
    out["entry"] = W.steps_shown(out["steps"]) >= W.ENTRY_MIN_STEPS
    return out


async def _payload(db: AsyncSession, symbol: str) -> dict | None:
    row = (await db.execute(text("SELECT payload FROM ivy_walkthroughs WHERE symbol = :s"), {"s": symbol.upper()})).scalar()
    return gate(row, settings.growth_enabled, settings.pe_enabled) if row else None


def _shown(admin: bool) -> None:
    if not (settings.ivy_walkthrough_enabled or admin):
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/walkthrough/compare")
async def compare(a: str = Query(..., max_length=10), b: str = Query(..., max_length=10), db: AsyncSession = Depends(get_db),
                  admin: bool = Depends(is_admin)) -> dict:
    _shown(admin)
    pa, pb = await _payload(db, a), await _payload(db, b)
    if not pa or not pb:
        raise HTTPException(status_code=404, detail="No walkthrough for one of these stocks")
    story = (await db.execute(text("SELECT sentence FROM ivy_compare_stories WHERE symbol = :a AND other = :b"), {"a": pa["symbol"], "b": pb["symbol"]})).scalar()
    title, idea = W.COMPARE_IDEA
    table = W.compare_table(pa["compare"], pb["compare"])
    side = lambda p, k: {**{f: p["compare"][f] for f in ("symbol", "name", "reit")}, "rows": {r["key"]: r[k] for r in table}}
    return {"a": side(pa, "a"), "b": side(pb, "b"), "rows": [{"key": r["key"], "label": r["label"]} for r in table], "missing": W.COMPARE_MISSING,
            "story": story, "idea": {"concept": "comparing", "title": title, "text": idea}}


@router.get("/walkthrough/{symbol}")
async def walkthrough(symbol: str, db: AsyncSession = Depends(get_db), admin: bool = Depends(is_admin)) -> dict:
    from app.services.walkthrough_compare import RIVAL_RULE, rival_for, ruler_for
    _shown(admin)
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
        me = tickers.get(p["symbol"]) or {}
        choices.append({"kind": "rival", "symbol": rival["symbol"], "name": short_name(tickers[rival["symbol"]]["name"], rival["symbol"]), "basis": rival["basis"],
                        "label": W.another(me.get("industry") if rival["basis"] == "sub-industry" else None, me.get("sector")), "rule": RIVAL_RULE})
    if ruler in have and ruler in tickers:
        choices.append({"kind": "ruler", "symbol": ruler, "name": short_name(tickers[ruler]["name"], ruler)})
    return {**p, "compare_choices": choices, "ask_enabled": bool(settings.ask_ivy_enabled or admin)}


@router.get("/walkthrough-featured")
async def featured(db: AsyncSession = Depends(get_db), admin: bool = Depends(is_admin)) -> dict:
    if not (settings.ivy_walkthrough_enabled or admin):
        return {"symbol": None, "name": None, "rule": None, "date": None}
    raw = (await db.execute(text("SELECT value, updated_at FROM system_metadata WHERE key = 'ivy_featured'"))).first()
    pick = json.loads(raw[0]) if raw and raw[0] else {}
    sym = pick.get("symbol")
    if not sym:
        return {"symbol": None, "name": None, "rule": pick.get("rule"), "date": pick.get("date")}
    name = (await db.execute(text("SELECT payload->>'name' FROM ivy_walkthroughs WHERE symbol = :s"), {"s": sym})).scalar()
    return {"symbol": sym if name else None, "name": name, "rule": pick.get("rule"), "date": pick.get("date"), "minutes": W.MINUTES}


IVY_QUICK_PICKS = ("NVDA", "AAPL", "JPM")          # the /ivy page's quick picks (Sam, 2026-11-02), offered only with a walkthrough entry
_ENTRY_CACHE: dict = {}


async def _entries(db: AsyncSession) -> tuple[int, str | None]:
    """How many stored walkthroughs a ticker page offers (gate's entry, with today's flags) and the latest as_of among them; computed
    once per nightly build (the cache key is the table's latest as_of, its row count and the flags)."""
    stamp = (await db.execute(text("SELECT max(as_of)::text, count(*) FROM ivy_walkthroughs"))).first()
    key = (stamp[0], stamp[1], settings.growth_enabled, settings.pe_enabled)
    if _ENTRY_CACHE.get("key") != key:
        n, latest = 0, None
        for payload, as_of in (await db.execute(text("SELECT payload, as_of::text FROM ivy_walkthroughs"))).all():
            if gate(payload, settings.growth_enabled, settings.pe_enabled)["entry"]:
                n += 1
                latest = max(latest or as_of, as_of)
        _ENTRY_CACHE.update(key=key, value=(n, latest))
    return _ENTRY_CACHE["value"]


@router.get("/ivy-page")
async def ivy_page(db: AsyncSession = Depends(get_db), admin: bool = Depends(is_admin)) -> dict:
    """The /ivy page's live parts. quick_picks: IVY_QUICK_PICKS that have a walkthrough entry. ideas: for each of the seven steps, its
    idea from the first quick pick (then the featured stock) where that step shows data, with the step to open. trust: counts of
    stored records, each with the date it is as of: served research notes (complete and checked), the statements in them the checker
    confirmed against the filings, and the stocks with a walkthrough entry."""
    _shown(admin)
    examples = list(IVY_QUICK_PICKS)
    raw = (await db.execute(text("SELECT value FROM system_metadata WHERE key = 'ivy_featured'"))).scalar()
    featured = (json.loads(raw) if raw else {}).get("symbol")
    if featured and featured not in examples:
        examples.append(featured)
    payloads = {sym: p for sym in examples if (p := await _payload(db, sym))}
    quick = [{"symbol": s, "name": payloads[s]["name"]} for s in IVY_QUICK_PICKS if s in payloads and payloads[s]["entry"]]
    ideas = []
    for n in range(1, 8):
        for sym in examples:
            p = payloads.get(sym)
            step = next((x for x in (p or {}).get("steps", []) if x["n"] == n), None) if p and p["entry"] else None
            if step and step["status"] != "absent" and step.get("idea"):
                ideas.append({"n": n, "key": step["key"], "concept": step["idea"]["concept"], "title": step["idea"]["title"],
                              "text": step["idea"]["text"], "symbol": sym, "name": p["name"]})
                break
    notes = (await db.execute(text("""SELECT count(*), COALESCE(sum((verification->'summary'->>'supported')::int), 0), max(verified_at)::date::text
        FROM research_notes WHERE status = 'complete' AND verification IS NOT NULL"""))).first()
    walks, walks_as_of = await _entries(db)
    return {"minutes": W.MINUTES, "quick_picks": quick, "ideas": ideas,
            "trust": {"notes": {"count": notes[0], "as_of": notes[2]}, "confirmed": {"count": int(notes[1]), "as_of": notes[2]},
                      "walkthroughs": {"count": walks, "as_of": walks_as_of}}}
