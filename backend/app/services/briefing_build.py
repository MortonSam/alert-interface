"""Gathers the stored rows a ticker's briefing rests on and composes the sentences (services/briefing).

Every input is a stored, dated row or the quote cache behind the same freshness test the quote endpoint uses; an
input that is absent, stale or excluded drops its clause.
"""
from __future__ import annotations

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
from app.services.implied_move import implied_move_allowed, straddle_implied_move
from app.services.next_earnings import NextEarnings, next_earnings_for
from app.services.fact_holds import holds_for
from app.services.price_history_exclusion import is_excluded
from app.services.rv_store import get_servable_rv
from app.services.ticker_aliases import resolve_symbol



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
    held = await holds_for(db, sym)                      # fail closed: a fact validate found wrong for this ticker is used nowhere below
    mismatch = await basis_mismatch_dates(db, ticker.id)
    rows = (await db.execute(text("""
        SELECT event_date, pct_change_1d, outcome::text AS outcome, eps_actual, eps_estimate, report_timing
        FROM historical_reactions WHERE ticker_id = :t AND event_type = 'earnings' ORDER BY event_date"""), {"t": ticker.id})).mappings().all()
    sample = [] if excluded or "typical_move" in held else [r for r in rows if r["pct_change_1d"] is not None and r["event_date"] not in mismatch]
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
        ne = await next_earnings_for(db, ticker.id, today) if "report_date" not in held else NextEarnings()
        if ne.date and 0 <= (ne.date - today).days <= B.NEXT_WITHIN_DAYS:
            ev_t = (await db.execute(select(Event.report_timing).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS, Event.event_date == ne.date))).scalar()
            implied = await _implied(db, sym, quote_price, ne.date, today) if implied_move_allowed(ne.confirmation) and "implied_move" not in held else {}   # never priced against an estimate
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


# ── the question strip ───────────────────────────────────────────────────────

async def build_questions(db: AsyncSession, symbol: str, today: date | None = None, *, raw: dict | None = None, all_candidates: bool = False) -> dict:
    """{symbol, name, questions: [...]}: the first four catalog questions this stock's data qualifies for (services/questions).
    With `raw` (a dict), the numbers behind the answers are recorded into it for services/ask_ivy's word-valued facts; with
    `all_candidates`, every qualifying question is returned, not only the first MAX_QUESTIONS."""
    from statistics import median
    from app.services import questions as Q
    today = today or date.today()
    sym = await resolve_symbol(db, symbol.upper())
    ticker = (await db.execute(select(Ticker).where(Ticker.symbol == sym))).scalar_one_or_none()
    if ticker is None or not ticker.is_active:
        return {"symbol": sym, "name": None, "questions": []}
    name = B.short_name(ticker.name) or sym

    q = await _quote(sym)
    quote_price = q.price if q and q.state == "ok" else None
    df = await price_bars.bars(db, sym, today - timedelta(days=B.WINDOW_52W_DAYS * Q.RANK_YEARS))
    facts = bar_facts(df, today)
    daily = daily_moves(df)

    excluded = await is_excluded(db, sym)
    held = await holds_for(db, sym)                      # fail closed (services/fact_holds): a held fact qualifies no question and reaches no Ask Ivy fact
    mismatch = await basis_mismatch_dates(db, ticker.id)
    rows = (await db.execute(text("""
        SELECT event_date, pct_change_1d, outcome::text AS outcome, report_timing FROM historical_reactions
        WHERE ticker_id = :t AND event_type = 'earnings' ORDER BY event_date"""), {"t": ticker.id})).mappings().all()
    sample = [] if excluded or "typical_move" in held else [r for r in rows if r["pct_change_1d"] is not None and r["event_date"] not in mismatch]
    moves = [float(r["pct_change_1d"]) for r in sample]
    sample_as_of = sample[-1]["event_date"] if sample else None
    typical_abs = sum(abs(m) for m in moves) / len(moves) if moves else None
    earnings_dates = (await db.execute(select(Event.event_date).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS,
                                                                       Event.event_date >= today - timedelta(days=60), Event.event_date <= today))).scalars().all()
    if raw is not None:
        raw.update(quote_price=quote_price, bars=facts, typical_abs=typical_abs, n_reports=len(moves), sample_as_of=sample_as_of)

    cands: list[dict | None] = []
    # 1. inside a report's window
    latest = max(earnings_dates, default=None)
    if latest is not None and B.in_reaction_window(latest, today) and typical_abs:
        hr = next((r for r in rows if r["event_date"] == latest), None)
        ev = (await db.execute(select(Event).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS, Event.event_date == latest))).scalars().first()
        timing = hr["report_timing"] if hr and hr["report_timing"] else (ev.report_timing if ev else None)
        move = _f(hr["pct_change_1d"]) if hr and hr["pct_change_1d"] is not None else move_from_bars(df, latest, timing)
        if move is not None:
            past = [abs(m) for r, m in zip(sample, moves) if r["event_date"] != latest]
            if raw is not None:
                raw.update(last_report={"event_date": latest, "timing": timing, "move_pct": move, "outcome": eps_outcome(_f(ev.eps_actual) if ev else None, _f(ev.eps_estimate) if ev else None)})
            cands.append(Q.q_reaction_normal(name=name, symbol=sym, event_date=latest, timing=timing, move_pct=move, typical_abs=typical_abs,
                                             larger_count=sum(1 for m in past if m > abs(move)), n_reports=len(past), sample_as_of=sample_as_of))
    # 2. a company-confirmed report within 45 days with a fresh implied move (an estimated date prices nothing: implied_move_allowed)
    ne = await next_earnings_for(db, ticker.id, today) if "report_date" not in held else NextEarnings()
    if raw is not None and ne.date:
        ev_t = (await db.execute(select(Event.report_timing).where(Event.ticker_id == ticker.id, Event.event_type == EventType.EARNINGS, Event.event_date == ne.date))).scalar()
        raw.update(next_report={"date": ne.date, "confirmation": ne.confirmation, "note": ne.note, "source": ne.source, "timing": ev_t})
    if ne.date and 0 <= (ne.date - today).days <= Q.NEXT_WITHIN_DAYS and typical_abs and implied_move_allowed(ne.confirmation) and "implied_move" not in held:
        implied = await _implied(db, sym, quote_price, ne.date, today)
        if raw is not None:
            raw.update(implied=implied or None)
        if implied:
            cands.append(Q.q_implied_big(name=name, symbol=sym, implied_pct=implied["implied_pct"], chain_date=implied["chain_date"], next_date=ne.date,
                                         typical_abs=typical_abs, n_reports=len(sample), sample_as_of=sample_as_of))
    # 3. beats followed by a fall
    beats = [r for r in sample if r["outcome"] == "beat"]
    cands.append(Q.q_beat_fell(name=name, symbol=sym, beats=len(beats), fell=sum(1 for r in beats if float(r["pct_change_1d"]) < 0), as_of=sample_as_of))
    # 4. a big non-earnings move
    exclude = set()
    for d in earnings_dates:
        exclude.add(d); exclude.add(nth_trading_day_after(d, 1))
    big = B.find_big_move(daily, exclude, today)
    if big and daily:
        all_abs = [abs(p) for d, p in daily if d > today - timedelta(days=366 * Q.RANK_YEARS)]
        smaller = sum(1 for a in all_abs if a < abs(big["move_pct"])) / len(all_abs) * 100
        cands.append(Q.q_big_move(name=name, symbol=sym, move_date=big["move_date"], move_pct=big["move_pct"], typical_abs=big["typical_abs"], multiple=big["multiple"],
                                  smaller_share=smaller, n_sessions=len(all_abs)))
    # 5. analyst upgrades
    ups = (await db.execute(text("""
        SELECT event_date FROM events WHERE ticker_id = :t AND event_type = 'analyst_action' AND metadata->>'action' = 'up' AND event_date >= :since"""),
        {"t": ticker.id, "since": today - timedelta(days=Q.UPGRADE_DAYS)})).scalars().all()
    stats = (await db.execute(text("SELECT upgrade_sessions, median_1d_upgrade, upgrade_5d_continuation_pct, upgrade_5d_sample, computed_at FROM analyst_reaction_stats WHERE symbol = :s"), {"s": sym})).mappings().first()
    if stats and stats["median_1d_upgrade"] is not None:
        cands.append(Q.q_upgrades(name=name, symbol=sym, upgrades_30d=len(ups), upgrade_sessions=stats["upgrade_sessions"] or 0, median_1d=float(stats["median_1d_upgrade"]),
                                  continuation_pct=_f(stats["upgrade_5d_continuation_pct"]), sample_5d=stats["upgrade_5d_sample"] or 0,
                                  stats_as_of=stats["computed_at"].date() if stats["computed_at"] else None, newest_upgrade=max(ups, default=None)))
    # 6. an ex-dividend date (hidden entirely while the dividend amount is held)
    exd = None if "dividend_amount" in held else (await db.execute(text("""
        SELECT event_date, (metadata->>'dividend_amount')::float AS amount, metadata->>'basis' AS basis, (metadata->>'declared_on')::date AS declared_on,
               metadata->>'declaration_accession' AS accession, COALESCE(updated_at, created_at)::date AS stored_on FROM events
        WHERE ticker_id = :t AND event_type = 'ex_dividend' AND event_date >= :today ORDER BY event_date LIMIT 1"""), {"t": ticker.id, "today": today})).mappings().first()
    if exd and raw is not None:
        raw.update(dividend={"ex_date": exd["event_date"], "declared_on": exd["declared_on"]})
    if exd:
        from app.scripts.seed_dividends import PER_PAYMENT_BASES
        amount = exd["amount"] if exd["basis"] in PER_PAYMENT_BASES else None       # an annual rate is never called a per-share dividend
        if amount is None:
            amount = _f(await db.scalar(text("SELECT dividend FROM price_bars_shadow WHERE symbol = :s AND dividend > 0 ORDER BY date DESC LIMIT 1"), {"s": sym}))
        cands.append(Q.q_ex_dividend(name=name, symbol=sym, ex_date=exd["event_date"], amount=amount, today=today,
                                     stored_on=min(exd["stored_on"], today) if exd["stored_on"] else None, declared_on=exd["declared_on"], accession=exd["accession"]))
    # 7. the usual move on earnings (evergreen)
    if moves and typical_abs:
        dated = [(r["event_date"], m) for r, m in zip(sample, moves)]
        cands.append(Q.q_usual_move(name=name, symbol=sym, typical_abs=typical_abs, n_reports=len(moves), best=max(dated, key=lambda x: x[1]),
                                    worst=min(dated, key=lambda x: x[1]), sample_as_of=sample_as_of))
    # 8. volatility against the stock's own year (evergreen)
    from app.services.rv_store import get_servable_rv
    rv_row, _ = await get_servable_rv(db, sym)
    if rv_row is not None and rv_row.rv_20d is not None and rv_row.rv_rank is not None:
        if raw is not None:
            raw.update(rv={"rv_20d": float(rv_row.rv_20d), "rv_rank": float(rv_row.rv_rank), "as_of": rv_row.as_of_date})
        cands.append(Q.q_volatile_now(name=name, symbol=sym, rv_20d=float(rv_row.rv_20d), rv_rank=float(rv_row.rv_rank), sample_days=int(rv_row.sample_days or 0), as_of=rv_row.as_of_date))
    # 9. trailing P/E against its history and its sector (evergreen; only a stored, fresh snapshot). Behind the PE_ENABLED flag: while it is
    #    off the snapshot is never read here, so neither the strip nor Ask Ivy (whose facts come from this function's candidates and `raw`) sees a P/E.
    from app.config import settings
    pe_row = None
    if settings.pe_enabled:
        pe_row = (await db.execute(text("""SELECT as_of_date, status, pe, window_start, window_end, window_source, hist_median, hist_share_above, hist_sessions, hist_excluded, hist_first, hist_last
            FROM pe_snapshots WHERE symbol = :s ORDER BY as_of_date DESC LIMIT 1"""), {"s": sym})).mappings().first()
    if pe_row and "pe" in held:
        pe_row = None                                                                        # fail closed: the P/E is held
    if pe_row and "release_eps" in held and str(pe_row["window_source"] or "").startswith("three XBRL quarters plus the release"):
        pe_row = None                                                                        # the window rests on a release figure validate found wrong
    if pe_row and pe_row["status"] == "ok" and pe_row["pe"] is not None:
        sec_row = (await db.execute(text("SELECT median_pe, shown, reason, fresh, active FROM pe_sector_snapshots WHERE sector = :sec ORDER BY as_of_date DESC LIMIT 1"),
                                    {"sec": ticker.sector or ""})).mappings().first()
        sector_median = float(sec_row["median_pe"]) if sec_row and sec_row["shown"] and sec_row["median_pe"] is not None else None
        if raw is not None:
            raw.update(pe={"pe": float(pe_row["pe"]), "as_of": pe_row["as_of_date"], "hist_median": _f(pe_row["hist_median"]), "sector": ticker.sector, "sector_median": sector_median})
        cands.append(Q.q_pe(name=name, symbol=sym, pe=float(pe_row["pe"]), window_start=pe_row["window_start"], window_end=pe_row["window_end"], as_of=pe_row["as_of_date"],
                            hist_median=_f(pe_row["hist_median"]), hist_share_above=pe_row["hist_share_above"], hist_sessions=pe_row["hist_sessions"], hist_excluded=pe_row["hist_excluded"],
                            hist_first=pe_row["hist_first"], hist_last=pe_row["hist_last"], sector=ticker.sector, sector_median=sector_median,
                            sector_fresh=(sec_row["fresh"] if sec_row and not sec_row["shown"] else None), sector_active=(sec_row["active"] if sec_row and not sec_row["shown"] else None)))
    return {"symbol": sym, "name": name, "questions": [c for c in cands if c] if all_candidates else Q.choose(cands)}
