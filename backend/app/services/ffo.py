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
MODEL_WINDOW = 1500                 # characters kept either side of each FFO mention for the model (the verbatim check reads the whole exhibit)
MODEL_MAX_CHARS = 24_000

_FFO = r"(?:(?:Nareit|NAREIT)[- ](?:defined\s+)?)?(?:FFO|[Ff]unds\s+[Ff]rom\s+[Oo]perations)(?:\s*\(\s*FFO\s*\))?"
_NOT_NAREIT = re.compile(r"\bcore\b|normali[sz]ed|adjusted|\bAFFO\b|as\s+adjusted|comparable|recurring", re.I)
_NOT_QUARTER = re.compile(r"full[- ]year|year[- ]to[- ]date|twelve\s+months|six\s+months|nine\s+months|guidance|outlook|expects?|range\s+of|\bfor\s+(?:the\s+)?(?:year|20\d\d)\b", re.I)
_PATTERNS = [
    # "FFO of $1.06 per diluted share", "Nareit FFO was $1.13 per share", "funds from operations ... totaled $2.4 million, or $0.52 per diluted share"
    re.compile(_FFO + r"[^.$]{0,120}?\$\s?(\(?\d{1,3}\.\d{2}\)?)\s+per\s+(?:diluted\s+)?(?:common\s+)?(?:share|unit)", re.S),
    # "FFO per diluted share was $1.06", "FFO per share - diluted of $1.06"
    re.compile(_FFO + r"\s+per\s+(?:diluted\s+)?(?:common\s+)?share[^.$]{0,60}?\$\s?(\(?\d{1,3}\.\d{2}\)?)", re.S),    # a table row: "FFO per diluted share 7.03 6.95", "FFO per common share and unit, diluted $ 1.07"
    re.compile(_FFO + r"[^.$\d]{0,40}?\bper\b[^.$\d]{0,40}?\bshare\b[^$\d]{0,40}?(?:\bdiluted\b[^$\d]{0,10})?\$?\s?(\(?\d{1,3}\.\d{2}\)?)", re.S),
]
REIT_SECTOR = "Real Estate"


def is_reit(sector: str | None, industry: str | None) -> bool:
    """Pure: GICS Real Estate with a REIT sub-industry ("Retail REITs", "REIT - Residential"); real estate services are not REITs."""
    return (sector or "") == REIT_SECTOR and "REIT" in (industry or "")


def _amount(s: str) -> float:
    neg = s.startswith("(") and s.endswith(")")
    v = float(s.strip("()"))
    return -v if neg else v


def parse_release_ffo(exhibit: str) -> dict | None:
    """Pure: the quarter's Nareit FFO per diluted share as the release states it in prose or a labelled row: {ffo, how, evidence}, the
    first statement that is neither core/normalized/adjusted/AFFO nor a full-year, year-to-date or guidance figure; None when none."""
    flat = re.sub(r"\s+", " ", exhibit or "")
    hits = []
    for i, pat in enumerate(_PATTERNS):
        for m in pat.finditer(flat):
            near = flat[max(0, m.start() - 25):m.start()]        # "Core ", "Normalized ", "Adjusted " directly in front of the label
            before = flat[max(0, m.start() - 150):m.start()]     # a guidance or full-year sentence leading up to it
            span = flat[m.start():m.end()]
            if _NOT_NAREIT.search(near + span) or _NOT_QUARTER.search(before + span):
                continue
            hits.append((m.start(), i, m))
    if not hits:
        return None
    _, i, m = min(hits)
    # a row that states basic first and diluted after ("FFO per share: Basic $7.04 Diluted $7.03") is read at its diluted figure
    dil = re.search(r"\bdiluted\b[^$\d]{0,15}\$?\s?(\(?\d{1,3}\.\d{2}\)?)", flat[m.start():m.start() + 160], re.I)
    if dil and re.search(r"\bbasic\b", flat[m.start():m.start() + dil.start()], re.I):
        return {"ffo": _amount(dil.group(1)), "how": "table row, diluted", "evidence": flat[m.start():m.start() + dil.end() + 20].strip()}
    return {"ffo": _amount(m.group(1)), "how": ("prose statement", "per-share statement", "table row")[i], "evidence": flat[m.start():m.end() + 40].strip()}


FFO_PROMPT = """You are reading the text of a REIT's earnings press release filed with the SEC (an 8-K exhibit). Return JSON only, no prose:
{{"ffo": <number or null>, "period_end": "<YYYY-MM-DD or null>", "quote": "<the exact sentence or table row, copied verbatim, that states the figure>"}}

The figure wanted is FFO (funds from operations, as Nareit defines it) per diluted share for the most recent quarter the release reports:
- the quarter, never the full year, year to date, twelve months or guidance;
- Nareit FFO (sometimes "FFO attributable to common stockholders"), never core FFO, normalized FFO, adjusted FFO or AFFO;
- per diluted share (or per diluted share and unit), never the dollar total;
- a negative figure written "$(0.35)" is -0.35.
Copy the quote exactly as the text reads it; never paraphrase. If the release states no such figure, return ffo null and quote null.
The report date is {report_date}.

TEXT:
{text}"""


def model_text(exhibit: str) -> str:
    """Pure: the exhibit's FFO passages (MODEL_WINDOW either side of each mention, merged), at most MODEL_MAX_CHARS; the whole
    flattened exhibit when it mentions FFO nowhere."""
    flat = re.sub(r"\s+", " ", exhibit or "").strip()
    spans = []
    for m in re.finditer(r"FFO|[Ff]unds [Ff]rom [Oo]perations", flat):
        a, b = max(0, m.start() - MODEL_WINDOW), min(len(flat), m.end() + MODEL_WINDOW)
        if spans and a <= spans[-1][1]:
            spans[-1] = (spans[-1][0], b)
        else:
            spans.append((a, b))
    out = " ... ".join(flat[a:b] for a, b in spans) if spans else flat
    return out[:MODEL_MAX_CHARS]


def parse_ffo_json(content: str) -> dict | None:
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        return None
    v = d.get("ffo")
    try:
        d["ffo"] = float(v) if v is not None else None
    except (TypeError, ValueError):
        d["ffo"] = None
    return d


_LABEL_NORM = re.compile(r"(?:core|normali[sz]ed|adjusted|comparable|modified)?(?:affo|ffo|fundsfromoperations)|net(?:income|earnings|loss)|earningspershare|eps")


def row_under_ffo(exhibit: str, quote: str) -> bool:
    """Pure: a table row with no label of its own ("Diluted $ 1.07 $ 1.06") sits, at one of its occurrences in the exhibit, under a Nareit FFO
    label: the nearest result label within 200 characters above it names FFO and no core, normalized, adjusted, modified or AFFO
    figure. Read on the normalized text (release_reader._norm: no spaces, no dollar signs, lower case)."""
    flat, q = R._norm(exhibit), R._norm(quote)
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
    core, normalized, adjusted or AFFO figure or a full-year one. Empty when it holds."""
    if ffo is None or not quote:
        return ["model read nothing"]
    problems = []
    if R._norm(quote) not in R._norm(exhibit):
        problems.append("the quote is not verbatim in the exhibit")
    forms = [f"{abs(ffo):.2f}"]
    if not any(f in quote for f in forms):
        problems.append("the quote does not contain the figure")
    if not re.search(r"FFO|funds\s+from\s+operations", quote, re.I) and not row_under_ffo(exhibit, quote):
        problems.append("the quote names no FFO, and the label above its row is not Nareit FFO")
    if _NOT_NAREIT.search(quote):
        problems.append("the quote names a core, normalized, adjusted or AFFO figure")
    if _NOT_QUARTER.search(quote):
        problems.append("the quote names a full-year, year-to-date or guidance figure")
    return problems


def decide_ffo(pattern: dict | None, model: dict | None, exhibit: str) -> tuple[float | None, str]:
    """Pure: (the agreed figure, the note): stored only when the pattern parser and the verified model reading agree to the cent."""
    p = pattern["ffo"] if pattern else None
    p_text = f"pattern {p:.2f} ({pattern['how']})" if pattern else "pattern read nothing"
    if model is None:
        return None, f"{p_text}; no model reading"
    m = model.get("ffo")
    problems = verify_ffo_quote(exhibit, model.get("quote"), m)
    m_text = f"model {m:.2f}" if m is not None else "model read nothing"
    if problems and m is not None:
        return None, f"{p_text}; {m_text}; model quote rejected: {'; '.join(problems)}"
    if p is not None and m is not None and round(p, 2) == round(m, 2):
        return p, f"both readers {p:.2f}"
    return None, f"{p_text}; {m_text}; readers disagree"


async def model_read(client, exhibit: str, report_date: date | None) -> dict:
    prompt = FFO_PROMPT.format(report_date=report_date.isoformat() if report_date else "unknown", text=model_text(exhibit))
    out = await client.read_release_eps(prompt)
    parsed = parse_ffo_json(out["content"]) or {"ffo": None, "period_end": None, "quote": None}
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

async def load_ffo(db, symbol: str) -> tuple[list[tuple[date, float]], dict[date, float]]:
    """([(period_end, ffo)] shown quarters ascending, {period_end: gap} held quarters) from ffo_quarters."""
    rows = (await db.execute(text("""SELECT period_end, ffo_per_share, state, xbrl_gap_pct FROM ffo_quarters
        WHERE symbol = :s AND state IN ('ok', 'held') ORDER BY period_end"""), {"s": symbol})).all()
    shown = [(r.period_end, float(r.ffo_per_share)) for r in rows if r.state == "ok"]
    held = {r.period_end: float(r.xbrl_gap_pct or 0) for r in rows if r.state == "held"}
    return shown, held


async def ticker_is_reit(db, symbol: str) -> bool:
    row = (await db.execute(text("SELECT sector, industry FROM tickers WHERE symbol = :s"), {"s": symbol})).first()
    return bool(row) and is_reit(row.sector, row.industry)
