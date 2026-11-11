"""Ivy's quick checks: one per walkthrough step from step 2 on, never written by a model.

Every question states one fact about this stock and asks what it means for the business or for someone holding the stock; the
answer is a reading no text on its screen states (the step's sentences give figures, never their meaning, and "The idea" appears
only after the visitor answers or skips). The right option follows the direction of the data by a fixed rule; each wrong option is
clearly wrong to someone who understood the idea. Each template returns {concept, question, options, answer (index into options),
why}, or None when the data cannot support a fair question. Options whose right answer is the same text for every stock are
ordered per stock (_ordered: a fixed hash of the stock's name), so the right answer's position is not always the same, and carry
`same_answer`: the frontend shows such a check only the first time a visitor meets that answer (the last one met for its concept),
and the line comparing the two stocks after that. Explanations never restate the rules below, and no screen shows them (Sam,
2026-10-29: step 4's closeness rule left its Go deeper).

The rules (each constant below is the threshold the explanation quotes):
  step 1  no check.
  step 2  earnings (or FFO) per share grew faster or slower than sales when one growth factor (1 + growth) is more than
          SAME_RATIO above or below the other; about as fast asks nothing, and nor does a slower case whose sales fell.
  step 3  a margin that rose by MARGIN_SAME_CENTS or more (in the whole cents shown) points to pricing power or lower costs,
          one that fell that much to competition or rising costs, anything less barely moved; a swing of CYCLICAL_SWING_CENTS
          or more is named cyclical.
  step 4  two moves are close when within CLOSE_POINTS percentage points or within CLOSE_SHARE of the larger move, whichever is
          wider. The year was the closer of the S&P 500 and the median stock of its sector when that one is close, else the
          company's own. A stock over walkthrough.INDEX_SHARE_NO_VERDICT of the index's market value gets no such verdict: its
          check asks what that share means (index_share_check).
  step 5  investors pay more or less than usual when the P/E is more than PE_SAME_RATIO above or below its five-year median;
          about usual asks nothing. The right answer fits the company's year (pe_check): when its four-quarter earnings per share
          and its price over the year differ by more than SAME_RATIO (as growth factors), in the direction that moved the P/E, and
          the P/E a year earlier was not already on the same side of the median, the answer is that fact; else the usual reading.
  step 6  report days move the stock k times as much as an ordinary day (the typical report-day move over the ordinary day's);
          under REPORT_MULTIPLE_MIN asks nothing.
  step 7  a risk maps to the result it would hit first by RISK_TARGETS, only when its heading and sentence match exactly one
          target and no supply-chain word (RISK_EXCLUDED); the options are this walkthrough's business results only.
"""
from __future__ import annotations

import hashlib
import re

from app.services.fiscal_periods import cap

SAME_RATIO = 0.05               # growth factors within 5% of each other grew "about as fast"
MARGIN_SAME_CENTS = 1           # margins within a cent of each dollar (as shown, in whole cents) "barely moved"
CYCLICAL_SWING_CENTS = 20       # a margin that moved this many cents of each dollar in three years marks a cyclical business
CLOSE_POINTS = 5.0
CLOSE_SHARE = 0.2
PE_SAME_RATIO = 0.05
REPORT_MULTIPLE_MIN = 1.5       # report days must move the stock at least this many times an ordinary day for step 6's check
GROWTH_FLAT_PCT = 2.0           # sales within this many percent of the year before read "about flat" (the summary's word)
MOVE_MARKET_SHARE = 0.5         # a single day is the market's when SPY moved the same way by at least this share of the stock's move

# step 7: the result a risk would hit first, by the words of its heading and sentence. A risk matching both, or none, or any
# supply-chain word, gets no check. RISK_WORDS is how the explanation names each list (a test holds them to the patterns).
RISK_TARGETS = (
    ("margins", re.compile(r"\b(?:prices?|pricing|oversupply|compet\w*)\b", re.I)),
    ("growth", re.compile(r"\b(?:customers?|concentrat\w*|demand|orders?|rents?|rental|tenants?|vacanc\w*|leases?|revenues?)\b", re.I)),
)
RISK_WORDS = {"margins": "prices, pricing, oversupply or competition", "growth": "customers, concentration, demand, orders, rent, tenants, vacancy, leases or revenue"}
RISK_EXCLUDED = re.compile(r"\b(?:supply|supplies|suppliers?|supply[- ]chains?)\b", re.I)
# a risk sentence that names its own answer's measure is never the question
RISK_GIVEAWAY = {"margins": re.compile(r"\b(?:margins?|profit\w*|keeps?|kept|slice)\b", re.I),
                 "growth": re.compile(r"\b(?:sales|revenues?|grow\w*|growth)\b", re.I)}
RISK_OPTION_STEPS = ("business", "growth", "margins")     # step 7's options: business results only, never the stock price or the P/E

CONCEPTS = ("segments", "growth", "margins", "market_vs_company", "pe", "p_ffo", "report_move", "risk_factors")


def _ordered(options: list[str], right: str, seed: str) -> tuple[list[str], int]:
    """Pure: the options in a fixed per-stock order (a hash of seed and each option), and the right one's index."""
    o = sorted(options, key=lambda x: hashlib.sha256(f"{seed}|{x}".encode()).hexdigest())
    return o, o.index(right)


# ── number words (shared with services/walkthrough) ────────────────────────────────────────────────────────────────────────

def pct(x: float) -> str:
    """"1,061.5%": the size of a change, no sign (the sentence says which way)."""
    return f"{abs(x):,.1f}%"


def signed(x: float) -> str:
    """A displayed figure: "+1,061.5%", "−0.5%" (a true minus sign), "0.0%"."""
    return ("+" if x > 0 else "−" if x < 0 else "") + pct(x)


def num(x: float, places: int = 1) -> str:
    """"1,234.5", "−9.0": thousands separators and a true minus sign."""
    return ("−" if x < 0 else "") + f"{abs(x):,.{places}f}"


def moved(x: float) -> str:
    """"rose 1.6%", "fell 0.4%", "was unchanged"."""
    return f"rose {pct(x)}" if x > 0 else f"fell {pct(x)}" if x < 0 else "was unchanged"


def a_an(number: str) -> str:
    """"an" before a number read aloud with a vowel sound (8, 11, 18, 80 to 89, 800 to 899, 11,000 ...), else "a"."""
    digits = number.split(".")[0].replace(",", "").lstrip("−+±")
    return "an" if digits.startswith("8") or (len(digits) % 3 == 2 and digits[:2] in ("11", "18")) else "a"


def change_noun(x: float) -> str:
    """"a 3.1% rise", "an 8.2% fall", "no change"."""
    if x == 0:
        return "no change"
    return f"{a_an(pct(x))} {pct(x)} {'rise' if x > 0 else 'fall'}"


def kept(x: float, tense: str = "keeps") -> str:
    """"keeps 81¢ of" / "lost 9¢ on" for a negative margin (tense "keeps" or "kept")."""
    if round(x) >= 0:
        return f"{tense} {round(x)}¢ of"
    return f"{'loses' if tense == 'keeps' else 'lost'} {abs(round(x))}¢ on"


# ── step 2 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def faster(a_pct: float, b_pct: float) -> str:
    """Pure: "faster", "slower" or "same": growth a against growth b by their growth factors (SAME_RATIO)."""
    r = (1 + a_pct / 100) / (1 + b_pct / 100)
    return "faster" if r > 1 + SAME_RATIO else "slower" if r < 1 - SAME_RATIO else "same"


GROWTH_RIGHT = {"faster": "Each sale earns more profit than a year ago", "slower": "It is selling more but earning less on each sale"}
GROWTH_RIGHT_REVENUE = {"faster": "Each dollar of revenue earns more profit than a year ago",
                        "slower": "It is bringing in more revenue but earning less on each dollar"}
GROWTH_TOGETHER = {"sales": "Its sales and profit always grow together", "revenue": "Its revenue and profit always grow together"}


def growth_check(name: str, sales_pct: float | None, period: str, per_share_pct: float | None, per_share: str = "earnings per share",
                 noun: str = "revenue") -> dict | None:
    """Earnings (or FFO) per share grew faster or slower than sales in the latest quarter: what does that usually mean? None when
    they grew about as fast, when either figure is missing, or in the slower case when sales fell (the right option says it is
    selling more)."""
    if sales_pct is None or per_share_pct is None or sales_pct <= -100 or per_share_pct <= -100:
        return None
    w = faster(per_share_pct, sales_pct)
    if w == "same" or (w == "slower" and sales_pct <= 0):
        return None
    right_words = GROWTH_RIGHT_REVENUE if noun == "revenue" else GROWTH_RIGHT
    right = right_words[w]
    other = right_words["slower" if w == "faster" else "faster"]
    options, answer = _ordered([right, other, GROWTH_TOGETHER[noun]], right, name)
    if per_share_pct < 0 <= sales_pct:
        fact = f"{name}'s {per_share} fell while its {noun} rose in {period}."
    elif sales_pct < 0 <= per_share_pct:
        fact = f"{name}'s {per_share} rose while its {noun} fell in {period}."
    else:
        fact = f"{name}'s {per_share} grew {w} than its {noun} in {period}."
    verb = lambda x: f"{'rose' if x >= 0 else 'fell'} {pct(x)}"
    why = (f"{cap(per_share)} {verb(per_share_pct)} while {noun} {verb(sales_pct)}. "
           + (f"When profit per share grows faster than {noun}, each dollar of {noun} is bringing in more profit than a year ago. "
              if w == "faster" else
              f"When profit per share grows more slowly than {noun}, the company is earning less on each dollar of {noun} than a year ago. ")
           + f"Share buybacks also lift {per_share}, since the same profit is split over fewer shares.")
    return {"concept": "growth", "options": options, "answer": answer, "why": why, "question": f"{fact} What does that usually mean?",
            "same_answer": f"growth:{w}"}


def growth_word(x: float) -> str:
    return "held about flat" if abs(x) < GROWTH_FLAT_PCT else "rose" if x > 0 else "fell"


# ── step 3 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def cents_word(c: int) -> str:
    return f"{c}¢" if c >= 0 else f"a loss of {abs(c)}¢"


def is_cyclical(now: float, then: float | None) -> bool:
    return then is not None and abs(round(now) - round(then)) >= CYCLICAL_SWING_CENTS


def margins_check(name: str, now: float, then: float | None, unit: str = "revenue dollar") -> dict | None:
    """Now against three years earlier, in the whole cents the step shows: what does a change like that usually point to?"""
    if then is None:
        return None
    options = ["Pricing power or lower costs", "Competition or rising costs", "Not much, the slice barely moved"]
    a, b = round(then), round(now)
    d = b - a
    pick = options[0] if d >= MARGIN_SAME_CENTS else options[1] if d <= -MARGIN_SAME_CENTS else options[2]
    if abs(d) < MARGIN_SAME_CENTS:
        why = f"The slice it keeps stayed at {cents_word(b)} of each dollar over three years, which Ivy reads as barely moved."
    else:
        why = (f"The slice it keeps went from {cents_word(a)} to {cents_word(b)} of each dollar in three years, {abs(d)}¢ {'more' if d > 0 else 'less'}. "
               + ("A rising margin usually points to pricing power or lower costs." if d > 0 else "A falling margin usually points to competition or rising costs."))
    if is_cyclical(now, then):
        why += (f" A swing of {CYCLICAL_SWING_CENTS}¢ or more in three years is the mark of a cyclical business, whose prices rise "
                "and fall with supply and demand, so one good year says little about the next.")
    return {"concept": "margins", "options": options, "answer": options.index(pick), "why": why,
            "question": f"{name} {kept(then, 'kept')} each {unit} three years earlier and {kept(now)} each one over the last four quarters. "
                        f"What does a change like that usually point to?"}


# ── step 4 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def close(a: float, b: float) -> bool:
    return abs(a - b) <= max(CLOSE_POINTS, CLOSE_SHARE * max(abs(a), abs(b)))


def year_owner(stock: float, sector: float, market: float) -> str:
    """Pure: "market", "industry" (its sector, as the visitor reads it) or "company" for a year's move: the closer of the two benchmarks when it is close by the rule
    (the S&P 500 on a tie), else the company's own."""
    near = [(abs(stock - market), 0, "market"), (abs(stock - sector), 1, "industry")]
    near = [x for x in near if close(stock, market if x[2] == "market" else sector)]
    return min(near)[2] if near else "company"


OWNER_SUMMARY = {"market": "in step with the whole market", "industry": "in step with its sector", "company": "mostly its own"}


def market_check(name: str, sector: str, stock: float, sector_pct: float, market: float) -> dict:
    options = ["The company", "Its sector", "The whole market"]
    owner = year_owner(stock, sector_pct, market)
    near_m, near_s = close(stock, market), close(stock, sector_pct)
    typ = f"the typical {sector} stock's"
    if owner == "company":
        why = f"{name}'s move is far from both {typ} and the S&P 500's, so its year was mostly the company's own."
    else:
        mine, other = ("the S&P 500's", typ) if owner == "market" else (typ, "the S&P 500's")
        whose = "the whole market" if owner == "market" else "its sector"
        why = (f"{name}'s move is close to both, and closer to {mine} than to {other}, so its year was mostly {whose}." if near_m and near_s else
               f"{name}'s move is close to {mine} and far from {other}, so its year was mostly {whose}.")
    return {"concept": "market_vs_company", "options": options, "answer": options.index({"company": "The company", "industry": "Its sector", "market": "The whole market"}[owner]),
            "why": why,
            "question": f"Over the year {name} {moved(stock)}, the typical {sector} stock {moved(sector_pct)} and the S&P 500 {moved(market)}. "
                        f"Was {name}'s year mostly the company, its sector, or the whole market?"}


INDEX_SHARE_RIGHT = "Its own moves are part of the index's move"
INDEX_SHARE_WRONG = ("The index holds no other large companies", "It can't rise in a year the index falls")


def index_share_check(name: str, share_pct: float) -> dict:
    """A stock big enough to move the index: what its share means when its year is set beside the S&P 500's."""
    options, answer = _ordered([INDEX_SHARE_RIGHT, *INDEX_SHARE_WRONG], INDEX_SHARE_RIGHT, name)
    return {"concept": "market_vs_company", "options": options, "answer": answer, "same_answer": "index_share",
            "question": f"{name} makes up {num(share_pct)}% of the S&P 500 by market value. What does that mean when you set its year beside the index's?",
            "why": f"At {num(share_pct)}% of the index, {name}'s own rises and falls are a real part of the S&P 500's, so the index's year is partly "
                   f"{name}'s year. The median stock of its sector is the fairer yardstick."}


def move_owner(stock_pct: float, spy_pct: float | None, min_spy_pct: float) -> str:
    """Pure: one day's move: "market" when SPY moved the same way by at least min_spy_pct and by at least MOVE_MARKET_SHARE of the
    stock's move; "company" otherwise (including a session with no SPY figure, which is never guessed)."""
    if spy_pct is None or stock_pct == 0:
        return "company"
    same_way = (spy_pct > 0) == (stock_pct > 0)
    if same_way and abs(spy_pct) >= min_spy_pct and abs(spy_pct) >= MOVE_MARKET_SHARE * abs(stock_pct):
        return "market"
    return "company"


# ── step 5 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def against(x: float, ref: float) -> str:
    if abs(x / ref - 1) <= PE_SAME_RATIO:
        return "same"
    return "above" if x > ref else "below"


def pe_word(pe: float, median: float) -> str:
    return {"same": "About the same as usual", "above": "More than usual", "below": "Less than usual"}[against(pe, median)]


PE_RIGHT = {"below": "They expect its profits to fall from here", "above": "They expect its profits to keep growing"}
PE_SPLIT = "Its stock split"


def pe_fact(a: str, year: dict | None, median: float) -> str | None:
    """Pure: the fact that moved this company's P/E to the side of its median it sits on, or None: its four-quarter earnings per
    share against its price over the year (growth factors more than SAME_RATIO apart, the way that moves the P/E toward `a`), when
    the P/E a year earlier was not already on that side."""
    if not year or year.get("eps_pct") is None or year.get("price_pct") is None or year.get("pe_then") is None:
        return None
    if against(year["pe_then"], median) == a:
        return None
    w = faster(year["eps_pct"], year["price_pct"])
    if a == "below" and w == "faster":
        return "Its profits grew faster than its price" if year["eps_pct"] >= 0 else "Its price fell faster than its profits"
    if a == "above" and w == "slower":
        return "Its price rose faster than its profits" if year["price_pct"] >= 0 else "Its profits fell faster than its price"
    return None


def usd(x: float) -> str:
    """Pure: what investors pay for $1 of profit (walkthrough.per_dollar's rule): "$28", "$7.9"."""
    return f"${x:,.0f}" if x >= 10 else f"${x:,.1f}"


def pe_check(name: str, pe: float, median: float, year: dict | None = None) -> dict | None:
    """Investors pay more or less than usual (the P/E against its own five-year median): what is a common reason? None when about
    usual. The right answer fits the company (pe_fact) when its year shows why; year: {eps_pct, price_pct, pe_then, now}."""
    from app.services.briefing import fmt_date
    a = against(pe, median)
    if a == "same":
        return None
    lower = a == "below"
    fact = pe_fact(a, year, median)
    if fact:
        options, answer = _ordered([fact, PE_RIGHT["above" if lower else "below"], PE_SPLIT], fact, name)
        verb = lambda x: f"{'rose' if x >= 0 else 'fell'} {pct(x)}"
        return {"concept": "pe", "options": options, "answer": answer,
                "question": f"Investors are paying {'less' if lower else 'more'} for each dollar of {name}'s profit than they usually do. What is the reason here?",
                "why": f"Investors pay about {usd(pe)} for each $1 of its profit, {'below' if lower else 'above'} the {usd(median)} of its five-year median, and a year earlier "
                       f"they paid {usd(year['pe_then'])}. In the year to {fmt_date(year['now'])} its earnings per share over four quarters {verb(year['eps_pct'])} while its "
                       f"share price {verb(year['price_pct'])}, so each dollar of profit costs {'less' if lower else 'more'} than it did. A stock split changes the share "
                       f"price and earnings per share together, so it leaves this figure unchanged."}
    right = PE_RIGHT[a]
    options, answer = _ordered([right, PE_RIGHT["above" if a == "below" else "below"], PE_SPLIT], right, name)
    return {"concept": "pe", "options": options, "answer": answer,
            "question": f"Investors are paying {'less' if lower else 'more'} for each dollar of {name}'s profit than they usually do. What is a common reason?",
            "why": f"Investors pay about {usd(pe)} for each $1 of its profit, {'below' if lower else 'above'} its five-year median of {usd(median)}. Paying "
                   f"{'less' if lower else 'more'} than usual commonly means " + ("investors expect its profits to fall from here, or its profits have grown faster than its price. " if lower else
                                        "investors expect its profits to keep growing, or its profits have fallen while its price held. ")
                   + "A stock split changes the share price and earnings per share together, so it leaves this figure unchanged."}


# ── step 6 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

REPORT_RIGHT = "Expect a bigger swing that day, in either direction"
REPORT_WRONG = ("Expect the stock to rise that day", "Report days rarely matter for this stock")


def report_multiple(typical: float, ordinary: float | None) -> float | None:
    return typical / ordinary if ordinary and ordinary > 0 else None


def report_check(name: str, typical: float, ordinary: float | None, due: str) -> dict | None:
    """Report days move the stock k times as much as an ordinary day: what does that mean for someone holding it through the next
    report (due: "its next report on Nov 17, 2026")? None under REPORT_MULTIPLE_MIN or without an ordinary day's move."""
    k = report_multiple(typical, ordinary)
    if k is None or k < REPORT_MULTIPLE_MIN:
        return None
    options, answer = _ordered([REPORT_RIGHT, *REPORT_WRONG], REPORT_RIGHT, name)
    return {"concept": "report_move", "options": options, "answer": answer,
            "question": f"Report days move {name} about {num(k)} times as much as an ordinary day. What does that mean for someone holding it through {due}?",
            "why": f"A typical report day has moved it ±{num(typical)}%, against about ±{num(ordinary)}% on an ordinary day. A report can move it either way, "
                   f"so holding through one means a bigger swing that day, up or down.", "same_answer": "report_move"}


# ── step 7 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def risk_target(heading: str, sentence: str = "") -> str | None:
    """Pure: "margins" or "growth" when the risk's heading and sentence match exactly one target and no supply-chain word, else None."""
    words = f"{heading or ''} {sentence or ''}"
    if RISK_EXCLUDED.search(words):
        return None
    hits = {step for step, rx in RISK_TARGETS if rx.search(words)}
    return hits.pop() if len(hits) == 1 else None


def risk_check(name: str, sentence: str, right: str, decoys: list[str], noun: str = "revenue") -> dict:
    options, answer = _ordered([right] + decoys[:2], right, name)
    each = "each revenue dollar" if noun == "revenue" else "each sale"
    return {"concept": "risk_factors", "options": options, "answer": answer,
            "question": f"{name} lists this risk. {sentence} If it came true, which of {name}'s own results would it hit most directly?",
            "why": f"{right} is the result such a risk would reach first. A risk about {RISK_WORDS['margins']} hits what a company keeps of {each}, "
                   f"and one about {RISK_WORDS['growth']} hits its {noun}."}
