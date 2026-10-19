"""Ivy's quick checks: one per walkthrough step, never written by a model.

Each template takes the stock's own figures, builds the question from them and computes the right answer by the same rule
the step's sentences use, so a check can never disagree with the screen it sits on. Every template returns
{concept, question, options, answer (index into options), why} or None when the data cannot support a fair question.
Options keep a fixed order (sorted or categorical), so the right answer's position follows the data, not a coin.
"""
from __future__ import annotations

from app.services.move_comparison import compare_moves

GROWTH_FLAT_PCT = 2.0           # sales within this many percent of the year before read "about flat"
MARGIN_SAME_POINTS = 1.0        # margins within this many points read "about the same"
CYCLICAL_SWING_POINTS = 20.0    # a margin that moved this many points in three years marks a cyclical business
PE_SAME_RATIO = 0.05            # a P/E within 5% of its five-year median reads "about the same as usual"

CONCEPTS = ("segments", "growth", "margins", "cyclical", "market_vs_company", "pe", "report_move", "risk_factors")


def _pct(x: float) -> str:
    return f"{x:+.1f}%"


def kept(x: float, tense: str = "keeps") -> str:
    """"keeps 81¢" / "lost 9¢ on" for a negative margin (tense "keeps" or "kept")."""
    if round(x) >= 0:
        return f"{tense} {round(x)}¢ of"
    return f"{'loses' if tense == 'keeps' else 'lost'} {abs(round(x))}¢ on"


def segments_check(name: str, segments: list[dict], period: str) -> dict | None:
    """Which line brings in the most sales: the top three segments by name (alphabetical), the largest is right."""
    if len(segments) < 2:
        return None
    top = max(segments, key=lambda s: s["value"])
    options = sorted(s["label"] for s in sorted(segments, key=lambda s: -s["value"])[:3])
    return {"concept": "segments", "question": f"Which part of {name} brought in the most sales in the {period}?", "options": options,
            "answer": options.index(top["label"]), "why": f"{top['label']} brought in {top['share']:.1f}% of {name}'s sales in the {period}."}


def growth_word(pct: float) -> str:
    if abs(pct) < GROWTH_FLAT_PCT:
        return "About flat"
    return "Grew" if pct > 0 else "Shrank"


def growth_check(name: str, ttm_pct: float, period: str) -> dict:
    """Over the last four quarters against the four before: grew, shrank or about flat (GROWTH_FLAT_PCT)."""
    options = ["Grew", "Shrank", "About flat"]
    word = growth_word(ttm_pct)
    return {"concept": "growth", "question": f"Did {name}'s sales over the {period} grow or shrink against the four quarters before?",
            "options": options, "answer": options.index(word),
            "why": f"Sales changed {_pct(ttm_pct)} against the four quarters before, and Ivy counts anything within {GROWTH_FLAT_PCT:.0f}% either way as about flat."}


def margins_check(name: str, now: float, measure_plain: str, unit: str = "sales") -> dict:
    """Of $100 of sales, how much is kept: the margin, its complement, and the margin's tenth (all rounded dollars, distinct)."""
    right = round(now)
    cands = [right, round(100 - now), round(now / 10)]
    seen: list[int] = []
    for c in cands:
        if c not in seen:
            seen.append(c)
    k = 1
    while len(seen) < 3:
        extra = right + 10 * k if right + 10 * k <= 100 else right - 10 * k
        if extra not in seen:
            seen.append(extra)
        k += 1
    options_n = sorted(seen)
    options = [f"About ${n}" if n >= 0 else f"A loss of about ${abs(n)}" for n in options_n]
    return {"concept": "margins", "question": f"If {name} makes $100 of {unit}, about how much does it keep {measure_plain}?",
            "options": options, "answer": options_n.index(right),
            "why": f"A {now:.1f}% margin means it keeps about ${right} of every $100 of {unit} {measure_plain}." if right >= 0 else
                   f"A {now:.1f}% margin means a loss of about ${abs(right)} on every $100 of {unit}."}


def is_cyclical(now: float, then: float | None) -> bool:
    return then is not None and abs(now - then) >= CYCLICAL_SWING_POINTS


def cyclical_check(name: str, now: float, then: float) -> dict:
    """A margin that swung CYCLICAL_SWING_POINTS or more in three years: what does a swing that size usually say?"""
    options = ["Its prices rise and fall with supply and demand", "Its costs are the same every year", "It stopped selling its main product"]
    return {"concept": "cyclical", "question": f"{name} {kept(then, 'kept')} each sales dollar three years ago and {kept(now)} each one now. What does a swing that size usually say about a business?",
            "options": options, "answer": 0,
            "why": f"A swing of {abs(now - then):.0f} points in three years is the mark of a cyclical business, whose prices follow supply and demand."}


MOVE_MARKET_SHARE = 0.5         # a day is the market's when SPY moved the same way by at least this share of the stock's move


def move_owner(stock_pct: float, spy_pct: float | None, min_spy_pct: float) -> str:
    """Pure: "market" when SPY moved the same way by at least min_spy_pct and by at least MOVE_MARKET_SHARE of the stock's move;
    "company" otherwise (including a session with no SPY figure, which is never guessed)."""
    if spy_pct is None or stock_pct == 0:
        return "company"
    same_way = (spy_pct > 0) == (stock_pct > 0)
    if same_way and abs(spy_pct) >= min_spy_pct and abs(spy_pct) >= MOVE_MARKET_SHARE * abs(stock_pct):
        return "market"
    return "company"


def market_check(name: str, day: str, stock_pct: float, spy_pct: float, min_spy_pct: float) -> dict:
    options = ["The company", "The market"]
    owner = move_owner(stock_pct, spy_pct, min_spy_pct)
    why = (f"The S&P 500 moved {_pct(spy_pct)} that day, at least half of {name}'s {_pct(stock_pct)} and the same way, so the market carried it."
           if owner == "market" else
           f"The S&P 500 moved {_pct(spy_pct)} that day, less than half of {name}'s {_pct(stock_pct)} or the other way, so most of the move was {name}'s own.")
    return {"concept": "market_vs_company", "question": f"On {day}, {name} moved {_pct(stock_pct)} and the S&P 500 moved {_pct(spy_pct)}. Was that move mostly the company or the market?",
            "options": options, "answer": options.index("The company" if owner == "company" else "The market"), "why": why}


def pe_word(pe: float, median: float) -> str:
    if abs(pe / median - 1) <= PE_SAME_RATIO:
        return "About the same as usual"
    return "More than usual" if pe > median else "Less than usual"


def pe_check(name: str, pe: float, median: float) -> dict:
    options = ["More than usual", "Less than usual", "About the same as usual"]
    word = pe_word(pe, median)
    return {"concept": "pe", "question": f"{name}'s P/E is {pe:.1f} and its five-year median is {median:.1f}. Are investors paying more or less than usual for each dollar of its profit?",
            "options": options, "answer": options.index(word),
            "why": f"{pe:.1f} against a median of {median:.1f}. Within {PE_SAME_RATIO:.0%} of the median reads about the same, above that more, below it less."}


def report_move_check(name: str, implied_pct: float, typical_pct: float) -> dict:
    """Uses services/move_comparison, the rule every page uses (over 1.2x more than usual, under 0.8x less)."""
    options = ["Bigger than usual", "Smaller than usual", "About its usual"]
    word = compare_moves(implied_pct, typical_pct)
    pick = {"more than usual": "Bigger than usual", "less than usual": "Smaller than usual", "about its usual": "About its usual"}[word]
    return {"concept": "report_move", "question": f"Options price a move of about ±{implied_pct:.1f}% around {name}'s next report. Its typical move after a report is ±{typical_pct:.1f}%. Is this report priced as bigger or smaller than usual?",
            "options": options, "answer": options.index(pick), "why": f"±{implied_pct:.1f}% is {implied_pct / typical_pct:.2f} times its typical ±{typical_pct:.1f}%, which reads {word}."}


def typical_move_check(name: str, typical_pct: float) -> dict:
    """With no options price: on a $100 stock, about how far is a typical report-day move (rounded dollars)."""
    right = max(1, round(typical_pct))
    opts = sorted({right, max(1, round(right / 4)) if right >= 4 else right + 2, right * 4})
    options = [f"About ${n}" for n in opts]
    return {"concept": "report_move", "question": f"{name} has moved ±{typical_pct:.1f}% on a typical report day. On a $100 stock, about how far is that?",
            "options": options, "answer": opts.index(right), "why": f"±{typical_pct:.1f}% of $100 is about ${right} either way."}


def risk_check(name: str, risk_plain: str) -> dict:
    options = ["It will happen", "It could happen, and the company must disclose it", "It has already happened"]
    return {"concept": "risk_factors", "question": f"{name}'s annual report lists this risk. \"{risk_plain}\" What does a listed risk tell you?",
            "options": options, "answer": 1, "why": "Item 1A lists what could hurt the company. A listed risk is a disclosure, not a prediction."}
