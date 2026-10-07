"""Trailing P/E from filings (report only until approved; nothing displays).

The trailing window is the latest four reported quarters of GAAP diluted EPS. Three sources, in order of authority: XBRL
company facts (quarterly EarningsPerShareDiluted facts, the fourth quarter derived from the 10-K's annual figure when only
that is filed), and, when the company has reported a quarter newer than XBRL holds, the GAAP diluted EPS parsed from that
quarter's earnings release (the Item 2.02 8-K's EX-99.1, stored in release_eps with the filing as its receipt). A window
that does not include the company's latest reported quarter is never used: when the latest quarter cannot be read, there
is no P/E. Every P/E is stated with the period its four quarters cover.

History: each session's close over the four quarters filed by that day (point in time). Sessions where trailing EPS is
negative or below MIN_EARNINGS_YIELD of the price (a P/E above 100) are excluded and counted; the summary is the median
and the share of sessions today's P/E sits above, never the minimum or maximum.
"""
from __future__ import annotations

import re
import statistics
from datetime import date, timedelta

QUARTER_DAYS = (80, 100)          # a quarterly EPS fact covers a period this long
EPS_FACT_MAX = 1_000_000          # an EPS fact beyond this is a tagging error (ICE's 2015 10-Qs carry $112,000,000 as EPS); Berkshire's class A EPS is ~30,000
YEAR_DAYS = (350, 380)            # an annual one
MIN_EARNINGS_YIELD = 0.01         # trailing EPS below 1% of price (P/E above 100) is excluded from history
RANGE_YEARS = 5
RELEASE_TOLERANCE = 0.01          # a release figure this far from the XBRL figure for the same quarter is flagged
SECTOR_COVERAGE_MIN = 0.90        # a sector median shows only when this share of the sector's active tickers has a fresh window
NOT_MEANINGFUL_REASON = "lost money over the last four quarters"
CLEAN_QUARTERS_NEEDED = 4         # after a spin-off, merger, share-exchange acquisition or rename-merge, this many full quarters must pass before a P/E
ACTION_VERBS = {"spin_off": "Spun off {name} on {date}", "merger": "Merged with {name} on {date}", "acquisition": "Acquired {name} by share exchange on {date}",
                "rename_merge": "Renamed from {name} on {date} after a merger"}
REFRESH_AFTER_REPORT_DAYS = 100   # quarters are re-read from XBRL while a report this recent may not have landed in XBRL yet
NEWER_REPORT_GRACE_DAYS = 20      # a report dated more than this many days after the latest XBRL quarter end is a newer quarter
MAX_QUARTER_GAP_DAYS = 125        # the release quarter must directly follow the newest XBRL quarter; a longer gap means a quarter is missing
PERIOD_END_MAX_DAYS = 120         # a release reports a quarter that ended within this many days before the report

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = re.compile(rf"({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})")
_MONEY = r"\$?\s?\(?-?\d{1,4}(?:,\d{3})*(?:\.\d{1,2})?\)?"
# "GAAP net income of $37.70 billion, or $32.87 per diluted share" (the quarter's highlight comes before the year's)
_PROSE = re.compile(rf"GAAP\s+(?:net\s+)?(?:income|earnings|loss)\b.{{0,80}}?,\s*or\s+(?:a\s+(?:loss|net loss)\s+of\s+)?(\(?\$\s?\(?-?\d{{1,4}}(?:,\d{{3}})*(?:\.\d{{1,2}})?\)?)\s+per\s+(?:basic\s+and\s+)?diluted\s+share", re.I)
# "GAAP diluted earnings per share $ 32.87 $ 24.67 ..." / "Diluted earnings per share 32.87 24.67 ..." (first column is the current quarter)
_ROW = re.compile(rf"(?<![A-Za-z-])(?:GAAP\s+)?diluted\s+(?:net\s+)?(?:earnings|income|loss)\s+per\s+(?:potential\s+)?(?:common\s+)?share(?:\s*\(\d\)|\s+\d)?\s*(?:attributable[^$\d]{{0,80}})?(?:\s+(?:of|was|were))?[:\s]*\$?\s?(\(?-?\d{{1,4}}(?:,\d{{3}})*\.\d{{1,2}}\)?)", re.I)
_ROW2 = re.compile(rf"earnings\s+per\s+share[^A-Za-z]{{0,20}}basic[^A-Za-z]{{0,40}}diluted\s*\$?\s?(\(?-?\d{{1,4}}(?:,\d{{3}})*\.\d{{1,2}}\)?)", re.I)
# a figure whose own clause carries one of these is never GAAP EPS (CRL's "non-GAAP earnings per share of $3.02", FRT's "Nareit FFO ... $1.88 per diluted share")
_NON_GAAP_NEAR = re.compile(r"non-?\s?gaap|adjusted|pro\s?forma|excluding|\bcore\b|operating (?:income|earnings|eps)|underlying|normali[sz]ed|\bffo\b|funds from operations"
                            r"|comparable (?:eps|earnings|net income|diluted|income)", re.I)
# a figure labelled as the year's is never the quarter's (SMCI's "for fiscal year 2026 was $2.5 billion, or $3.63 per diluted share", CAH's "GAAP diluted EPS was $7.23"
# in the fiscal-year paragraph); a clause that also names a quarter is left to the other rules
_ANNUAL_LABEL = re.compile(r"fiscal[- ]year|full[- ]year|year[- ]ended|twelve[- ]months|12[- ]months|year[- ]to[- ]date|\bannual\b", re.I)
_QUARTER_WORD = re.compile(r"quarter|\bQ[1-4]\b|three months|\d{1,2} weeks", re.I)
_NUM = r"(\(?-?\d{1,4}(?:,\d{3})*\.\d{1,2}\)?)"
_DNUM = r"(\(?\$\s?\(?-?\d{1,4}(?:,\d{3})*\.\d{1,2}\)?)"      # with the dollar sign, a loss written "($0.35)" or "$(0.35)"
# other phrasings, tried after _PROSE and _ROW, in this order
_PROSE_ANY = re.compile(rf"\b(?:net\s+(?:income|earnings|loss)|earnings|income)\b[^;]{{0,120}}?,?\s+or\s+(?:a\s+(?:loss|net loss)\s+of\s+)?{_DNUM}\s+per\s+(?:basic\s+and\s+)?diluted\s+(?:common\s+)?share", re.I)
# utilities and others: "GAAP net income of $0.37 per share", "earnings per share (EPS) of $5.73 on a GAAP basis", "reported EPS of $1.38 ... (GAAP)",
# "earnings per share of $1.03 on an as-reported ... basis", "GAAP earnings per share (EPS) was $0.99", "diluted earnings per share were $56.05"
_GAAP_PER_SHARE = re.compile(rf"GAAP\s+net\s+(?:income|earnings)\s+of\s+{_DNUM}\s+per\s+(?:diluted\s+)?share", re.I)
_EPS_GAAP_BASIS = re.compile(rf"(?:earnings\s+per\s+share|EPS)(?:\s+\(EPS\))?\s+of\s+{_DNUM}\s+on\s+a\s+GAAP\s+basis", re.I)
_REPORTED_EPS_GAAP = re.compile(rf"reported\s+(?:diluted\s+)?EPS\s+of\s+{_DNUM}[^.]{{0,160}}?\bGAAP\b", re.I)
_AS_REPORTED = re.compile(rf"earnings\s+per\s+share\s+of\s+{_DNUM}\s+on\s+an\s+as-reported", re.I)
_GAAP_EPS_WAS = re.compile(rf"GAAP\s+(?:diluted\s+)?(?:earnings|loss|income)\s+per\s+(?:diluted\s+)?share(?:\s+\(EPS\))?\s+(?:was|were|of)\s+{_DNUM}", re.I)   # "GAAP loss per share of $(0.03)" (CRL)
_DILUTED_WERE = re.compile(rf"\bdiluted\s+(?:net\s+)?earnings\s+per\s+share\s+(?:were|was)\s+{_DNUM}", re.I)
# rows: "Net income per share: Basic $ 57.17 $ 50.02 Diluted $ 56.05", "Earnings (loss) per common share - diluted $ 0.99", "EPS (Diluted) $ (0.01)",
# "Diluted earnings per share (EPS) ... GAAP $5.73", "Diluted net earnings per share: ... Net earnings $ 2.04" (the total, after continuing operations)
_ROW_NET_BASIC_DILUTED = re.compile(rf"net\s+(?:income|earnings)\s+per\s+(?:common\s+)?share:?\s*basic\s*\$?\s?\(?-?[\d,]+\.\d{{1,2}}\)?(?:\s*\$?\s?\(?-?[\d,]+\.\d{{1,2}}\)?){{0,3}}\s*diluted\s*\$?\s?{_NUM}", re.I)
# the total row only: a "from continuing operations - diluted" row is not the whole EPS (Dominion states both; the total is read)
_ROW_DASH = re.compile(rf"(?:reported\s+)?(?:net\s+)?(?:earnings|income)(?:\s*/?\s*\(loss\))?\s+per\s+(?:common\s+)?share(?:\s+attributable\s+to\s+[A-Z][\w.&'’ ]{{0,40}}?)?\s*[—–-]+\s*diluted(?:\s*\((?:GAAP|[a-z]|\d)\))*\s*\$?\s?{_NUM}", re.I)
_EPS_DILUTED_PAREN = re.compile(rf"\bEPS\s+\(diluted\)\s*\$?\s?{_NUM}", re.I)
_DILUTED_EPS_GAAP_COL = re.compile(rf"diluted\s+earnings\s+per\s+share(?:\s+\(EPS\))?[^$]{{0,120}}?\bGAAP\s+\$?\s?{_NUM}", re.I)
_PER_SHARE_NUM = r"(\(?-?\d{1,3}\.\d{2}\)?)"      # a per-share amount: two decimals, under 1,000; never "397.0" (millions) or "429.7"
_DILUTED_BLOCK_NET = re.compile(rf"diluted\s+(?:net\s+)?(?:earnings|income)(?:\s*\(loss\))?\s+per\s+(?:common\s+)?share(?:\s+attributable\s+to\s+[A-Z][\w.&'’ ]{{0,40}}?)?:?\s*"
                                rf"(?:(?:earnings|income|loss|net earnings|net income)?\s*(?:\(loss\)\s+)?(?:from\s+)?)?continuing\s+operations\s+\$?\s?\(?-?\d{{1,3}}\.\d{{2}}\)?(?:\s+\$?\s?\(?-?\d{{1,3}}\.\d{{2}}\)?)*"
                                rf"(?:\s+(?:losses?|earnings|income)?\s*(?:\(loss\)\s+)?(?:from\s+)?discontinued\s+operations\s+\$?\s?\(?-?\d{{1,3}}\.\d{{2}}\)?(?:\s+[—-]|\s+\$?\s?\(?-?\d{{1,3}}\.\d{{2}}\)?)*)?"
                                rf"\s+(?:discontinued\s+operations\s+[^$]{{0,40}})?net\s+(?:earnings|income)(?:\s+attributable\s+to\s+[A-Z][\w.&'’ ]{{0,40}}?)?\s+\$?\s?{_PER_SHARE_NUM}", re.I)
# a per-share block whose header is followed straight by the attributable line ("Diluted earnings per common share … Net income attributable to PFG $1.84"):
# the amount must look like a per-share figure (two decimals, under 1,000), which a net income in millions ("$ 397.0", "$ 1,204.2") never does
_DILUTED_HEADER_NET = re.compile(rf"diluted\s+(?:net\s+)?(?:earnings|income)\s+per\s+(?:common\s+)?share(?![^$]{{0,120}}continuing)[^$]{{0,120}}?\bnet\s+(?:income|earnings)(?:\s*\(loss\))?\s+attributable\s+to\s+[A-Z][\w.&'’ ]{{0,40}}?\s+\$?\s?{_PER_SHARE_NUM}(?![\d,])", re.I)
# third pass (utilities and others): "GAAP earnings of $713 million or $1.31 per share", "reported earnings (GAAP) of $230 million, or $0.30 per share",
# "GAAP EPS decreased 3% to $1.25", "earnings per share were $1.60", "Diluted Net Income Per Share 1 $ 1.03" (a footnote mark), "Earnings per diluted share $1.25",
# "Net Income per diluted share $0.21", "Net Income per diluted share: • $1.83 GAAP", "GAAP diluted net income per potential common share $ 1.83",
# "reported EPS of $3.32 and comparable EPS of $3.74" (reported against a non-GAAP measure), "On a basic and diluted basis, net income attributable to X per share ... was $Y"
_GAAP_MILLION_PER_SHARE = re.compile(rf"(?:GAAP\s+(?:net\s+)?(?:income|earnings)|(?:reported\s+)?earnings\s+\(GAAP\))\s+of\s+\$\s?[\d.,]+\s+(?:million|billion),?\s+or\s+{_DNUM}\s+per\s+(?:diluted\s+)?share", re.I)
_GAAP_PAREN_PER_SHARE = re.compile(rf"(?:reported\s+)?earnings\s+\(GAAP\)\s+of\s+{_DNUM}\s+per\s+share", re.I)
_GAAP_EPS_CHANGE = re.compile(rf"GAAP(?:\s+\d)?\s+(?:diluted\s+)?(?:EPS|earnings\s+per\s+share(?:\s+\(EPS\))?)\s+(?:increased|decreased|grew|fell|rose|declined|was\s+(?:up|down))\s+[\d.]+%?\s+to\s+{_DNUM}", re.I)   # a footnote mark after GAAP (CAH)
_EPS_WERE = re.compile(rf"(?<![A-Za-z-])earnings\s+per\s+(?:diluted\s+)?share\s+(?:were|was)\s+{_DNUM}", re.I)   # "earnings per diluted share was $0.97" (FRT)
_ROW_FOOTNOTE = re.compile(rf"(?<![A-Za-z-])diluted\s+net\s+income\s+per\s+share\s+\d\s+\$\s?{_NUM}", re.I)
_ROW_PER_DILUTED = re.compile(rf"(?<![A-Za-z-])(?:net\s+income|earnings)\s+per\s+diluted\s+share:?\s*(?:•\s*)?\$?\s?{_NUM}(?:\s+GAAP)?", re.I)
_ROW_POTENTIAL = re.compile(rf"GAAP\s+diluted\s+net\s+income\s+per\s+potential\s+common\s+share\s*\$?\s?{_NUM}", re.I)
_REPORTED_VS_NONGAAP = re.compile(rf"reported\s+EPS\s+of\s+{_DNUM}\s+and\s+(?:comparable|adjusted|non-GAAP)\s+EPS", re.I)
_BASIC_AND_DILUTED_BASIS = re.compile(rf"on\s+a\s+basic\s+and\s+diluted\s+basis,\s+net\s+income[^$]{{0,160}}?\bwas\s+{_DNUM}", re.I)
_LABELLED = re.compile(rf"(?<![A-Za-z-])(?:earnings\s+per\s+share:?\s*GAAP:?|GAAP\s+(?:diluted\s+)?EPS(?:\s+of|\s+was|:)?|diluted\s+EPS(?:\s+of|\s+was|:)?|GAAP\s+earnings\s+per\s+(?:diluted\s+)?share(?:\s+of|\s+was|:)?)\s*\$\s?{_NUM}", re.I)
_ROW_NET = re.compile(rf"net\s+(?:income|earnings)\s+per\s+(?:common\s+)?(?:diluted\s+)?share[^$\d]{{0,30}}diluted\s*\$?\s?{_NUM}", re.I)
_PER_DILUTED = re.compile(rf"{_DNUM}\s+per\s+diluted\s+(?:common\s+)?share", re.I)
_PER_SHARE = re.compile(rf"\bnet\s+income\b[^;]{{0,120}}?,?\s+or\s+\$\s?{_NUM}\s+per\s+share", re.I)       # insurers' "per share net income": diluted by their statements
# a figure inside an outlook is never the quarter's result: a guidance word nearby, or a range to a second amount right after it
_GUIDANCE_NEAR = re.compile(r"outlook|guidance|expect|forecast|anticipat|projected|target|estimates?\b|(?:fiscal|fy)\s*'?\d{2,4}\s+(?:guidance|outlook)|next\s+(?:quarter|year)|first\s+quarter\s+of\s+fiscal", re.I)
# a per-share figure in a sentence about an item, charge, impact or adjustment is never the quarter's EPS
_ITEM_NEAR = re.compile(r"related to|impact of|impacts? from|charges?\s+of|approximately|amortization|adjustments?|impairment|benefit of|expense of|effect of|headwind|tailwind|one-time|non-?recurring", re.I)
# a figure introduced by a comparison is the prior period's (introduced_by_comparison)
_RANGE_AFTER = re.compile(r"^\s*(?:to|[–—-]|±)\s*\$?\s?\d", re.I)
_CONTINUING_TABLE = re.compile(r"(?:diluted\s+)?(?:earnings|income|EPS)[^.]{0,60}?\(a\)\s+from\s+continuing\s+operations|per\s+share:?\s+continuing\s+operations\s+\$|\(a\)\s+from\s+continuing\s+operations", re.I)
_PERIOD_END = re.compile(rf"(?:(?:three|3)\s+months|\d{{1,2}}\s+weeks|quarter|qtr\.?|fiscal\s+quarter|quarterly\s+period)\s+ended\s+({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})", re.I)
_QTR_HEADER = re.compile(rf"(?:[1-4](?:st|nd|rd|th)\s+Qtr\.?|Q[1-4])[^A-Za-z]{{0,40}}(?:[1-4](?:st|nd|rd|th)\s+Qtr\.?|Q[1-4]|Year\s+Ended|Twelve\s+Months)?[^A-Za-z]{{0,40}}(?:Year\s+Ended\s+)?({_MONTHS})\s+(\d{{1,2}}),\s+(\d{{4}})", re.I)


def _to_date(m: re.Match, g: int = 1) -> date | None:
    try:
        return date(int(m.group(g + 2)), [x.lower() for x in _MONTHS.split("|")].index(m.group(g).lower()) + 1, int(m.group(g + 1)))
    except ValueError:
        return None


def _num(s: str) -> float:
    s = s.replace("$", "").replace(",", "").replace(" ", "").strip()
    neg = "(" in s or s.startswith("-")
    v = float(s.strip("()-"))
    return -v if neg else v


def _sentence_around(flat: str, start: int, end: int) -> tuple[str, str]:
    """Pure: (the sentence text before the match, the whole sentence), bounded by the nearest sentence ends or bullets."""
    # a headline runs straight into the dateline in flattened text ("affirms guidance and outlooks NEW ORLEANS – Entergy reported"): the dash ends it
    left = max(flat.rfind(". ", 0, start), flat.rfind("•", 0, start), flat.rfind("; ", 0, start), flat.rfind("▪", 0, start), flat.rfind("◦", 0, start), flat.rfind(" – ", 0, start), flat.rfind(" — ", 0, start))
    left = left + 1 if left >= 0 else 0
    right_candidates = [i for i in (flat.find(". ", end), flat.find("•", end), flat.find("; ", end), flat.find("▪", end), flat.find("◦", end)) if i >= 0]
    right = min(right_candidates) if right_candidates else len(flat)
    return flat[left:start], flat[left:right]


_COMPARISON_CUE = re.compile(r"compared\s+(?:with|to)|versus|vs\.?|in\s+the\s+(?:prior|year-ago|same)\s+(?:year|quarter|period)|a\s+year\s+(?:ago|earlier)|last\s+year|prior-year|year-ago", re.I)


def introduced_by_comparison(before: str) -> bool:
    """Pure: the figure is the prior period's: a comparison cue precedes it in the clause, with nothing but the compared amount
    (and an ", or" join) between them. A cue earlier in the sentence, before a clause break (", while", "; ", " and "), compares
    something else: "net income was $931.6 million compared to $837.0 million last year, while diluted EPS were $56.05"."""
    m = None
    for m in _COMPARISON_CUE.finditer(before):
        pass
    if m is None:
        return False
    tail = re.sub(r",\s+or\s+", " or ", before[m.end():])
    return not re.search(r",|;|\bwhile\b|\band\b", tail)


def _same_clause(flat: str, start: int, back: int) -> str:
    """Pure: up to `back` characters before the match, cut at the start of its bullet or sentence, so a neighbouring bullet's
    "adjusted" never disqualifies this one."""
    before = flat[max(0, start - back):start]
    cut = max(before.rfind("•"), before.rfind("▪"), before.rfind("◦"), before.rfind(". "), before.rfind("; "))
    return before[cut + 1:] if cut >= 0 else before


def _guidance_near(flat: str, start: int, end: int) -> bool:
    """Pure: a guidance word in the figure's own bullet or sentence (the text before it in that clause, and the clause itself up to
    80 characters after the figure), never in a headline several bullets earlier."""
    before, sentence = _sentence_around(flat, start, end)
    return bool(_GUIDANCE_NEAR.search(before)) or bool(_GUIDANCE_NEAR.search(flat[end:min(len(flat), end + 80)].split("•")[0].split(". ")[0]))


def _disqualified(flat: str, start: int, end: int) -> bool:
    """Pure: the sentence describes an item, charge, impact or adjustment, or the figure is introduced by a comparison."""
    before, sentence = _sentence_around(flat, start, end)
    return bool(_ITEM_NEAR.search(sentence)) or introduced_by_comparison(before)


def _previous_sentence(flat: str, sentence_start: int) -> str:
    """Pure: the sentence or bullet just before the one starting at `sentence_start`."""
    head = flat[:max(0, sentence_start - 1)]
    left = max(head.rfind(". "), head.rfind("•"), head.rfind("; "), head.rfind("▪"), head.rfind("◦"))
    return head[left + 1:] if left >= 0 else head[-300:]


def is_annual_figure(flat: str, start: int, end: int, figure_at: int | None = None) -> bool:
    """Pure: the figure is labelled as the year's, never the quarter's: the text before it in its own sentence or bullet carries a
    fiscal-year, full-year, year-ended, twelve-months or year-to-date label and no quarter word; or it carries neither and the sentence
    before it (the paragraph's subject: "Fiscal year 2026 revenues were $254.2 billion...") carries the label with no quarter word."""
    # only the text before the figure labels it: in a flattened table the next table's "Year Ended" header follows the row (ACN);
    # `figure_at` is the number's position, since a match may start at its subject ("Net income for fiscal year 2026 was ..., or $3.26")
    before, _ = _sentence_around(flat, figure_at if figure_at is not None else start, end)
    if _QUARTER_WORD.search(before):
        return False
    if _ANNUAL_LABEL.search(before):
        return True
    prev = _previous_sentence(flat, (figure_at if figure_at is not None else start) - len(before))
    return bool(_ANNUAL_LABEL.search(prev)) and not _QUARTER_WORD.search(prev)


def parse_release_eps(text: str, report_date: date | None = None) -> dict | None:
    """Pure: the quarter's GAAP diluted EPS stated in an earnings release, with how it was read.

    Tries, in order: the highlights sentence "GAAP net income of $X, or $Y per diluted share" (the first such sentence is
    the quarter; the year's follows); the "GAAP diluted earnings per share" table row (first column, the current quarter);
    the income statement's "Earnings per share: Basic … Diluted …" row; a labelled figure ("Earnings per Share: GAAP: $Y",
    "Diluted EPS $Y"); a dash or net-income row ("Earnings per share—diluted $Y"); a net-income sentence without the word
    GAAP ("net income of $X, or $Y per diluted share"); the first "$Y per diluted share"; and, last, an insurer's "net income
    of $X, or $Y per share". A figure whose own clause carries non-GAAP, adjusted, core, operating, FFO, funds from operations,
    normalized or comparable is never GAAP EPS; one labelled fiscal year, full year, year ended, twelve months or year to date is
    never the quarter (is_annual_figure); a continuing-operations-only figure stays unread. Returns {eps, how, evidence, period_end}
    or None when no GAAP diluted figure can be read."""
    if not text:
        return None
    flat = re.sub(r"\s+", " ", text)
    period_end = None
    for m in list(_PERIOD_END.finditer(flat)) + list(_QTR_HEADER.finditer(flat)):
        d = _to_date(m)
        # the quarter a release reports ended within PERIOD_END_MAX_DAYS before the report; an older date is a comparison period
        if d and (report_date is None or 0 <= (report_date - d).days <= PERIOD_END_MAX_DAYS):
            period_end = d
            break
    for hit in _PROSE.finditer(flat):
        if _NON_GAAP_NEAR.search(_same_clause(flat, hit.start(), 12) + hit.group(0)):      # "Non-GAAP net income ... , or $3.63 per diluted share" (SMCI)
            continue
        if _guidance_near(flat, hit.start(), hit.end()) or _disqualified(flat, hit.start(), hit.end()) or is_annual_figure(flat, hit.start(), hit.end(), hit.start(1)):
            continue
        return {"eps": _num(hit.group(1)), "how": "highlights sentence", "evidence": flat[max(0, hit.start() - 20):hit.end() + 10].strip(), "period_end": period_end}
    attempts = ((_DILUTED_BLOCK_NET, "diluted EPS block, net earnings line", 0), (_DILUTED_HEADER_NET, "diluted EPS block, attributable line", 0), (_ROW, "diluted EPS row", 12), (_ROW2, "income statement EPS row", 12), (_ROW_NET_BASIC_DILUTED, "net income per share row, basic then diluted", 12),
                (_LABELLED, "labelled GAAP EPS", 40), (_GAAP_EPS_WAS, "GAAP EPS sentence", 12), (_EPS_GAAP_BASIS, "EPS on a GAAP basis", 12), (_REPORTED_EPS_GAAP, "reported EPS, GAAP named", 12),
                (_AS_REPORTED, "as-reported EPS", 12), (_DILUTED_EPS_GAAP_COL, "diluted EPS, GAAP column", 12), (_ROW_DASH, "EPS row, dash diluted", 12), (_EPS_DILUTED_PAREN, "EPS (Diluted) row", 12),
                (_ROW_NET, "net income per share row", 12), (_DILUTED_WERE, "diluted EPS were sentence", 12), (_PROSE_ANY, "net income sentence", 12), (_GAAP_PER_SHARE, "GAAP net income per share", 12),
                (_GAAP_MILLION_PER_SHARE, "GAAP earnings, or per share", 12), (_GAAP_PAREN_PER_SHARE, "reported earnings (GAAP) per share", 12), (_GAAP_EPS_CHANGE, "GAAP EPS change sentence", 12),
                (_ROW_FOOTNOTE, "diluted net income per share row (footnote)", 12), (_ROW_POTENTIAL, "GAAP diluted per potential common share", 12), (_ROW_PER_DILUTED, "per diluted share row", 12),
                (_REPORTED_VS_NONGAAP, "reported EPS against a non-GAAP measure", 12), (_BASIC_AND_DILUTED_BASIS, "basic and diluted basis sentence", 12), (_EPS_WERE, "EPS were sentence", 12),
                (_PER_DILUTED, "per diluted share", 80), (_PER_SHARE, "per share net income sentence", 12))
    for pattern, how, back in attempts:
        for hit in pattern.finditer(flat):
            before = _same_clause(flat, hit.start(), max(back, 12))
            own = "" if how == "reported EPS against a non-GAAP measure" else hit.group(0)      # that pattern names the comparable figure on purpose (STZ)
            if _NON_GAAP_NEAR.search(before + own):                      # joined, so "non-" + "GAAP earnings per share of $3.02" reads as non-GAAP (CRL)
                continue
            if _guidance_near(flat, hit.start(), hit.end()) or _RANGE_AFTER.search(flat[hit.end():hit.end() + 12]) or is_annual_figure(flat, hit.start(), hit.end(), hit.start(1)):
                continue
            if how in ("net income sentence", "per diluted share", "per share net income sentence", "labelled GAAP EPS", "GAAP EPS sentence", "EPS on a GAAP basis", "reported EPS, GAAP named",
                       "as-reported EPS", "diluted EPS were sentence", "GAAP net income per share") and _disqualified(flat, hit.start(), hit.end()):
                continue
            if "continuing operations" in _sentence_around(flat, hit.start(), hit.end())[1].lower() and how not in ("diluted EPS block, net earnings line",) and "dash" not in how:
                continue        # a continuing-operations figure is not the whole GAAP diluted EPS; the net-earnings line of a diluted block is
            if how not in ("diluted EPS block, net earnings line", "diluted EPS block, attributable line") and _CONTINUING_TABLE.search(flat):
                continue        # the release splits EPS into continuing and discontinued operations: only a stated total counts
            return {"eps": _num(hit.group(1)), "how": how, "evidence": flat[max(0, hit.start() - 20):hit.end() + 40].strip(), "period_end": period_end}
    return None


PE_COMPUTATION_VERSION = 2       # 2 (2026-10-07): quarters and closes restated to the current share basis across recorded splits before any window or history


def split_factor(filed: date, splits: list[tuple[date, float | None]] | None) -> tuple[float, list[str]]:
    """Pure: (the product of the ratios of every recorded split effective after `filed`, the splits' labels). A fact filed before
    a split is on the old share basis; one filed after it is restated by the company. A split with no readable ratio is ignored."""
    factor, notes = 1.0, []
    for day, ratio in splits or []:
        if ratio and filed < day:
            factor *= ratio
            notes.append(f"{ratio:g}:1 split of {day.isoformat()}" if ratio >= 1 else f"1:{1 / ratio:g} reverse split of {day.isoformat()}")
    return factor, notes


def eps_quarters(facts: dict, splits: list[tuple[date, float | None]] | None = None) -> list[dict]:
    """Pure: quarterly GAAP diluted EPS from a companyfacts document, oldest first: the quarterly facts, plus the fourth
    quarter derived as the fiscal year's annual figure less the three quarters inside it. One value per period end, the
    latest filed wins. Every fact is first restated to the current share basis across `splits` [(effective date, new-for-old
    ratio)]: a fact filed before a split is divided by its ratio (BKNG's 10-K of Feb 2026, before the 25:1 split of Apr 6, 2026,
    carries $79.66 that is $3.19 today), so a derived quarter never subtracts restated quarters from an unrestated year.
    Each: {end, start, eps, filed, form, derived, source, diluted_shares, rebased?}."""
    series = (facts.get("facts", {}).get("us-gaap", {}).get("EarningsPerShareDiluted", {}).get("units", {}).get("USD/shares", []))
    quarters: dict[date, dict] = {}
    annual: list[dict] = []
    for e in series:
        try:
            start, end, filed = date.fromisoformat(e["start"]), date.fromisoformat(e["end"]), date.fromisoformat(e["filed"])
        except (KeyError, ValueError):
            continue
        days = (end - start).days
        if abs(float(e["val"])) > EPS_FACT_MAX:
            continue                                            # a dollar amount tagged as a per-share figure; never a quarter, never in a derivation
        factor, notes = split_factor(filed, splits)
        row = {"end": end, "start": start, "eps": round(float(e["val"]) / factor, 4), "filed": filed, "form": e.get("form", ""), "derived": False, "source": "xbrl"}
        if notes:
            row["rebased"] = "; ".join(notes)
        if QUARTER_DAYS[0] <= days <= QUARTER_DAYS[1]:
            if end not in quarters or filed >= quarters[end]["filed"]:
                quarters[end] = row
        elif YEAR_DAYS[0] <= days <= YEAR_DAYS[1]:
            annual.append(row)
    for a in annual:
        if a["end"] in quarters:
            continue
        inside = [q for q in quarters.values() if a["start"] <= q["start"] and q["end"] < a["end"]]
        if len(inside) == 3:
            quarters[a["end"]] = {"end": a["end"], "start": max(q["end"] for q in inside) + timedelta(days=1), "eps": round(a["eps"] - sum(q["eps"] for q in inside), 4),
                                  "filed": a["filed"], "form": a["form"], "derived": True, "source": "xbrl", **({"rebased": a["rebased"]} if a.get("rebased") else {})}
    shares = share_quarters(facts, splits)
    for q in quarters.values():
        q["diluted_shares"] = shares.get(q["end"])
    return sorted(quarters.values(), key=lambda q: q["end"])


def rebase_closes(bars: list[tuple[date, float]], splits: list[tuple[date, float | None]] | None) -> list[tuple[date, float]]:
    """Pure: raw closes restated to the current share basis: a close before a split is divided by its ratio, as the quarters are,
    so a session's P/E is one basis over the same basis."""
    if not splits:
        return bars
    return [(d, c / split_factor(d, splits)[0]) for d, c in bars]


SHARES_TAG = "WeightedAverageNumberOfDilutedSharesOutstanding"
SHARE_JUMP_PCT = 10               # a quarter-to-quarter change in diluted shares above this, with no recorded action, is worth a look
SCALE_FLIP_RATIO = 20             # a swing this large between quarters is a units change in the facts (thousands vs units), never a real count


def share_quarters(facts: dict, splits: list[tuple[date, float | None]] | None = None) -> dict[date, float]:
    """Pure: {quarter end: weighted-average diluted shares} from a companyfacts document (quarterly facts only, latest filed wins),
    restated to the current share basis across `splits` (a count filed before a split is multiplied by its ratio)."""
    series = facts.get("facts", {}).get("us-gaap", {}).get(SHARES_TAG, {}).get("units", {}).get("shares", [])
    out: dict[date, tuple[date, float]] = {}
    for e in series:
        try:
            start, end, filed = date.fromisoformat(e["start"]), date.fromisoformat(e["end"]), date.fromisoformat(e["filed"])
        except (KeyError, ValueError):
            continue
        if QUARTER_DAYS[0] <= (end - start).days <= QUARTER_DAYS[1] and (end not in out or filed >= out[end][0]):
            out[end] = (filed, float(e["val"]) * split_factor(filed, splits)[0])
    return {k: v[1] for k, v in out.items()}


SPLIT_MATCH_TOLERANCE = 0.15     # a jump within this share of a recorded split's ratio (or its inverse) is that split, restated in a later filing
SPLIT_LOOKAHEAD_DAYS = 400       # a split this long after the later quarter can still restate it in the facts filed afterwards


def split_ratio(text_: str | None) -> float | None:
    """Pure: "10:1" -> 10.0 (ten new for one old), "1:5" -> 0.2 (a reverse split), None when unreadable."""
    if not text_ or ":" not in text_:
        return None
    try:
        new, old = (float(x) for x in text_.split(":", 1))
        return new / old if old else None
    except ValueError:
        return None


def share_jumps(quarters: list[dict], action_dates: list[date], splits: list[tuple[date, float | None]] | None = None) -> list[dict]:
    """Pure: consecutive quarters whose diluted share count moved more than SHARE_JUMP_PCT with no recorded action between the
    earlier quarter's start and the later quarter's end, and no recorded split (between them or within SPLIT_LOOKAHEAD_DAYS after,
    since facts filed after a split restate earlier quarters) whose ratio or inverse matches the change. Each: {from_end, to_end,
    from_shares, to_shares, change_pct}."""
    rows = [q for q in quarters if q.get("diluted_shares")]
    splits = splits or []
    out = []
    for a, b in zip(rows, rows[1:]):
        ratio = b["diluted_shares"] / a["diluted_shares"]
        if ratio >= SCALE_FLIP_RATIO or ratio <= 1 / SCALE_FLIP_RATIO:
            continue                 # a reporting-scale change (thousands against units), not a corporate action: left to the facts, not flagged here
        change = (ratio - 1) * 100
        if abs(change) <= SHARE_JUMP_PCT or any(a["start"] <= d <= b["end"] for d in action_dates):
            continue
        explained = False
        for d, r in splits:
            if r and a["start"] <= d <= b["end"] + timedelta(days=SPLIT_LOOKAHEAD_DAYS):
                if abs(ratio / r - 1) <= SPLIT_MATCH_TOLERANCE or abs(ratio * r - 1) <= SPLIT_MATCH_TOLERANCE:
                    explained = True
                    break
        if not explained:
            out.append({"from_end": a["end"], "to_end": b["end"], "from_shares": a["diluted_shares"], "to_shares": b["diluted_shares"], "change_pct": round(change, 1)})
    return out


def trailing_four(quarters: list[dict], as_of: date, known_by: date | None = None) -> list[dict] | None:
    """Pure: the four most recent quarters ending on or before as_of and filed by known_by (point in time), oldest first."""
    known_by = known_by or as_of
    eligible = [q for q in quarters if q["end"] <= as_of and q["filed"] <= known_by]
    return eligible[-4:] if len(eligible) >= 4 else None


def newer_quarter_reported(quarters: list[dict], latest_report: date | None) -> bool:
    """Pure: the company reported a quarter XBRL does not hold yet (the latest report is well after the newest XBRL quarter end
    and after that quarter's filing)."""
    if latest_report is None or not quarters:
        return False
    last = quarters[-1]
    return latest_report > last["filed"] and (latest_report - last["end"]).days > NEWER_REPORT_GRACE_DAYS


def fresh_window(quarters: list[dict], latest_report: date | None, release: dict | None, as_of: date) -> tuple[list[dict] | None, str]:
    """Pure: (the four quarters a shown P/E may rest on, why or why not). The window must include the latest reported quarter:
    XBRL alone when it holds that quarter; three XBRL quarters plus the stored release figure when the release is newer; None
    when the newest quarter cannot be read."""
    if newer_quarter_reported(quarters, latest_report):
        if release is None or release.get("eps") is None:
            return None, f"the {latest_report.isoformat()} report is newer than XBRL (through {quarters[-1]['end'].isoformat()}) and its release EPS is not stored"
        three = [q for q in quarters if q["end"] <= as_of][-3:]
        if len(three) < 3:
            return None, "fewer than three XBRL quarters before the release quarter"
        rel_end = release.get("period_end") or latest_report
        if (rel_end - three[-1]["end"]).days > MAX_QUARTER_GAP_DAYS:
            return None, f"XBRL is more than one quarter behind the latest report (through {three[-1]['end'].isoformat()}, release quarter ended {rel_end.isoformat()})"
        rel = {"end": rel_end, "start": three[-1]["end"] + timedelta(days=1), "eps": float(release["eps"]), "filed": latest_report,
               "form": f"earnings release 8-K {release.get('accession') or ''}".strip(), "derived": False, "source": "release"}
        return three + [rel], "three XBRL quarters plus the release quarter"
    four = trailing_four(quarters, as_of)
    if four is None:
        return None, "fewer than four reported quarters in XBRL"
    return four, "XBRL holds the latest reported quarter"


def pe(price: float | None, four: list[dict] | None) -> float | None:
    if price is None or not four:
        return None
    total = sum(q["eps"] for q in four)
    return round(price / total, 2) if total > 0 else None


def period_label(four: list[dict]) -> str:
    return f"{four[0]['start'].isoformat()} to {four[-1]['end'].isoformat()}"


def pe_history(bars: list[tuple[date, float]], quarters: list[dict], current: float | None) -> dict:
    """Pure: {sessions, excluded, median, share_above, first, last} over the bars: each day's close over the four quarters
    filed by that day; a day with trailing EPS at or below zero or below MIN_EARNINGS_YIELD of the close is excluded."""
    kept: list[float] = []
    excluded = 0
    first = last = None
    for d, close in bars:
        four = trailing_four(quarters, d, d)
        if four is None:
            continue
        total = sum(q["eps"] for q in four)
        if total <= 0 or total < MIN_EARNINGS_YIELD * close:
            excluded += 1
            continue
        kept.append(round(close / total, 2))
        first = first or d
        last = d
    out = {"sessions": len(kept), "excluded": excluded, "median": round(statistics.median(kept), 1) if kept else None, "first": first, "last": last, "share_above": None}
    if kept and current is not None:
        out["share_above"] = round(sum(1 for v in kept if v < current) / len(kept) * 100)
    return out


def release_difference(release_eps: float, xbrl_eps: float) -> tuple[float, bool]:
    """Pure: (difference, flagged) between a stored release figure and the XBRL figure for the same quarter."""
    diff = round(release_eps - xbrl_eps, 4)
    return diff, abs(diff) > RELEASE_TOLERANCE


def snapshot(price: float | None, quarters: list[dict], latest_report: date | None, release: dict | None, as_of: date) -> dict:
    """Pure: what the nightly stores for one ticker: status ok (a P/E), not_meaningful (a fresh window whose trailing EPS is zero
    or negative) or missing (no fresh window), with the reason, the window and its four quarters."""
    four, why = fresh_window(quarters, latest_report, release, as_of)
    base = {"status": "missing", "reason": None, "trailing_eps": None, "pe": None, "window_start": None, "window_end": None, "window_source": None,
            "latest_report": latest_report, "quarters": None}
    if four is None:
        return {**base, "reason": why}
    total = round(sum(q["eps"] for q in four), 4)
    base.update(window_start=four[0]["start"], window_end=four[-1]["end"], window_source=why, trailing_eps=total,
                quarters=[{**q, "end": q["end"].isoformat(), "start": q["start"].isoformat(), "filed": q["filed"].isoformat()} for q in four])
    if price is None:
        return {**base, "reason": "no stored close"}
    if total <= 0:
        return {**base, "status": "not_meaningful", "reason": NOT_MEANINGFUL_REASON}
    return {**base, "status": "ok", "pe": round(price / total, 2)}


def sector_summary(statuses: list[tuple[str, float | None]], active: int) -> dict:
    """Pure: the sector median over tickers with a P/E, shown only when fresh windows (ok or not meaningful) cover at least
    SECTOR_COVERAGE_MIN of the sector's active tickers. `statuses` are (status, pe) per ticker with a snapshot."""
    fresh = sum(1 for s, _ in statuses if s in ("ok", "not_meaningful", "not_meaningful_yet"))   # a fresh window, with or without a usable P/E
    values = sorted(p for s, p in statuses if s == "ok" and p is not None)
    coverage = fresh / active if active else 0.0
    shown = active > 0 and coverage >= SECTOR_COVERAGE_MIN and bool(values)
    reason = None if shown else (f"only {fresh} of {active} active tickers have a fresh P/E window ({coverage:.0%}; {SECTOR_COVERAGE_MIN:.0%} needed)" if active else "no active tickers")
    return {"median_pe": round(statistics.median(values), 2) if values else None, "with_pe": len(values), "fresh": fresh, "active": active, "shown": shown, "reason": reason}


def needs_refresh(stored_quarters: list[dict], latest_report: date | None, today: date) -> bool:
    """Pure: re-read XBRL when nothing is stored, or when a report in the last REFRESH_AFTER_REPORT_DAYS is newer than the
    stored quarters hold (its 10-Q or 10-K may have landed since the last read)."""
    if not stored_quarters:
        return True
    if latest_report is None or (today - latest_report).days > REFRESH_AFTER_REPORT_DAYS:
        return False
    return newer_quarter_reported(stored_quarters, latest_report)


def action_reason(action: dict) -> str:
    """Pure: "Spun off <name> on <date>; four full quarters after it are needed". `action` is {kind, date, name}; a missing
    name reads "a business"."""
    from app.services.briefing import fmt_date
    verb = ACTION_VERBS.get(action["kind"], "Had a corporate action ({kind}) on {date}").format(name=action.get("name") or "a business", date=fmt_date(action["date"]), kind=action["kind"])
    return f"{verb}; {CLEAN_QUARTERS_NEEDED} full quarters after it are needed"


def actions_in_window(actions: list[dict], start: date, as_of: date) -> list[dict]:
    """Pure: the recorded corporate actions dated from the window's first day through the price date. An action after the
    window's last quarter but before the price still breaks the comparison: today's post-action price over pre-action earnings."""
    return [a for a in actions if start <= a["date"] <= as_of]


def snapshot_with_actions(price: float | None, quarters: list[dict], latest_report: date | None, release: dict | None, as_of: date, actions: list[dict]) -> dict:
    """Pure: snapshot(), then a window holding a spin-off, merger, share-exchange acquisition or rename-merge becomes
    not_meaningful_yet with the action's reason: four clean quarters must exist before a P/E."""
    snap = snapshot(price, quarters, latest_report, release, as_of)
    if snap["window_start"] and snap["window_end"]:
        inside = actions_in_window(actions, snap["window_start"], as_of)
        if inside:
            return {**snap, "status": "not_meaningful_yet", "pe": None, "reason": action_reason(max(inside, key=lambda a: a["date"]))}
    return snap


def pe_history_clean(bars: list[tuple[date, float]], quarters: list[dict], current: float | None, action_dates: list[date]) -> dict:
    """Pure: pe_history, with sessions whose four-quarter window holds a corporate action excluded as well (and counted)."""
    kept: list[float] = []
    excluded = 0
    first = last = None
    for d, close in bars:
        four = trailing_four(quarters, d, d)
        if four is None:
            continue
        total = sum(q["eps"] for q in four)
        if total <= 0 or total < MIN_EARNINGS_YIELD * close or any(four[0]["start"] <= a <= d for a in action_dates):
            excluded += 1
            continue
        kept.append(round(close / total, 2))
        first = first or d
        last = d
    out = {"sessions": len(kept), "excluded": excluded, "median": round(statistics.median(kept), 1) if kept else None, "first": first, "last": last, "share_above": None}
    if kept and current is not None:
        out["share_above"] = round(sum(1 for v in kept if v < current) / len(kept) * 100)
    return out


EPS_MAX_SHARE_OF_PRICE = 0.25       # a quarter's EPS above this share of the stock's close on the report date is not a per-share figure
EPS_MAX_ADJUSTED_RATIO = 5.0        # a GAAP figure more than this many times (or under a fifth of) the stored adjusted EPS for the same report, both positive, is refused
EPS_MAX_YEAR_RATIO = 10.0           # a quarter's EPS more than this many times (or under a tenth of) the same quarter a year earlier, both positive, is noted for the digest


def implausible(eps: float, close: float | None, adjusted_eps: float | None) -> str | None:
    """Pure: why a parsed quarterly GAAP EPS cannot be right, or None; a refusal (the figure is recorded as unread). Against the
    close on the report date (a per-share figure is a fraction of the price) and against the stored adjusted EPS for the same
    report (events.eps_actual) when both are positive: GAAP and adjusted differ by charges, never by a factor of five."""
    if close is not None and close > 0 and abs(eps) > EPS_MAX_SHARE_OF_PRICE * close:
        return f"{eps:+.2f} is more than {EPS_MAX_SHARE_OF_PRICE:.0%} of the {close:.2f} close on the report date"
    if adjusted_eps is not None and eps > 0 and adjusted_eps > 0:
        ratio = eps / adjusted_eps
        if ratio > EPS_MAX_ADJUSTED_RATIO or ratio < 1 / EPS_MAX_ADJUSTED_RATIO:
            return f"{eps:+.2f} is {ratio:.1f}x the stored adjusted EPS for the report ({adjusted_eps:+.2f})"
    return None


def year_over_year_note(eps: float, prior_year_eps: float | None) -> str | None:
    """Pure: a note when the figure is more than EPS_MAX_YEAR_RATIO times (or under a tenth of) the same quarter a year earlier,
    both positive. A warning for the digest only: the figure is stored (Micron's 32.87 against 2.83 was real)."""
    if prior_year_eps is not None and eps > 0 and prior_year_eps > 0:
        ratio = eps / prior_year_eps
        if ratio > EPS_MAX_YEAR_RATIO or ratio < 1 / EPS_MAX_YEAR_RATIO:
            return f"{eps:+.2f} is {ratio:.1f}x the same quarter a year earlier ({prior_year_eps:+.2f})"
    return None
