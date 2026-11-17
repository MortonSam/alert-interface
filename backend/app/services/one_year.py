"""The one-year price change: one rule everywhere (Sam's item 8, 2026-11-16).

    end    the latest stored close (or the end session a caller aligns several series on)
    start  the close of the last trading session on or before the same calendar date one year earlier (Feb 29 -> Feb 28)

Both closes are what a holder of one share then experienced, in today's shares: raw closes from the stored Intrinio daily bars
(price_bars_shadow, read through services/price_bars), adjusted for

- splits, by the recorded split history (events of type split, with their "new:old" ratio: the records the P/E and growth figures
  restate share counts with, valuation.rebase_closes): a close before a split is divided by its ratio. The bars' own split_ratio column
  is not used: Intrinio books some spin-offs there (DTE, DELL, IBM, T, GE, MMM, FLEX, ILMN; HON on 2026-06-29 as a ratio of 2 with no
  price change), while every true split since 2021 has its event record.
- spin-offs, the way a split is (Sam, 2026-11-16: a spin-off is not a price drop): for each recorded spin-off (event_type spin_off, or a
  filing's corporate action spin_off), the value the bars book on its ex-date (the dividend column, the bar nearest the record within
  SPIN_OFF_MATCH_DAYS) scales every earlier close by (previous close - value) / previous close. The value is used only when it is
  recorded reliably: above zero, below the previous close, on a bar with no split_ratio of its own, and confirmed by a second source
  within SPIN_OFF_GAP_SHARE of the value or SPIN_OFF_GAP_PCT of the previous close: the price gap at that bar's open, or the value the
  record's own adjustment ratio implies (the reclassified spin_off records carry one, SPGI's 37:35). Otherwise no change reaches
  across the spin-off (the closes before it are left out, so a one-year change spanning it is absent). On the Nov 12 production copy
  HON's Jun 29 booking is not used: 115 on a bar with a ratio of 2, the day's 1-for-2 reverse split, which has no split record.

Regular dividends and special cash payouts are not added back: the change is the price a holder saw, spin-offs counted.

Before this rule the walkthrough counted 252 sessions back on dividend-adjusted closes and the ticker page's 1Y header took the first
dividend-adjusted bar on or after 366 days before today against the live quote (LLY +55.9 against +45.8, GOOGL with opposite signs,
overnight report 2026-11-12). Every one-year price change reads one_year_change; tests/test_one_year guards against a second rule.
"""
from __future__ import annotations

from datetime import date

ONE_YEAR_VERSION = 1             # 1 (2026-11-16): the rule above; bump when it changes so stored figures stay comparable
MAX_START_GAP_DAYS = 7           # the start session lies at most this many days before the target date (a holiday weekend is 4);
                                 # a longer gap (a halt, bars that begin later) leaves the change absent, never estimated
SPIN_OFF_MATCH_DAYS = 4          # a recorded spin-off and the bar that books its value can sit a weekend apart (BDX Feb 9 / Feb 10)
SPIN_OFF_GAP_SHARE = 0.25        # the booked value matches the ex-date open's gap within a quarter of the value,
SPIN_OFF_GAP_PCT = 2.0           # or within this percent of the previous close (an ordinary day's opening move)


def year_earlier(d: date) -> date:
    """Pure: the same calendar date one year earlier; Feb 29 maps to Feb 28."""
    try:
        return d.replace(year=d.year - 1)
    except ValueError:
        return d.replace(year=d.year - 1, day=28)


def split_adjusted(closes, splits) -> list[tuple[date, float]]:
    """Pure: holder_adjusted with splits only, over [(date, close)]."""
    return holder_adjusted(closes, splits)


def holder_adjusted(bars, splits, spin_offs=()) -> list[tuple[date, float]]:
    """Pure: [(date, close)] oldest first, in today's shares, from raw bars [(date, close[, open, dividend, bar split_ratio])], the
    recorded splits [(effective date, new-for-old ratio)] and the recorded spin-offs (dates, or (date, the record's adjustment ratio)). A close before a split is divided by its
    ratio (10 for 10:1, 0.2 for 1:5); a close before a reliably booked spin-off is scaled by its factor (spin_off_factors). Closes that
    are missing or not positive are left out, and so is every close before a split whose ratio is unreadable or a spin-off whose value
    is not recorded reliably (its basis is unknown, so no change reaches across it)."""
    from app.services.valuation import split_factor
    readable = [(d, r) for d, r in splits or [] if r]
    rows = []
    for b in sorted(bars, key=lambda r: r[0]):
        d, c, o, div, sr = (tuple(b) + (None, None, None))[:5]
        if c is None or float(c) <= 0:
            continue
        k = split_factor(d, readable)[0]
        rows.append((d, float(c) / k, float(o) / k if o else None, float(div) / k if div else None, None if sr is None else float(sr)))
    factors, broken = spin_off_factors(rows, spin_offs)
    floor = max([d for d, r in splits or [] if not r] + broken, default=None)
    out = []
    for d, c, *_ in rows:
        if floor is not None and d < floor:
            continue
        for ex, f in factors:
            if d < ex:
                c *= f
        out.append((d, c))
    return out


def spin_off_factors(rows, spin_offs) -> tuple[list[tuple[date, float]], list[date]]:
    """Pure: ([(ex-date, factor for every earlier close)], [dates no change may reach across]) from split-adjusted bars
    [(date, close, open, dividend, bar split_ratio)] oldest first and the recorded spin-offs (dates, or (date, adjustment ratio)). Two
    records of one spin-off (SPGI's reclassified record and its filing's action, Jul 1 and Jul 2) find the same bar and count once,
    with either record's ratio."""
    ratios: dict[date, list[float]] = {}
    for x in spin_offs or []:
        d, r = x if isinstance(x, tuple) else (x, None)
        ratios.setdefault(d, [])
        if r:
            ratios[d].append(r)
    done: set[date] = set()
    factors, broken = [], []
    for s in sorted(ratios):
        near = [(abs((r[0] - s).days), i) for i, r in enumerate(rows) if abs((r[0] - s).days) <= SPIN_OFF_MATCH_DAYS and r[3]]
        if not near:
            broken.append(s)                                     # recorded, but no value booked beside it
            continue
        i = min(near)[1]
        d, _, o, value, sr = rows[i]
        if d in done:
            continue
        done.add(d)
        prev = rows[i - 1][1] if i > 0 else None
        record = [r for t, rs in ratios.items() if abs((t - d).days) <= SPIN_OFF_MATCH_DAYS for r in rs]
        if spin_off_reliable(prev, o, value, sr, record):
            factors.append((d, (prev - value) / prev))
        else:
            broken.append(d)
    return factors, broken


def spin_off_reliable(prev: float | None, open_: float | None, value: float | None, bar_ratio: float | None,
                      record_ratios: list[float] = ()) -> bool:
    """Pure: whether a spin-off's booked value can adjust the closes before it (holder_adjusted's rule): in range, on a bar with no
    ratio of its own, and confirmed by the open's gap or by a record's adjustment ratio (new for old: 37:35 implies 2/37 of the close)."""
    if not prev or not value or not 0 < value < prev or bar_ratio not in (None, 1.0):
        return False
    within = lambda other: abs(other - value) <= max(SPIN_OFF_GAP_SHARE * value, SPIN_OFF_GAP_PCT / 100 * prev)
    return bool((open_ and within(prev - open_)) or any(r > 1 and within(prev * (1 - 1 / r)) for r in record_ratios))


def start_session(series: list[tuple[date, float]], end: date) -> tuple[date, float] | None:
    """Pure: the (date, close) of the last session on or before year_earlier(end), within MAX_START_GAP_DAYS of it; None otherwise."""
    target = year_earlier(end)
    before = [(d, c) for d, c in series if d <= target]
    if not before:
        return None
    d, c = max(before, key=lambda x: x[0])
    return (d, c) if (target - d).days <= MAX_START_GAP_DAYS else None


def one_year_change(series: list[tuple[date, float]], end: date | None = None) -> dict | None:
    """Pure: {pct, change, start_date, start_close, end_date, end_close} over a holder-adjusted close series (holder_adjusted), ending at
    its latest close or at `end` (which must be one of its sessions). pct is unrounded percent; None when either close is missing."""
    if not series:
        return None
    by = dict(series)
    end = max(by) if end is None else end
    if end not in by:
        return None
    start = start_session(series, end)
    if start is None or start[1] <= 0:
        return None
    s_day, s_close = start
    e_close = by[end]
    return {"pct": (e_close / s_close - 1) * 100, "change": e_close - s_close, "start_date": s_day, "start_close": s_close,
            "end_date": end, "end_close": e_close}
