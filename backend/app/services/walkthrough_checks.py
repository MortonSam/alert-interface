"""Ivy's quick checks: one per walkthrough step from step 2 on, never written by a model.

Every question states one fact about this stock and asks what it means for the business or for someone holding the stock; the
answer is a reading no text on its screen states (the step's sentences give figures, never their meaning, and "The idea" appears
only after the visitor answers or skips). The right option follows the direction of the data by a fixed rule; each wrong option is
clearly wrong to someone who understood the idea. Each template returns {concept, question, options, answer (index into options),
why}, or None when the data cannot support a fair question. Options whose right answer is the same text for every stock are
ordered per stock (_ordered: a fixed hash of the stock's name), so the right answer's position is not always the same.

The rules (each constant below is the threshold the explanation quotes):
  step 1  no check.
  step 2  earnings (or FFO) per share grew faster or slower than sales when one growth factor (1 + growth) is more than
          SAME_RATIO above or below the other; about as fast asks nothing, and nor does a slower case whose sales fell.
  step 3  a margin that rose by MARGIN_SAME_CENTS or more (in the whole cents shown) points to pricing power or lower costs,
          one that fell that much to competition or rising costs, anything less barely moved; a swing of CYCLICAL_SWING_CENTS
          or more is named cyclical.
  step 4  two moves are close when within CLOSE_POINTS percentage points or within CLOSE_SHARE of the larger move, whichever is
          wider. The year was the closer of the S&P 500 and the median stock of its sector when that one is close, else the
          company's own.
  step 5  investors pay more or less than usual when the P/E is more than PE_SAME_RATIO above or below its five-year median;
          about usual asks nothing.
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
                 noun: str = "sales") -> dict | None:
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
           + f"Share buybacks also lift {per_share}, since the same profit is split over fewer shares. "
           + f"Ivy asks this only when the two growth rates are more than {SAME_RATIO:.0%} apart.")
    return {"concept": "growth", "options": options, "answer": answer, "why": why, "question": f"{fact} What does that usually mean?"}


def growth_word(x: float) -> str:
    return "held about flat" if abs(x) < GROWTH_FLAT_PCT else "rose" if x > 0 else "fell"


# ── step 3 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def cents_word(c: int) -> str:
    return f"{c}¢" if c >= 0 else f"a loss of {abs(c)}¢"


def is_cyclical(now: float, then: float | None) -> bool:
    return then is not None and abs(round(now) - round(then)) >= CYCLICAL_SWING_CENTS


def margins_check(name: str, now: float, then: float | None, unit: str = "sales dollar") -> dict | None:
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
    """Pure: "market", "industry" or "company" for a year's move: the closer of the two benchmarks when it is close by the rule
    (the S&P 500 on a tie), else the company's own."""
    near = [(abs(stock - market), 0, "market"), (abs(stock - sector), 1, "industry")]
    near = [x for x in near if close(stock, market if x[2] == "market" else sector)]
    return min(near)[2] if near else "company"


OWNER_SUMMARY = {"market": "in step with the whole market", "industry": "in step with its industry", "company": "mostly its own"}


def market_check(name: str, sector: str, stock: float, sector_pct: float, market: float) -> dict:
    options = ["The company", "Its industry", "The whole market"]
    owner = year_owner(stock, sector_pct, market)
    near_m, near_s = close(stock, market), close(stock, sector_pct)
    typ = f"the typical {sector} stock's"
    rule = (f" Ivy calls two moves close when they are within {CLOSE_POINTS:.0f} points or within a fifth of the larger move, whichever is wider, "
            "and when both are close it picks the closer one.")
    if owner == "company":
        why = f"{name}'s move is far from both {typ} and the S&P 500's, so its year was mostly the company's own."
    else:
        mine, other = ("the S&P 500's", typ) if owner == "market" else (typ, "the S&P 500's")
        whose = "the whole market" if owner == "market" else "its industry"
        why = (f"{name}'s move is close to both, and closer to {mine} than to {other}, so its year was mostly {whose}." if near_m and near_s else
               f"{name}'s move is close to {mine} and far from {other}, so its year was mostly {whose}.")
    return {"concept": "market_vs_company", "options": options, "answer": options.index({"company": "The company", "industry": "Its industry", "market": "The whole market"}[owner]),
            "why": why + rule,
            "question": f"Over the year {name} {moved(stock)}, the typical {sector} stock {moved(sector_pct)} and the S&P 500 {moved(market)}. "
                        f"Was {name}'s year mostly the company, its industry, or the whole market?"}


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


def pe_check(name: str, pe: float, median: float) -> dict | None:
    """Investors pay more or less than usual (the P/E against its own five-year median): what is a common reason? None when about
    usual."""
    a = against(pe, median)
    if a == "same":
        return None
    right = PE_RIGHT[a]
    options, answer = _ordered([right, PE_RIGHT["above" if a == "below" else "below"], PE_SPLIT], right, name)
    lower = a == "below"
    return {"concept": "pe", "options": options, "answer": answer,
            "question": f"Investors are paying {'less' if lower else 'more'} for each dollar of {name}'s profit than they usually do. What is a common reason?",
            "why": f"Its P/E of {num(pe)} is {'below' if lower else 'above'} its five-year median of {num(median)}. A {'lower' if lower else 'higher'} P/E than usual "
                   f"commonly means investors expect its profits to {'fall' if lower else 'keep growing'}. A stock split changes the share price and earnings "
                   f"per share together, so it leaves the P/E unchanged. Ivy asks this only when the P/E is more than {PE_SAME_RATIO:.0%} from its median."}


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
                   f"so holding through one means a bigger swing that day, up or down. Ivy asks this only when report days move a stock at least "
                   f"{num(REPORT_MULTIPLE_MIN)} times as much as an ordinary day."}


# ── step 7 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def risk_target(heading: str, sentence: str = "") -> str | None:
    """Pure: "margins" or "growth" when the risk's heading and sentence match exactly one target and no supply-chain word, else None."""
    words = f"{heading or ''} {sentence or ''}"
    if RISK_EXCLUDED.search(words):
        return None
    hits = {step for step, rx in RISK_TARGETS if rx.search(words)}
    return hits.pop() if len(hits) == 1 else None


def risk_check(name: str, sentence: str, right: str, decoys: list[str], noun: str = "sales") -> dict:
    options, answer = _ordered([right] + decoys[:2], right, name)
    each = "each revenue dollar" if noun == "revenue" else "each sale"
    return {"concept": "risk_factors", "options": options, "answer": answer,
            "question": f"{name} lists this risk. {sentence} If it came true, which of {name}'s own results would it hit most directly?",
            "why": f"{right} is the result such a risk would reach first. A risk about {RISK_WORDS['margins']} hits what a company keeps of {each}, "
                   f"and one about {RISK_WORDS['growth']} hits its {noun}."}
