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

EPS_TAGS = ("EarningsPerShareDiluted", "EarningsPerShareBasic")
QUARTER_DAYS = (75, 100)
YEAR_DAYS = (350, 380)
MATCH_TOLERANCE = 0.01       # |stored - xbrl| for "matched" against a filed quarterly value
DERIVED_TOLERANCE = 0.03     # for a Q4 derived as FY minus three quarters: FY EPS is computed on the
                             # year's weighted share count, so it is not the exact sum of the quarters
SPLIT_TOLERANCE = 0.03       # relative, for off_by_split
MAX_LAG_DAYS = 120           # event must fall within this many days after the period end
BASIS_MISMATCH_FRACTION = 0.20   # actual must sit this far (x |estimate|) from GAAP while the estimate matches it


@dataclass(frozen=True)
class Fact:
    end: date
    value: float
    tag: str
    filed: str        # ISO date of the filing that reported it


def _entries(facts_json: dict, tag: str) -> list[dict]:
    return facts_json.get("facts", {}).get("us-gaap", {}).get(tag, {}).get("units", {}).get("USD/shares", [])


def quarter_facts(facts_json: dict) -> dict[date, list[Fact]]:
    """{period_end: [every quarterly EPS value reported for it]}, diluted first, basic as fallback.

    Includes derived Q4 values (FY minus the three quarters inside it) tagged
    "derived_q4:<tag>" when the filer reported no standalone Q4 value.
    """
    out: dict[date, list[Fact]] = {}
    for tag in EPS_TAGS:
        quarters: dict[date, list[Fact]] = {}
        years: list[tuple[date, date, float]] = []
        for e in _entries(facts_json, tag):
            try:
                start, end, val = date.fromisoformat(e["start"]), date.fromisoformat(e["end"]), float(e["val"])
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


def classify(actual: Decimal, estimate: Decimal | None, event_date: date,
             facts: dict[date, list[Fact]], cands: list[Candidate]) -> Classification:
    """Match the actual, then the estimate against the same XBRL quarter.

    basis_mismatch: the estimate matches GAAP (same tolerances, split-aware)
    while the actual does not and sits more than BASIS_MISMATCH_FRACTION x
    |estimate| away from the GAAP figure. The two were reported on different
    bases, so no Beat/Miss can be read from them.
    """
    am = match_actual(actual, event_date, facts, cands)
    if estimate is None or am.status == "no_fact":
        return Classification(am, None, False)
    em = match_actual(estimate, event_date, facts, cands)
    mismatch = (
        em.status in ("matched", "off_by_split")
        and am.status == "unmatched"
        and am.xbrl_eps is not None
        and abs(float(actual) - am.xbrl_eps) > BASIS_MISMATCH_FRACTION * abs(float(estimate))
    )
    return Classification(am, em.status, mismatch)
