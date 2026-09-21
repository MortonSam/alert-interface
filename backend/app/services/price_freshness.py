"""One test for whether a ticker's daily price history can be shown.

Used by the validate check and by the quote, chart and RV endpoints so they
agree: a history is unusable when its last bar is more than MAX_STALE_SESSIONS
exchange sessions old, or when its last close is more than MAX_QUOTE_DIVERGENCE
away from the ticker's quote (the series belongs to another instrument).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from app.services.trading_calendar import sessions_after

MAX_STALE_SESSIONS = 3
MAX_QUOTE_DIVERGENCE = 0.25


@dataclass(frozen=True)
class HistoryState:
    state: str            # "ok" | "stale" | "mismatch" | "no_data"
    reason: str | None
    last_bar_date: date | None

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
        return HistoryState("no_data", "No price history available", None)
    missed = sessions_after(last_bar_date, today or date.today())
    if missed > MAX_STALE_SESSIONS:
        return HistoryState(
            "stale",
            f"Price history stopped on {last_bar_date.isoformat()} ({missed} sessions ago)",
            last_bar_date,
        )
    div = quote_divergence(last_close, quote)
    if div is not None and div > MAX_QUOTE_DIVERGENCE:
        return HistoryState(
            "mismatch",
            f"Price history close {last_close:.2f} on {last_bar_date.isoformat()} is "
            f"{div * 100:.0f}% away from the quote {quote:.2f}",
            last_bar_date,
        )
    return HistoryState("ok", None, last_bar_date)
