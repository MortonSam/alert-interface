"""The headline guard: a headline shown beside a stock's move must not contradict it. Vendor-independent: it reads only the
headline text, the stock's own name forms and our close-to-close move, never anything a news vendor attaches.

A headline is suppressed when
  - its verb clearly points the other way from the day's move: an UP_VERBS word on a down day, or a DOWN_VERBS word on an up
    day (a headline with words from both lists is not clear, and passes this test);
  - it states a percent move for the stock that differs from our move by more than PERCENT_TOLERANCE_PP points, or has the
    opposite sign. A percent counts as a move only when a move word (either list, or MOVE_CUES) sits right before it, or
    "shares"/"stock" leads into it, so "raises its dividend 5%" or "revenue up 20%" in a results headline is not read as the
    stock's move.
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
PERCENT_TOLERANCE_PP = 1.0

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


def check(headline: str, move_pct: float | None) -> Verdict:
    """Pure: whether a headline may show beside a stock that moved `move_pct` percent close to close."""
    stated = stated_move(headline)
    if move_pct is None or move_pct == 0:
        return Verdict(None, stated)
    d = direction(headline)
    if d and (d > 0) != (move_pct > 0):
        return Verdict(f"its verb says {'up' if d > 0 else 'down'} on {'a down' if move_pct < 0 else 'an up'} day", stated)
    if stated is not None:
        if (stated > 0) != (move_pct > 0):
            return Verdict("its stated move has the opposite sign", stated)
        if abs(stated - move_pct) > PERCENT_TOLERANCE_PP:
            return Verdict(f"its stated move differs from ours by more than {PERCENT_TOLERANCE_PP:g} points", stated)
    return Verdict(None, stated)
