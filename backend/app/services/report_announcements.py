"""Company announcements of a results date: the one source that confirms a future earnings date.

Two cheap feeds, both matched with the same rule: a sentence that says the company will
announce, report or release quarterly results, carrying an explicit calendar date within the
next ANNOUNCE_HORIZON_DAYS. Sources: Finnhub company news (headline + summary, which is where
the wire copy of an IR press release lands) and EDGAR 8-Ks carrying Item 7.01 or 8.01. Nothing is
inferred from a date alone; the results phrase must be within the same passage.

A press release confirms only when the announcing entity is the issuer itself: its first sentence
(the headline) must name the company as the tickers table names it, or its common short form
(names_issuer). "GM Financial to Release Third Quarter 2026 Operating Results" is GM Financial's
release, not General Motors', and confirms nothing for GM. An 8-K is filed under the issuer's own
CIK, so the filer is the issuer by construction.
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


# ── The announcing entity must be the issuer ─────────────────────────────────

_CORPORATE_SUFFIXES = {"inc", "incorporated", "corp", "corporation", "company", "companies", "co", "cos", "ltd", "limited",
                       "plc", "nv", "sa", "ag", "se", "llc", "lp", "holdings", "holding", "group", "hc", "the"}
# words a headline may put straight after the issuer's name without naming a different entity
_HEADLINE_WORDS = {"to", "will", "on", "of", "and", "its", "for", "in", "at", "with", "a", "an",
                   "announces", "announce", "announced", "schedules", "schedule", "sets", "set", "invites", "reports", "report",
                   "release", "releases", "hosts", "host", "holds", "hold", "webcast", "webcasts", "conference", "call",
                   "earnings", "results", "date", "dates", "details", "first", "second", "third", "fourth", "quarter", "quarterly",
                   "fiscal", "fy", "q1", "q2", "q3", "q4", "full", "half", "year", "operating", "and"}
# a first word too generic to stand for the company on its own
_GENERIC_FIRST_WORDS = {"general", "american", "united", "national", "first", "international", "global", "standard", "consolidated",
                        "universal", "allied", "southern", "northern", "western", "eastern", "pacific", "atlantic", "central",
                        "federal", "public", "service", "energy", "capital", "bank", "financial", "group", "health", "north", "south"}


def _tokens(text: str) -> list[str]:
    """Words with everything but letters and digits removed, empties dropped ("JPMorgan Chase & Co." -> jpmorgan, chase, co)."""
    out = []
    for w in re.split(r"\s+", text):
        t = re.sub(r"[^0-9a-z]", "", w.lower())
        if t:
            out.append(t)
    return out


def _raw_words(text: str) -> list[str]:
    """The words of `text` aligned with _tokens (only words that leave a token)."""
    return [w for w in re.split(r"\s+", text) if re.sub(r"[^0-9a-z]", "", w.lower())]


def issuer_forms(name: str) -> list[str]:
    """The forms a headline may use for the issuer: the stored name, its legal short form (corporate suffixes and
    parentheticals removed) and, when distinctive, the short form's first word ("Verizon", "T-Mobile", "Marsh")."""
    base = re.sub(r"\([^)]*\)", " ", name)                     # "Kimco Realty Corporation (HC)"
    full = _tokens(base)
    short = list(full)
    while short and short[-1] in _CORPORATE_SUFFIXES:
        short.pop()
    while short and short[0] in _CORPORATE_SUFFIXES:
        short.pop(0)
    forms = [" ".join(full)]
    if short and short != full:
        forms.append(" ".join(short))
    if short and len(short) > 1 and len(short[0]) >= 5 and short[0] not in _GENERIC_FIRST_WORDS:
        forms.append(short[0])
    return [f for f in forms if f]


def names_issuer(first_sentence: str, name: str) -> bool:
    """True when the sentence names the issuer and not a different entity built on its name.

    The form must start at a word boundary; the words may run together ("JPMorganChase"). The word after the
    matched form may be lowercase, a corporate suffix, a number or an ordinary headline word ("Third", "Invites"),
    but not another capitalised word: "General Motors Financial Company" and "Quest Software" name someone else."""
    toks, words = _tokens(first_sentence), _raw_words(first_sentence)
    if len(toks) != len(words):
        words = toks
    for form in issuer_forms(name):
        target = form.replace(" ", "")
        for i in range(len(toks)):
            joined, j = "", i
            while j < len(toks) and len(joined) < len(target):
                joined += toks[j]
                j += 1
            if joined != target:
                continue
            if j >= len(toks):
                return True
            nxt, nxt_tok = words[j], toks[j]
            if not nxt[:1].isupper() or nxt_tok in _CORPORATE_SUFFIXES or nxt_tok in _HEADLINE_WORDS or nxt_tok[:1].isdigit():
                return True
    return False


def from_news(items: list[dict], today: date, issuer: str | None = None) -> Announcement | None:
    """Finnhub company-news items: headline + summary, newest first. With `issuer` (the tickers table's name),
    an item counts only when its headline names the issuer (names_issuer)."""
    for it in sorted(items, key=lambda i: i.get("datetime") or 0, reverse=True):
        headline = str(it.get("headline", ""))
        if issuer is not None and not names_issuer(headline, issuer):
            continue
        text = f"{headline}. {it.get('summary', '')}"
        published = date.fromtimestamp(it["datetime"]).isoformat() if it.get("datetime") else "?"
        hit = find_announced_date(text, today, f"press release via Finnhub news {published}: {headline[:80]}")
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
