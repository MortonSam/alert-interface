"""Pure matching of stored earnings actuals against EDGAR XBRL EPS facts.

companyfacts lists every EPS value a filer ever reported, keyed by period.
Quarterly values have ~90-day durations; Q4 is usually only in the 10-K as a
full-year figure, so Q4 is derived as FY minus the three quarters inside it
when no standalone Q4 value exists. Later filings restate earlier periods
(after a split, on the new share count), so every value reported for a
period end is kept and any of them may match.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.services.split_basis import Candidate

# Diluted first, then the tags filers use instead of it; each later tag only
# fills quarters the earlier ones lack (ABNB files IncomeLossFromContinuing-
# OperationsPerDilutedShare; some filers only EarningsPerShareBasicAndDiluted).
EPS_TAGS = (
    "EarningsPerShareDiluted",
    "IncomeLossFromContinuingOperationsPerDilutedShare",
    "EarningsPerShareBasicAndDiluted",
    "EarningsPerShareBasic",
    "IncomeLossFromContinuingOperationsPerBasicShare",
)
QUARTER_DAYS = (75, 119)     # 13-week quarters, and the 16-week first quarter of 52/53-week filers (Kroger)
YEAR_DAYS = (350, 380)
MATCH_TOLERANCE = 0.01       # |stored - xbrl| for "matched" against a filed quarterly value
DERIVED_TOLERANCE = 0.03     # for a Q4 derived as FY minus three quarters: FY EPS is computed on the
                             # year's weighted share count, so it is not the exact sum of the quarters
SPLIT_TOLERANCE = 0.03       # relative, for off_by_split
MAX_LAG_DAYS = 120           # event must fall within this many days after the period end

# Per-filer overrides, keyed by 10-digit CIK: which tags carry the diluted EPS
# that Yahoo's figure is comparable to, and a factor to bring the XBRL unit
# onto the traded share class. Filers not listed use EPS_TAGS and factor 1.
#
# Limits of what companyfacts can give: a filer that reports EPS per share
# class tags each value with a StatementClassOfStock dimension, and
# companyfacts carries only undimensioned facts. Those filers have no EPS
# fact here under any tag, so an override cannot reach them; their figures
# live in each filing's own XBRL instance (see check_eps_basis notes).
FILER_EPS_OVERRIDES: dict[str, dict] = {
    # Berkshire Hathaway: undimensioned EPS is per Class A share (EarningsPerShareBasic,
    # filed through 2013); one Class A = 1,500 Class B, the traded BRK-B unit.
    "0001067983": {"tags": ("EarningsPerShareBasic",), "unit_factor": 1 / 1500},
}


def filer_override(cik: str | None) -> dict:
    return FILER_EPS_OVERRIDES.get(cik or "", {})
BASIS_MISMATCH_FRACTION = 0.20   # actual must sit this far (x |estimate|) from GAAP while the estimate matches it
BASIS_MISMATCH_MIN_ESTIMATE = 0.25   # cent-level estimates coincide with GAAP too easily to prove a basis
BASIS_MISMATCH_MIN_ROWS = 2      # a basis pattern is a property of the feed for a ticker, not one quarter


@dataclass(frozen=True)
class Fact:
    end: date
    value: float
    tag: str
    filed: str        # ISO date of the filing that reported it


def _entries(facts_json: dict, tag: str) -> list[dict]:
    return facts_json.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD/shares", [])


def quarter_facts(facts_json: dict, cik: str | None = None) -> dict[date, list[Fact]]:
    """{period_end: [every quarterly EPS value reported for it]}, diluted first, EPS_TAGS order as fallback.

    Includes derived Q4 values (FY minus the three quarters inside it) tagged
    "derived_q4:<tag>" when the filer reported no standalone Q4 value. A CIK
    in FILER_EPS_OVERRIDES swaps the tag list and scales every value by its
    unit factor.
    """
    override = filer_override(cik)
    tags = tuple(override.get("tags", EPS_TAGS))
    factor = float(override.get("unit_factor", 1.0))
    out: dict[date, list[Fact]] = {}
    for tag in tags:
        quarters: dict[date, list[Fact]] = {}
        years: list[tuple[date, date, float]] = []
        for e in _entries(facts_json, tag):
            try:
                start, end = date.fromisoformat(e["start"]), date.fromisoformat(e["end"])
                val = round(float(e["val"]) * factor, 4)
            except (KeyError, ValueError, TypeError):
                continue
            days = (end - start).days
            if QUARTER_DAYS[0] <= days <= QUARTER_DAYS[1]:
                quarters.setdefault(end, []).append(Fact(end, val, tag, e.get("filed", "")))
            elif YEAR_DAYS[0] <= days <= YEAR_DAYS[1]:
                years.append((start, end, val))
        for start, end, fy_val in years:
            if end in quarters:
                continue
            inside = sorted({q for q in quarters if start < q < end})
            if len(inside) != 3:
                continue
            q_sum = sum(_latest(quarters[q]).value for q in inside)
            quarters.setdefault(end, []).append(Fact(end, round(fy_val - q_sum, 4), f"derived_q4:{tag}", ""))
        for end, facts in quarters.items():
            if end not in out:               # diluted wins; basic only fills gaps
                out[end] = facts
    return out


def _latest(facts: list[Fact]) -> Fact:
    return max(facts, key=lambda f: f.filed)


@dataclass(frozen=True)
class Match:
    status: str                     # matched / off_by_split / unmatched / no_fact
    xbrl_eps: float | None = None
    tag: str | None = None
    period_end: date | None = None
    split_factor: float | None = None


def match_actual(actual: Decimal, event_date: date, facts: dict[date, list[Fact]],
                 cands: list[Candidate]) -> Match:
    """Match a stored actual to the XBRL quarter whose period end is nearest before the event.

    `cands` are the split candidates recorded after the event (split_basis.candidates),
    used for off_by_split when the XBRL value is on a different share count.
    """
    ends = [e for e in facts if e <= event_date and (event_date - e).days <= MAX_LAG_DAYS]
    if not ends:
        return Match("no_fact")
    end = max(ends)
    values = facts[end]
    a = float(actual)
    for f in sorted(values, key=lambda f: f.filed, reverse=True):
        tol = DERIVED_TOLERANCE if f.tag.startswith("derived_q4:") else MATCH_TOLERANCE
        if abs(f.value - a) <= tol:
            return Match("matched", f.value, f.tag, end)
    if a != 0:
        for f in values:
            if f.value == 0:
                continue
            ratio = abs(f.value / a)
            for F, _ in cands:
                if abs(ratio - F) / F <= SPLIT_TOLERANCE or abs(1 / ratio - F) / F <= SPLIT_TOLERANCE:
                    return Match("off_by_split", f.value, f.tag, end, F)
    latest = _latest(values)
    return Match("unmatched", latest.value, latest.tag, end)


@dataclass(frozen=True)
class Classification:
    actual: Match
    estimate_status: str | None       # matched / off_by_split / unmatched, or None when there is no estimate / no fact
    basis_mismatch: bool
    estimate_split_factor: float | None = None   # the factor that made the estimate match, when one did


def _gaap_on_estimate_basis(xbrl: float, estimate: float, factor: float | None) -> float:
    """The GAAP figure on the estimate's share count: divided or multiplied by the
    factor, whichever brought the estimate to match it."""
    if factor is None:
        return xbrl
    down, up = xbrl / factor, xbrl * factor
    return down if abs(down - estimate) <= abs(up - estimate) else up


def classify(actual: Decimal, estimate: Decimal | None, event_date: date,
             facts: dict[date, list[Fact]], cands: list[Candidate]) -> Classification:
    """Match the actual, then the estimate against the same XBRL quarter.

    basis_mismatch needs all of: |estimate| >= BASIS_MISMATCH_MIN_ESTIMATE; the
    estimate matches GAAP (same tolerances, split-aware); the actual does not
    match and sits more than BASIS_MISMATCH_FRACTION x |estimate| from GAAP
    *on the estimate's share count*, so a split factor that explains the
    estimate cannot also explain the actual. The per-ticker minimum of
    BASIS_MISMATCH_MIN_ROWS is applied by the caller over all its rows.
    """
    am = match_actual(actual, event_date, facts, cands)
    if estimate is None or am.status == "no_fact":
        return Classification(am, None, False)
    em = match_actual(estimate, event_date, facts, cands)
    if em.status not in ("matched", "off_by_split") or am.status != "unmatched" or am.xbrl_eps is None:
        return Classification(am, em.status, False, em.split_factor)
    e, a = float(estimate), float(actual)
    gaap = _gaap_on_estimate_basis(am.xbrl_eps, e, em.split_factor)
    mismatch = abs(e) >= BASIS_MISMATCH_MIN_ESTIMATE and abs(a - gaap) > BASIS_MISMATCH_FRACTION * abs(e)
    return Classification(am, em.status, mismatch, em.split_factor)


def apply_min_rows(flags: list[bool]) -> list[bool]:
    """A ticker with fewer than BASIS_MISMATCH_MIN_ROWS flagged rows keeps none of them."""
    if sum(flags) < BASIS_MISMATCH_MIN_ROWS:
        return [False] * len(flags)
    return list(flags)
