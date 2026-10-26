"""The report-date reader: a company's own words set its earnings date.

Two readers over the same passage, as the release EPS reader works (services/release_reader). The pattern reader finds a
sentence that says the company will post, report, release, announce or publish its quarter's results on an explicit calendar
date, with the quarter named and the timing (before the open, after the close, or a clock time) when stated; a date that closes
a period ("quarter ended September 30, 2026") is never the results date. The model reads the same passage and returns JSON with
the date, the timing and the sentence it read them from; code checks the sentence is verbatim and carries the date. A date counts
as confirmed only when both readers name the same date and that date is in the future at reading time.

Sources (scripts/confirm_report_dates): every 8-K exhibit (any item: Tesla's 2026-10-02 deliveries release, an Item 2.02 8-K, said
"Tesla will post its financial results for the third quarter of 2026 after market close on Wednesday, October 21, 2026"), every
ingested press release (Finnhub company news as stored in news_stories) and the company's IR feed items. Each confirmation stores
the source kind, the accession or URL, the quote, when it was read and READER_VERSION; the calendar note is written in the form
the page already reads ("confirmed: 8-K Item 2.02 exhibit filed 2026-10-02: ..." / "confirmed: press release via ...").
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date

READER_VERSION = 3                   # 2 (2026-10-20): every quote is classed (QUOTE_CLASSES); only a release date in the company's own words confirms
                                     # 3 (2026-10-26): the company's IR events feed and event pages are read; exchange tags with a name or a second
                                     # symbol, "today announced it will release" and "after the New York Stock Exchange closes" are read; a model quote
                                     # that carries the timing in the sentence after the date sentence stands with that sentence (Visa, Kraft Heinz)
QUOTE_CLASSES = ("release", "call_only", "third_party")
HORIZON_DAYS = 120                   # a results date further out than this is not a scheduled report

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_MON_ABBR = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
_DATE = re.compile(rf"(?:(?:Mon|Tues|Wednes|Thurs|Fri|Satur|Sun)day,?\s+)?((?:{_MONTHS})|(?:{_MON_ABBR})\.?)\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?(?![\d:])", re.I)   # the year may be absent ("Oct. 30")
_VERB = re.compile(r"\b(?:will|to|plans?\s+to|expects?\s+to|intends?\s+to|is\s+scheduled\s+to|scheduled\s+to|anticipates?)\s+"
                   r"(?:post|report|release|announce|publish|issue|host|hold|discuss|webcast)\b"
                   r"|\b(?:has\s+)?scheduled\s+(?:a|an|its|the)\s+(?:(?:earnings|results)\s+)?(?:conference\s+call|call|webcast)\b", re.I)
_TZ_OFFSET_H = {"central": 1, "ct": 1, "cst": 1, "cdt": 1, "mountain": 2, "mt": 2, "mst": 2, "mdt": 2, "pacific": 3, "pt": 3, "pst": 3, "pdt": 3}
_TZ = re.compile(r"\b(central|mountain|pacific|eastern|ct|cst|cdt|mt|mst|mdt|pt|pst|pdt|et|est|edt)\b", re.I)
_QUARTER = re.compile(r"\b(?:(?:first|second|third|fourth|1st|2nd|3rd|4th)[- ]quarter|Q[1-4]\b|quarterly|full[- ]year|fiscal[- ]year|year[- ]end)", re.I)
_RESULTS = re.compile(r"\b(?:financial results|operating results|results|earnings)\b", re.I)
_PERIOD = re.compile(r"(?:quarter|period|year|months?|half|weeks?)\s+(?:ended|ending|end)|fiscal\s+year\s+(?:ended|ending)|as\s+of|"
                     r"(?:three|six|nine|twelve)\s+months\s+(?:ended|ending)|through\b", re.I)
PERIOD_WINDOW = 40
_EXCHANGE = r"(?:New\s+York\s+Stock\s+Exchange|NYSE|Nasdaq(?:\s+Stock\s+Market)?|stock\s+market)"
_AMC = re.compile(r"after\s+(?:the\s+)?(?:market|markets|trading)?\s*(?:close|closes|closing)|after\s+the\s+(?:closing\s+)?bell|following\s+the\s+(?:market\s+)?close|after\s+market\s+hours"
                  rf"|after\s+the\s+{_EXCHANGE}\s+(?:closes|close)|after\s+the\s+close\s+of\s+(?:the\s+)?(?:market|trading|regular\s+trading|{_EXCHANGE})", re.I)
_BMO = re.compile(r"before\s+(?:the\s+)?(?:market|markets|trading)?\s*(?:open|opens|opening)|before\s+the\s+(?:opening\s+)?bell|prior\s+to\s+(?:the\s+)?(?:market\s+)?open|pre-?market"
                  rf"|before\s+the\s+{_EXCHANGE}\s+opens|before\s+the\s+(?:opening|open)\s+of\s+(?:the\s+)?(?:market|trading|{_EXCHANGE})", re.I)
_CLOCK = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)\b", re.I)
MARKET_OPEN, MARKET_CLOSE = (9, 30), (16, 0)


@dataclass(frozen=True)
class ReadDate:
    day: date
    timing: str          # "bmo" | "amc" | "unknown"
    quarter: str         # the quarter phrase the sentence named
    sentence: str        # the sentence, as it reads in the text


def _to_date(m: re.Match, today: date | None = None) -> date | None:
    """The date a match names; without a year, the next such day on or after `today` (a release names the coming date)."""
    mon = m.group(1).rstrip(".").lower()
    names = [x.lower() for x in _MONTHS.split("|")]
    try:
        month = names.index(mon) + 1 if mon in names else next(i + 1 for i, n in enumerate(names) if n.startswith(mon[:3]))
        if m.group(3):
            return date(int(m.group(3)), month, int(m.group(2)))
        if today is None:
            return None
        d = date(today.year, month, int(m.group(2)))
        return d if d >= today else date(today.year + 1, month, int(m.group(2)))
    except ValueError:
        return None


def timing_of(sentence: str) -> str:
    """Pure: bmo, amc or unknown from the sentence's own words, or from a clock time against the session (9:30 to 4:00 Eastern)."""
    if _AMC.search(sentence):
        return "amc"
    if _BMO.search(sentence):
        return "bmo"
    for m in _CLOCK.finditer(sentence):
        hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3).replace(".", "").lower()
        if hour == 12:
            hour = 0
        hour += 12 if ampm == "pm" else 0
        tz = _TZ.search(sentence[m.end():m.end() + 24])                         # "3:30 p.m. Central time" is 4:30 Eastern
        hour += _TZ_OFFSET_H.get(tz.group(1).lower(), 0) if tz else 0
        if (hour, minute) < MARKET_OPEN:
            return "bmo"
        if (hour, minute) >= MARKET_CLOSE:
            return "amc"
    return "unknown"


def sentences(text: str) -> list[str]:
    """Sentences of the flattened text: split at sentence ends, bullets and rows of asterisks (a release's "***" separator)."""
    flat = re.sub(r"\s+", " ", text or "")
    # a clock or corporate abbreviation ("8:00 a.m. ET", "Citigroup Inc. plans") never ends a sentence
    end = r"(?<!\b[ap]\.m\.)(?<!\bInc\.)(?<!\bCorp\.)(?<!\bCo\.)(?<!\bLtd\.)(?<!\bU\.S\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bDr\.)(?<!\bNo\.)(?<=[.!?])\s+(?=[A-Z\"“(])"
    return [s.strip() for s in re.split(end + r"|\s*[•▪◦]\s*|\s*\*{2,}\s*", flat) if s.strip()]


def read_report_date(text: str, today: date) -> ReadDate | None:
    """Pure: the first sentence that schedules the quarter's results on an explicit future date within HORIZON_DAYS.

    The sentence must carry a release verb (or a scheduled call), the quarter (or the full or fiscal year) and a results word, and
    the date must come after that anchor and not close a period. A sentence that only schedules a conference call or webcast, with
    no results word, is not a results date; a sentence whose date has passed is not a confirmation. When a later sentence names
    the same day with its timing (a headline without the timing, then the body with it), the sentence with the timing is kept."""
    first: ReadDate | None = None
    for s in sentences(text):
        v = _VERB.search(s)
        if not v or not _RESULTS.search(s):
            continue
        q = _QUARTER.search(s, v.end()) or _QUARTER.search(s)      # the quarter the verb's clause names, else anywhere in the sentence
        if not q:
            continue
        previous_end = 0
        for m in _DATE.finditer(s):
            d, start = _to_date(m, today), m.start()
            period = bool(_PERIOD.search(s[max(previous_end, start - PERIOD_WINDOW):start]))
            previous_end = m.end()
            if d is None or start < v.end() or period:
                continue
            if d <= today or (d - today).days > HORIZON_DAYS:
                continue
            hit = ReadDate(d, timing_of(s), q.group(0), s)
            if first is None:
                first = hit
            if hit.timing != "unknown" and hit.day == first.day:
                return hit
            break
    return first


# ── what a quote is (Sam, 2026-10-20) ──────────────────────────────────────────
# Only a release date in the company's own words confirms or changes a date. A call date alone leaves it estimated (Tyler's call
# was Oct 29 with its release after the close on Oct 28; Veralto's Oct 30 with the release Oct 29), and text the company didn't
# issue is ignored (a preview: "Gallagher (AJG) is back in focus as the insurer prepares to report", "says Jefferies" on Biogen).

_RELEASE_VERB = re.compile(r"\b(?:post|posts|report|reports|release|releases|released|announce|announces|publish|publishes|published|issue|issues|issued)\b"
                           r"|\bearnings\s+release\b|\bpress\s+release\b", re.I)
_CALL_WORDS = re.compile(r"\b(?:conference\s+call|call|webcast|webcasts|discuss|host|hosts|hold|holds|teleconference|audio)\b", re.I)
# a wire release carries its dateline ("PLANO, Texas, October 13, 2026--", "(GLOBE NEWSWIRE) --", "/PRNewswire/ --")
_WIRE = re.compile(r"\b(?:Business\s*Wire|GLOBE\s*NEWSWIRE|PR\s*Newswire|/PRNewswire/|ACCESSWIRE|Newsfile|EQS-News|Marketwired)\b"
                   r"|(?:^|(?<=\.\s))[A-Z][A-Z .'-]+,(?:\s+[A-Z][A-Za-z.]+,)?\s+(?:[A-Z][a-z]{2,8}\.?)\s+\d{1,2},\s+\d{4}\s*(?:--|—|-\s)", re.M)
# a writer other than the company: a preview, an analyst's note, a report about the report
_THIRD_PARTY = re.compile(r"\b(?:analysts?\s+(?:expect|are\s+expecting|expecting|estimate|forecast|polled|surveyed)|consensus|is\s+expected\s+to\s+(?:report|post|announce)|"
                          r"are\s+expected\s+to\s+(?:report|post)|says\s+[A-Z]|according\s+to|preview|back\s+(?:in|on)\s+(?:focus|investors|the\s+radar)|"
                          r"investors[’']\s+radar|prepares?\s+to\s+report|is\s+set\s+to\s+report|ahead\s+of\s+(?:its|the)\s+(?:report|earnings)|Wall\s+Street|"
                          r"Zacks|price\s+target|EPS\s+estimate|per\s+share\s+estimate)\b", re.I)


def company_issued(source_kind: str, text: str, symbol: str) -> bool:
    """Pure: the text is the company's own. Its 8-K exhibits and its IR feed are; a press release carried by Finnhub or the stored
    news is when it reads as wire copy (a wire dateline, or the company named with its own exchange tag, "(NYSE: ABT)") and reads as
    nobody else's (no preview or analyst phrasing). The issuer's name in the headline is checked before this (names_issuer)."""
    if source_kind in COMPANY_SOURCES:
        return True
    t = text or ""
    if _THIRD_PARTY.search(t):
        return False
    return bool(_WIRE.search(t) or exchange_tagged(t, symbol) or _SELF_ANNOUNCED.search(t))


COMPANY_SOURCES = ("8-K exhibit", "IR feed", "IR events")
# the company speaking of itself: "Realty Income ... today announced it will release", "Ares Management Corporation announced today that it will report"
_SELF_ANNOUNCED = re.compile(r"\b(?:today\s+announced|announced\s+today)\s+(?:that\s+)?(?:it|the\s+company)\s+(?:will|plans\s+to|intends\s+to)\s+"
                             r"(?:release|report|announce|issue|post|publish)\b", re.I)


def exchange_tagged(text: str, symbol: str) -> bool:
    """Pure: the company named with its own exchange tag, as only its own release writes it: "(NYSE: ABT)", "(Realty Income, NYSE: O)",
    "(Nasdaq: FOXA, FOX)", "(Cboe: CBOE)"."""
    sym = re.escape(symbol.replace("-", "."))
    return re.search(rf"\((?:[^()]{{0,60}}?[,;]\s*)?(?:NYSE|NASDAQ|Nasdaq|NYSE\s+American|Cboe(?:\s+BZX)?|TSX)\s*:\s*(?:[A-Z][A-Z.]{{0,5}},\s*)*{sym}\b", text or "") is not None


def sentence_class(sentence: str, day: date, today: date) -> str:
    """Pure: "release" when a release verb leads to the date with no call or webcast words between them ("will report results ...
    after the market closes on Monday, October 26, 2026", "plans to issue a press release ... on Thursday, October 29, 2026"),
    else "call_only" ("will host a conference call to discuss its third-quarter 2026 results at 10 a.m. Central time, Thursday, Nov. 5")."""
    for m in _DATE.finditer(sentence):
        if _to_date(m, today) != day:
            continue
        before = sentence[:m.start()]
        verbs = list(_RELEASE_VERB.finditer(before))
        for v in reversed(verbs):                       # the release verb nearest the date
            if not _CALL_WORDS.search(before[v.end():]):
                return "release"
    return "call_only"


def classify_quote(source_kind: str, text: str, sentence: str, day: date, symbol: str, today: date) -> str:
    """Pure: one of QUOTE_CLASSES for a sentence the reader found."""
    if not company_issued(source_kind, text, symbol):
        return "third_party"
    return sentence_class(sentence, day, today)


def read_release_date(text: str, today: date) -> ReadDate | None:
    """Pure: the first sentence read_report_date accepts whose date is a release date (sentence_class); a company text that names
    its call first and its release after ("will discuss ... on a call Thursday, October 29. The related press release will be issued
    after the market closes on Wednesday, October 28, 2026.") gives the release."""
    flat = sentences(text)
    for i in range(len(flat)):
        hit = read_report_date(" ".join(flat[i:i + 1]), today)
        if hit and sentence_class(hit.sentence, hit.day, today) == "release":
            if hit.timing == "unknown" and i + 1 < len(flat) and not _DATE.search(flat[i + 1]):
                # the timing in the next sentence, in words only ("... on Tuesday, October 27, 2026. After market close, Visa will furnish the results")
                nxt = flat[i + 1]
                timing = "amc" if _AMC.search(nxt) else "bmo" if _BMO.search(nxt) else "unknown"
                hit = ReadDate(hit.day, timing, hit.quarter, hit.sentence)
            return hit
    return None


# ── the model as the second reader ───────────────────────────────────────────

PROMPT = """You are reading text a public company published (an SEC 8-K exhibit, a press release or an investor-relations item).
Return JSON only, no prose: {{"date": "<YYYY-MM-DD or null>", "timing": "<bmo|amc|unknown>", "quote": "<the one sentence, copied verbatim, that names the date on which the company will report its quarterly results; the sentence with the date, even when the timing is in another sentence>"}}
The date wanted is the calendar day the company says it will post, report, release or announce its quarterly (or full-year) financial
results. Never a period end ("quarter ended September 30"), never a conference-call-only sentence without results, never a date in the
past of {today}. Never the date of a conference call or webcast: if the text gives only a call date and not the day the results
themselves come out, return date null and quote null. timing is "bmo" when the sentence says before the market opens (or a clock time before 9:30 a.m. Eastern), "amc" when after
the close (or at or after 4:00 p.m. Eastern), else "unknown". If no such sentence exists, return date null and quote null. Copy the sentence
exactly; never paraphrase.

TEXT:
{text}"""


def build_prompt(text: str, today: date, limit: int = 12_000) -> str:
    return PROMPT.format(today=today.isoformat(), text=re.sub(r"\s+", " ", text or "").strip()[:limit])


def parse_model_json(content: str) -> dict | None:
    m = re.search(r"\{.*\}", content or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
    except ValueError:
        # the model copies the release's own quotation marks unescaped ("The Kraft Heinz Company (NYSE: KHC) ("Kraft Heinz") will
        # release ..."): the fields are read by position, the quote running to the object's last quotation mark
        body = m.group(0)
        date_m = re.search(r'"date"\s*:\s*(?:"([^"]*)"|null)', body)
        timing_m = re.search(r'"timing"\s*:\s*"([^"]*)"', body)
        quote_m = re.search(r'"quote"\s*:\s*(?:"(.*)"|null)\s*\}\s*$', body, re.S)
        if not date_m:
            return None
        d = {"date": date_m.group(1), "timing": timing_m.group(1) if timing_m else None, "quote": quote_m.group(1) if quote_m else None}
    try:
        day = date.fromisoformat(str(d.get("date"))[:10]) if d.get("date") else None
    except ValueError:
        day = None
    timing = str(d.get("timing") or "unknown").lower()
    return {"date": day, "timing": timing if timing in ("bmo", "amc") else "unknown", "quote": (d.get("quote") or "").strip() or None}


def _norm(t: str | None) -> str:
    return re.sub(r"[\s$,\"'“”‘’]+", "", (t or "")).lower()


def verify_quote(text: str, quote: str | None, day: date | None) -> list[str]:
    """Pure: why the model's quote cannot stand, or [] when it is verbatim in the text and names the date it returned."""
    if not quote:
        return ["no quote"]
    if _norm(quote) not in _norm(text):
        return ["quote is not verbatim in the text"]
    if day is None:
        return ["no date"]
    if not any(_to_date(m, day) == day for m in _DATE.finditer(quote)):
        return [f"quote does not name {day.isoformat()}"]
    return []


def screen(text: str, today: date) -> list[str]:
    """Pure, for diagnosis: sentences with a results word and a future date, whether or not the reader accepts them."""
    out = []
    for s in sentences(text):
        if _RESULTS.search(s) and any((d := _to_date(m, today)) and today < d <= today + __import__("datetime").timedelta(days=HORIZON_DAYS) for m in _DATE.finditer(s)):
            out.append(s)
    return out


def decide(pattern: ReadDate | None, model: dict | None, text: str, today: date) -> tuple[date | None, str]:
    """Pure: (the confirmed date or None, the note). Confirmed only when both readers name the same future date."""
    p = pattern.day if pattern else None
    p_text = f"pattern {p.isoformat()} ({pattern.timing})" if pattern else "pattern read nothing"
    if model is None:
        return None, f"{p_text}; no model reading"
    m = model.get("date")
    if m and model.get("quote") and pattern and m != pattern.day and (m.month, m.day) == (pattern.day.month, pattern.day.day):
        # a quote with no year ("Boeing to Release Third Quarter Results on October 27"): the model guessed one (2021, 2025, 2027);
        # the date it names is the next such day, as the pattern reader reads it
        named = [d for x in _DATE.finditer(model["quote"]) if not x.group(3) and (d := _to_date(x, today))]
        if pattern.day in named:
            m = pattern.day
            model = {**model, "date": m}
    problems = verify_quote(text, model.get("quote"), m) if m else ["model read nothing"]
    if m and problems and pattern and pattern.day == m and model.get("quote") and _norm(pattern.sentence + model["quote"]) in _norm(text):
        # the model quoted the timing sentence that follows the date sentence: the two together are the company's words for the date
        model = {**model, "quote": f"{pattern.sentence} {model['quote']}"}
        problems = verify_quote(text, model["quote"], m)
    m_text = f"model {m.isoformat()} ({model.get('timing')})" if m else "model read nothing"
    if m and problems:
        return None, f"{p_text}; {m_text}; model quote rejected: {'; '.join(problems)}"
    if m and sentence_class(model["quote"], m, today) != "release":
        return None, f"{p_text}; {m_text}; model quote names a call, not the release"
    if p and m and p == m:
        if p <= today:
            return None, f"both readers {p.isoformat()}, not in the future"
        return p, f"both readers {p.isoformat()}"
    return None, f"{p_text}; {m_text}; readers disagree"


async def model_read(client, text: str, today: date) -> dict:
    from app.services.research_cost import estimate_cost_usd
    out = await client.read_report_date(build_prompt(text, today))
    parsed = parse_model_json(out["content"]) or {"date": None, "timing": "unknown", "quote": None}
    return {**parsed, "model": out["model_used"], "input_tokens": out["input_tokens"], "output_tokens": out["output_tokens"],
            "cost_usd": estimate_cost_usd(out["model_used"], out["input_tokens"], out["output_tokens"])}


def passage(text: str, sentence: str, around: int = 800) -> str:
    """The sentence with its surroundings, for the model: the whole document is never needed."""
    flat = re.sub(r"\s+", " ", text or "")
    i = flat.find(sentence[:60])
    return flat[max(0, i - around): i + len(sentence) + around] if i >= 0 else flat[:2 * around]


def confirmation_note(kind: str, reference: str, filed_or_published: str, quote: str) -> str:
    """The calendar note the page reads: an 8-K note starts "8-K", a release note "press release" (frontend confirmedKind)."""
    q = re.sub(r"\s+", " ", quote).strip()
    if kind == "8-K exhibit":
        return f"confirmed: 8-K {reference} filed {filed_or_published}: {q}"
    if kind == "IR events":
        return f"confirmed: events feed via IR {filed_or_published} {reference}: {q}"
    if kind == "IR feed":
        return f"confirmed: press release via IR feed {filed_or_published} {reference}: {q}"
    return f"confirmed: press release via Finnhub news {filed_or_published}: {q}"
