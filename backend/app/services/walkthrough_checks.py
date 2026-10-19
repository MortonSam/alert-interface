"""Ivy's quick checks: one per walkthrough step, never written by a model.

Every question (a) cannot be answered from any text on its own screen, (b) uses this company's own numbers and (c) needs at
least two facts from the walkthrough put together. No arithmetic drills and no definitions: the answer is a reading of the
numbers by a fixed rule, and the step's own sentences never state that reading. Each template returns {concept, question,
options, answer (index into options), why}, or None when the data cannot support a fair question. Options keep a fixed order
(categorical, or sorted by their text), so the right answer's position follows the data, not a coin.

The rules (each constant below is the threshold the explanation quotes):
  step 1  depends on one line when the biggest is ONE_LINE_SHARE or more of sales, two lines when the biggest two make
          TWO_LINES_SHARE or more, several otherwise.
  step 2  earnings per share grew faster or slower than sales when one growth factor (1 + growth) is more than SAME_RATIO
          above or below the other; the same rule compares the latest quarter with the last four quarters.
  step 3  a margin that rose by MARGIN_SAME_POINTS or more points to pricing power or lower costs, one that fell that much to
          competition or rising costs, anything less barely moved; a swing of CYCLICAL_SWING_POINTS or more is named cyclical.
  step 4  two moves are close when within CLOSE_POINTS percentage points or within CLOSE_SHARE of the larger move, whichever is
          wider. The year was the whole market's when the stock is close to the S&P 500, else its industry's when close to the
          median stock of its sector, else the company's own.
  step 5  the P/E reads above or below a reference when more than PE_SAME_RATIO away from it.
  step 6  a report-day move is bigger or smaller than usual when more than REPORT_SAME_RATIO away from the typical move.
  step 7  a risk heading maps to the walkthrough number it would show up in first by RISK_TARGETS (first match wins).
"""
from __future__ import annotations

import hashlib
import re

from app.services.fiscal_periods import cap

ONE_LINE_SHARE = 66.7           # the biggest line alone brings in two thirds of sales or more
TWO_LINES_SHARE = 80.0          # the biggest two together bring in four fifths or more
SAME_RATIO = 0.05               # growth factors within 5% of each other grew "about as fast"
MARGIN_SAME_POINTS = 1.0        # margins within a point "barely moved"
CYCLICAL_SWING_POINTS = 20.0    # a margin that moved this many points in three years marks a cyclical business
CLOSE_POINTS = 5.0
CLOSE_SHARE = 0.2
PE_SAME_RATIO = 0.05
REPORT_SAME_RATIO = 0.2         # Sam's rule: "about the same" is within 20% of the typical report-day move
GROWTH_FLAT_PCT = 2.0           # sales within this many percent of the year before read "about flat" (the summary's word)
MOVE_MARKET_SHARE = 0.5         # a single day is the market's when SPY moved the same way by at least this share of the stock's move

# step 7: a risk heading's words, and the step whose number would show the risk first (order matters: the first match wins)
RISK_TARGETS = (
    (re.compile(r"\b(?:prices?|pricing|supply|oversupply|compet\w*)\b", re.I), "margins"),
    (re.compile(r"\b(?:customers?|concentrat\w*|demand|orders?)\b", re.I), "growth"),
)
# a risk sentence that names its own answer's measure is never the question
RISK_GIVEAWAY = {"margins": re.compile(r"\b(?:margins?|profit\w*|keeps?|kept|slice)\b", re.I),
                 "growth": re.compile(r"\b(?:sales|revenues?|grow\w*|growth)\b", re.I)}

CONCEPTS = ("segments", "growth", "margins", "market_vs_company", "pe", "p_ffo", "report_move", "risk_factors")


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


def _sorted(options: list[str], right: str) -> tuple[list[str], int]:
    o = sorted(options)
    return o, o.index(right)


# ── step 1 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def dependence(shares: list[float]) -> str:
    top = sorted(shares, reverse=True)
    if top[0] >= ONE_LINE_SHARE:
        return "One line"
    if len(top) > 1 and top[0] + top[1] >= TWO_LINES_SHARE:
        return "Two lines"
    return "Several lines"


def segments_check(name: str, segments: list[dict], period: str) -> dict | None:
    """The biggest two lines' shares: does the company depend on one line, two, or several?"""
    if len(segments) < 2:
        return None
    a, b = sorted(segments, key=lambda s: -s["share"])[:2]
    options = ["One line", "Two lines", "Several lines"]
    word = dependence([s["share"] for s in segments])
    why = {"One line": f"{a['label']} alone brought in {pct(a['share'])}, two thirds or more of its sales, so {name} depends mostly on one line.",
           "Two lines": f"{a['label']} and {b['label']} together brought in {pct(a['share'] + b['share'])}, four fifths or more of its sales, so {name} depends mostly on those two.",
           "Several lines": f"Its biggest two lines together brought in {pct(a['share'] + b['share'])}, under four fifths of its sales, so {name} leans on several lines."}[word]
    return {"concept": "segments", "options": options, "answer": options.index(word), "why": why,
            "question": f"In {period}, {a['label']} brought in {pct(a['share'])} of {name}'s sales and {b['label']} {pct(b['share'])}. "
                        f"Does {name} depend mostly on one line of business, two, or several?"}


# ── step 2 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def faster(a_pct: float, b_pct: float) -> str:
    """Pure: "faster", "slower" or "same": growth a against growth b by their growth factors (SAME_RATIO)."""
    r = (1 + a_pct / 100) / (1 + b_pct / 100)
    return "faster" if r > 1 + SAME_RATIO else "slower" if r < 1 - SAME_RATIO else "same"


def growth_check(name: str, sales_pct: float, quarter: str, per_share_pct: float | None = None, per_share: str = "earnings per share",
                 ttm_pct: float | None = None) -> dict | None:
    """With a per-share figure for the same quarter: did it grow faster or slower than sales? Else, with the last four quarters:
    was the latest quarter's sales growth faster or slower than the year's? None with neither (one fact is no question)."""
    if per_share_pct is not None and sales_pct > -100 and per_share_pct > -100:
        options = ["Faster than its sales", "About as fast as its sales", "Slower than its sales"]
        w = faster(per_share_pct, sales_pct)
        pick = {"faster": options[0], "same": options[1], "slower": options[2]}[w]
        verb = lambda x: f"{'rose' if x >= 0 else 'fell'} {pct(x)}"
        why = (f"{cap(per_share)} {verb(per_share_pct)} while sales {verb(sales_pct)}, "
               + {"faster": "so each dollar of sales turned into more profit per share than a year earlier.",
                  "slower": "so each dollar of sales turned into less profit per share than a year earlier.",
                  "same": "so profit per share kept pace with sales."}[w]
               + f" Ivy counts the two as about as fast when they are within {SAME_RATIO:.0%} of each other.")
        return {"concept": "growth", "options": options, "answer": options.index(pick), "why": why,
                "question": f"In {quarter}, {name}'s sales {verb(sales_pct)} from a year earlier and its {per_share} {verb(per_share_pct)}. "
                            f"Did its {per_share} grow faster or slower than its sales?"}
    if ttm_pct is not None:
        options = ["Faster in the latest quarter", "About the same", "Slower in the latest quarter"]
        w = faster(sales_pct, ttm_pct)
        pick = {"faster": options[0], "same": options[1], "slower": options[2]}[w]
        verb = lambda x: f"{'rose' if x >= 0 else 'fell'} {pct(x)}"
        return {"concept": "growth", "options": options, "answer": options.index(pick),
                "question": f"{name}'s sales {verb(ttm_pct)} over the last four quarters against the four before, and {verb(sales_pct)} in {quarter} "
                            f"against a year earlier. Was its growth faster or slower in the latest quarter than over the whole year?",
                "why": f"{pct(sales_pct)} in the latest quarter against {pct(ttm_pct)} over the year reads "
                       + {"faster": "faster", "slower": "slower", "same": "about the same"}[w]
                       + f". Ivy counts the two as about the same when they are within {SAME_RATIO:.0%} of each other."}
    return None


def growth_word(x: float) -> str:
    return "held about flat" if abs(x) < GROWTH_FLAT_PCT else "rose" if x > 0 else "fell"


# ── step 3 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def is_cyclical(now: float, then: float | None) -> bool:
    return then is not None and abs(now - then) >= CYCLICAL_SWING_POINTS


def margins_check(name: str, now: float, then: float | None, unit: str = "sales dollar") -> dict | None:
    """Now against three years earlier: what does a change like that usually point to (the idea box's reading, applied)?"""
    if then is None:
        return None
    options = ["Pricing power or lower costs", "Competition or rising costs", "Not much, the slice barely moved"]
    d = now - then
    pick = options[0] if d >= MARGIN_SAME_POINTS else options[1] if d <= -MARGIN_SAME_POINTS else options[2]
    if abs(d) < MARGIN_SAME_POINTS:
        why = f"The slice it keeps moved less than {MARGIN_SAME_POINTS:.0f} point in three years, which Ivy reads as barely moved."
    else:
        why = (f"The slice it keeps {'rose' if d > 0 else 'fell'} by {num(abs(d))} points in three years. "
               + ("A rising margin usually points to pricing power or lower costs." if d > 0 else "A falling margin usually points to competition or rising costs."))
    if is_cyclical(now, then):
        why += (f" A swing of {CYCLICAL_SWING_POINTS:.0f} points or more in three years is the mark of a cyclical business, whose prices rise "
                "and fall with supply and demand, so one good year says little about the next.")
    return {"concept": "margins", "options": options, "answer": options.index(pick), "why": why,
            "question": f"{name} {kept(then, 'kept')} each {unit} three years earlier and {kept(now)} each one over the last four quarters. "
                        f"What does a change like that usually point to?"}


# ── step 4 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def close(a: float, b: float) -> bool:
    return abs(a - b) <= max(CLOSE_POINTS, CLOSE_SHARE * max(abs(a), abs(b)))


def year_owner(stock: float, sector: float, market: float) -> str:
    """Pure: "market", "industry" or "company" for a year's move (the step 4 rule in the module docstring)."""
    if close(stock, market):
        return "market"
    if close(stock, sector):
        return "industry"
    return "company"


OWNER_SUMMARY = {"market": "in step with the whole market", "industry": "in step with its industry", "company": "mostly its own"}


def market_check(name: str, sector: str, stock: float, sector_pct: float, market: float) -> dict:
    options = ["The company", "Its industry", "The whole market"]
    owner = year_owner(stock, sector_pct, market)
    rule = (f" Ivy calls two moves close when they are within {CLOSE_POINTS:.0f} points or within a fifth of the larger move, whichever is wider, "
            "and checks the whole market first.")
    why = {"market": f"{name}'s {pct(stock)} {'rise' if stock >= 0 else 'fall'} is close to the S&P 500's, so its year was mostly the whole market.",
           "industry": f"{name}'s move is far from the S&P 500's but close to the typical {sector} stock's, so its year was mostly its industry.",
           "company": f"{name}'s move is far from both the typical {sector} stock's and the S&P 500's, so its year was mostly the company's own."}[owner]
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


def pe_check(name: str, pe: float, median: float, sector: str | None = None, sector_median: float | None = None) -> dict:
    """Against its own five-year median and the median stock of its sector: below both, above both, or between them. When the
    P/E is about level with either (PE_SAME_RATIO) or the sector has no median shown, against its own median alone."""
    a = against(pe, median)
    b = against(pe, sector_median) if sector_median else None
    if b is not None and "same" not in (a, b):
        options = ["Below both", "Between the two", "Above both"]
        pick = options[0] if a == b == "below" else options[2] if a == b == "above" else options[1]
        return {"concept": "pe", "options": options, "answer": options.index(pick),
                "question": f"{name}'s P/E is {num(pe)}. Its own five-year median is {num(median)}, and the median {sector} stock in the S&P 500 is at "
                            f"{num(sector_median)}. Next to its own past and its sector, where does today's price for each dollar of its profit sit?",
                "why": f"{num(pe)} is {'below' if a == 'below' else 'above'} its own median of {num(median)} and {'below' if b == 'below' else 'above'} "
                       f"its sector's {num(sector_median)}. Ivy reads a P/E within {PE_SAME_RATIO:.0%} of a median as level with it."}
    options = ["More than usual", "About the same as usual", "Less than usual"]
    word = pe_word(pe, median)
    return {"concept": "pe", "options": options, "answer": options.index(word),
            "question": f"{name}'s P/E is {num(pe)} and its five-year median is {num(median)}. Are investors paying more or less than usual for each dollar of its profit?",
            "why": f"{num(pe)} against a median of {num(median)}. Ivy reads a P/E within {PE_SAME_RATIO:.0%} of its median as about the same, above that more, below it less."}


# ── step 6 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def report_size(move: float, typical: float) -> str:
    r = abs(move) / typical
    return "Bigger" if r > 1 + REPORT_SAME_RATIO else "Smaller" if r < 1 - REPORT_SAME_RATIO else "About the same"


def last_report_check(name: str, day: str, move: float, typical: float) -> dict:
    options = ["Bigger", "About the same", "Smaller"]
    word = report_size(move, typical)
    return {"concept": "report_move", "options": options, "answer": options.index(word),
            "question": f"Last report, on {day}, {name} {moved(move)}. Its typical report day is ±{num(typical)}%. Was that a bigger or smaller move than usual?",
            "why": f"{cap(a_an(pct(move)))} {pct(move)} move against a typical ±{num(typical)}% reads {word.lower()}. Ivy counts a move within {REPORT_SAME_RATIO:.0%} of the typical one "
                   f"as about the same."}


def multiple_options(ratio: float) -> tuple[list[int], int]:
    """Pure: (three distinct multiples in ascending order, the right one): the ratio rounded (at least 1), and two wrong ones."""
    right = max(1, round(ratio))
    wrong = [right * 2, right + 1] if right <= 2 else [max(1, round(right / 2)), right * 2]
    opts = sorted({right, *wrong})
    k = 1
    while len(opts) < 3:
        opts = sorted({*opts, right * 2 + k})
        k += 1
    return opts, right


def ordinary_day_check(name: str, ordinary: float, typical: float) -> dict | None:
    if ordinary <= 0:
        return None
    opts, right = multiple_options(typical / ordinary)
    options = [f"About {n} {'time' if n == 1 else 'times'}" for n in opts]
    return {"concept": "report_move", "options": options, "answer": opts.index(right),
            "question": f"On an ordinary day {name} moves about ±{num(ordinary)}%. On report days it moves ±{num(typical)}%. Roughly how many times bigger is a report day?",
            "why": f"±{num(typical)}% is {num(typical / ordinary)} times ±{num(ordinary)}%, so a report day moves it about {right} {'time' if right == 1 else 'times'} as much as an ordinary day."}


# ── step 7 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def risk_target(heading: str) -> str | None:
    for rx, step in RISK_TARGETS:
        if rx.search(heading or ""):
            return step
    return None


def risk_number_check(name: str, sentence: str, right: str, decoys: list[str]) -> dict:
    options, answer = _sorted([right] + decoys[:2], right)
    return {"concept": "risk_factors", "options": options, "answer": answer,
            "question": f"{name} lists this risk. {sentence} If it came true, which number from this walkthrough would show it first?",
            "why": f"{right} is the first number such a risk would reach. Ivy maps a risk about prices, supply or competition to what the company keeps "
                   f"of each sale, and one about customers, demand or orders to its sales."}


def risk_list_check(name: str, sentence: str, decoys: list[str]) -> dict | None:
    if len(decoys) < 2:
        return None
    options, answer = _sorted([sentence] + decoys[:2], sentence)
    return {"concept": "risk_factors", "options": options, "answer": answer,
            "question": f"Which of these does {name} list as a risk?",
            "why": f"The right one comes from Item 1A of {name}'s annual report. The other two come from the annual reports of companies in other sectors."}


def names_itself(sentence: str, name: str | None, symbol: str | None = None) -> bool:
    """Pure: the sentence names its own company by the first word of its name or its symbol ("Apple's markets", "AMD sells"), which
    would give it away among the options of step 7's fallback check."""
    words = [w for w in [(name or "").split()[0] if name else "", symbol or ""] if w]
    return any(re.search(rf"\b{re.escape(w)}\b", sentence, re.I) for w in words)


def decoy_order(symbol: str, other: str) -> str:
    """Pure: a fixed, per-stock order for picking decoys (the same every night for the same pool)."""
    return hashlib.sha256(f"{symbol}:{other}".encode()).hexdigest()
