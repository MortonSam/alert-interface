"""What Ivy's walkthrough reads, per stock, from stored and dated sources (services/walkthrough builds the steps from it).

Nothing here fetches a price. Prices come from the stored Intrinio bars (services/price_bars), the implied move from the stored
options chain, growth from growth_figures, the P/E from pe_snapshots and its daily series from the same quarters and closes
compute_pe used. The SEC reads (the 10-K's segments and risk factors, the company facts for margins) are the only network calls,
and a 10-K whose accession is already stored is never read again.
"""
from __future__ import annotations

from datetime import date, timedelta
from statistics import median

from sqlalchemy import text

from app.services import price_bars
from app.services import valuation as V

YEAR_SESSIONS = 252
QUARTER_SESSIONS = 63
BARS_LOOKBACK_DAYS = 400
BIG_MOVES_SHOWN = 3
STALE_BAR_DAYS = 7                  # a stock whose last stored close is this much older than SPY's is not compared


async def load_universe(db, today: date) -> dict:
    """Everything shared across stocks, read once per run: tickers, profiles, mergers and recorded corporate actions, adjusted
    closes for every active stock and SPY, sector medians, growth, P/E snapshots, sector P/E medians and next reports."""
    from app.services.market_day import BENCHMARK
    from app.services.next_earnings import batch_next_earnings
    from app.services.ticker_exits import MERGED, REASON_PREFIXES
    tickers = {r.symbol: dict(r._mapping) for r in (await db.execute(text(
        "SELECT id, symbol, name, sector, industry, market_cap, index_member FROM tickers WHERE is_active ORDER BY symbol"))).all()}
    syms = list(tickers)
    profiles = {r.symbol: dict(r._mapping) for r in (await db.execute(text(
        "SELECT symbol, short_description, fetched_at, latest_filing_date FROM company_profiles WHERE symbol = ANY(:s)"), {"s": syms})).all()}
    mergers: dict[str, dict] = {}
    for r in (await db.execute(text("""SELECT a.symbol, o.name, a.renamed_on FROM ticker_aliases a JOIN tickers o ON o.symbol = a.old_symbol
            WHERE o.inactive_reason LIKE :m ORDER BY a.renamed_on"""), {"m": REASON_PREFIXES[MERGED] + "%"})).all():
        mergers[r.symbol] = {"name": r.name, "date": r.renamed_on}
    actions: dict[str, list[dict]] = {}
    for r in (await db.execute(text("""SELECT t.symbol, e.event_date, COALESCE(e.metadata->>'corporate_action', 'spin_off') AS kind, e.metadata->>'counterparty' AS name
            FROM events e JOIN tickers t ON t.id = e.ticker_id WHERE t.symbol = ANY(:s) AND (e.event_type = 'spin_off' OR (e.event_type = 'other' AND e.metadata ? 'corporate_action'))"""),
            {"s": syms})).all():
        actions.setdefault(r.symbol, []).append({"kind": r.kind, "date": r.event_date, "name": r.name})
    for r in (await db.execute(text("SELECT symbol, old_symbol, renamed_on FROM ticker_aliases WHERE symbol = ANY(:s)"), {"s": syms})).all():
        actions.setdefault(r.symbol, []).append({"kind": "rename_merge", "date": r.renamed_on, "name": r.old_symbol})
    for sym, acts in actions.items():           # a recorded merger or share-exchange acquisition counts too (the exit record may be missing)
        deals = [a for a in acts if a["kind"] in ("merger", "acquisition") and a.get("name")]
        latest = max(deals, key=lambda a: a["date"], default=None)
        if latest and (sym not in mergers or latest["date"] > mergers[sym]["date"]):
            mergers[sym] = {"name": latest["name"], "date": latest["date"]}
    splits: dict[str, list[tuple]] = {}
    for r in (await db.execute(text("""SELECT t.symbol, e.event_date, e.metadata->>'split_ratio' FROM events e JOIN tickers t ON t.id = e.ticker_id
            WHERE t.symbol = ANY(:s) AND e.event_type = 'split' ORDER BY e.event_date"""), {"s": syms})).all():
        splits.setdefault(r[0], []).append((r[1], V.split_ratio(r[2])))

    frames = price_bars.bulk_closes_sync(syms + [BENCHMARK], today - timedelta(days=BARS_LOOKBACK_DAYS))
    closes = {s: [(ts.date(), float(c)) for ts, c in df["Close"].dropna().items()] for s, df in frames.items()}
    spy = closes.get(BENCHMARK, [])
    sectors = sector_changes(tickers, closes, spy)

    growth: dict[str, list[dict]] = {}
    for r in (await db.execute(text("""SELECT symbol, metric, period_end, year_ago_end, value, year_ago_value, growth_pct, phrase, held_reason, readers, version, computed_at
            FROM growth_figures WHERE symbol = ANY(:s) ORDER BY symbol, metric, period_end"""), {"s": syms})).all():
        growth.setdefault(r.symbol, []).append(dict(r._mapping))
    pe = {r.symbol: dict(r._mapping) for r in (await db.execute(text("""SELECT DISTINCT ON (symbol) symbol, as_of_date, status, reason, pe, trailing_eps, window_start, window_end,
            window_source, hist_median, hist_share_above, hist_sessions, hist_first, hist_last FROM pe_snapshots WHERE symbol = ANY(:s) ORDER BY symbol, as_of_date DESC"""), {"s": syms})).all()}
    pe_sector = {r.sector: dict(r._mapping) for r in (await db.execute(text(
        "SELECT DISTINCT ON (sector) sector, as_of_date, median_pe, shown, reason, fresh, active FROM pe_sector_snapshots ORDER BY sector, as_of_date DESC"))).all()}
    ids = [t["id"] for t in tickers.values()]
    nexts = await batch_next_earnings(db, ids, today)
    next_by_symbol = {t["symbol"]: nexts.get(t["id"]) for t in tickers.values()}
    return {"today": today, "tickers": tickers, "profiles": profiles, "mergers": mergers, "actions": actions, "splits": splits, "closes": closes,
            "spy": spy, "sectors": sectors, "growth": growth, "pe": pe, "pe_sector": pe_sector, "next": next_by_symbol}


# ── prices: the stock against SPY and its sector ───────────────────────────────────────────────────────────────────────────

def change(series: list[tuple[date, float]], sessions: int) -> tuple[float, date, date] | None:
    """Pure: (percent change over the last `sessions` sessions, start session, end session) of an adjusted close series."""
    if len(series) <= sessions:
        return None
    (d0, c0), (d1, c1) = series[-sessions - 1], series[-1]
    if c0 <= 0:
        return None
    return round((c1 / c0 - 1) * 100, 1), d0, d1


def aligned(series: list[tuple[date, float]], calendar: list[date]) -> dict[date, float] | None:
    """Pure: the series on the benchmark's calendar (None when its last close is not the benchmark's last session)."""
    by = dict(series)
    if not calendar or calendar[-1] not in by:
        return None
    return {d: by[d] for d in calendar if d in by}


def sector_changes(tickers: dict, closes: dict, spy: list[tuple[date, float]]) -> dict[str, dict]:
    """Pure: {sector: {members, change_1y, change_3m, index: [(date, median indexed level)]}} over the active S&P 500 members with a
    full year of closes on SPY's calendar. The index line is the median member's level each session, each member indexed to 100
    a year before the last session."""
    cal = [d for d, _ in spy[-YEAR_SESSIONS - 1:]]
    out: dict[str, dict] = {}
    by_sector: dict[str, list[dict[date, float]]] = {}
    for sym, t in tickers.items():
        if not t.get("index_member") or not t.get("sector"):
            continue
        a = aligned(closes.get(sym, []), cal)
        if a is None or len(a) != len(cal):
            continue
        by_sector.setdefault(t["sector"], []).append(a)
    for sec, members in by_sector.items():
        if len(members) < 3:
            continue
        idx = [(d, round(median(m[d] / m[cal[0]] * 100 for m in members), 2)) for d in cal]
        q0 = cal[-QUARTER_SESSIONS - 1]
        out[sec] = {"members": len(members), "change_1y": round(median((m[cal[-1]] / m[cal[0]] - 1) * 100 for m in members), 1),
                    "change_3m": round(median((m[cal[-1]] / m[q0] - 1) * 100 for m in members), 1), "index": idx, "start": cal[0], "end": cal[-1]}
    return out


def biggest_moves(series: list[tuple[date, float]], spy: list[tuple[date, float]], report_days: set[date], min_spy_pct: float, n: int = BIG_MOVES_SHOWN) -> list[dict]:
    """Pure: the stock's n largest daily moves (adjusted close to close) of the last QUARTER_SESSIONS sessions, each with SPY's
    move that session and whose it was (walkthrough_checks.move_owner); a session the company reported on or just after is marked."""
    from app.services.walkthrough_checks import move_owner
    spy_by = dict(spy)
    spy_days = [d for d, _ in spy]
    spy_moves = {d: round((spy_by[d] / spy_by[p] - 1) * 100, 2) for p, d in zip(spy_days, spy_days[1:])}
    recent = series[-QUARTER_SESSIONS - 1:]
    moves = [(d, round((c / pc - 1) * 100, 2)) for (pd_, pc), (d, c) in zip(recent, recent[1:]) if pc > 0]
    out = []
    for d, m in sorted(moves, key=lambda x: -abs(x[1]))[:n]:
        s = spy_moves.get(d)
        out.append({"date": d, "move_pct": m, "spy_pct": s, "owner": move_owner(m, s, min_spy_pct), "report_day": d in report_days})
    return out


# ── per stock ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

async def typical_move(db, ticker_id, symbol: str, held: set[str]) -> dict | None:
    """The typical 1-day move after a report as the question strip computes it (services/briefing_build.build_questions): the
    mean absolute stored move over every report, none for an excluded price history or a held typical move, basis-mismatch
    reports left out."""
    from app.services.basis_exclusion import basis_mismatch_dates
    from app.services.price_history_exclusion import is_excluded
    if "typical_move" in held or await is_excluded(db, symbol):
        return None
    mismatch = await basis_mismatch_dates(db, ticker_id)
    rows = (await db.execute(text("""SELECT event_date, pct_change_1d FROM historical_reactions WHERE ticker_id = :t AND event_type = 'earnings'
        AND pct_change_1d IS NOT NULL ORDER BY event_date"""), {"t": ticker_id})).all()
    sample = [(d, float(m)) for d, m in rows if d not in mismatch]
    if not sample:
        return None
    return {"pct": round(sum(abs(m) for _, m in sample) / len(sample), 1), "n": len(sample), "as_of": sample[-1][0], "dates": [d for d, _ in sample]}


async def implied_move(db, symbol: str, report_date: date, today: date) -> dict | None:
    """The at-the-money straddle over the stock price, from the stored chain for the first expiration on or after the report,
    only while that chain is fresh (chain_store.is_fresh); the price is the chain's own underlying price."""
    from app.services import chain_store
    from app.services.implied_move import straddle_implied_move
    exp = await chain_store.pick_expiration(db, symbol, report_date.isoformat())
    if not exp:
        return None
    got = await chain_store.get_chain(db, symbol, exp)
    if not got or not got[1] or not chain_store.is_fresh(got[1], today=today):
        return None
    chain, last_trade = got
    spot = chain.get("underlying_price")
    if not spot:
        return None
    im = straddle_implied_move(chain.get("calls") or [], chain.get("puts") or [], float(spot))
    if im is None:
        return None
    return {"pct": round(im.pct * 100, 1), "chain_date": date.fromisoformat(str(last_trade)[:10]), "expiration": date.fromisoformat(exp)}


async def pe_series(db, symbol: str, splits: list[tuple], actions: list[dict], today: date) -> list[tuple[date, float]]:
    """The daily P/E over the stored five years, from the quarters and raw closes compute_pe reads (valuation.pe_series_clean)."""
    quarters = [{"end": r[0], "start": r[1], "eps": float(r[2]), "filed": r[3], "derived": bool(r[4])} for r in (await db.execute(text(
        "SELECT period_end, period_start, eps, filed_on, derived FROM eps_quarters WHERE symbol = :s ORDER BY period_end"), {"s": symbol})).all()]
    if not quarters:
        return []
    raw = [(r[0], float(r[1])) for r in (await db.execute(text("SELECT date, close FROM price_bars_shadow WHERE symbol = :s AND date >= :d ORDER BY date"),
                                                           {"s": symbol, "d": today - timedelta(days=366 * V.RANGE_YEARS)})).all()]
    bars = V.rebase_closes(raw, splits)
    return V.pe_series_clean(bars, quarters, [a["date"] for a in actions])


async def report_days(db, ticker_id) -> set[date]:
    """Sessions a report moved the stock on: the report day and the session after it."""
    from app.services.trading_calendar import nth_trading_day_after
    rows = (await db.execute(text("SELECT event_date FROM events WHERE ticker_id = :t AND event_type = 'earnings' AND event_date >= :d"),
                             {"t": ticker_id, "d": date.today() - timedelta(days=BARS_LOOKBACK_DAYS)})).scalars().all()
    out: set[date] = set()
    for d in rows:
        out.add(d)
        out.add(nth_trading_day_after(d, 1))
    return out
