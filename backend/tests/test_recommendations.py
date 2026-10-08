"""Analyst recommendation trends: the Build lean and the Discover buy-share line name the day the trend was checked, and a stale
trend (older than MAX_AGE_DAYS) is neutral on Build and left out of Discover. 2026-10-08: the nightly re-fetched the same ~120
tickers every night (nearest earnings first), so 370 of 503 tickers rendered trends weeks old as current."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import recommendations as R

NOW = datetime(2026, 10, 8, 14, 0, tzinfo=timezone.utc)


def row(period, fetched_days_ago, strong_buy=10, buy=10, hold=8, sell=1, strong_sell=1):
    return SimpleNamespace(period=period, fetched_at=NOW - timedelta(days=fetched_days_ago), strong_buy=strong_buy, buy=buy, hold=hold, sell=sell, strong_sell=strong_sell)


def test_the_lean_names_the_day_the_trend_was_checked_and_a_stale_trend_is_neutral():
    rows = [row(date(2026, 10, 1), 2), row(date(2026, 7, 1), 2, strong_buy=5, buy=10)]
    assert R.analyst_lean(rows, NOW) == ("bullish", "Buy share 67% of 30 analysts, up from 60% three months ago (Finnhub, checked Oct 6)")
    assert R.analyst_lean([row(date(2026, 10, 1), 2)], NOW) == ("neutral", "Buy share 67% of 30 analysts, but no earlier period for comparison (Finnhub, checked Oct 6)")
    assert R.analyst_lean([row(date(2026, 10, 1), 2, 1, 1, 1, 0, 0)], NOW) == ("neutral", "Fewer than 5 analysts covering (3) (Finnhub, checked Oct 6)")
    stale = [row(date(2026, 9, 1), 21), row(date(2026, 6, 1), 21, strong_buy=5, buy=10)]
    assert R.analyst_lean(stale, NOW) == ("neutral", "Recommendation data is 21 days old (last checked Sep 17); not used")
    assert R.analyst_lean([], NOW) == ("neutral", "No recommendation data yet")
    assert R.is_stale(NOW - timedelta(days=R.MAX_AGE_DAYS), NOW) is False and R.is_stale(NOW - timedelta(days=R.MAX_AGE_DAYS + 1), NOW) is True
    assert R.is_stale(None, NOW) is True


def test_discover_drops_a_stale_or_thin_trend_and_dates_a_usable_one():
    rows = [row(date(2026, 10, 1), 2), row(date(2026, 7, 1), 2, strong_buy=5, buy=10)]
    buy = R.buy_share_delta(rows, NOW)
    assert buy == {"buy_share": 20 / 30, "delta": 20 / 30 - 15 / 25, "total": 30, "as_of": "2026-10-01", "checked": "checked Oct 6"}
    assert R.buy_share_line(buy) == "Buy share 67% of 30 analysts, up 7 points in 3 months (checked Oct 6)"
    assert R.buy_share_delta([row(date(2026, 9, 1), 21), row(date(2026, 6, 1), 21)], NOW) is None       # stale: left out
    assert R.buy_share_delta([row(date(2026, 10, 1), 2)], NOW) is None                                    # no earlier period
    assert R.buy_share_delta([row(date(2026, 10, 1), 2, 1, 1, 1, 0, 0), row(date(2026, 7, 1), 2)], NOW) is None   # too few analysts
    assert R.FRESH_DAYS < R.MAX_AGE_DAYS and R.REFRESH_AFTER_DAYS < R.FRESH_DAYS


def test_the_build_route_and_discover_read_the_service():
    from pathlib import Path
    root = Path(__file__).parent.parent / "app"
    thesis = (root / "routers" / "thesis.py").read_text()
    assert "lean_from_recommendations(rec_rows, datetime.now(timezone.utc))" in thesis and 'three months ago"' not in thesis
    discover = (root / "routers" / "discover.py").read_text()
    assert "buy_share_delta(rows, now)" in discover and "buy_share_line(buy_share)" in discover and 'points in 3 months"' not in discover
    refresh = (root / "scripts" / "refresh_recommendations.py").read_text()
    assert "REFRESH_AFTER_DAYS" in refresh and "EARNINGS_SOON_DAYS" in refresh and "nulls_first()" in refresh
    assert refresh.index("latest_fetch.c.max_fetched.asc().nulls_first()") < refresh.index("next_earnings.c.next_earn.asc().nulls_last()")   # staleness decides before earnings
