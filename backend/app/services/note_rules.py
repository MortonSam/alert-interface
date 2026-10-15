"""What a research note may say, checked in code after the model writes it (services/research_note_service).

    note_problems(structured) -> the rules a draft breaks, in words the model is shown on its one retry
    enforce(structured)       -> the note as stored: at most MAX_POINTS points per section, points that repeat the ticker page or
                                 state a bare number dropped, verdict sentences dropped from the Bottom Line, dashes and
                                 articles corrected everywhere
    clean_text(text)          -> no em or en dashes, and "a"/"an" right before a number ("an 18-of-20", "a 5% rise")

Each section holds at most MAX_POINTS points and may hold none. Every point that states a figure carries a comparison (the
company's own history, the same quarter a year earlier, or sector peers): COMPARISON_CUE. Nothing repeats what the ticker page
already shows (the beat rate and the moves after past reports): REPEATS. The Bottom Line summarizes what to watch and gives no
verdict on the stock: VERDICT_WORDS.
"""
from __future__ import annotations

import re

MAX_POINTS = 3
SECTIONS = ("highlights", "watch", "risks")

# a verdict on the stock; none of these anywhere in a note, and the Bottom Line gives no verdict at all
VERDICT_WORDS = re.compile(
    r"\b(?:compelling|exceptional|strong[- ]buy|buy rating|sell rating|undervalued|overvalued|bargain|cheap(?:ly valued)?|"
    r"attractive(?:ly)? valu\w*|attractive entry|must[- ]own|top pick|no[- ]brainer|bullish|bearish|outperform\w*|underperform\w*|"
    r"well[- ]positioned|best[- ]in[- ]class|buying opportunity)\b", re.I)

# what the ticker page already shows: the beat rate and counts, and the stock's moves after past reports
REPEATS = re.compile(
    r"\bbeat(?:s|en)? (?:rate|estimates?|expectations|consensus|the consensus|analyst)|\bbeat rate\b|"
    r"\b(?:beat|missed|topped) (?:in )?\d+ (?:of|out of) (?:its |the )?(?:last )?\d+\b|\b\d+[- ]of[- ]\d+\b|"
    r"\bpost[- ]earnings\b|\bearnings (?:reaction|move|surprise)s?\b|\b(?:eps |earnings )?surprise\b|"
    r"\b(?:1|3|5|one|three|five)[- ]day (?:move|reaction|return|change)s?\b|"
    r"\b(?:stock|shares) (?:has |have )?(?:moved|rose|fell|jumped|dropped|gained|lost|reacted)\b[^.]*\b(?:after|following) "
    r"(?:its |the )?(?:last |past |recent )?(?:earnings|reports?|results)\b", re.I)

# a comparison: own history, a year earlier, or peers
COMPARISON_CUE = re.compile(
    r"year earlier|year ago|year-ago|a year before|prior[- ]year|last year|from a year|five-year|5-year|\d+-year|"
    r"\baverage\b|\bmedian\b|\bpeers?\b|\bsector\b|\bindustry\b|compared|versus|\bvs\.?|than\b|\bfrom \$?\d|"
    r"up from|down from|previous quarter|prior quarter|sequential|historical|its own history|\bsince\b|\brecord\b", re.I)

# a figure: a percentage, a dollar amount, or a number with a unit; a bare year or a date is not a figure
FIGURE = re.compile(r"\$\s?\d|\d+(?:\.\d+)?\s?%|\b\d[\d,]*(?:\.\d+)?\s?(?:billion|million|thousand|bps|basis points|x)\b", re.I)


def _an_for_number(token: str) -> bool:
    """Pure: the number is spoken with a vowel sound first: 8, 80-89, 800..., 11 and 18 (and 11,000, 18 million...)."""
    digits = token.replace(",", "").split(".")[0]
    if not digits.isdigit():
        return False
    if digits.startswith("8"):
        return True
    return len(digits) % 3 == 2 and digits[:2] in ("11", "18")


_ARTICLE_NUMBER = re.compile(r"\b(a|an|A|An)(\s+)(\d[\d,]*(?:\.\d+)?)")


def clean_text(text: str) -> str:
    """Pure: dashes become plain punctuation and the article before a number is the spoken one."""
    if not text:
        return text
    t = re.sub(r"(\d)\s*[–—]\s*(\d)", r"\1 to \2", text)            # 2025–2026, 5—7%
    t = re.sub(r"\s*[—–]\s*", ", ", t)
    t = re.sub(r",\s*,", ",", t)

    def art(m: re.Match) -> str:
        word, space, num = m.group(1), m.group(2), m.group(3)
        want = "an" if _an_for_number(num) else "a"
        if word[0].isupper():
            want = want.capitalize()
        return f"{want}{space}{num}"
    return _ARTICLE_NUMBER.sub(art, t)


def point_problems(point: dict) -> list[str]:
    """Pure: why one point breaks the rules."""
    text = f"{point.get('lead', '')}. {point.get('detail', '')}"
    out = []
    if REPEATS.search(text):
        out.append("repeats what the ticker page shows (beat rate or moves after past reports)")
    if FIGURE.search(text) and not COMPARISON_CUE.search(text):
        out.append("states a figure with no comparison (its own history, the same quarter a year earlier, or sector peers)")
    if VERDICT_WORDS.search(text):
        out.append("gives a verdict on the stock")
    if re.search(r"[—–]", text):
        out.append("uses a dash")
    return out


def note_problems(structured: dict) -> list[str]:
    """Pure: every rule the draft breaks, one line each."""
    out: list[str] = []
    for sec in SECTIONS:
        items = structured.get(sec) or []
        if len(items) > MAX_POINTS:
            out.append(f"{sec}: {len(items)} points, at most {MAX_POINTS}")
        for i, p in enumerate(items):
            for why in point_problems(p):
                out.append(f"{sec} point {i + 1} ({p.get('lead', '')!r}): {why}")
    bl = structured.get("bottom_line") or ""
    if VERDICT_WORDS.search(bl):
        out.append("bottom_line: gives a verdict on the stock")
    if REPEATS.search(bl):
        out.append("bottom_line: repeats what the ticker page shows")
    if re.search(r"[—–]", bl + (structured.get("what_they_do") or "")):
        out.append("bottom_line or what_they_do: uses a dash")
    return out


def _sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])", text.strip()) if s]


def enforce(structured: dict) -> dict:
    """Pure: the note as stored. Points that repeat the page, state a bare figure or give a verdict are dropped, then each
    section keeps its first MAX_POINTS; Bottom Line sentences with a verdict or a repeat are dropped; text is cleaned."""
    out = dict(structured)
    for sec in SECTIONS:
        kept = [p for p in (structured.get(sec) or []) if not [w for w in point_problems(p) if w != "uses a dash"]]
        out[sec] = [{**p, "lead": clean_text(p.get("lead", "")), "detail": clean_text(p.get("detail", ""))} for p in kept[:MAX_POINTS]]
    bl = [s for s in _sentences(structured.get("bottom_line") or "") if not VERDICT_WORDS.search(s) and not REPEATS.search(s)]
    out["bottom_line"] = clean_text(" ".join(bl))
    out["what_they_do"] = clean_text(structured.get("what_they_do") or "")
    out.pop("rating", None)                # no verdict on the stock, so no rating badge
    return out
