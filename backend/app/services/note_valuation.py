"""What a served research note may say (2026-10-15).

1. Valuation multiples follow the site's P/E hold. While PE_ENABLED is off a visitor sees no P/E or other multiple anywhere in a
   note: points and Bottom Line sentences that name one are dropped, as are verification claims that name one, the multiple fields of
   the financials block, and sentences of an older markdown note.
2. A note never states a figure the Overview states for the same fact. The Overview's market value is the latest quote times the
   shares outstanding, dated, and shown only where it agrees with the dated market cap on file; a note's market cap is the figure at
   the hour it was written. The served note drops its market cap stat and every sentence that states a market cap figure, so the
   page shows one market value, the Overview's (VMRK's note said $47.32B beside an Overview of $23 billion on 2026-10-15).
3. A note states no beat rate and no move after past reports (Sam, 2026-10-19): the stats strip's "EPS beats 10/20" and "Latest Move
   -14.5% post-earnings 1d" are dropped as served; the ticker page's Evidence holds the past reports.
4. The strip's EPS is the SEC diluted figure the note's text uses (2026-10-20): TSLA's strip showed the vendor's "EPS $0.33" beside text
   saying diluted EPS was $0.32. Every vendor estimate, actual and surprise is dropped as served, and the router sets eps_sec from
   eps_quarters for the strip's quarter (sec_eps_for); validate note_eps_agrees fails when a served strip and its text disagree.

Applied at serve time to stored notes (routers/research_notes), so no stored note is rewritten.
"""
from __future__ import annotations

import re
from datetime import date, timedelta

VALUATION = re.compile(
    r"\bP\s?/\s?E\b|\bPE ratio|price[- /]to[- ]earnings|price/earnings|earnings multiple|\bmultiples?\b|\bEV\s?/\s?(?:EBITDA|sales|revenue)"
    r"|price[- /]to[- ](?:sales|book|free cash flow|cash flow)|\bP\s?/\s?[SB]\b|\bPEG\b|\btimes (?:forward |trailing )?(?:earnings|sales|EBITDA)"
    r"|\b\d+(?:\.\d+)?\s?x (?:forward |trailing )?(?:earnings|sales|EBITDA|revenue)", re.I)
MARKET_CAP_FIGURE = re.compile(r"market (?:cap(?:italization)?|value)[^.]{0,60}?\$\s?\d|\$\s?\d[\d.,]*\s?(?:[BMT]|billion|trillion|million)\b[^.]{0,30}market (?:cap|value)", re.I)
VALUATION_FIELDS = ("pe_ttm", "forward_pe", "peg_ttm", "ps_ttm", "pb", "ev_ebitda", "pe_percentile", "pe_sector_median")
OVERVIEW_STATS = ("market_cap",)
PAST_REPORT_STATS = ("beat_count", "total_quarters", "quarters_with_data", "quarters_without_data", "basis_excluded", "unavailable_reason",
                     "latest_move_1d", "latest_outcome")
VENDOR_STATS = ("eps_estimate", "eps_actual", "eps_beat_pct", "revenue_estimate", "revenue_actual", "revenue_beat_pct")
# the note's own statement of the quarter's EPS: "Diluted EPS of $0.32", "EPS was $1.24", "Diluted EPS for the quarter ended June 27,
# 2026 was $2.02", "$0.32 diluted"; a trailing, annual or
# half-year figure is not the quarter's
TEXT_EPS = re.compile(r"(?<![\w-])(?:diluted )?EPS (?:for the (?:quarter|three months) ended [A-Za-z]{3,9}\.? \d{1,2},? \d{4},? )?(?:of|was|at|came in at|reached|rose to|fell to) (-?)\$(\d+\.\d{2})"
                      r"|(-?)\$(\d+\.\d{2}) (?:per )?diluted", re.I)
NOT_QUARTER = re.compile(r"(?:trailing|(?:four|4)(?:[- ](?:most[- ]recent|latest|last|prior|previous))?[- ]quarters?|twelve[- ]months?|full[- ]year|annual"
                         r"|first[- ]half|half[- ]year|TTM|nine[- ]months?|six[- ]months?|year[- ]to[- ]date|YTD|combined)[\w ,-]{0,24}$", re.I)
                                                    # "Over the trailing four quarters, EPS of $1.08"; CBOE 2026-10-28: "The four most recent
                                                    # quarters combined show diluted EPS of $12.83"
# a figure labeled as other than GAAP is not the strip's (EMR 2026-10-28: "Adjusted diluted EPS of $1.71"; ES: "non-GAAP EPS was $0.87")
NOT_GAAP = re.compile(r"(?:adjusted|non[- ]?GAAP|excluding[\w ,-]{0,30}|core|operating|pro[- ]forma)[ ,]+(?:diluted |net |earnings |\w+ ){0,2}$", re.I)
_SENTENCES = re.compile(r"(?<=[.!?])\s+(?=[A-Z])")


def _drop(text: str | None, *patterns: re.Pattern) -> str | None:
    if not text:
        return text
    return " ".join(x for x in _SENTENCES.split(text) if x and not any(p.search(x) for p in patterns))


def served(structured: dict | None, verification: dict | None, content: str | None, valuation_shown: bool) -> tuple[dict | None, dict | None, str | None]:
    """Pure: (structured, verification, content) as a visitor may see them. Verification totals are recounted by the caller."""
    pats = (MARKET_CAP_FIGURE,) if valuation_shown else (MARKET_CAP_FIGURE, VALUATION)
    if structured:
        s = dict(structured)
        for sec in ("highlights", "watch", "risks"):
            s[sec] = [p for p in (s.get(sec) or []) if not any(x.search(f"{p.get('lead', '')} {p.get('detail', '')}") for x in pats)]
        s["bottom_line"] = _drop(s.get("bottom_line"), *pats) or ""
        if isinstance(s.get("stats"), dict):
            s["stats"] = {k: (None if k in OVERVIEW_STATS or k in PAST_REPORT_STATS or k in VENDOR_STATS else v) for k, v in s["stats"].items()}
        if not valuation_shown and isinstance(s.get("financials"), dict):
            s["financials"] = {k: v for k, v in s["financials"].items() if k not in VALUATION_FIELDS}
        structured = s
    if verification and isinstance(verification.get("claims"), list):
        verification = {**verification, "claims": [c for c in verification["claims"] if isinstance(c, dict) and not any(
            x.search(str(c.get(k) or "")) for x in pats for k in ("claim", "reason", "evidence"))]}
    content = _drop(content, *pats)
    return structured, verification, content


def leaks(structured: dict | None, verification: dict | None, content: str | None, valuation_shown: bool) -> list[str]:
    """Pure: every place a served note still names a multiple (while they are held), a market cap figure, a beat rate or a move after
    past reports (the stats strip); empty when clean."""
    out = [f"past-report stat: {k}" for k in ("beat_count", "latest_move_1d")
           if structured and isinstance(structured.get("stats"), dict) and structured["stats"].get(k) is not None]
    texts = [content or ""]
    if structured:
        texts += [f"{p.get('lead', '')} {p.get('detail', '')}" for sec in ("highlights", "watch", "risks") for p in (structured.get(sec) or [])]
        texts.append(structured.get("bottom_line") or "")
    if verification:
        texts += [str(c.get("claim") or "") for c in verification.get("claims") or [] if isinstance(c, dict)]
    pats = [("market cap figure", MARKET_CAP_FIGURE)] + ([] if valuation_shown else [("valuation multiple", VALUATION)])
    return out + [f"{name}: {t[:120]}" for t in texts for name, p in pats if p.search(t)]


def labeled_other(t: str, start: int) -> bool:
    """Pure: the EPS figure at `start` is labeled as other than the quarter's GAAP figure: adjusted or non-GAAP, or trailing, four
    quarters, year-to-date or another span (the label within the 60 characters before it, in its own sentence)."""
    before = t[max(0, start - 60):start]
    before = re.split(r"[.!?]\s+(?=[A-Z])|\n", before)[-1]
    return bool(NOT_QUARTER.search(before) or NOT_GAAP.search(before))


def text_eps(texts: list[str]) -> float | None:
    """Pure: the first quarterly EPS figure the note's text states, in reading order, or None."""
    for t in texts:
        for m in TEXT_EPS.finditer(t or ""):
            if labeled_other(t or "", m.start()):
                continue
            sign, digits = (m.group(1), m.group(2)) if m.group(2) else (m.group(3), m.group(4))
            return -float(digits) if sign else float(digits)
    return None


_MON = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?"
QUARTER_ENDED = re.compile(rf"quarter (?:ended|ending) {_MON} (\d{{1,2}}),? (\d{{4}})", re.I)
MONTH_QUARTER = re.compile(rf"\b{_MON} (\d{{4}}) quarter\b", re.I)          # "the March 2026 quarter" (EL, CRL 2026-10-28)
QUARTER_LABEL = re.compile(r"\b(?:Q([1-4])|(first|second|third|fourth)[- ]quarter)(?: of)?(?: fiscal)? (?:FY ?)?(\d{4})\b", re.I)
_ORDINAL = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
QUARTER_END_DAYS = 7           # "the quarter ended June 27, 2026" is the strip's quarter when within this many days of its period end
QUARTER_LABEL_DAYS = 45        # "Q2 2026" is the strip's quarter when its calendar quarter ends this close to the period end


def named_quarter(sentence: str) -> tuple[date, bool] | None:
    """Pure: the first quarter a sentence names, as (the day it ended, False) for "the quarter ended June 27, 2026", or (its calendar
    quarter's last day, True) for "Q1 2026" or "first quarter of 2026"; None when it names none."""
    hits = []
    for m in QUARTER_ENDED.finditer(sentence):
        try:
            hits.append((m.start(), date(int(m.group(3)), _MONTHS.index(m.group(1)[:3].lower()) + 1, int(m.group(2))), False))
        except ValueError:
            continue
    for m in MONTH_QUARTER.finditer(sentence):
        month, year = _MONTHS.index(m.group(1)[:3].lower()) + 1, int(m.group(2))
        hits.append((m.start(), (date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)), True))
    for m in QUARTER_LABEL.finditer(sentence):
        n = int(m.group(1)) if m.group(1) else _ORDINAL[m.group(2).lower()]
        year = int(m.group(3))
        hits.append((m.start(), date(year, 12, 31) if n == 4 else date(year, 3 * n + 1, 1) - timedelta(days=1), True))
    if not hits:
        return None
    _, day, label = min(hits, key=lambda h: h[0])
    return day, label


def same_quarter(named, period_end) -> bool:
    """Pure: a named quarter (named_quarter) is the quarter that ended on `period_end`."""
    day, label = named
    return abs((day - period_end).days) <= (QUARTER_LABEL_DAYS if label else QUARTER_END_DAYS)


def _sentence_around(t: str, start: int, end: int) -> str:
    """The sentence holding t[start:end], up to its end."""
    begin = max([t.rfind("\n", 0, start) + 1] + [m.end() for m in _SENTENCES.finditer(t, 0, start)])
    stop = next((m.start() for m in _SENTENCES.finditer(t, end)), len(t))
    nl = t.find("\n", end)
    return t[begin:min(stop, nl) if nl >= 0 else stop]


def quarter_text_eps(texts: list[str], period_end) -> float | None:
    """Pure: the first quarterly EPS figure the text states for the quarter that ended on `period_end`: a figure whose sentence names
    another quarter is skipped (META's "Diluted EPS of $10.44 in Q1 2026" beside a strip showing Q2), one that names none is taken
    as the latest quarter's."""
    for t in texts:
        t = t or ""
        for m in TEXT_EPS.finditer(t):
            if labeled_other(t, m.start()):
                continue
            named = named_quarter(_sentence_around(t, m.start(), m.end()))
            if named is not None and not same_quarter(named, period_end):
                continue
            sign, digits = (m.group(1), m.group(2)) if m.group(2) else (m.group(3), m.group(4))
            return -float(digits) if sign else float(digits)
    return None


def note_texts(structured: dict | None, content: str | None) -> list[str]:
    """Pure: a served note's prose in reading order (the markdown content when present, else its points and Bottom Line)."""
    if content:
        return [content]
    if not structured:
        return []
    return [structured.get("bottom_line") or ""] + [f"{p.get('lead', '')} {p.get('detail', '')}" for sec in ("highlights", "watch", "risks")
                                                    for p in (structured.get(sec) or [])]


def eps_disagreement(structured: dict | None, content: str | None, period_end=None) -> str | None:
    """Pure: why a served note's strip EPS and its text disagree, or None. With the strip quarter's `period_end`, only a figure the text
    states for that quarter is compared (quarter_text_eps)."""
    st = (structured or {}).get("stats") if isinstance((structured or {}).get("stats"), dict) else None
    strip = st.get("eps_sec") if st else None
    texts = note_texts(structured, content)
    said = text_eps(texts) if period_end is None else quarter_text_eps(texts, period_end)
    if strip is None or said is None or round(float(strip), 2) == round(said, 2):
        return None
    return f"strip EPS ${float(strip):.2f}, text ${said:.2f}"


async def sec_quarter_for(db, symbol: str, quarter_date: str | None) -> dict | None:
    """The quarter a report on `quarter_date` announced, {period_end, eps, ...} from SEC filings (eps_quarters), or None."""
    if not quarter_date:
        return None
    from app.services.eps_year_ago import load_quarters, quarter_for_report, year_ago_pairs
    return quarter_for_report(year_ago_pairs(await load_quarters(db, symbol)), date.fromisoformat(str(quarter_date)[:10]))


async def sec_eps_for(db, symbol: str, quarter_date: str | None) -> float | None:
    """The GAAP diluted EPS from SEC filings (eps_quarters) for the quarter a report on `quarter_date` announced, or None."""
    pair = await sec_quarter_for(db, symbol, quarter_date)
    return pair["eps"] if pair else None


async def with_sec_eps(db, symbol: str, structured: dict | None) -> dict | None:
    """The served note with its strip's eps_sec set from SEC filings for the strip's quarter."""
    if not structured or not isinstance(structured.get("stats"), dict):
        return structured
    st = dict(structured["stats"])
    st["eps_sec"] = await sec_eps_for(db, symbol, st.get("latest_quarter_date"))
    return {**structured, "stats": st}
