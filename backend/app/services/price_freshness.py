"""One test for whether a ticker's daily price history can be shown.

Used by the validate check and by the quote, chart and RV endpoints so they
agree: a history is unusable when its last bar is more than MAX_STALE_SESSIONS
exchange sessions old, or when its last close is more than MAX_QUOTE_DIVERGENCE
away from the ticker's quote (the series belongs to another instrument).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

from app.services.trading_calendar import sessions_after

MAX_STALE_SESSIONS = 3
MAX_QUOTE_DIVERGENCE = 0.25


@dataclass(frozen=True)
class HistoryState:
    state: str            # "ok" | "stale" | "mismatch" | "no_data"
    reason: str | None    # plain language, safe to show a visitor
    last_bar_date: date | None
    detail: str | None = None   # technical detail, for logs only

    @property
    def ok(self) -> bool:
        return self.state == "ok"


def quote_divergence(last_close: float | None, quote: float | None) -> float | None:
    if not last_close or not quote or last_close <= 0 or quote <= 0:
        return None
    return abs(last_close - quote) / quote


def assess_history(
    last_bar_date: date | None,
    last_close: float | None,
    quote: float | None,
    today: date | None = None,
) -> HistoryState:
    if last_bar_date is None:
        return HistoryState("no_data", "No price history is available for this ticker", None)
    missed = sessions_after(last_bar_date, today or date.today())
    if missed > MAX_STALE_SESSIONS:
        return HistoryState(
            "stale",
            f"Price history for this ticker stopped updating on {last_bar_date.isoformat()}",
            last_bar_date,
            detail=f"last bar {last_bar_date} is {missed} sessions old",
        )
    div = quote_divergence(last_close, quote)
    if div is not None and div > MAX_QUOTE_DIVERGENCE:
        return HistoryState(
            "mismatch",
            "The price history we have for this ticker does not match its current price, so it is not shown",
            last_bar_date,
            detail=f"last close {last_close:.2f} on {last_bar_date} is {div * 100:.0f}% from quote {quote:.2f}",
        )
    return HistoryState("ok", None, last_bar_date)


@dataclass(frozen=True)
class QuoteState:
    price: float | None       # None unless the quote may be shown
    state: str                # "ok" | "stale" | "no_data"
    reason: str | None        # plain language, safe to show a visitor
    traded_on: date | None
    traded_on_ts: int | None = None   # the quote's own last-trade time, Unix UTC


def assess_quote(quote_price: float | None, timestamp: int | None, today: date | None = None) -> QuoteState:
    """A quote may be shown, or fed to a model, only if its last trade is recent."""
    if not quote_price or quote_price <= 0:
        return QuoteState(None, "no_data", "No current price is available for this ticker", None)
    if not timestamp:
        return QuoteState(None, "no_data", "The latest price has no trade time, so it cannot be confirmed as current", None)
    traded = datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
    missed = sessions_after(traded, today or date.today())
    if missed > MAX_STALE_SESSIONS:
        return QuoteState(None, "stale", f"The latest price is from {traded.isoformat()} and is no longer current",
                          traded, int(timestamp))
    return QuoteState(float(quote_price), "ok", None, traded, int(timestamp))
