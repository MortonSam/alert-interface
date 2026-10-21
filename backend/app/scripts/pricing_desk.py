"""Nightly: the pricing desk (Ivy v3). For every active stock with a confirmed or estimated report in the next REPORT_WINDOW_DAYS,
a card from the serving chain and the stock's own history (services/pricing_desk), stored under pricing_card:{SYM}; a verdict row per
report in pricing_verdicts (the first night's row stands, later nights update its expected values until the report); and a
settlement pass that closes each structure after the report from the stored post-report chain. Cards for reports more than
CARD_KEEP_DAYS past are removed.

    python -m app.scripts.pricing_desk                  # the nightly step
    python -m app.scripts.pricing_desk --symbols=AAPL   # one stock, printed, still stored
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, select, text

from app.database import ScriptSessionLocal
from app.models.pricing_verdict import PricingVerdict
from app.services import chain_store
from app.services.pricing_desk import (PRICING_COMPUTATION_VERSION, REPORT_WINDOW_DAYS, STEP_LABEL, STRUCTURES, Odds, build_card, card_key, dumps, fill,
                                       intrinsic)
from app.services.step_outcomes import record_step_fields
from app.services.system_metadata_service import set_value
from app.services.trading_calendar import is_trading_day

CARD_KEEP_DAYS = 3


def post_session(report_date: date, timing: str | None) -> date:
    """The first session after the report: the report day for a before-open report, else the next session."""
    if (timing or "").lower() == "bmo":
        return report_date
    d = report_date + timedelta(days=1)
    while not is_trading_day(d):
        d += timedelta(days=1)
    return d


def settle_structure(name: str, entry: dict, quotes_post: dict[float, dict] | None, spot_post: float | None) -> float | None:
    """Pure: dollars per $100 risked when the structure is closed after the report: each leg at the real bid or ask of the post-report
    chain, or its intrinsic value at the post-report close when the chain has no quote (an expiry-day close)."""
    exit_value = 0.0
    for L in entry["legs"]:
        q = (quotes_post or {}).get(float(L["strike"]), {}).get(L["kind"])
        v = fill(q, "sell" if L["side"] == "buy" else "buy", 0.5) if q else None
        if v is None:
            if spot_post is None:
                return None
            v = intrinsic(L["kind"], float(L["strike"]), spot_post)
        exit_value += v if L["side"] == "buy" else -v
    risk = entry["max_loss_per_contract"]
    if not risk:
        return None
    return round((exit_value * 100 - entry["cost_per_contract"]) / risk * 100, 2)


async def load_odds(s) -> Odds:
    """The reactions with, for each, the move over 1..MAX_HORIZON sessions from the close before the report (stored bars, adjusted)."""
    from bisect import bisect_left
    from app.scripts.ivy_v3_pull import sessions as report_sessions
    from app.services import price_bars
    from app.services.pricing_desk import MAX_HORIZON
    rows = [dict(r) for r in (await s.execute(text("""SELECT t.symbol, t.sector, hr.event_date, hr.pct_change_1d, hr.report_timing FROM historical_reactions hr
        JOIN tickers t ON t.id = hr.ticker_id WHERE hr.event_type = 'earnings' AND hr.pct_change_1d IS NOT NULL"""))).mappings().all()]
    bars = price_bars.bulk_bars_sync(sorted({r["symbol"] for r in rows}), min(r["event_date"] for r in rows) - timedelta(days=10)) if rows else {}
    closes = {sym: ([t.date() for t in df.index], df["Close"].tolist()) for sym, df in bars.items()}
    for r in rows:
        ds, cs = closes.get(r["symbol"], ([], []))
        pre, _ = report_sessions(r["event_date"], r["report_timing"])
        i = bisect_left(ds, pre)
        moves = {}
        if i < len(ds) and ds[i] == pre and cs[i]:
            for h in range(2, MAX_HORIZON + 1):
                if i + h < len(ds):
                    moves[h] = cs[i + h] / cs[i] - 1
        r["moves"] = moves
    return Odds(rows)


async def candidates(s, today: date, only: set[str] | None) -> list[dict]:
    rows = (await s.execute(text("""
        SELECT DISTINCT ON (t.symbol) t.symbol, e.event_date, e.is_confirmed, e.unresolved_since, e.report_timing
        FROM tickers t JOIN events e ON e.ticker_id = t.id
        WHERE t.is_active AND e.event_type = 'earnings' AND e.event_date BETWEEN :a AND :b AND e.unresolved_since IS NULL
        ORDER BY t.symbol, e.event_date"""), {"a": today, "b": today + timedelta(days=REPORT_WINDOW_DAYS)})).mappings().all()
    return [dict(r) for r in rows if not only or r["symbol"] in only]


async def close_on(s, sym: str, d: date) -> float | None:
    v = (await s.execute(text("SELECT close FROM price_bars_shadow WHERE symbol = :s AND date = :d"), {"s": sym, "d": d})).scalar()
    return float(v) if v is not None else None


def _dec(v):
    return Decimal(str(v)) if v is not None else None


async def upsert_verdict(s, card: dict, today: date) -> None:
    sym, rd = card["symbol"], date.fromisoformat(card["report_date"])
    st = card["structures"]
    evs = {n: (st.get(n) or {}).get("ev_per_100") for n in STRUCTURES}
    legs = {n: {"legs": st[n]["legs"], "cost_per_contract": st[n]["cost_per_contract"], "max_loss_per_contract": st[n]["max_loss_per_contract"]} for n in STRUCTURES if st.get(n)}
    row = (await s.execute(select(PricingVerdict).where(PricingVerdict.symbol == sym, PricingVerdict.report_date == rd))).scalar_one_or_none()
    if row is None:
        s.add(PricingVerdict(symbol=sym, report_date=rd, computed_at=datetime.fromisoformat(card["computed_at"]), computation_version=card["computation_version"],
                             verdict=card["verdict"], verdict_structure=card["verdict_structure"], ev_long_call=_dec(evs["long_call"]), ev_long_straddle=_dec(evs["long_straddle"]),
                             ev_bull_call_spread=_dec(evs["bull_call_spread"]), ev_iron_condor=_dec(evs["iron_condor"]), legs=legs))
    elif row.settled_at is None and rd >= today:
        row.computed_at = datetime.fromisoformat(card["computed_at"]); row.computation_version = card["computation_version"]
        row.verdict, row.verdict_structure = card["verdict"], card["verdict_structure"]
        row.ev_long_call, row.ev_long_straddle = _dec(evs["long_call"]), _dec(evs["long_straddle"])
        row.ev_bull_call_spread, row.ev_iron_condor = _dec(evs["bull_call_spread"]), _dec(evs["iron_condor"])
        row.legs = legs


def orphans(cards: list[tuple[str, str, date]], verdicts: list[tuple[object, str, date]], reports: dict[str, set[date]]) -> tuple[list[str], list[object]]:
    """Pure: the cards (by key) and unsettled verdicts (by id) priced for a report date that is no longer a stored earnings date of
    their stock: the date moved after they were priced (2026-10-21: CB's Oct 21 card after its date became Oct 20, VMRK's after
    Oct 21 became Nov 4). Such a card would show a report that isn't on file and fail validate on its old version, and such a
    verdict would be settled against a session that wasn't its report; both are dropped."""
    return ([k for k, sym, d in cards if d not in reports.get(sym, set())],
            [i for i, sym, d in verdicts if d not in reports.get(sym, set())])


async def drop_orphans(s) -> tuple[list[str], list[str]]:
    """Remove orphans() from the store; returns (card keys, "SYM report_date" of each dropped verdict)."""
    cards = [(k, k.split(":", 1)[1], date.fromisoformat(d)) for k, d in (await s.execute(text(
        "SELECT key, value::json->>'report_date' FROM system_metadata WHERE key LIKE 'pricing_card:%'"))).all() if d]
    verdicts = [(r.id, r.symbol, r.report_date) for r in (await s.execute(select(PricingVerdict).where(PricingVerdict.settled_at.is_(None)))).scalars().all()]
    syms = sorted({x[1] for x in cards} | {x[1] for x in verdicts})
    reports: dict[str, set[date]] = {}
    for sym, d in (await s.execute(text("""SELECT t.symbol, e.event_date FROM events e JOIN tickers t ON t.id = e.ticker_id
            WHERE e.event_type = 'earnings' AND t.symbol = ANY(:s)"""), {"s": syms})).all():
        reports.setdefault(sym, set()).add(d)
    gone_cards, gone_ids = orphans(cards, verdicts, reports)
    if gone_cards:
        await s.execute(text("DELETE FROM system_metadata WHERE key = ANY(:k)"), {"k": gone_cards})
    dropped = [f"{sym} {d.isoformat()}" for i, sym, d in verdicts if i in set(gone_ids)]
    if gone_ids:
        await s.execute(delete(PricingVerdict).where(PricingVerdict.id.in_(gone_ids)))
    return gone_cards, dropped


async def settle(s, today: date) -> tuple[int, list[str]]:
    """Fill the settled columns of every unsettled row whose report has passed and whose post-report chain or close is stored."""
    rows = (await s.execute(select(PricingVerdict).where(PricingVerdict.settled_at.is_(None), PricingVerdict.report_date < today))).scalars().all()
    settled, waiting = 0, []
    for r in rows:
        timing = (await s.execute(text("""SELECT e.report_timing FROM events e JOIN tickers t ON t.id = e.ticker_id WHERE t.symbol = :s AND e.event_type = 'earnings'
            AND e.event_date = :d LIMIT 1"""), {"s": r.symbol, "d": r.report_date})).scalar()
        post = post_session(r.report_date, timing)
        if post >= today:
            waiting.append(f"{r.symbol}: post-report session {post} not yet stored"); continue
        spot_post = await close_on(s, r.symbol, post)
        quotes = None
        exp = (r.legs or {}).get("_expiration")
        if exp:
            got = await chain_store.get_chain(s, r.symbol, exp)
            if got and str(got[1])[:10] == post.isoformat():
                from app.services.pricing_desk import quotes_by_strike
                quotes = quotes_by_strike(got[0].get("calls") or [], got[0].get("puts") or [])
        if quotes is None and spot_post is None:
            waiting.append(f"{r.symbol}: no post-report chain or close stored for {post}"); continue
        move = (await s.execute(text("""SELECT hr.pct_change_1d FROM historical_reactions hr JOIN tickers t ON t.id = hr.ticker_id
            WHERE t.symbol = :s AND hr.event_type = 'earnings' AND abs(hr.event_date - :d) <= 1 LIMIT 1"""), {"s": r.symbol, "d": r.report_date})).scalar()
        for n in STRUCTURES:
            entry = (r.legs or {}).get(n)
            if entry:
                setattr(r, f"settled_{n}", _dec(settle_structure(n, entry, quotes, spot_post)))
        r.actual_move_pct = _dec(round(float(move), 4)) if move is not None else None
        r.settled_at = datetime.now(timezone.utc)
        settled += 1
    return settled, waiting


async def main(argv: list[str]) -> int:
    only = {x.strip().upper() for x in next((a.split("=", 1)[1] for a in argv if a.startswith("--symbols=")), "").split(",") if x.strip()} or None
    today = date.today()
    cards, verdicts, skipped = 0, {"no_edge": 0, "possible_edge": 0}, {}
    async with ScriptSessionLocal() as s:
        odds = await load_odds(s)
        cands = await candidates(s, today, only)
        for c in cands:
            sym, rd = c["symbol"], c["event_date"]
            try:
                exp = await chain_store.pick_expiration(s, sym, rd.isoformat())
                got = await chain_store.get_chain(s, sym, exp) if exp else None
                if not got:
                    skipped[sym] = "no serving chain for the report's expiry"; continue
                chain, chain_date = got
                if not chain_store.is_fresh(chain_date):
                    skipped[sym] = f"chain {chain_date} is stale"; continue
                spot = await close_on(s, sym, date.fromisoformat(str(chain_date)[:10]))
                if spot is None:
                    skipped[sym] = f"no stored close for {chain_date}"; continue
                card = build_card(symbol=sym, report_date=rd, report_confirmation="confirmed" if c["is_confirmed"] else "estimated", chain=chain, chain_date=str(chain_date)[:10],
                                  chain_source=chain_store.chain_source(chain), expiration=exp, spot=spot, odds=odds, today=today)
                if isinstance(card, str):
                    skipped[sym] = card; continue
                for n in STRUCTURES:                                  # settlement needs the expiry beside the legs
                    if card["structures"].get(n):
                        for L in card["structures"][n]["legs"]:
                            L["expiration"] = exp
                await set_value(s, card_key(sym), dumps(card))
                await upsert_verdict(s, card, today)
                row = (await s.execute(select(PricingVerdict).where(PricingVerdict.symbol == sym, PricingVerdict.report_date == rd))).scalar_one_or_none()
                if row is not None and row.settled_at is None:
                    row.legs = {**row.legs, "_expiration": exp}
                cards += 1; verdicts[card["verdict"]] += 1
                if only:
                    print(json.dumps(card, indent=1)[:3000])
            except Exception as exc:
                from app.services.redact import redact
                skipped[sym] = f"error: {redact(exc)[:120]}"
        await s.commit()
        # stale cards leave the store; settled rows stay in the ledger
        old = (await s.execute(text("SELECT key, value::json->>'report_date' FROM system_metadata WHERE key LIKE 'pricing_card:%'"))).all()
        gone = [k for k, d in old if d and date.fromisoformat(d) < today - timedelta(days=CARD_KEEP_DAYS)]
        if gone:
            await s.execute(text("DELETE FROM system_metadata WHERE key = ANY(:k)"), {"k": gone})
        moved_cards, moved_verdicts = await drop_orphans(s)        # before settling: a report that moved is never settled
        settled, waiting = await settle(s, today)
        await s.commit()
    reasons = {}
    for v in skipped.values():
        reasons[v[:50]] = reasons.get(v[:50], 0) + 1
    print(f"{STEP_LABEL}: {len(cands)} report(s) in {REPORT_WINDOW_DAYS} days, {cards} card(s) ({verdicts}), {len(skipped)} skipped {reasons}, {settled} verdict(s) settled, "
          f"{len(waiting)} waiting, {len(gone)} old card(s) removed, {len(moved_cards)} card(s) and {len(moved_verdicts)} verdict(s) of moved reports dropped "
          f"{moved_verdicts}, version {PRICING_COMPUTATION_VERSION}")
    await record_step_fields(STEP_LABEL, {"reports": len(cands), "cards": cards, "verdicts": verdicts, "skipped": skipped, "settled": settled, "waiting": waiting[:30],
                                          "removed": len(gone), "moved_cards": moved_cards, "moved_verdicts": moved_verdicts,
                                          "version": PRICING_COMPUTATION_VERSION, "error": None})
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
