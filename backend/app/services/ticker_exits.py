"""Why an inactive ticker stopped, read from its stored inactive_reason, and the line its page shows when the stock no longer trades.

Every writer of tickers.inactive_reason starts the reason with one of REASON_PREFIXES (seed_sp500's index leavers, the records
build's delisting rule, scripts/record_ticker_exits for filing-sourced exits), so the kind is read from the stored row, never guessed.
A kind with a successor (a merger or a ticker change) has an alias and its old symbol redirects; a kind whose stock still trades
(an index leaver) keeps its page. Only a kind in EXIT_LINES gets the "no longer trades" page, its line built from the stored name
and inactive_since; a no-successor kind without an approved line (DELISTED) shows the ordinary inactive page until one is approved.
"""
from __future__ import annotations

import re
from datetime import date

TAKEN_PRIVATE = "taken_private"
MERGED = "merged"
TICKER_CHANGED = "ticker_changed"
LEFT_INDEX = "left_index"
DELISTED = "delisted"

# the stored reason's opening words, as each writer spells them
REASON_PREFIXES = {
    TAKEN_PRIVATE: "taken private on ",
    MERGED: "merged into ",
    TICKER_CHANGED: "ticker changed to ",
    LEFT_INDEX: "left the S&P 500",
    DELISTED: "delisted: ",
}
NO_LONGER_TRADES = (TAKEN_PRIVATE, DELISTED)          # no successor: the shares are gone, not renamed or exchanged
EXIT_LINES = {
    TAKEN_PRIVATE: "{name} was taken private on {date}, and its stock no longer trades.",
}

_SUFFIX = re.compile(r",?\s+(Inc\.?|Incorporated|Corporation|Corp\.?|Company|Co\.?|Ltd\.?|Limited|plc|PLC|N\.V\.|S\.A\.|L\.P\.|LP|Holdings?)$")


def exit_kind(reason: str | None) -> str | None:
    """The kind of exit a stored inactive_reason records; None for no reason or one no writer spells."""
    for kind, prefix in REASON_PREFIXES.items():
        if reason and reason.startswith(prefix):
            return kind
    return None


def plain_name(name: str | None) -> str | None:
    """The company name without its legal suffix ("Electronic Arts Inc." -> "Electronic Arts")."""
    out = (name or "").strip()
    while out and (m := _SUFFIX.search(out)):
        out = out[:m.start()].rstrip(" ,")
    return out or None


def long_date(d: date) -> str:
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def exit_line(name: str | None, reason: str | None, since: date | None) -> str | None:
    """The page's line for a stock that no longer trades; None when the kind has no approved line or a fact is missing."""
    kind, plain = exit_kind(reason), plain_name(name)
    if kind not in EXIT_LINES or since is None or plain is None:
        return None
    return EXIT_LINES[kind].format(name=plain, date=long_date(since))
