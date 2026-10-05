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
from app.services.trading_calendar import nth_trading_day_after
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


def daily_moves(df) -> list[tuple[date, float]]:
    """[(session, close-to-close percent move)] ascending from an adjusted frame."""
    if df is None or df.empty or "Close" not in df:
        return []
    closes = df["Close"].dropna()
    pct = closes.pct_change().dropna() * 100
    return [(ts.date(), float(v)) for ts, v in pct.items()]


async def build_briefing(db: AsyncSession, symbol: str, today: date | None = None) -> dict:
    """{symbol, name, state, sentences: [profile?, happening?]}; an inactive ticker returns no sentences and its state."""
    today = today or date.today()
    sym = await resolve_symbol(db, symbol.upper())
    ticker = (await db.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one_or_none()
    if ticker is None:
        return {"symbol": sym, "name": None, "state": None, "sentences": []}
    if not ticker.is_active:
        return {"symbol": sym, "name": ticker.name, "state": ticker.inactive_reason or "not an active ticker", "sentences": []}
    sentences: list[dict] = []

    # the quote serves both blocks: the market value and sentence A
    q = await _quote(sym)
    quote_price = q.price if q and q.state == "ok" else None
    quote_ts = q.traded_on_ts if q else None

    # block 1: what it is (description from the stored Intrinio profile; sector and sub-industry are GICS from the constituent list)
    prof = (await db.execute(text("SELECT short_description, source, fetched_at FROM company_profiles WHERE symbol = :s"), {"s": sym})).mappings().first()
    if prof:
        s1 = B.profile_sentence(name=ticker.name, short_description=prof["short_description"], profile_as_of=prof["fetched_at"].date() if prof["fetched_at"] else None,
                                profile_source=(prof["source"] or "intrinio").capitalize(), gics_sector=ticker.sector, gics_sub_industry=ticker.industry,
                                gics_as_of=ticker.updated_at.date() if ticker.updated_at else None, index_member=bool(ticker.index_member),
                                quote_price=quote_price, quote_ts=quote_ts, shares_outstanding=_f(ticker.shares_outstanding),
                                shares_as_of=ticker.shares_as_of.date() if ticker.shares_as_of else None)
        if s1:
            sentences.append(s1)

    # block 2: what's been happening
    df = await price_bars.bars(db, sym, today - timedelta(days=B.WINDOW_52W_DAYS + 7))
    facts = bar_facts(df, today)
    stock = {"quote_price": quote_price, "quote_ts": quote_ts, **facts}

    excluded = await is_excluded(db, sym)
    mismatch = await basis_mismatch_dates(db, ticker.id)
    rows = (await db.execute(text("""
        SELECT event_date, pct_change_1d, outcome::text AS outcome, eps_actual, eps_estimate, report_timing
        FROM historical_reactions WHERE ticker_id = :t AND event_type = 'earnings' ORDER BY event_date"""), {"t": ticker.id})).mappings().all()
    sample = [] if excluded else [r for r in rows if r["pct_change_1d"] is not None and r["event_date"] not in mismatch]
    sample_as_of = sample[-1]["event_date"] if sample else None
    earnings_dates = (await db.execute(select(Event.event_date).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS,
                                                                       Event.event_date >= today - timedelta(days=60), Event.event_date <= today))).scalars().all()

    reported = big = upcoming = None
    latest = max(earnings_dates, default=None)
    if latest is not None and B.in_reaction_window(latest, today):
        ev = (await db.execute(select(Event).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS, Event.event_date == latest))).scalars().first()
        hr = next((r for r in rows if r["event_date"] == latest), None)
        timing = hr["report_timing"] if hr and hr["report_timing"] else (ev.report_timing if ev else None)
        actual = _f(ev.eps_actual if ev and ev.eps_actual is not None else (hr["eps_actual"] if hr else None))
        estimate = _f(ev.eps_estimate if ev and ev.eps_estimate is not None else (hr["eps_estimate"] if hr else None))
        stored = _f(hr["pct_change_1d"]) if hr else None
        reported = {"today": today, "event_date": latest, "timing": timing, "eps_actual": actual, "eps_estimate": estimate, "outcome": eps_outcome(actual, estimate),
                    "bars_through": facts.get("last_close_date"), "pct_change_1d": stored if stored is not None else move_from_bars(df, latest, timing)}
    else:
        ne = await next_earnings_for(db, ticker.id, today)
        if ne.date and 0 <= (ne.date - today).days <= B.NEXT_WITHIN_DAYS:
            ev_t = (await db.execute(select(Event.report_timing).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS, Event.event_date == ne.date))).scalar()
            implied = await _implied(db, sym, quote_price, ne.date, today)
            avg_abs = sum(abs(float(r["pct_change_1d"])) for r in sample) / len(sample) if sample else None
            upcoming = {"today": today, "next_date": ne.date, "confirmation": ne.confirmation, "note": ne.note, "source": ne.source,
                        "timing": ev_t if ev_t in B.TIMING_PHRASE else None, "avg_abs_1d": avg_abs, "sample_n": len(sample), "sample_as_of": sample_as_of, **implied}
        exclude = set()
        for d in earnings_dates:
            exclude.add(d); exclude.add(nth_trading_day_after(d, 1))
        big = B.find_big_move(daily_moves(df), exclude, today)
    s2 = B.happening_sentence(sym, stock=stock, reported=reported, big_move=big, upcoming=upcoming)
    if s2:
        sentences.append(s2)
    return {"symbol": sym, "name": ticker.name, "state": None, "sentences": sentences}


async def featured_example(db: AsyncSession, today: date | None = None) -> dict:
    """The home page's example: the nightly pick from system_metadata with its catalyst and pattern sentences; symbol None when none qualifies."""
    from app.services.system_metadata_service import get_value
    raw = await get_value(db, FEATURED_KEY)
    pick = json.loads(raw) if raw else {}
    if not pick.get("symbol"):
        return {"symbol": None, "name": None, "state": None, "picked_on": None, "earnings_date": None, "rule": pick.get("rule"), "sentences": []}
    brief = await build_briefing(db, pick["symbol"], today)
    return {"symbol": brief["symbol"], "name": brief["name"], "state": brief.get("state"), "picked_on": pick.get("picked_on"), "earnings_date": pick.get("earnings_date"),
            "rule": pick.get("rule"), "sentences": [s for s in brief["sentences"] if s["key"] in FEATURED_SENTENCES]}
