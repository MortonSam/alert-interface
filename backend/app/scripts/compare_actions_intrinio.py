"""One-time, report only: where yfinance and Intrinio disagree on splits and ex-dividends in the overlap year.

The overlap year is the last OVERLAP_DAYS. yfinance's side is the stored events (source yfinance); Intrinio's side is
the shadow bars' split_ratio and dividend fields. Splits match when the dates are within one session; a match with a
different ratio is a disagreement, as is a split on one side only. Ex-dividend dates match on the exact date; only
dates the bars reach (on or before the last stored bar) are compared, and amounts are not, because yfinance stored
the annual rate and Intrinio the cash per share.

    python -m app.scripts.compare_actions_intrinio
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta

from sqlalchemy import text

from app.database import ScriptSessionLocal
from app.scripts.seed_historical_reactions import REFERENCE_SYMBOL, _build_date_cache
from app.services import price_bars
from app.services.corporate_actions import dividends_from_adjustments, session_distance, splits_from_adjustments

OVERLAP_DAYS = 365


def compare_splits(stored: list[dict], bars: list[dict], sessions) -> dict:
    """stored/bars: {symbol, date, split_ratio}. Returns {agree, ratio_differs, yfinance_only, intrinio_only}."""
    by_sym: dict[str, list[dict]] = {}
    for b in bars:
        by_sym.setdefault(b["symbol"], []).append(b)
    used: set[tuple[str, date]] = set()
    agree, ratio_differs, yf_only = [], [], []
    for s in sorted(stored, key=lambda x: (x["symbol"], x["date"])):
        near = [b for b in by_sym.get(s["symbol"], []) if abs((s["date"] - b["date"]).days) <= 4 and (session_distance(sessions, s["date"], b["date"]) or 0) <= 1]
        if not near:
            yf_only.append(s)
            continue
        b = min(near, key=lambda b: abs((s["date"] - b["date"]).days))
        used.add((b["symbol"], b["date"]))
        (agree if b["split_ratio"] == s["split_ratio"] else ratio_differs).append({**s, "intrinio_date": b["date"], "intrinio_ratio": b["split_ratio"]})
    intrinio_only = [b for b in bars if (b["symbol"], b["date"]) not in used]
    return {"agree": agree, "ratio_differs": ratio_differs, "yfinance_only": yf_only, "intrinio_only": intrinio_only}


def compare_dividends(stored: list[dict], bars: list[dict], last_bar: date) -> dict:
    """stored/bars: {symbol, date}. Exact-date matches; stored dates after the last bar are not comparable."""
    bar_set = {(b["symbol"], b["date"]) for b in bars}
    comparable = [s for s in stored if s["date"] <= last_bar]
    agree = [s for s in comparable if (s["symbol"], s["date"]) in bar_set]
    yf_only = [s for s in comparable if (s["symbol"], s["date"]) not in bar_set]
    stored_set = {(s["symbol"], s["date"]) for s in stored}
    intrinio_only = [b for b in bars if (b["symbol"], b["date"]) not in stored_set]
    return {"agree": agree, "yfinance_only": yf_only, "intrinio_only": intrinio_only, "not_comparable": len(stored) - len(comparable)}


async def main() -> int:
    since = date.today() - timedelta(days=OVERLAP_DAYS)
    async with ScriptSessionLocal() as s:
        ev = (await s.execute(text("""select t.symbol, e.event_type::text as event_type, e.event_date, e.metadata->>'split_ratio' as split_ratio
                                     from events e join tickers t on t.id = e.ticker_id
                                     where e.source = 'yfinance' and e.event_type in ('split', 'ex_dividend') and e.event_date >= :since
                                     order by t.symbol, e.event_date"""), {"since": since})).all()
        bars = (await s.execute(text("select symbol, date, split_ratio, factor, dividend from price_bars_shadow where date >= :since and (split_ratio <> 1 or factor <> 1 or dividend <> 0) order by symbol, date"),
                                {"since": since})).all()
        last_bar = (await s.execute(text("select max(date) from price_bars_shadow"))).scalar()
    sessions = _build_date_cache(price_bars.history_sync(REFERENCE_SYMBOL, since))
    yf_splits = [{"symbol": r.symbol, "date": r.event_date, "split_ratio": r.split_ratio} for r in ev if r.event_type == "split"]
    yf_divs = [{"symbol": r.symbol, "date": r.event_date} for r in ev if r.event_type == "ex_dividend"]
    bar_splits = [{"symbol": r.symbol, **sp} for r in bars for sp in splits_from_adjustments([r])]
    bar_divs = [{"symbol": r.symbol, **dv} for r in bars for dv in dividends_from_adjustments([r])]
    sp = compare_splits(yf_splits, bar_splits, sessions)
    dv = compare_dividends(yf_divs, bar_divs, last_bar)
    print(f"\nSplits and ex-dividends, yfinance (stored events) vs Intrinio (shadow bars), {since} to {last_bar}")
    print(f"  splits: yfinance {len(yf_splits)}, Intrinio {len(bar_splits)}; agree {len(sp['agree'])}, ratio differs {len(sp['ratio_differs'])}, "
          f"yfinance only {len(sp['yfinance_only'])}, Intrinio only {len(sp['intrinio_only'])}")
    for x in sp["ratio_differs"]:
        print(f"    ratio differs  {x['symbol']:6} yfinance {x['date']} {x['split_ratio']:>6}   Intrinio {x['intrinio_date']} {x['intrinio_ratio']}")
    for x in sp["yfinance_only"]:
        print(f"    yfinance only  {x['symbol']:6} {x['date']} {x['split_ratio']}")
    for x in sp["intrinio_only"]:
        print(f"    Intrinio only  {x['symbol']:6} {x['date']} {x['split_ratio']} (price factor {x['intrinio_split_ratio']})")
    print(f"  ex-dividends: yfinance {len(yf_divs)} ({dv['not_comparable']} after the last bar, not comparable), Intrinio {len(bar_divs)}; "
          f"agree {len(dv['agree'])}, yfinance only {len(dv['yfinance_only'])}, Intrinio only {len(dv['intrinio_only'])}")
    for x in dv["yfinance_only"][:40]:
        print(f"    yfinance only  {x['symbol']:6} {x['date']}")
    print(f"    Intrinio only: {len(dv['intrinio_only'])} ex-dates the stored table never had (yfinance seeded the next ex-date only)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
