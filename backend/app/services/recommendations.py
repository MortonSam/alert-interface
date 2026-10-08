"""Analyst recommendation trends (Finnhub, table analyst_recommendations): how fresh a stored trend must be to be shown, and the
lean read from it. The nightly refreshes every active ticker within FRESH_DAYS; a trend older than MAX_AGE_DAYS is not shown or used
(the Build lean goes neutral and says why; the Discover buy-share line is left out), and every line built from a trend names the day
it was checked, so nothing stale renders as current.
"""
from __future__ import annotations

from datetime import datetime, timezone

FRESH_DAYS = 7                 # validate_data's bar: a trend fetched within this many days is fresh
MAX_AGE_DAYS = 14              # older than this, a trend is stale: hidden on Discover, neutral on Build
REFRESH_AFTER_DAYS = 4         # the nightly re-asks Finnhub for a ticker fetched longer ago than this (120 a night covers 503 in five)
EARNINGS_SOON_DAYS = 14        # a ticker reporting within this many days is refreshed ahead of the rest of the stale ones
MIN_ANALYSTS = 5
SOURCE = "Finnhub"


def age_days(fetched_at: datetime | None, now: datetime) -> int | None:
    if fetched_at is None:
        return None
    if fetched_at.tzinfo is None:
        fetched_at = fetched_at.replace(tzinfo=timezone.utc)
    return max(0, (now - fetched_at).days)


def is_stale(fetched_at: datetime | None, now: datetime) -> bool:
    age = age_days(fetched_at, now)
    return age is None or age > MAX_AGE_DAYS


def checked_label(fetched_at: datetime) -> str:
    """"checked Oct 6": the day the trend was last fetched (the data's own date, never the request time)."""
    return f"checked {fetched_at.strftime('%b')} {fetched_at.day}"


def buy_share(row) -> tuple[float, int]:
    total = row.strong_buy + row.buy + row.hold + row.sell + row.strong_sell
    return ((row.strong_buy + row.buy) / total, total) if total else (0.0, 0)


def earlier_period(rows, latest):
    """The first row whose period is 60 or more days before the latest (rows ordered by period, newest first)."""
    for r in rows:
        if (latest.period - r.period).days >= 60:
            return r
    return None


def analyst_lean(rows, now: datetime) -> tuple[str, str]:
    """Pure: (direction, justification) for the Build page's analyst lean from a ticker's rows (newest period first). A stale or
    missing trend is neutral and says so; a usable one names the day it was checked."""
    if not rows:
        return "neutral", "No recommendation data yet"
    latest = rows[0]
    age = age_days(latest.fetched_at, now)
    if is_stale(latest.fetched_at, now):
        when = f" (last {checked_label(latest.fetched_at)})" if latest.fetched_at is not None else ""
        return "neutral", f"Recommendation data is {age} days old{when}; not used" if age is not None else "Recommendation data has no fetch date; not used"
    checked = f"{SOURCE}, {checked_label(latest.fetched_at)}"
    latest_share, latest_total = buy_share(latest)
    earlier = earlier_period(rows, latest)
    if earlier is None:
        if latest_total < MIN_ANALYSTS:
            return "neutral", f"Fewer than {MIN_ANALYSTS} analysts covering ({latest_total}) ({checked})"
        return "neutral", f"Buy share {latest_share:.0%} of {latest_total} analysts, but no earlier period for comparison ({checked})"
    earlier_share, earlier_total = buy_share(earlier)
    if latest_total < MIN_ANALYSTS or earlier_total < MIN_ANALYSTS:
        return "neutral", f"Fewer than {MIN_ANALYSTS} analysts covering ({checked})"
    delta = latest_share - earlier_share
    if delta >= 0.03:
        return "bullish", f"Buy share {latest_share:.0%} of {latest_total} analysts, up from {earlier_share:.0%} three months ago ({checked})"
    if delta <= -0.03:
        return "bearish", f"Buy share {latest_share:.0%} of {latest_total} analysts, down from {earlier_share:.0%} three months ago ({checked})"
    return "neutral", f"Buy share {latest_share:.0%} of {latest_total} analysts, stable vs {earlier_share:.0%} three months ago ({checked})"


def buy_share_delta(rows, now: datetime) -> dict | None:
    """Pure: Discover's buy-share shift for a ticker from its rows (newest period first), or None when the trend is stale, has no
    earlier period, or has fewer than MIN_ANALYSTS analysts in either period."""
    if not rows:
        return None
    latest = rows[0]
    if is_stale(latest.fetched_at, now):
        return None
    ls, lt = buy_share(latest)
    earlier = earlier_period(rows, latest)
    if earlier is None or lt < MIN_ANALYSTS:
        return None
    es, et = buy_share(earlier)
    if et < MIN_ANALYSTS:
        return None
    return {"buy_share": ls, "delta": ls - es, "total": lt, "as_of": latest.period.isoformat(), "checked": checked_label(latest.fetched_at)}


def buy_share_line(buy: dict) -> str:
    """Pure: Discover's buy-share sentence, with the day the trend was checked."""
    share_pct = round(buy["buy_share"] * 100)
    delta_pp = round(abs(buy["delta"]) * 100)
    direction = "up" if buy["delta"] >= 0 else "down"
    return f"Buy share {share_pct}% of {buy['total']} analysts, {direction} {delta_pp} points in 3 months ({buy['checked']})"
