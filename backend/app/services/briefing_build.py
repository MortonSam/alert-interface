"""Gathers the stored rows a ticker's briefing rests on and composes the sentences (services/briefing).

Every input is a stored, dated row or the quote cache behind the same freshness test the quote endpoint uses; an
input that is absent, stale or excluded drops its clause. The home page's featured example reads the same builder.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import EventType
from app.models.event import Event
from app.models.ticker import Ticker
from app.services import briefing as B
from app.services import chain_store, price_bars
from app.services.basis_exclusion import basis_mismatch_dates
from app.services.eps_actuals import eps_outcome
from app.services.implied_move import straddle_implied_move
from app.services.next_earnings import next_earnings_for
from app.services.price_history_exclusion import is_excluded
from app.services.rv_store import get_servable_rv
from app.services.ticker_aliases import resolve_symbol

FEATURED_KEY = "featured_example"          # system_metadata: the home page's nightly pick, {symbol, earnings_date, picked_on, ...}
FEATURED_SENTENCES = ("profile", "happening")       # the home block shows the same two blocks


def _f(x) -> float | None:
    return None if x is None else float(x)


async def _quote(sym: str):
    from app.routers.tickers import _guarded_price            # the quote endpoint's own reader; lazy to avoid a cycle
    try:
        return await _guarded_price(sym)
    except Exception:
        return None


def bar_facts(df, today: date) -> dict:
    """last close and date, the 52-week high (highest close) and its date, and the three-month anchor close and date,
    from an adjusted frame. The quote is compared with these in the sentence; the last close is a receipt."""
    if df is None or df.empty or "Close" not in df:
        return {}
    closes = df["Close"].dropna()
    if closes.empty:
        return {}
    out = {"last_close": float(closes.iloc[-1]), "last_close_date": closes.index[-1].date()}
    year = closes[closes.index.date >= today - timedelta(days=B.WINDOW_52W_DAYS)]
    if not year.empty:
        out["high_52w"] = float(year.max()); out["high_52w_date"] = year.idxmax().date()
    q = closes[closes.index.date >= today - timedelta(days=B.WINDOW_3M_DAYS)]
    if not q.empty:
        out["anchor_close_3m"] = float(q.iloc[0]); out["anchor_date_3m"] = q.index[0].date()
    return out


def move_from_bars(df, event_date: date, timing: str | None) -> float | None:
    """The 1-day move from the stored bars through the seeder's own window function; None unless both bars exist."""
    if df is None or df.empty or timing not in B.TIMING_PHRASE:
        return None
    from app.scripts.seed_historical_reactions import _build_date_cache, _compute_v3, load_reference_sessions   # the seeder's window, not a copy
    try:
        data = _compute_v3(df, _build_date_cache(df), event_date, timing, load_reference_sessions())
    except Exception:
        return None
    pct = (data or {}).get("pct_change_1d")
    return float(pct) if pct is not None else None


async def _implied(db: AsyncSession, sym: str, spot: float | None, min_date: date, today: date) -> dict:
    exp = await chain_store.pick_expiration(db, sym, min_date.isoformat())
    if not exp:
        return {}
    got = await chain_store.get_chain(db, sym, exp)
    if not got or not got[1] or not chain_store.is_fresh(got[1], today=today):
        return {}
    im = straddle_implied_move(got[0].get("calls") or [], got[0].get("puts") or [], spot)
    if im is None:
        return {}
    return {"implied_pct": im.pct, "chain_date": date.fromisoformat(str(got[1])[:10]), "expiration": date.fromisoformat(exp)}


async def build_briefing(db: AsyncSession, symbol: str, today: date | None = None) -> dict:
    """{symbol, name, sentences: [profile?, happening?]} for one ticker; empty when nothing is stored for it."""
    today = today or date.today()
    sym = await resolve_symbol(db, symbol.upper())
    ticker = (await db.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one_or_none()
    if ticker is None:
        return {"symbol": sym, "name": None, "sentences": []}
    sentences: list[dict] = []

    # block 1: what it is
    prof = (await db.execute(text("SELECT short_description, sector, industry_group, industry_category, fetched_at FROM company_profiles WHERE symbol = :s"), {"s": sym})).mappings().first()
    if prof:
        s1 = B.profile_sentence(short_description=prof["short_description"], sector=prof["sector"], industry=prof["industry_category"] or prof["industry_group"],   # the category reads as a name; the group is a SIC phrase
                                profile_as_of=prof["fetched_at"].date() if prof["fetched_at"] else None,
                                market_cap=_f(ticker.market_cap), market_cap_as_of=ticker.market_cap_updated_at.date() if ticker.market_cap_updated_at else None)
        if s1:
            sentences.append(s1)

    # block 2: what's been happening
    q = await _quote(sym)
    df = await price_bars.bars(db, sym, today - timedelta(days=B.WINDOW_52W_DAYS + 7))
    facts = bar_facts(df, today)
    price = {"quote_price": q.price if q and q.state == "ok" else None, "quote_ts": q.traded_on_ts if q else None, **facts}

    excluded = await is_excluded(db, sym)
    mismatch = await basis_mismatch_dates(db, ticker.id)
    rows = (await db.execute(text("""
        SELECT event_date, pct_change_1d, outcome::text AS outcome, eps_actual, eps_estimate, report_timing
        FROM historical_reactions WHERE ticker_id = :t AND event_type = 'earnings' ORDER BY event_date"""), {"t": ticker.id})).mappings().all()
    sample = [] if excluded else [r for r in rows if r["pct_change_1d"] is not None and r["event_date"] not in mismatch]
    sample_as_of = sample[-1]["event_date"] if sample else None

    reported = upcoming = None
    latest = (await db.execute(select(Event).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS, Event.event_date <= today)
                               .order_by(Event.event_date.desc()).limit(1))).scalar_one_or_none()
    if latest is not None and B.in_reaction_window(latest.event_date, today):
        hr = next((r for r in rows if r["event_date"] == latest.event_date), None)
        timing = hr["report_timing"] if hr and hr["report_timing"] else latest.report_timing
        actual = _f(latest.eps_actual if latest.eps_actual is not None else (hr["eps_actual"] if hr else None))
        estimate = _f(latest.eps_estimate if latest.eps_estimate is not None else (hr["eps_estimate"] if hr else None))
        stored = _f(hr["pct_change_1d"]) if hr else None
        reported = {"today": today, "event_date": latest.event_date, "timing": timing, "eps_actual": actual, "eps_estimate": estimate,
                    "outcome": eps_outcome(actual, estimate), "bars_through": facts.get("last_close_date"),
                    "pct_change_1d": stored if stored is not None else move_from_bars(df, latest.event_date, timing)}
    else:
        ne = await next_earnings_for(db, ticker.id, today)
        if ne.date:
            ev = (await db.execute(select(Event.report_timing).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS, Event.event_date == ne.date))).scalar()
            implied = await _implied(db, sym, q.price if q and q.state == "ok" else None, ne.date, today)
            avg_abs = sum(abs(float(r["pct_change_1d"])) for r in sample) / len(sample) if sample else None
            upcoming = {"today": today, "next_date": ne.date, "confirmation": ne.confirmation, "note": ne.note, "source": ne.source,
                        "timing": ev if ev in B.TIMING_PHRASE else None, "avg_abs_1d": avg_abs, "sample_n": len(sample), "sample_as_of": sample_as_of, **implied}
    s2 = B.happening_sentence(sym, price=price, reported=reported, upcoming=upcoming)
    if s2:
        sentences.append(s2)
    return {"symbol": sym, "name": ticker.name, "sentences": sentences}


async def featured_example(db: AsyncSession, today: date | None = None) -> dict:
    """The home page's example: the nightly pick from system_metadata with its catalyst and pattern sentences; symbol None when none qualifies."""
    from app.services.system_metadata_service import get_value
    raw = await get_value(db, FEATURED_KEY)
    pick = json.loads(raw) if raw else {}
    if not pick.get("symbol"):
        return {"symbol": None, "name": None, "picked_on": None, "earnings_date": None, "rule": pick.get("rule"), "sentences": []}
    brief = await build_briefing(db, pick["symbol"], today)
    return {"symbol": brief["symbol"], "name": brief["name"], "picked_on": pick.get("picked_on"), "earnings_date": pick.get("earnings_date"),
            "rule": pick.get("rule"), "sentences": [s for s in brief["sentences"] if s["key"] in FEATURED_SENTENCES]}
