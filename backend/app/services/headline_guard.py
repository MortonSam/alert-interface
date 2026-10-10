"""The headline guard: a headline shown beside a stock's move must not contradict it. Vendor-independent: it reads only the
headline text, the stock's own name forms and our close-to-close move, never anything a news vendor attaches.

Only the clauses that name the stock are judged (a headline is split at ";", ":", dashes, commas and "as", "while", "after",
"amid", "but", "following", "and"), and a clause about a non-price figure (FIGURE_WORDS: volume, revenue, sales, ...) or a
longer period (since December, this year, in September, ...) does not count. In what remains, a headline is suppressed when
  - its verb clearly points the other way from the day's move: an UP_VERBS word on a down day, or a DOWN_VERBS word on an up
    day (words from both lists are not clear, and pass);
  - it states a percent move for the stock with the opposite sign. A same-direction percent that differs from our close passes:
    headlines are written while the stock is still moving. A percent counts as a move only when a move word sits right before
    it, or "shares"/"stock" leads into it.
Freshness (published after the previous session's 4:00pm New York close) is services/news.headline_problem's first test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# both word lists, here and nowhere else
UP_VERBS = ("surge", "surges", "surged", "surging", "soar", "soars", "soared", "soaring", "jump", "jumps", "jumped", "jumping",
            "rally", "rallies", "rallied", "rallying")
DOWN_VERBS = ("fall", "falls", "fell", "falling", "slide", "slides", "slid", "sliding", "plunge", "plunges", "plunged", "plunging",
              "sink", "sinks", "sank", "sunk", "sinking")
# words that mark a following percent as a price move without saying which way on their own
MOVE_CUES = ("up", "down", "rise", "rises", "rose", "gain", "gains", "gained", "climb", "climbs", "climbed", "drop", "drops",
             "dropped", "slip", "slips", "slipped", "tumble", "tumbles", "tumbled", "lose", "loses", "lost", "higher", "lower")
CUE_SIGN = {**{w: 1 for w in UP_VERBS}, **{w: -1 for w in DOWN_VERBS},
            **{w: 1 for w in ("up", "rise", "rises", "rose", "gain", "gains", "gained", "climb", "climbs", "climbed", "higher")},
            **{w: -1 for w in ("down", "drop", "drops", "dropped", "slip", "slips", "slipped", "tumble", "tumbles", "tumbled",
                               "lose", "loses", "lost", "lower")}}
FIGURE_WORDS = ("volume", "volumes", "revenue", "revenues", "sales", "earnings", "profit", "profits", "income", "eps", "deliveries",
                "orders", "bookings", "users", "subscribers", "traffic", "margin", "margins", "dividend", "guidance", "outlook",
                "forecast", "production", "shipments", "backlog")
_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_PERIOD = re.compile(rf"\b(?:since|this\s+(?:year|month|week|quarter)|year[- ]to[- ]date|ytd|so\s+far|last\s+(?:week|month|year|quarter)|"
                     rf"over\s+the\s+(?:past|last)|in\s+(?:{_MONTHS})|in\s+\d{{4}}|in\s+a\s+year|for\s+the\s+(?:week|month|year)|"
                     rf"(?:week|month|year)ly\s+(?:gain|loss|drop|rise))\b", re.I)
_FIGURE = re.compile(r"\b(?:" + "|".join(FIGURE_WORDS) + r")\b", re.I)
_CLAUSE = re.compile(r"\s*(?:[;:|\u2014\u2013]|\s-\s|,\s+|\s(?:as|while|after|amid|but|following|and)\s)\s*", re.I)

_UP = re.compile(r"\b(?:" + "|".join(UP_VERBS) + r")\b", re.I)
_DOWN = re.compile(r"\b(?:" + "|".join(DOWN_VERBS) + r")\b", re.I)
_CUE_PCT = re.compile(r"\b(" + "|".join(sorted(CUE_SIGN, key=len, reverse=True)) + r")\b(?:\s+(?:by|as\s+much\s+as|nearly|almost|about|over|more\s+than))?\s+([+-]?\d+(?:\.\d+)?)\s?%", re.I)
_SHARES_PCT = re.compile(r"\b(?:shares|stock)\b[^.%]{0,40}?([+-]\d+(?:\.\d+)?)\s?%", re.I)


@dataclass(frozen=True)
class Verdict:
    reason: str | None          # None: the headline may show
    stated_pct: float | None    # the percent move the headline states, signed when it says which way


def direction(headline: str) -> int:
    """Pure: +1 when the headline's verbs clearly say up, -1 clearly down, 0 when neither or both."""
    up, down = bool(_UP.search(headline)), bool(_DOWN.search(headline))
    return 1 if up and not down else -1 if down and not up else 0


def stated_move(headline: str) -> float | None:
    """Pure: the percent move the headline states, signed by its move word ("falls 6%" -> -6.0, "up 3.5%" -> 3.5)."""
    m = _CUE_PCT.search(headline)
    if m:
        value = float(m.group(2))
        return value if value < 0 or m.group(2).startswith("+") else CUE_SIGN[m.group(1).lower()] * value
    m = _SHARES_PCT.search(headline)
    return float(m.group(1)) if m else None


def clauses_about(headline: str, forms: list[str]) -> list[str]:
    """Pure: the clauses of the headline that name the stock (by any of `forms`), each from the point where it names the stock,
    less those about a non-price figure or a longer period. With no forms, the whole headline is one clause."""
    parts = [p for p in _CLAUSE.split(headline) if p and p.strip()]
    if forms:
        def from_name(p: str) -> str | None:       # the clause from where it names the stock: a verb before the name is another's
            hits = [m.start() for f in forms for m in [re.search(rf"(?<![A-Za-z0-9]){re.escape(f)}(?:'s|’s)?(?![A-Za-z0-9])", p,
                                                                   0 if f.isupper() else re.I)] if m]
            return p[min(hits):] if hits else None
        parts = [q for q in (from_name(p) for p in parts) if q]
    return [p for p in parts if not _PERIOD.search(p) and not _FIGURE.search(p)]


def check(headline: str, move_pct: float | None, forms: list[str] | None = None) -> Verdict:
    """Pure: whether a headline may show beside a stock that moved `move_pct` percent close to close. `forms` are the words that
    name the stock (services/news.name_forms); only the clauses that name it are judged."""
    judged = clauses_about(headline, forms or [])
    stated = next((v for v in (stated_move(c) for c in judged) if v is not None), None)
    if move_pct is None or move_pct == 0 or not judged:
        return Verdict(None, stated)
    ups = sum(1 for c in judged if direction(c) > 0)
    downs = sum(1 for c in judged if direction(c) < 0)
    d = 1 if ups and not downs else -1 if downs and not ups else 0
    if d and (d > 0) != (move_pct > 0):
        return Verdict(f"its verb says {'up' if d > 0 else 'down'} on {'a down' if move_pct < 0 else 'an up'} day", stated)
    if stated is not None and (stated > 0) != (move_pct > 0):
        return Verdict("its stated move has the opposite sign", stated)
    return Verdict(None, stated)
