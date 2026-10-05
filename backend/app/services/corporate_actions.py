"""Recorded corporate-action dates (splits and ex-dividends) from the events table.

One source for every consumer that needs to know whether a price gap on a date
is explained by a corporate action: the RV guard in rv_math and any reaction
pipeline that shares its exclusion.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

ACTION_EVENT_TYPES = ("split", "ex_dividend", "spin_off")     # a spin-off day's price gap is explained too


async def load_action_dates(session: AsyncSession, symbols: list[str]) -> dict[str, set[date]]:
    """{symbol: {dates with a recorded split or ex-dividend}} for the given symbols."""
    if not symbols:
        return {}
    rows = (await session.execute(
        text("""
            SELECT t.symbol, e.event_date
            FROM events e
            JOIN tickers t ON t.id = e.ticker_id
            WHERE t.symbol = ANY(:symbols) AND e.event_type = ANY(:types)
        """),
        {"symbols": list(symbols), "types": list(ACTION_EVENT_TYPES)},
    )).all()
    out: dict[str, set[date]] = {s: set() for s in symbols}
    for symbol, event_date in rows:
        out.setdefault(symbol, set()).add(event_date)
    return out


# ── Splits and ex-dividends from Intrinio's price adjustments ─────────────────
#
# Intrinio's split_ratio is the price factor on the split day: 0.1 for a 10-for-1, 3.0 for a 1-for-3 reverse. The
# stored shape (events.metadata.split_ratio) is yfinance's "shares after : shares before" string, "10:1" or "1:3", so
# the factor is inverted before formatting. The dividend field is the cash per share on the ex-date.

from fractions import Fraction

MAX_RATIO_SIDE = 50           # a whole ratio (X:1 or 1:X) with a side above this is not a split
MAX_FRACTIONAL_SIDE = 10      # a fractional ratio (3:2, 5:4) with a side above this is a spin-off or stub factor (41:40, 37:35, 29:22), not a split
SPLIT_RATIO_TOLERANCE = 0.02  # how closely Intrinio's split_ratio must match its price factor on a day that also pays a dividend
STORED_SPLIT_SOURCE = "intrinio"


def format_ratio(factor: float) -> str:
    """yfinance-style 'X:1' or '1:X' from a shares-after/shares-before factor (10.0 -> '10:1', 0.5 -> '1:2', 1.5 -> '3:2')."""
    if factor >= 1:
        if factor == int(factor):
            return f"{int(factor)}:1"
        frac = Fraction(factor).limit_denominator(100)
        return f"{frac.numerator}:{frac.denominator}"
    inv = 1 / factor
    if abs(inv - round(inv)) < 1e-6:
        return f"1:{int(round(inv))}"
    frac = Fraction(factor).limit_denominator(100)
    return f"{frac.numerator}:{frac.denominator}"


def is_real_split_ratio(ratio_str: str) -> bool:
    """A whole ratio with the big side at most MAX_RATIO_SIDE, or a fractional one with both sides at most MAX_FRACTIONAL_SIDE."""
    try:
        a, b = (int(x) for x in ratio_str.split(":"))
    except (ValueError, AttributeError):
        return False
    if a <= 0 or b <= 0:
        return False
    if a == 1 or b == 1:
        return max(a, b) <= MAX_RATIO_SIDE
    return max(a, b) <= MAX_FRACTIONAL_SIDE


def split_price_factor(split_ratio, factor, dividend) -> float | None:
    """The price factor of a split on an Intrinio adjustment day, or None when the day is no split.

    Intrinio is not consistent: a plain split carries the factor in both fields (NVDA 2024-06-10: 0.1 and 0.1); some
    carry it in factor alone (DXCM 2022-06-13: factor 0.25, split_ratio 1); a separation can carry a split_ratio the
    price never followed (HON 2026-06-29: split_ratio 2, factor 1.0095, dividend 115). So: with no dividend the price
    factor is the split; with a dividend the split_ratio counts only when the price factor confirms it."""
    try:
        f = float(factor) if factor is not None else None
        sr = float(split_ratio) if split_ratio is not None else None
        dv = float(dividend) if dividend is not None else 0.0
    except (TypeError, ValueError):
        return None
    if dv <= 0:
        pf = f if f is not None and f > 0 else sr
    else:
        pf = sr if sr is not None and f is not None and abs(f - sr) <= SPLIT_RATIO_TOLERANCE else None
    if pf is None or pf <= 0 or abs(pf - 1.0) < 1e-9:
        return None
    return pf


def split_ratio_from_intrinio(split_ratio, factor=None, dividend=None) -> str | None:
    """The stored 'X:Y' string for an Intrinio adjustment day; None when it is no split, or not a real split ratio."""
    pf = split_price_factor(split_ratio, factor if factor is not None else split_ratio, dividend)
    if pf is None:
        return None
    ratio = format_ratio(1.0 / pf)
    return ratio if is_real_split_ratio(ratio) else None


def _field(r, name):
    return r[name] if isinstance(r, dict) else getattr(r, name, None)


def splits_from_adjustments(rows) -> list[dict]:
    """[{date, split_ratio ('X:Y'), intrinio_split_ratio}] from bar rows or adjustment records (date, split_ratio, factor, dividend)."""
    out = []
    for r in rows:
        ratio = split_ratio_from_intrinio(_field(r, "split_ratio"), _field(r, "factor"), _field(r, "dividend"))
        if ratio:
            out.append({"date": date.fromisoformat(str(_field(r, "date"))[:10]), "split_ratio": ratio,
                        "intrinio_split_ratio": float(split_price_factor(_field(r, "split_ratio"), _field(r, "factor") if _field(r, "factor") is not None else _field(r, "split_ratio"), _field(r, "dividend")))})
    return out


def dividends_from_adjustments(rows) -> list[dict]:
    """[{date, amount}] for every record with a cash dividend on its date."""
    out = []
    for r in rows:
        d, dv = _field(r, "date"), _field(r, "dividend")
        if dv is not None and float(dv) > 0:
            out.append({"date": date.fromisoformat(str(d)[:10]), "amount": round(float(dv), 6)})
    return out


def session_distance(sessions, a: date, b: date) -> int | None:
    """Sessions between two dates on the session calendar (0 on the same session); None when either is off the calendar's range."""
    import numpy as np
    if sessions is None or len(sessions) == 0:
        return None
    ia, ib = int(np.searchsorted(sessions, a)), int(np.searchsorted(sessions, b))
    return abs(ia - ib)


def unmatched_splits(stored: list[dict], bar_splits: list[dict], sessions, max_sessions: int = 1) -> list[str]:
    """Stored splits ({symbol, date, split_ratio}) with no bar split ({symbol, date, split_ratio}) for the symbol within
    max_sessions, or with one whose ratio differs; each as a sentence."""
    by_sym: dict[str, list[dict]] = {}
    for b in bar_splits:
        by_sym.setdefault(b["symbol"], []).append(b)
    out = []
    for s in stored:
        near = [b for b in by_sym.get(s["symbol"], []) if (session_distance(sessions, s["date"], b["date"]) or 0) <= max_sessions
                and abs((s["date"] - b["date"]).days) <= 4]
        if not near:
            out.append(f"{s['symbol']} {s['date'].isoformat()} {s['split_ratio']}: no split factor on the shadow bars within one session")
        elif all(b["split_ratio"] != s["split_ratio"] for b in near):
            out.append(f"{s['symbol']} {s['date'].isoformat()} {s['split_ratio']}: the shadow bars say {', '.join(b['split_ratio'] for b in near)}")
    return out


def spin_off_reclassification(stored: list[dict], bar_splits: list[dict], sessions, max_sessions: int = 1) -> list[dict]:
    """Stored split rows ({id, symbol, date, split_ratio}) that the shadow bars show no split factor for within max_sessions:
    these are spin-off or separation adjustments that yfinance recorded as splits. Pure; the reclassify script applies it."""
    by_sym: dict[str, list[dict]] = {}
    for b in bar_splits:
        by_sym.setdefault(b["symbol"], []).append(b)
    out = []
    for s in stored:
        near = [b for b in by_sym.get(s["symbol"], []) if (session_distance(sessions, s["date"], b["date"]) or 0) <= max_sessions
                and abs((s["date"] - b["date"]).days) <= 4]
        if not near:
            out.append(s)
    return out
