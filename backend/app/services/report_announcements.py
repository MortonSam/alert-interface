"""Company announcements of a results date: the one source that confirms a future earnings date.

Two cheap feeds, both matched with the same rule: a sentence that says the company will
announce, report or release quarterly results, carrying an explicit calendar date within the
next ANNOUNCE_HORIZON_DAYS. Sources: Finnhub company news (headline + summary, which is where
the wire copy of an IR press release lands) and EDGAR 8-Ks carrying Item 7.01 or 8.01. Nothing is
inferred from a date alone; the results phrase must be within the same passage.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

ANNOUNCE_HORIZON_DAYS = 90

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE = re.compile(rf"(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,?\s+)?({_MONTHS})\s+(\d{{1,2}}),?\s+(\d{{4}})", re.I)
_RESULTS = re.compile(
    r"\b(?:will|to|plans? to|expects? to|intends? to|is scheduled to)\s+(?:announce|report|release|host|hold)\b[^.]{0,160}?"
    r"\b(?:results|earnings)\b", re.I)
_TIMING_AMC = re.compile(r"after (?:the )?(?:market|close|closing)|after the close|following the (?:market )?close", re.I)
_TIMING_BMO = re.compile(r"before (?:the )?(?:market|open|opening)|before the (?:market )?open|pre-?market", re.I)


@dataclass(frozen=True)
class Announcement:
    day: date
    timing: str      # "amc" | "bmo" | "unknown"
    evidence: str    # "Finnhub news 2026-08-28: NIKE, Inc. to Announce ..." / "8-K Item 7.01 filed 2026-08-28"


def _to_date(m: re.Match) -> date | None:
    try:
        month = [x.lower() for x in _MONTHS.split("|")].index(m.group(1).lower()) + 1
        return date(int(m.group(3)), month, int(m.group(2)))
    except ValueError:
        return None


def find_announced_date(text: str, today: date, evidence: str) -> Announcement | None:
    """The results date a passage announces, if it names one within the horizon."""
    if not text:
        return None
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text):
        if not _RESULTS.search(sentence):
            continue
        for m in _DATE.finditer(sentence):
            d = _to_date(m)
            if d is None or d < today or (d - today).days > ANNOUNCE_HORIZON_DAYS:
                continue
            timing = "amc" if _TIMING_AMC.search(sentence) else "bmo" if _TIMING_BMO.search(sentence) else "unknown"
            return Announcement(d, timing, evidence)
    return None


def from_news(items: list[dict], today: date) -> Announcement | None:
    """Finnhub company-news items: headline + summary, newest first."""
    for it in sorted(items, key=lambda i: i.get("datetime") or 0, reverse=True):
        text = f"{it.get('headline', '')}. {it.get('summary', '')}"
        published = date.fromtimestamp(it["datetime"]).isoformat() if it.get("datetime") else "?"
        hit = find_announced_date(text, today, f"press release via Finnhub news {published}: {str(it.get('headline', ''))[:80]}")
        if hit:
            return hit
    return None


def from_8k_text(text: str, filed: str, items: str, today: date) -> Announcement | None:
    item = "7.01" if "7.01" in (items or "") else "8.01"
    return find_announced_date(text, today, f"8-K Item {item} filed {filed}")


def edgar_ir_8ks(records: list[dict], today: date, lookback_days: int = 45) -> list[dict]:
    """8-K records carrying Item 7.01 or 8.01 filed within the lookback."""
    start = today - timedelta(days=lookback_days)
    out = []
    for r in records:
        items = [i.strip() for i in (r.get("items") or "").split(",")]
        if not ({"7.01", "8.01"} & set(items)):
            continue
        try:
            filed = date.fromisoformat(r["filing_date"])
        except (KeyError, TypeError, ValueError):
            continue
        if start <= filed <= today:
            out.append(r)
    return out
