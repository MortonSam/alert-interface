"""The headline guard: a headline shown beside a stock's move must not contradict it. Vendor-independent: it reads only the
headline text, the stock's own name forms and our close-to-close move, never anything a news vendor attaches.

Only the clauses that name the stock are judged (a headline is split at ";", ":", dashes, commas and "as", "while", "after",
"amid", "but", "following", "and"), and a clause about a non-price figure (FIGURE_WORDS: volume, revenue, sales, ...) or a
longer period (since December, this year, in September, in three months, from its record high, off its highs, ...) does not
count. In what remains, a headline is suppressed when
  - its move word clearly points the other way from the day's move: an UP_VERBS word (or up/higher) on a down day, or a
    DOWN_VERBS word (or down/lower) on an up day. The word counts only when it directly follows the stock's name (or
    "shares"/"stock" after it) within three words with no hedge (HEDGES: might, could, poised, ...) before it (subject_word);
    clauses pointing both ways are not clear, and pass;
  - it calls the stock flat (FLAT_PHRASES: treads water, little changed, flat, unchanged, holds steady) beside a printed move
    larger than FLAT_BAND_PP either way;
  - it states a percent move for the stock more than PERCENT_TOLERANCE_PP points from, or of the other sign than, the exact
    figure the page prints beside it (the mover's change, or the change shown with the story), at every hour. A percent counts
    as a move only when a move word sits right before it, or "shares"/"stock" leads into it.
Freshness (published after the previous session's 4:00pm New York close) is services/news.headline_problem's first test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# every move word the guard knows, here and nowhere else: each is a direction word for the verb check and a cue for a stated percent
UP_VERBS = ("surge", "surges", "surged", "surging", "soar", "soars", "soared", "soaring", "jump", "jumps", "jumped", "jumping",
            "rally", "rallies", "rallied", "rallying", "rise", "rises", "rose", "rising", "risen", "gain", "gains", "gained", "gaining",
            "climb", "climbs", "climbed", "climbing", "spike", "spikes", "spiked", "spiking", "rocket", "rockets", "rocketed",
            "skyrocket", "skyrockets", "skyrocketed", "leap", "leaps", "leaped", "leapt", "pop", "pops", "popped", "advance",
            "advances", "advanced", "rebound", "rebounds", "rebounded", "rebounding")
DOWN_VERBS = ("fall", "falls", "fell", "falling", "slide", "slides", "slid", "sliding", "plunge", "plunges", "plunged", "plunging",
              "sink", "sinks", "sank", "sunk", "sinking", "drop", "drops", "dropped", "dropping", "slip", "slips", "slipped", "slipping",
              "tumble", "tumbles", "tumbled", "tumbling", "crash", "crashes", "crashed", "crashing", "lose", "loses", "lost", "losing",
              "decline", "declines", "declined", "declining", "slump", "slumps", "slumped", "slumping", "dive", "dives", "dived", "dove",
              "diving", "plummet", "plummets", "plummeted", "plummeting", "tank", "tanks", "tanked", "tanking", "retreat", "retreats",
              "retreated", "skid", "skids", "skidded", "sag", "sags", "sagged", "dip", "dips", "dipped", "dipping", "shed", "sheds")
# direction adverbs ("edges higher", "trades up", "Humana up 13%"): they count right after the name or after a linking verb, never
# after another verb ("Intel steps up", "Tesla shuts down")
ADVERBS = {"up": 1, "higher": 1, "down": -1, "lower": -1}
LINKS = ("is", "are", "was", "were", "trades", "traded", "trading", "edges", "edged", "edging", "moves", "moved", "moving", "ticks",
         "ticked", "inches", "inched", "heads", "headed", "trends", "opens", "opened", "closes", "closed", "ends", "ended", "finishes",
         "finished", "shares", "stock")
# verbs that also take an object ("Nvidia gains approval", "Apple drops lawsuit"): a move only when a percent, nothing, or one of
# FOLLOWERS comes next ("Palo Alto and CrowdStrike Gain 4%", "AT&T drops on ...")
AMBIGUOUS = ("gain", "gains", "gained", "drop", "drops", "dropped", "lose", "loses", "lost", "pop", "pops", "advance", "advances",
             "advanced", "shed", "sheds", "dive", "dives", "tank", "tanks", "rocket", "rockets", "crash", "crashes", "crashed")
FOLLOWERS = ("on", "as", "after", "amid", "following", "in", "despite", "while", "with", "since", "from", "ground", "sharply",
             "slightly", "again", "today", "premarket", "early", "late", "more", "nearly", "almost", "about", "over", "by", "toward",
             "towards", "further", "after-hours", "midday", "friday", "monday", "tuesday", "wednesday", "thursday")
# flat words: they contradict any printed move larger than FLAT_BAND_PP either way
FLAT_PHRASES = ("treads water", "treading water", "tread water", "little changed", "holds steady", "holding steady", "flat", "unchanged")
FLAT_BAND_PP = 2.0
CUE_SIGN = {**{w: 1 for w in UP_VERBS}, **{w: -1 for w in DOWN_VERBS}, **ADVERBS}
MOVE_WORDS = tuple(CUE_SIGN)        # every move word: a direction word for the verb check and a cue for a stated percent
FIGURE_WORDS = ("volume", "volumes", "revenue", "revenues", "sales", "earnings", "profit", "profits", "income", "eps", "deliveries",
                "orders", "bookings", "users", "subscribers", "traffic", "margin", "margins", "dividend", "guidance", "outlook",
                "forecast", "production", "shipments", "backlog")
_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_PERIOD = re.compile(rf"\b(?:since|this\s+(?:year|month|week|quarter)|year[- ]to[- ]date|ytd|so\s+far|last\s+(?:week|month|year|quarter)|"
                     rf"over\s+the\s+(?:past|last)|in\s+(?:{_MONTHS})|in\s+\d{{4}}|in\s+a\s+year|for\s+the\s+(?:week|month|year)|"
                     rf"(?:week|month|year)ly\s+(?:gain|loss|drop|rise)|"
                     rf"in\s+(?:[2-9]|\d{{2,}}|two|three|four|five|six|seven|eight|nine|ten|twelve|several|a\s+few)\s+(?:trading\s+)?(?:days|sessions)|"
                     rf"in\s+(?:\d+|a|one|two|three|four|five|six|seven|eight|nine|ten|twelve|several|a\s+few)\s+(?:week|month|year)s?|"
                     rf"(?:from|off|below|above)\s+(?:its|their|the|a)\s+(?:record|all[- ]time|52[- ]week)?\s*(?:high|highs|peak|peaks|low|lows|top)|"
                     rf"(?:from|off)\s+(?:record|all[- ]time|52[- ]week)\s+(?:high|highs|low|lows))\b", re.I)
# hedged forms: a verb after these is a forecast or a possibility, not the day's move
# a word that starts a new subject: a verb after it is about something else ("Home Depot until rates fall")
BREAKERS = ("until", "if", "when", "before", "after", "despite", "because", "unless", "as", "while", "amid", "with", "on", "for",
            "than", "since", "even", "though", "although", "where", "whose", "that", "which", "its", "their", "his", "her")
HEDGES = ("might", "could", "may", "would", "should", "poised", "set", "likely", "expected", "aims", "eyes", "seen", "can", "will", "to")
_FIGURE = re.compile(r"\b(?:" + "|".join(FIGURE_WORDS) + r")\b", re.I)
_CLAUSE = re.compile(r"\s*(?:[;:|\u2014\u2013]|\s-\s|,\s+|\s(?:as|while|after|amid|but|following|and)\s)\s*", re.I)

_UP = re.compile(r"\b(?:" + "|".join(UP_VERBS) + r")\b", re.I)
_DOWN = re.compile(r"\b(?:" + "|".join(DOWN_VERBS) + r")\b", re.I)
_MOVE_ANY = re.compile(r"\b(?:" + "|".join(UP_VERBS + DOWN_VERBS + tuple(ADVERBS) + FLAT_PHRASES) + r")\b", re.I)
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


def _case(form: str) -> int:
    """Regex flags for a name form: a ticker ("MU", "AT&T") matches its capitals only; a name ("Micron", "NVIDIA") any case."""
    return 0 if form.isupper() and len(form) <= 5 else re.I


def _norm(w: str) -> str:
    return w.lower().strip(".,'’%")


def subject_word(clause: str, forms: list[str]) -> str | None:
    """Pure: "up", "down" or "flat" when a move word directly follows the stock's name (or "(TICKER)", "shares"/"stock" after it)
    within three words, with no hedge (might, could, poised, ...) or subject breaker before it; None otherwise. An adverb (up,
    higher, down, lower) counts only first or after a linking verb (trades, edges, is, ...); an AMBIGUOUS verb only before a
    percent, nothing, or one of FOLLOWERS. `clause` starts at the name (clauses_about)."""
    words = re.findall(r"[A-Za-z0-9'’.&+%-]+|\([^)]*\)", clause)
    # skip the name itself (it may be several words) and an optional "(TICKER)", "'s", "shares"/"stock"
    start = 0
    for f in sorted(forms, key=len, reverse=True):
        n = len(f.split())
        if " ".join(words[:n]).lower().rstrip("'’s").rstrip("'’") == f.lower() or " ".join(words[:n]).lower().startswith(f.lower()):
            start = n
            break
    rest = words[start:]
    if rest and rest[0].startswith("("):
        rest = rest[1:]
    if rest and rest[0].lower() in ("shares", "stock", "stocks"):
        rest = rest[1:]
    norm = [_norm(w) for w in rest]
    for i, w in enumerate(norm[:3]):
        if " ".join(norm[i:i + 2]) in FLAT_PHRASES or w in FLAT_PHRASES:
            return "flat"
        if w in HEDGES or w in BREAKERS:
            return None
        if w in ADVERBS:
            return ("up" if ADVERBS[w] > 0 else "down") if i == 0 or norm[i - 1] in LINKS else None
        if w in CUE_SIGN:
            nxt = norm[i + 1] if i + 1 < len(norm) else ""
            if w in AMBIGUOUS and nxt and not (re.match(r"^[+-]?\d", nxt) or nxt in FOLLOWERS):
                return None
            return "up" if CUE_SIGN[w] > 0 else "down"
    return None


def subject_direction(clause: str, forms: list[str]) -> int:
    """Pure: +1 or -1 when a direction word directly follows the stock's name (subject_word); 0 otherwise. With no forms, any
    clear verb in the clause counts."""
    if not forms:
        return direction(clause)
    w = subject_word(clause, forms)
    return 1 if w == "up" else -1 if w == "down" else 0


def stated_move(headline: str) -> float | None:
    """Pure: the percent move the headline states, signed by its move word ("falls 6%" -> -6.0, "up 3.5%" -> 3.5)."""
    m = _CUE_PCT.search(headline)
    if m:
        value = float(m.group(2))
        return value if value < 0 or m.group(2).startswith("+") else CUE_SIGN[m.group(1).lower()] * value
    m = _SHARES_PCT.search(headline)
    return float(m.group(1)) if m else None


_ITEM = r"[A-Z][\w&.'’-]*(?:\s+[A-Z][\w&.'’-]*){0,3}(?:\s*\([A-Z.]{1,6}\))?"
_SEP = r"(?:\s*,\s*(?:and\s+)?|\s+and\s+|\s*&\s*)"
_GROUP = re.compile(rf"((?:{_ITEM})(?:{_SEP}(?:{_ITEM}))+)\s+(?:(?i:shares|stocks?)\s+)?(?:(?i:are|were|is)\s+)?"
                    rf"((?i:{'|'.join(UP_VERBS + DOWN_VERBS)}))\b((?:\s+(?i:by\s+)?[+-]?\d+(?:\.\d+)?\s?%)?)")


def group_clauses(headline: str, forms: list[str]) -> list[str]:
    """Pure: when a list of companies shares one move verb ("Verizon, AT&T, T-Mobile Stocks Slide as ..."), that verb (and a
    percent right after it) is each listed company's move: one "<name> <verb>" clause for the stock when the list names it."""
    out = []
    for m in _GROUP.finditer(headline):
        listed = m.group(1)
        for f in forms:
            if re.search(rf"(?<![A-Za-z0-9]){re.escape(f)}(?:'s|’s)?(?![A-Za-z0-9])", listed, _case(f)):
                out.append(f"{f} {m.group(2)}{m.group(3) or ''}")
                break
    return out


def clauses_about(headline: str, forms: list[str]) -> list[str]:
    """Pure: the clauses of the headline that name the stock (by any of `forms`), each from the point where it names the stock,
    plus its clause from a group sharing one move verb (group_clauses), less those about a non-price figure or a longer period.
    With no forms, the whole headline is one clause."""
    parts = [p for p in _CLAUSE.split(headline) if p and p.strip()]
    if forms:
        def from_name(p: str) -> str | None:       # the clause from where it names the stock: a verb before the name is another's
            hits = [m.start() for f in forms for m in [re.search(rf"(?<![A-Za-z0-9]){re.escape(f)}(?:'s|’s)?(?![A-Za-z0-9])", p,
                                                                   _case(f))] if m]
            return p[min(hits):] if hits else None
        parts = [q for q in (from_name(p) for p in parts) if q] + group_clauses(headline, forms)
    return [p for p in parts if not _PERIOD.search(p) and not _FIGURE.search(p)]


# a headline counts for a stock only when it leads with it: the stock is named in the first clause (before the first semicolon,
# colon, dash or "as", or a comma after a clause that states a move), once a leading market-wrap prefix is skipped
_WRAP = re.compile(r"^\W*(?:stock\s+market\s+(?:today|midday|close|wrap|update)\b[^:]*:|stocks?\s+making\s+the\s+biggest\s+moves\b[^:]*:)\s*", re.I)
_LEAD_BREAK = re.compile(r";|:(?!\d)|\s-\s|[\u2014\u2013]|\sas\s", re.I)
# a sentence end ("Big Tech Needs Power. Constellation ..."), not an initial, a month or an abbreviation (U.S., Oct., Inc., vs.)
_SENTENCE = re.compile(r"(?<![A-Z])(?<!\bvs)(?<!\bInc)(?<!\bCorp)(?<!\bCo)(?<!\bSt)(?<!\bMr)(?<!\bNo)"
                       r"(?<!\b(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec))(?<!\bSept)\.\s+(?=[A-Z])")


def first_clause(headline: str) -> str:
    """Pure: the headline's first clause after any market-wrap prefix ("Stock Market Today, Oct. 9: ...")."""
    h = _WRAP.sub("", headline or "", count=1)
    ends = [m.start() for m in (_LEAD_BREAK.search(h), _SENTENCE.search(h)) if m]
    head = h[:min(ends)] if ends else h
    out = []
    for seg in head.split(","):          # a list of names stays one clause; "Stocks Edge Higher, Humana jumps 13%" does not
        out.append(seg)
        if _MOVE_ANY.search(seg):
            break
    return ",".join(out)


def leads_with(headline: str, forms: list[str]) -> bool:
    """Pure: the headline names the stock (by any of `forms`) in its first clause (first_clause)."""
    head = first_clause(headline)
    return any(re.search(rf"(?<![A-Za-z0-9]){re.escape(f)}(?:'s|’s)?(?![A-Za-z0-9])", head, _case(f)) for f in forms)


PERCENT_TOLERANCE_PP = 1.5     # a stated percent must be this close to the figure the page prints beside it, and of the same sign

# Explainers of today's move ("Why X stock soared today", "Why X shares are trading lower today", "Here's why X fell") are news:
# eligible everywhere, ranked as news when they agree with today's direction. Opinion and promotion show nowhere on Discover.
_EXPLAINER = re.compile(r"^\W*why\b|\bhere['’]?s\s+why\b|\bhere\s+is\s+why\b|what['’]?s\s+going\s+on\s+with", re.I)
_OPINION = re.compile(
    # valuation views
    r"\b(?:under|over)valued\b|\blooks?\s+(?:discounted|cheap|expensive|attractive)\b|\bmay\s+be\s+reasonable\b|"
    r"\bfairly\s+(?:priced|valued)\b|\bfair\s+value\b|\bthesis\b|"
    # hedged takes
    r"\b(?:may|might|could)\b|"
    # recommendations
    # (buy and sell advice is services/news._RECOMMENDATION, which tells "Sell Micron Now" from "Insiders sell Micron shares")
    r"\bshould\s+you\b|\bis\s+it\s+time\b|\bjim\s+cramer\b|\breasons?\s+to\s+(?:buy|hold|sell|own|keep|add|avoid)\b|"
    r"\bin\s+your\s+portfolio\b|"
    # rankings and lists
    r"\b(?:top|best)\s+(?:\d+\s+)?(?:[\w-]+\s+){0,2}stocks?\b|\b(?:top|best)\s+\d+\b|\branks?\b|\branking\b|#\s?\d+\b|"
    # digests
    r"important\s+facts\s+to\s+note|what\s+you\s+(?:should|need\s+to)\s+know|things\s+to\s+know|what\s+to\s+know|"
    r"\bhere['’]?s\s+(?:what|how)\b|\bhere\s+is\s+(?:what|how)\b|what\s+needs\s+to\s+happen|"
    # comparisons
    r"worth\s+more\s+than|^\W*better\b|"
    # trading ideas ("How to Play Unusual Options Activity in Oracle Stock")
    r"\bhow\s+to\s+(?:play|trade|profit)\b|\bways?\s+to\s+play\b|\bunusual\s+options\s+activity\b|\btrade\s+ideas?\b|"
    r"\boptions?\s+trade\s+(?:idea|of\s+the)|\bplay(?:ing)?\s+(?:the|this)\s+(?:dip|move|rally|breakout|earnings)\b", re.I)
# "vs." or "versus" is opinion when it compares stocks: with better, which, stock(s), buy, or two tickers ("NVDA vs. AMD"), or a
# company on either side ("Oracle vs. Cisco: The Dividend Battle ..."); legal news ("Apple vs. Epic ruling", "FTC vs. Meta trial")
# and a regulator on the left stay eligible
_VERSUS = re.compile(r"\bvs\.?(?=\s)|\bversus\b", re.I)
_COMPARES_STOCKS = re.compile(r"\bbetter\b|\bwhich\b|\bstocks?\b|\bbuy\b", re.I)
_TICKER_TOKEN = re.compile(r"(?<![A-Za-z&])[A-Z]{2,5}(?![A-Za-z&])")
_NAME_VS_NAME = re.compile(r"(?<![\w&.'’-])[A-Z][\w&.'’-]*(?:\s+[A-Z][\w&.'’-]*){0,3}\s+(?:vs\.?|versus)\s+[A-Z][\w&'’-]")
_LEGAL = re.compile(r"\b(?:ruling|rules|trial|lawsuit|suit|sues|sued|case|court|courts|judge|jury|verdict|appeal|appeals|settlement|"
                    r"settle|settles|antitrust|litigation|patent|injunction|arbitration|ftc|doj|sec|regulators?|state\s+of)\b", re.I)
NOT_TICKERS = {"AI", "US", "USA", "UK", "EU", "CEO", "CFO", "IPO", "ETF", "EPS", "FDA", "FTC", "SEC", "DOJ", "GDP", "NYSE", "CMS",
               "NIH", "GLP", "EV", "EVS", "TV", "PC", "ID", "OK", "MHZ"}
# thesis pieces: "Company (TICKER): Expanding ...", "Company (TICKER) Capitalizing on ..." (case-sensitive: the ticker's capitals)
_THESIS = re.compile(r"\([A-Z][A-Z.-]{0,6}\)\s*:?\s+[A-Z][a-z]+ing\b")


def is_explainer(headline: str) -> bool:
    """Pure: an explainer of the day's move (Why..., Here's why..., What's going on with...)."""
    return bool(_EXPLAINER.search(headline or ""))


def is_opinion(headline: str) -> bool:
    """Pure: opinion or promotion, shown nowhere on Discover: valuation views, hedged takes (may, might, could), recommendations
    (buy, sell, should you, is it time, Jim Cramer), rankings and lists, digests (important facts to note, what you should know,
    here's what), comparisons (worth more than; "vs." between stocks), trading ideas (how to play, unusual options activity), and thesis pieces ("Company (TICKER): Expanding ...")."""
    h = headline or ""
    if _VERSUS.search(h) and (_COMPARES_STOCKS.search(h) or len({t for t in _TICKER_TOKEN.findall(h) if t not in NOT_TICKERS}) >= 2
                              or (_NAME_VS_NAME.search(h) and not _LEGAL.search(h))):
        return True
    return bool(_THESIS.search(h) or _OPINION.search(h))


def check(headline: str, move_pct: float | None, forms: list[str] | None = None) -> Verdict:
    """Pure: whether a headline may show beside a stock whose printed change is `move_pct` percent (the exact figure the page
    shows next to it). `forms` are the words that name the stock (services/news.name_forms); only the clauses that name it are
    judged. A stated percent must be within PERCENT_TOLERANCE_PP points of the printed figure and of the same sign, at every hour."""
    judged = clauses_about(headline, forms or [])
    stated = next((v for v in (stated_move(c) for c in judged) if v is not None), None)
    if move_pct is None or move_pct == 0 or not judged:
        return Verdict(None, stated)
    dirs = [subject_direction(c, forms or []) for c in judged]
    ups, downs = sum(1 for x in dirs if x > 0), sum(1 for x in dirs if x < 0)
    d = 1 if ups and not downs else -1 if downs and not ups else 0
    if d and (d > 0) != (move_pct > 0):
        return Verdict(f"its verb says {'up' if d > 0 else 'down'} on {'a down' if move_pct < 0 else 'an up'} day", stated)
    if forms and abs(move_pct) > FLAT_BAND_PP and any(subject_word(c, forms) == "flat" for c in judged):
        return Verdict(f"its words say flat against the {move_pct:+.2f}% printed beside it (more than {FLAT_BAND_PP:g} points)", stated)
    if stated is not None and (stated > 0) != (move_pct > 0):
        return Verdict("its stated move has the opposite sign", stated)
    if stated is not None and abs(stated - move_pct) > PERCENT_TOLERANCE_PP:
        return Verdict(f"it states {stated:+g}% against the {move_pct:+.2f}% printed beside it "
                       f"(more than {PERCENT_TOLERANCE_PP:g} points apart)", stated)
    return Verdict(None, stated)


def agrees(headline: str, move_pct: float | None, forms: list[str] | None = None) -> bool:
    """Pure: the headline states a move in the same direction as the stock's: a verb that follows its name, or a stated percent,
    with the stock's sign. The mover slot takes a headline from a source outside the established ones only when this holds."""
    if not move_pct:
        return False
    judged = clauses_about(headline, forms or [])
    for c in judged:
        d = subject_direction(c, forms or [])
        v = stated_move(c)
        if (d and (d > 0) == (move_pct > 0)) or (v is not None and (v > 0) == (move_pct > 0)):
            return True
    return False


def period_move_against(headline: str, move_pct: float | None, forms: list[str] | None = None) -> bool:
    """Pure: the headline states a move for the stock over a longer period (since December, in one month, from its record high)
    that runs against today's move. It may stand in "In the news", never beside a mover, where it reads as today's move."""
    if not move_pct:
        return False
    parts = [p for p in _CLAUSE.split(headline) if p and p.strip()]
    for p in parts:
        if not _PERIOD.search(p):
            continue
        hits = [m.start() for f in (forms or []) for m in [re.search(rf"(?<![A-Za-z0-9]){re.escape(f)}(?:'s|’s)?(?![A-Za-z0-9])", p,
                                                                     _case(f))] if m]
        if forms and not hits:
            continue
        c = p[min(hits):] if hits else p
        d = subject_direction(c, forms or [])
        v = stated_move(c)
        sign = d or (1 if v and v > 0 else -1 if v and v < 0 else 0)
        if sign and (sign > 0) != (move_pct > 0):
            return True
    return False
