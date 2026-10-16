"""FFO per share for REITs (2026-10-15). A REIT's GAAP EPS swings with depreciation and property sales, so a REIT (GICS Real Estate,
a REIT sub-industry) shows FFO per diluted share against the same quarter a year earlier instead of EPS.

The figure is read from the quarter's earnings release (the Item 2.02 8-K's exhibit) by two readers that must agree to the cent, as
release EPS is (services/release_reader): the pattern parser (parse_release_ffo) and the model (FFO_PROMPT, its quote checked verbatim
in the exhibit by verify_ffo_quote). Nareit-defined FFO only: never core, normalized, adjusted or AFFO.

Each agreed figure is cross-checked against FFO computed from XBRL where the tags exist (xbrl_ffo_quarters: net income to common
plus depreciation and amortization and impairments of real estate, less gains on property sales, over weighted diluted shares). A gap over FFO_GAP_PCT holds the
figure (state "held") and the page says so; with no XBRL figure the agreed reading stands, and its reason says the cross-check was
unavailable. Rows live in ffo_quarters (scripts/seed_release_ffo writes them).
"""
from __future__ import annotations

import json
import re
from datetime import date

from sqlalchemy import text

from app.services import release_reader as R
from app.services.valuation import QUARTER_DAYS

FFO_COMPUTATION_VERSION = 1
FFO_GAP_PCT = 5.0                   # an XBRL cross-check further off than this holds the release figure
MEASURE = "FFO per share"
HELD_LINE = "FFO per share for this quarter is held because the release's figure and the one computed from the company's filings differ by {gap:.1f}%."
UNREAD_LINE = "FFO per share for this quarter is held because the two readings of its earnings release do not agree."
DERIVED_NOTE = " (the release's Nareit FFO over its diluted shares)"   # after a figure the release states only in total (AMT, PLD)
NONE_REASON = "the release and its exhibits mention no FFO"        # a REIT whose every report says this keeps EPS (WY)
MODEL_WINDOW = 1500                 # characters kept either side of each FFO mention for the model (the verbatim check reads the whole exhibit)
MODEL_MAX_CHARS = 40_000

_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)   # SPG's tables put a zero-width space between every cell
_QUOTES = str.maketrans({"\u201c": '"', "\u201d": '"', "\u2018": "'", "\u2019": "'"})
_AMT = r"(\(?\d{1,3}\.\d{2}\)?)"
_FFO = (r"(?<![A-Za-z])(?:(?:Nareit|NAREIT)[- ](?:defined\s+)?)?(?:FFO|funds\s+from\s+operations)"
        r"(?:\s*\(\s*(?:FFO|Nareit|NAREIT)\s*\))?")
_PER_SHARE = r"\s+per\s+(?:diluted\s+)?(?:common\s+)?(?:share|unit)"
_NOT_NAREIT = re.compile(r"\bcore\b|normali[sz]ed|adjusted|\bAFFO\b|as\s+adjusted|comparable|recurring|modified|real\s+estate\s+(?:FFO|funds)|"
                         r"\badjustments?\b|joint\s+venture|noncontrolling|payout|excluding|growth|reconciliation|net\s+(?:income|earnings)", re.I)
_NOT_QUARTER = re.compile(r"full[- ]year|year[- ]to[- ]date|twelve\s+months|six\s+months|nine\s+months|guidance|outlook|expects?|projected|"
                          r"range\s+of|\bfor\s+(?:the\s+)?(?:year|20\d\d)\b", re.I)
_GUIDANCE_HEAD = re.compile(r"guidance|outlook|projected|expected\s+to\s+range|for\s+the\s+year\s+ending|"
                            r"(?:results|highlights)\s+for\s+the\s+(?:six|nine|twelve)\s+months|year[- ]to[- ]date\s+results", re.I)   # SPG, EXR
_QUARTER_HEAD = re.compile(r"three\s+months\s+ended|(?:results|highlights)\s+for\s+the\s+(?:quarter|three\s+months)|quarter\s+ended|for\s+the\s+(?:first|second|third|fourth)\s+quarter|\b[1-4]Q\s?\d{2}\b|\bQ[1-4]\s+20\d\d\b", re.I)
GUIDANCE_LOOKBACK = 700             # characters behind a figure searched for a guidance or outlook heading
_PATTERNS = [
    # "FFO of $1.06 per diluted share", "Nareit FFO was $1.13 per share"
    ("prose statement", re.compile(_FFO + r"[^.$]{0,120}?\$\s?" + _AMT + _PER_SHARE, re.S | re.I)),
    # "Funds From Operations ("FFO") was $1.185 billion, or $3.12 per diluted share"
    ("prose statement", re.compile(_FFO + r"[^$.;]{0,80}?\$\s?[\d.,]+\s*(?:million|billion|thousand)?,?\s+or\s+\$\s?" + _AMT + _PER_SHARE, re.S | re.I)),
    # "FFO per diluted share was $1.06", "Funds from operations (FFO) per Share - diluted $ 2.10"
    ("per-share statement", re.compile(_FFO + _PER_SHARE.replace("(?:share|unit)", "share") + r"[^.$]{0,60}?\$\s?" + _AMT, re.S | re.I)),
    # a table row: "FFO per diluted share 7.03 6.95", "Funds from operations per share attributable to ... – diluted 2.44 3.73"
    ("table row", re.compile(_FFO + r"[^.$\d]{0,40}?\bper\b[^.$\d]{0,40}?\bshare\b[^$\d]{0,80}?(?:\bdiluted\b[^$\d]{0,10})?\$?\s?" + _AMT, re.S | re.I)),
    # a total then its per-share figure: "FFO $ 298,556 $ 2.81 $ 339,175 $ 3.14"
    ("table row", re.compile(r"(?<![A-Za-z])(?:(?:Nareit|NAREIT)\s+)?FFO(?:\s*\((?:Nareit|NAREIT)\))?\s+\$\s?\d{1,3}(?:,\d{3})+\s+\$\s?" + _AMT, re.I)),
    # a row of per-share figures under a per-share heading: "NAREIT FFO $ 1.56 $ 1.24", "FFO (Nareit) $0.76 $0.89", "FFO $ 1.07 $ 0.98"
    ("table row", re.compile(r"(?<![A-Za-z])(?:(?:Nareit|NAREIT)\s+)?(?:FFO|funds\s+from\s+operations)(?:\s*\((?:Nareit|NAREIT|from\s+above)\))?\s+\$\s?" + _AMT
                             + r"\s+\$?\s?\(?\d{1,3}\.\d{2}", re.I)),
]
# the derived reading, for a release that states Nareit FFO only in total (AMT, PLD): the total over the quarter's diluted shares
_TOTAL = re.compile(r"(?<![A-Za-z])((?:Nareit|NAREIT)(?:[- ]defined)?\s+(?:FFO|funds\s+from\s+operations)(?:\s*\(FFO\))?\s+attributable\s+to\s+[^$\d]{0,80}?)"
                    r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d+)?)(?![\d,])(?!\s*(?:to|–|-)\s*\$?\s?\d)", re.I)
_SHARES = re.compile(r"((?:divided\s+by\s+)?(?:the\s+)?(?:diluted\s+)?weighted[- ]average\s+(?:number\s+of\s+)?(?:diluted\s+)?(?:common\s+)?(?:diluted\s+)?"
                     r"shares(?:\s+and\s+units)?(?:\s+of\s+common\s+stock)?\s+outstanding[^$\d]{0,40}?)(\d{1,3}(?:,\d{3})+(?:\.\d+)?)(?![\d,])(?!\s*(?:to|–|-)\s*\d)", re.I)
_UNIT = re.compile(r"in\s+(thousands|millions)", re.I)
UNIT_SCALE = {"thousands": 1e3, "millions": 1e6, None: 1.0}
UNIT_LOOKBACK = 3000                # characters behind a total or share row searched for its table's "(in thousands)" heading
DERIVED_BAND = (0.05, 50.0)         # a derived figure outside this is a unit misread, never shown
DERIVED_HOW = "Nareit FFO total over diluted shares"
REIT_SECTOR = "Real Estate"


def flatten(exhibit: str) -> str:
    """Pure: one line of text, zero-width characters dropped and footnote markers ("(1)", "(c)(d)") after a label removed."""
    flat = re.sub(r"\s+", " ", (exhibit or "").translate(_ZERO_WIDTH)).strip()
    return re.sub(r"(?<=[A-Za-z)*])\s?\((?:\d{1,2}|[a-z])\)(?=[\s($])", "", flat)


def is_reit(sector: str | None, industry: str | None) -> bool:
    """Pure: GICS Real Estate with a REIT sub-industry ("Retail REITs", "REIT - Residential"); real estate services are not REITs."""
    return (sector or "") == REIT_SECTOR and "REIT" in (industry or "")


def _amount(s: str) -> float:
    neg = s.startswith("(") and s.endswith(")")
    v = float(s.strip("()"))
    return -v if neg else v


def _in_guidance(flat: str, at: int) -> bool:
    """Pure: the figure sits under a guidance or outlook heading, with no quarter heading after it."""
    back = flat[max(0, at - GUIDANCE_LOOKBACK):at]
    g = [m.end() for m in _GUIDANCE_HEAD.finditer(back)]
    q = [m.end() for m in _QUARTER_HEAD.finditer(back)]
    return bool(g) and (not q or g[-1] > q[-1])


def _unit(flat: str, at: int, label: str = "") -> str | None:
    m = _UNIT.search(label) or (list(_UNIT.finditer(flat[max(0, at - UNIT_LOOKBACK):at])) or [None])[-1]
    return m.group(1).lower() if m else None


def derived_ffo(flat: str) -> dict | None:
    """Pure: Nareit FFO per diluted share from the release's quarter total and diluted share count, when it states no per-share figure:
    the first Nareit FFO total row (never core, normalized, adjusted or AFFO; never a range), over the first diluted weighted share
    row after it (else before it), each scaled by its table's "(in thousands)" or "(in millions)". None outside DERIVED_BAND."""
    totals = [m for m in _TOTAL.finditer(flat) if not _NOT_NAREIT.search(m.group(1)) and not _in_guidance(flat, m.start())]
    if not totals:
        return None
    first = float(totals[0].group(2).replace(",", ""))     # AMT states $ 1,249 in its highlights and $ 1,249.3 in its reconciliation:
    same = [m for m in totals if abs(float(m.group(2).replace(",", "")) - first) <= max(1.0, first * 0.001)]
    total = max(same, key=lambda m: (_unit(flat, m.start()) is not None, len(m.group(2))))   # the one under a stated unit, most precise
    rows = [m for m in _SHARES.finditer(flat) if re.search(r"diluted", m.group(1), re.I) and not re.search(r"basic", m.group(1), re.I)
            and not _in_guidance(flat, m.start())]
    shares = next((m for m in rows if m.start() > total.start()), rows[0] if rows else None)
    if shares is None:
        return None
    t_unit, s_unit = _unit(flat, total.start()), _unit(flat, shares.start(), shares.group(1))
    t, s = float(total.group(2).replace(",", "")) * UNIT_SCALE[t_unit], float(shares.group(2).replace(",", "")) * UNIT_SCALE[s_unit]
    v = t / s if s else 0
    if not DERIVED_BAND[0] <= v <= DERIVED_BAND[1]:
        return None
    return {"ffo": round(v, 2), "how": DERIVED_HOW, "total": t, "shares": s,
            "evidence": f"{flat[total.start():total.end()].strip()} ({t_unit or 'dollars'}) over {flat[shares.start():shares.end()].strip()} ({s_unit or 'shares'})"}


def parse_release_ffo(exhibit: str) -> dict | None:
    """Pure: the quarter's Nareit FFO per diluted share as the release states it in prose or a labelled row: {ffo, how, evidence}, the
    first statement that is neither core/normalized/adjusted/AFFO/Real Estate FFO, a basic-only row, nor a full-year, year-to-date or
    guidance figure; with none, the derived reading (derived_ffo); None when neither."""
    flat = flatten(exhibit)
    hits = []
    for i, (how, pat) in enumerate(_PATTERNS):
        for m in pat.finditer(flat):
            near = flat[max(0, m.start() - 25):m.start()]        # "Core ", "Normalized ", "Basic " directly in front of the label
            before = flat[max(0, m.start() - 150):m.start()]     # a guidance or full-year sentence leading up to it
            span = flat[m.start():m.end()]
            if _NOT_NAREIT.search(near + span) or _NOT_QUARTER.search(before + span) or _in_guidance(flat, m.start()):
                continue
            if re.search(r"compared\s+(?:to|with)|versus|\bvs\b|prior[- ]year", re.split(r"[.•;]\s", near)[-1], re.I):
                continue                                         # BXP: "..., compared to FFO of $271.7 million, or $1.71 per diluted share"
            if re.search(r"\bbasic\b", near, re.I) and not re.search(r"\bdiluted\b", near + span, re.I):
                continue                                         # EQIX: "Basic FFO per share $ 8.66" before "Diluted FFO per share $ 8.61"
            hits.append((m.start(), i, how, m))
    if not hits:
        return derived_ffo(flat)
    _, _, how, m = min(hits, key=lambda h: (h[0], h[1]))
    # a row that states basic first and diluted after ("FFO per share: Basic $7.04 Diluted $7.03") is read at its diluted figure
    dil = re.search(r"\bdiluted\b[^$\d]{0,15}\$?\s?(\(?\d{1,3}\.\d{2}\)?)", flat[m.start():m.start() + 160], re.I)
    if dil and re.search(r"\bbasic\b", flat[m.start():m.start() + dil.start()], re.I):
        return {"ffo": _amount(dil.group(1)), "how": "table row, diluted", "evidence": flat[m.start():m.start() + dil.end() + 20].strip()}
    return {"ffo": _amount(m.group(m.lastindex)), "how": how, "evidence": flat[m.start():m.end() + 40].strip()}


def parse_release_ffo_all(exhibits: list[tuple[str, str]]) -> tuple[dict | None, tuple[str, str] | None]:
    """Pure: the first exhibit, in candidate order, with a stated per-share figure, else the first with a derived one: (reading, exhibit)."""
    derived = None
    supplement = re.compile(r"supplement|presentation|slides|fact\s*sheet", re.I)
    exhibits = sorted(exhibits, key=lambda d: 1 if supplement.search(d[0]) else 0)   # by name (CCI's "q22026supplement.htm"): the release's
    for ex in exhibits:                                   # own row leads with the quarter; its supplement's eight-quarter row leads with the oldest
        hit = parse_release_ffo(ex[1])
        if hit and hit["how"] != DERIVED_HOW:
            return hit, ex
        if hit and derived is None:
            derived = (hit, ex)
    return derived or (None, None)


FFO_PROMPT = """You are reading the text of a REIT's earnings release and its supplement, filed with the SEC (8-K exhibits, each headed
[EXHIBIT name]). Answer with the JSON object alone, first and with no prose before or after it:
{{"ffo": <number or null>, "period_end": "<YYYY-MM-DD or null>", "quote": "<the exact sentence or table row, copied verbatim, that states the figure>",
  "total": <number or null>, "total_unit": "<thousands, millions or dollars>", "total_quote": "<the exact table row stating the total>",
  "shares": <number or null>, "shares_unit": "<thousands, millions or shares>", "shares_quote": "<the exact table row stating the diluted shares>"}}

The figure wanted is FFO (funds from operations, as Nareit defines it) per diluted share for the most recent quarter the release reports:
- the quarter, never the full year, year to date, six or twelve months, or guidance and outlook;
- Nareit FFO (sometimes "FFO attributable to common stockholders", "FFO (Nareit)", "NAREIT defined FFO"), never core FFO, normalized FFO,
  adjusted FFO, AFFO, FFO as modified, or a company measure such as "Real Estate FFO";
- per diluted share (or per diluted share and unit), never the basic figure when a diluted one is stated;
- a negative figure written "$(0.35)" is -0.35.
If the release states Nareit FFO per diluted share, return it in "ffo" with its quote and leave total and shares null.
Only if it states no Nareit FFO per share at all, but states the quarter's Nareit FFO in total and the quarter's weighted average diluted
shares, return ffo null and the two figures exactly as printed (total, shares), each with its table's unit and its row quoted verbatim.
Copy every quote exactly as the text reads it; never paraphrase. If the release states none of these, return nulls.
The report date is {report_date}.

TEXT:
{text}"""


_PER_SHARE_MENTION = re.compile(r"(?:FFO|funds\s+from\s+operations)[^.]{0,100}?per\s+(?:diluted\s+)?(?:common\s+)?share|"
                                r"per\s+(?:diluted\s+)?share\s+(?:data|amounts)", re.I)


def model_text(exhibits: list[tuple[str, str]]) -> str:
    """Pure: each exhibit's FFO passages (MODEL_WINDOW either side of each mention, merged), headed by its name, at most MODEL_MAX_CHARS;
    an exhibit that mentions FFO nowhere is left out unless none does."""
    parts = []
    for name, ex in exhibits:
        flat = flatten(ex)
        spans = []
        for m in re.finditer(r"FFO|[Ff]unds [Ff]rom [Oo]perations|[Ww]eighted[- ]average", flat):
            a, b = max(0, m.start() - MODEL_WINDOW), min(len(flat), m.end() + MODEL_WINDOW)
            if spans and a <= spans[-1][1]:
                spans[-1] = (spans[-1][0], b)
            else:
                spans.append((a, b))
        if spans and re.search(r"FFO|[Ff]unds [Ff]rom [Oo]perations", flat):
            per_share = lambda ab: len(_PER_SHARE_MENTION.findall(flat[ab[0]:ab[1]]))
            ranked = sorted(spans, key=lambda ab: -per_share(ab))                 # stable: equal passages keep the exhibit's order
            parts.append(f"[EXHIBIT {name}] " + " ... ".join(flat[a:b] for a, b in ranked))
    if not parts and exhibits:
        parts = [f"[EXHIBIT {exhibits[0][0]}] " + flatten(exhibits[0][1])]
    return "\n\n".join(parts)[:MODEL_MAX_CHARS]


def parse_ffo_json(content: str) -> dict | None:
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    for k in ("ffo", "total", "shares"):
        v = d.get(k)
        if isinstance(v, str):                       # the model sometimes answers a figure as printed: "1,278.9", "$(0.35)"
            v = v.replace(",", "").replace("$", "").strip()
            v = f"-{v[1:-1]}" if v.startswith("(") and v.endswith(")") else v
        try:
            d[k] = float(v) if v not in (None, "") else None
        except (TypeError, ValueError):
            d[k] = None
    return d


def _vnorm(t: str | None) -> str:
    """The verbatim check's normalization: release_reader's (whitespace, dollar signs, commas, zero-width, case) plus curly quotes."""
    return R._norm((t or "").translate(_QUOTES))


def _verbatim(exhibit: str, quote: str) -> bool:
    """Pure: the quote stands, word for word, in the exhibit as filed or as the model read it (flatten: footnote markers and zero-width
    characters removed)."""
    q = _vnorm(quote)
    return bool(q) and (q in _vnorm(exhibit) or q in _vnorm(flatten(exhibit)))


_LABEL_NORM = re.compile(r"(?:core|normali[sz]ed|adjusted|comparable|modified)?(?:affo|ffo|fundsfromoperations)|net(?:income|earnings|loss)|earningspershare|eps")


def row_under_ffo(exhibit: str, quote: str) -> bool:
    """Pure: a table row with no label of its own ("Diluted $ 1.07 $ 1.06") sits, at one of its occurrences in the exhibit, under a Nareit FFO
    label: the nearest result label within 200 characters above it names FFO and no core, normalized, adjusted, modified or AFFO
    figure. Read on the normalized text (release_reader._norm: no spaces, no dollar signs, lower case)."""
    flat, q = _vnorm(exhibit), _vnorm(quote)
    if not q:
        return False
    at = flat.find(q)
    while at >= 0:                       # the same row may repeat under another label (O's Normalized FFO equals its FFO some quarters):
        labels = list(_LABEL_NORM.finditer(flat[max(0, at - 200):at]))     # the row's text, so its figure, is identical in each
        if labels and labels[-1].group(0) in ("ffo", "fundsfromoperations"):
            return True
        at = flat.find(q, at + 1)
    return False


def verify_ffo_quote(exhibit: str, quote: str | None, ffo: float | None) -> list[str]:
    """Pure: why the model's quote cannot be trusted: not verbatim in the exhibit, without the figure, naming no FFO, or naming a
    core, normalized, adjusted, AFFO or Real Estate FFO figure or a full-year one. Empty when it holds."""
    if ffo is None or not quote:
        return ["model read nothing"]
    problems = []
    if not _verbatim(exhibit, quote):
        problems.append("the quote is not verbatim in the exhibit")
    if f"{abs(ffo):.2f}" not in quote.translate(_ZERO_WIDTH):
        problems.append("the quote does not contain the figure")
    if not re.search(r"FFO|funds\s+from\s+operations", quote, re.I) and not row_under_ffo(exhibit, quote):
        problems.append("the quote names no FFO, and the label above its row is not Nareit FFO")
    if _NOT_NAREIT.search(quote):
        problems.append("the quote names a core, normalized, adjusted or AFFO figure")
    if _NOT_QUARTER.search(quote):
        problems.append("the quote names a full-year, year-to-date or guidance figure")
    return problems


def _printed(v: float) -> str:
    return f"{v:.6f}".rstrip("0").rstrip(".")


def model_derived(exhibit: str, model: dict) -> tuple[float | None, list[str]]:
    """Pure: the model's derived figure (its total over its diluted shares, each at its stated unit) and why it cannot be trusted."""
    t, s = model.get("total"), model.get("shares")
    if t is None or s is None:
        return None, ["model read nothing"]
    problems = []
    for q, v, what in ((model.get("total_quote"), t, "total"), (model.get("shares_quote"), s, "shares")):
        if not q or not _verbatim(exhibit, q):
            problems.append(f"the {what} quote is not verbatim in the exhibit")
        elif _printed(v) not in _vnorm(q):
            problems.append(f"the {what} quote does not contain the figure")
    if not re.search(r"FFO|funds\s+from\s+operations", model.get("total_quote") or "", re.I) or _NOT_NAREIT.search(model.get("total_quote") or ""):
        problems.append("the total quote names no Nareit FFO")
    if not re.search(r"diluted", model.get("shares_quote") or "", re.I):
        problems.append("the shares quote names no diluted shares")
    scale = lambda u: UNIT_SCALE.get((u or "").lower() if (u or "").lower() in ("thousands", "millions") else None)
    v = t * scale(model.get("total_unit")) / (s * scale(model.get("shares_unit")))
    if not DERIVED_BAND[0] <= v <= DERIVED_BAND[1]:
        problems.append("the derived figure is outside any plausible FFO per share")
    return round(v, 2), problems


def quarter_end_fallback(exhibits: list[tuple[str, str]], report_date: date, model_period_end: str | None) -> date | None:
    """Pure: when the release's period-end detector finds none (CCI's Q4 header "Three Months Ended For the Twelve Months Ended ... December
    31, 2025"), the latest calendar quarter end before the report, only if the release prints that date and the model names the same."""
    y, m = report_date.year, report_date.month
    ends = [date(y - 1, 12, 31), date(y, 3, 31), date(y, 6, 30), date(y, 9, 30)]
    end = max(e for e in ends if e < report_date)
    printed = f"{end:%B} {end.day}, {end.year}"
    if model_period_end != end.isoformat() or not any(printed in flatten(t) for _, t in exhibits):
        return None
    return end


def decide_ffo(pattern: dict | None, model: dict | None, exhibit: str) -> tuple[float | None, str]:
    """Pure: (the agreed figure, the note): stored only when the pattern parser and the verified model reading agree to the cent, a stated
    figure against a stated figure, a derived one (Nareit FFO total over diluted shares) against a derived one."""
    p = pattern["ffo"] if pattern else None
    p_text = f"pattern {p:.2f} ({pattern['how']})" if pattern else "pattern read nothing"
    if model is None:
        return None, f"{p_text}; no model reading"
    derived = bool(pattern) and pattern["how"] == DERIVED_HOW
    if model.get("ffo") is None and model.get("total") is not None:
        m, problems = model_derived(exhibit, model)
        m_text = f"model {m:.2f} ({DERIVED_HOW})" if m is not None else "model read nothing"
        if problems and m is not None:
            return None, f"{p_text}; {m_text}; model rows rejected: {'; '.join(problems)}"
        if derived and m is not None and round(p, 2) == round(m, 2):
            return p, f"both readers {p:.2f} ({DERIVED_HOW})"
        return None, f"{p_text}; {m_text}; readers disagree"
    m = model.get("ffo")
    problems = verify_ffo_quote(exhibit, model.get("quote"), m)
    m_text = f"model {m:.2f}" if m is not None else "model read nothing"
    if problems and m is not None:
        return None, f"{p_text}; {m_text}; model quote rejected: {'; '.join(problems)}"
    if p is not None and m is not None and not derived and round(p, 2) == round(m, 2):
        return p, f"both readers {p:.2f}"
    return None, f"{p_text}; {m_text}; readers disagree"


MODEL_ATTEMPTS = 2                  # a dropped connection is retried once
MODEL_MAX_TOKENS = 1200             # the derived answer's three quoted rows; at 400 the model's working ran out before its JSON (AMT, PLD)


async def model_read(client, exhibits: list[tuple[str, str]], report_date: date | None) -> dict:
    prompt = FFO_PROMPT.format(report_date=report_date.isoformat() if report_date else "unknown", text=model_text(exhibits))
    for attempt in range(MODEL_ATTEMPTS):
        try:
            out = await client.read_release_eps(prompt, max_tokens=MODEL_MAX_TOKENS)
            break
        except Exception:
            if attempt == MODEL_ATTEMPTS - 1:
                raise
    parsed = parse_ffo_json(out["content"]) or {"ffo": None, "period_end": None, "quote": None, "total": None, "shares": None}
    parsed["raw"] = (out["content"] or "")[:400]          # printed by the seed when the model reads nothing
    from app.services.research_cost import estimate_cost_usd
    return {**parsed, "cost_usd": estimate_cost_usd(out["model_used"], out["input_tokens"], out["output_tokens"])}


# ── the XBRL cross-check ──────────────────────────────────────────────────────

NET_INCOME_TAGS = ("NetIncomeLossAvailableToCommonStockholdersDiluted", "NetIncomeLossAvailableToCommonStockholdersBasic", "NetIncomeLoss")
DA_TAGS = ("RealEstateDepreciationAndAmortization", "DepreciationAndAmortizationRealEstate", "DepreciationAndAmortization",
           "DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet")
IMPAIRMENT_TAGS = ("ImpairmentOfRealEstate", "RealEstateImpairmentCharges", "ImpairmentOfLongLivedAssetsHeldForUse")   # Nareit FFO adds them back
GAIN_TAGS = ("GainsLossesOnSalesOfInvestmentRealEstate", "GainLossOnSaleOfProperties", "GainLossOnSaleOfPropertiesBeforeApplicableIncomeTaxes",
             "GainLossOnDispositionOfProperty", "GainLossOnSaleOfRealEstateInvestmentProperty")
SHARES_TAG = "WeightedAverageNumberOfDilutedSharesOutstanding"


def _quarterly(facts: dict, tag: str, unit: str) -> dict[date, float]:
    """Pure: {quarter end: value} for a duration tag's three-month facts, the latest filed winning."""
    series = facts.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get(unit, [])
    out: dict[date, tuple[date, float]] = {}
    for e in series:
        try:
            start, end, filed = date.fromisoformat(e["start"]), date.fromisoformat(e["end"]), date.fromisoformat(e["filed"])
        except (KeyError, ValueError):
            continue
        if QUARTER_DAYS[0] <= (end - start).days <= QUARTER_DAYS[1] and (end not in out or filed >= out[end][0]):
            out[end] = (filed, float(e["val"]))
    return {k: v[1] for k, v in out.items()}


def _first(facts: dict, tags: tuple[str, ...], unit: str) -> tuple[str | None, dict[date, float]]:
    for t in tags:
        got = _quarterly(facts, t, unit)
        if got:
            return t, got
    return None, {}


def xbrl_ffo_quarters(facts: dict) -> dict[date, dict]:
    """Pure: {quarter end: {ffo_per_share, net_income, da, gains, shares, tags}} for each quarter where net income, depreciation and
    amortization and diluted shares all exist as three-month facts (gains count as zero when the company tags none that quarter)."""
    ni_tag, ni = _first(facts, NET_INCOME_TAGS, "USD")
    da_tag, da = _first(facts, DA_TAGS, "USD")
    g_tag, gains = _first(facts, GAIN_TAGS, "USD")
    i_tag, impair = _first(facts, IMPAIRMENT_TAGS, "USD")
    shares = _quarterly(facts, SHARES_TAG, "shares")
    out = {}
    for end in sorted(set(ni) & set(da) & set(shares)):
        if not shares[end]:
            continue
        g, imp = gains.get(end, 0.0), impair.get(end, 0.0)
        out[end] = {"ffo_per_share": round((ni[end] + da[end] + imp - g) / shares[end], 4), "net_income": ni[end], "da": da[end], "gains": g,
                    "impairments": imp, "shares": shares[end],
                    "tags": [t for t in (ni_tag, da_tag, g_tag if end in gains else None, i_tag if end in impair else None) if t]}
    return out


def cross_check(ffo: float, xbrl: dict | None) -> tuple[str, float | None, str]:
    """Pure: (state, gap in percent, reason) for an agreed release figure against the XBRL computation."""
    if not xbrl:
        return "ok", None, "both readers agree; XBRL cross-check unavailable (the filing tags no quarterly net income, depreciation and diluted shares for this quarter)"
    x = xbrl["ffo_per_share"]
    if not x:
        return "ok", None, "both readers agree; XBRL cross-check unavailable (zero computed)"
    gap = abs(ffo / x - 1) * 100
    if gap > FFO_GAP_PCT:
        return "held", round(gap, 2), f"release {ffo:.2f} against {x:.2f} from XBRL ({', '.join(xbrl['tags'])}), {gap:.1f}% apart, over {FFO_GAP_PCT:.0f}%"
    return "ok", round(gap, 2), f"both readers agree; XBRL {x:.2f} within {gap:.1f}%"


# ── reading what is stored ────────────────────────────────────────────────────

async def load_ffo(db, symbol: str) -> dict:
    """What the page reads from ffo_quarters: {shown: [(period_end, ffo)] ascending, derived: {period_end} read as Nareit FFO over diluted
    shares, held: {period_end: the line saying why}, reports_ffo: whether any quarter is shown or held (WY's releases name no FFO, so it
    keeps EPS, as does a REIT none of whose quarters has been read yet)}."""
    rows = (await db.execute(text("""SELECT period_end, ffo_per_share, state, xbrl_gap_pct, how FROM ffo_quarters
        WHERE symbol = :s ORDER BY period_end"""), {"s": symbol})).all()
    held = {r.period_end: HELD_LINE.format(gap=float(r.xbrl_gap_pct or 0)) for r in rows if r.state == "held"}
    held |= {r.period_end: UNREAD_LINE for r in rows if r.state == "unread"}
    return {"shown": [(r.period_end, float(r.ffo_per_share)) for r in rows if r.state == "ok"],
            "derived": {r.period_end for r in rows if r.state == "ok" and r.how == DERIVED_HOW},
            "held": held, "reports_ffo": any(r.state in ("ok", "held") for r in rows)}


async def ticker_is_reit(db, symbol: str) -> bool:
    row = (await db.execute(text("SELECT sector, industry FROM tickers WHERE symbol = :s"), {"s": symbol})).first()
    return bool(row) and is_reit(row.sector, row.industry)
