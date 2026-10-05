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
from app.services.implied_move import straddle_implied_move
from app.services.next_earnings import next_earnings_for
from app.services.price_history_exclusion import is_excluded
from app.services.rv_store import get_servable_rv
from app.services.ticker_aliases import resolve_symbol

FEATURED_KEY = "featured_example"          # system_metadata: the home page's nightly pick, {symbol, earnings_date, picked_on, ...}
FEATURED_SENTENCES = ("catalyst", "pattern")


def _f(x) -> float | None:
    return None if x is None else float(x)


async def _quote(sym: str):
    from app.routers.tickers import _guarded_price            # the quote endpoint's own reader; lazy to avoid a cycle
    try:
        return await _guarded_price(sym)
    except Exception:
        return None


def bar_facts(df, today: date) -> dict:
    """last close and date, 52-week high (highest close) and its date, three-month change and its start, from an adjusted frame."""
    if df is None or df.empty or "Close" not in df:
        return {}
    closes = df["Close"].dropna()
    if closes.empty:
        return {}
    last_date = closes.index[-1].date()
    out = {"last_close": float(closes.iloc[-1]), "last_close_date": last_date}
    year = closes[closes.index.date >= today - timedelta(days=B.WINDOW_52W_DAYS)]
    if not year.empty:
        out["high_52w"] = float(year.max()); out["high_52w_date"] = year.idxmax().date()
    q = closes[closes.index.date >= today - timedelta(days=B.WINDOW_3M_DAYS)]
    if len(q) >= 2:
        out["change_3m_pct"] = (float(q.iloc[-1]) / float(q.iloc[0]) - 1) * 100; out["change_3m_from"] = q.index[0].date()
    return out


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
    """{symbol, name, sentences: [...]} for one ticker; sentences is empty when nothing is stored for it."""
    today = today or date.today()
    sym = await resolve_symbol(db, symbol.upper())
    ticker = (await db.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one_or_none()
    if ticker is None:
        return {"symbol": sym, "name": None, "sentences": []}
    sentences: list[dict] = []

    # 1. position
    q = await _quote(sym)
    df = await price_bars.bars(db, sym, today - timedelta(days=B.WINDOW_52W_DAYS + 7))
    facts = bar_facts(df, today)
    rv_row, _ = await get_servable_rv(db, sym)
    s = B.position_sentence(sym, quote_price=(q.price if q and q.state == "ok" else None), quote_ts=(q.traded_on_ts if q else None),
                            rv_rank=_f(rv_row.rv_rank) if rv_row is not None else None, rv_as_of=rv_row.as_of_date if rv_row is not None else None, **facts)
    if s:
        sentences.append(s)

    # the earnings sample: stored reactions with a 1-day move, EPS-basis-unclear quarters and excluded symbols left out
    excluded = await is_excluded(db, sym)
    mismatch = await basis_mismatch_dates(db, ticker.id)
    rows = (await db.execute(text("""
        SELECT event_date, pct_change_1d, outcome::text AS outcome, eps_actual, eps_estimate, report_timing
        FROM historical_reactions WHERE ticker_id = :t AND event_type = 'earnings' ORDER BY event_date"""), {"t": ticker.id})).mappings().all()
    sample = [] if excluded else [r for r in rows if r["pct_change_1d"] is not None and r["event_date"] not in mismatch]
    sample_as_of = sample[-1]["event_date"] if sample else None

    # 2. catalyst, or the reported state inside a report's reaction window
    latest = (await db.execute(select(Event).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS, Event.event_date <= today)
                               .order_by(Event.event_date.desc()).limit(1))).scalar_one_or_none()
    if latest is not None and B.in_reaction_window(latest.event_date, today):
        hr = next((r for r in rows if r["event_date"] == latest.event_date), None)
        sentences.append(B.reported_sentence(
            today=today, event_date=latest.event_date, timing=(hr["report_timing"] if hr and hr["report_timing"] else latest.report_timing),
            eps_actual=_f(hr["eps_actual"] if hr else getattr(latest, "eps_actual", None)), eps_estimate=_f(hr["eps_estimate"] if hr else getattr(latest, "eps_estimate", None)),
            outcome=(hr["outcome"] if hr else getattr(getattr(latest, "outcome", None), "value", getattr(latest, "outcome", None))),
            pct_change_1d=_f(hr["pct_change_1d"]) if hr else None))
    else:
        ne = await next_earnings_for(db, ticker.id, today)
        timing = None
        if ne.date:
            ev = (await db.execute(select(Event.report_timing).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS, Event.event_date == ne.date))).scalar()
            timing = ev if ev in B.TIMING_PHRASE else None
        implied = await _implied(db, sym, q.price if q and q.state == "ok" else None, ne.date or today + timedelta(days=7), today)
        avg_abs = sum(abs(float(r["pct_change_1d"])) for r in sample) / len(sample) if sample else None
        s = B.catalyst_sentence(today=today, next_date=ne.date, confirmation=ne.confirmation, note=ne.note, source=ne.source, timing=timing,
                                avg_abs_1d=avg_abs, sample_n=len(sample), sample_as_of=sample_as_of, **implied)
        if s:
            sentences.append(s)

    # 3. pattern
    beats = [r for r in sample if r["outcome"] == "beat"]
    s = B.pattern_sentence(total=len(sample), beat_count=len(beats), fell_after_beat=sum(1 for r in beats if float(r["pct_change_1d"]) < 0),
                           as_of=sample_as_of, basis_excluded=sum(1 for r in rows if r["event_date"] in mismatch and r["pct_change_1d"] is not None))
    if s:
        sentences.append(s)

    # 4. street
    acts = (await db.execute(text("""
        SELECT event_date, metadata->>'action' AS action, metadata->>'price_target' AS price_target FROM events
        WHERE ticker_id = :t AND event_type = 'analyst_action' AND event_date >= :since"""), {"t": ticker.id, "since": today - timedelta(days=B.STREET_DAYS)})).mappings().all()
    stats = (await db.execute(text("SELECT median_1d_upgrade, upgrade_sessions, computed_at FROM analyst_reaction_stats WHERE symbol = :s"), {"s": sym})).mappings().first()
    s = B.street_sentence(today=today, actions=[{"date": a["event_date"], "action": a["action"], "price_target": a["price_target"]} for a in acts],
                          median_1d_upgrade=_f(stats["median_1d_upgrade"]) if stats else None, upgrade_sessions=stats["upgrade_sessions"] if stats else None,
                          stats_as_of=stats["computed_at"].date() if stats and stats["computed_at"] else None)
    if s:
        sentences.append(s)

    # 5. risk
    s = B.risk_sentence(moves=[(r["event_date"], float(r["pct_change_1d"])) for r in sample])
    if s:
        sentences.append(s)
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
