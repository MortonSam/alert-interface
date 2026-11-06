"""The company's own explanation beside a walkthrough step's figures (Sam, 2026-10-29: "every step pairs its figures with the
company's own explanation, quoted from its own filings").

    step 2 (growth)    its stated reason for the change in its sales (or revenue) in the step's quarter, naming the segment it credits
    step 3 (margins)   its stated reason for the change in the step's margin
    step 6 (upcoming)  what it said to expect next, from the outlook or guidance in its last earnings release, only when it gave one

The sources are the step quarter's 10-Q or 10-K (its MD&A: Item 2 of a 10-Q, Item 7 of a 10-K) and that quarter's earnings release
(the Item 2.02 8-K's exhibits); the outlook comes from the latest release alone. The model picks a passage and copies it; it never
writes one. A quote stands only when it passes every check, the same two-stage path step 7's risk sentences take
(walkthrough_story): code first (quote_problems: verbatim in the paragraph it names, at most QUOTE_SENTENCES sentences and QUOTE_WORDS
words, about the step's measure, a stated reason for steps 2 and 3, an expectation from the release for step 6), then the
verifier's model, which must find that the passage is the company explaining that figure for that period (or stating what it
expects next). A failure is sent back once with its reasons; a quote that fails twice is dropped, and the step shows no
explanation at all, never one Ivy wrote. Each quote is stored with its filing's receipt (form, accession, filed, url) and shown with
a "Read it in the filing" link.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import date, timedelta

QUOTES_VERSION = 1
QUOTE_WORDS = 70
QUOTE_SENTENCES = 2
PARAGRAPH_MIN_CHARS = 30                # an outlook bullet is short ("Revenue is expected to be $54.0 billion, plus or minus 2%.")
PROMPT_CHARS = 26000                    # of candidate paragraphs sent to the model
RELEASE_DAYS = 120                      # a quarter's release is the first Item 2.02 8-K filed within this many days after it ends
LAST_RELEASE_DAYS = 200                 # the outlook's release: the latest Item 2.02 8-K within this many days
KEYS = ("growth", "margins", "outlook")

_MDNA_START = re.compile(r"\s*item\s*(?:2|7)\s*[.:\-–—]?\s*(?:\n\s*)?management", re.I)
_MDNA_END = re.compile(r"\s*item\s*(?:3|7a|8)\s*[.:\-–—]?\s*(?:\n\s*)?(?:quantitative|financial statements)", re.I)
HEADING_MAX_CHARS = 120               # MU's "ITEM 2. MANAGEMENT'S DISCUSSION AND ANALYSIS OF FINANCIAL CONDITION AND RESULTS OF OPERATIONS" is 95
TOPIC = {
    "growth": re.compile(r"\b(?:revenues?|sales)\b", re.I),
    "outlook": re.compile(r"\b(?:expects?|expected|outlook|guidance|anticipat\w*|forecast\w*|projects?|projected)\b", re.I),
}
MARGIN_TOPIC = {"gross": re.compile(r"\bgross (?:margins?|profit)\b", re.I),
                "operating": re.compile(r"\boperating (?:margins?|income)\b", re.I),
                "net": re.compile(r"\b(?:net (?:income|interest) margin|net margin|net income)\b", re.I)}
# a stated reason: the company says why, in its own connective
REASON = re.compile(r"\b(?:driven|due to|primarily|reflect\w*|result(?:ed|ing)? (?:from|of)|as a result|led by|because|attributable|"
                    r"owing to|benefit\w*|offset|reflecting|thanks to|(?:on|from) (?:the )?(?:higher|lower|strong\w*|increased|decreased|improved|favorable|unfavorable|"
                    r"growth|ramp|mix|demand|pricing)|mix (?:of|shift))\b", re.I)
NUMERIC_ROW = re.compile(r"^[\s\d$%.,()\-–—]+$")
# step 2 shows the change from a year earlier: a passage comparing only with the quarter before explains another figure
SEQUENTIAL = re.compile(r"\bsequential\w*|\bquarter[- ]over[- ]quarter\b", re.I)
QUARTER_OF = re.compile(r"\b(first|second|third|fourth) quarter of (?:fiscal )?(?:year )?(\d{4})\b", re.I)
YEAR_AGO = re.compile(r"\byear[- ](?:ago|earlier|over[- ]year)|\bprior[- ]year\b|\bsame (?:quarter|period) (?:of|in|last)|\blast year\b", re.I)
SOURCE_KEYS = {"M": "periodic", "R": "release", "O": "last_release", "N": "margin_periodic"}


def mdna(paragraphs: list[dict]) -> list[dict]:
    """Pure: the paragraphs of the MD&A: the longest span from an "Item 2 (or 7). Management's Discussion" heading to the next
    Item 3, 7A or 8 heading (a table of contents holds a short one)."""
    best = None
    for i, p in enumerate(paragraphs):
        if len(p["text"]) > HEADING_MAX_CHARS or not _MDNA_START.match(p["text"]):
            continue
        j = i + 1
        while j < len(paragraphs) and not (len(paragraphs[j]["text"]) <= HEADING_MAX_CHARS and _MDNA_END.match(paragraphs[j]["text"])):
            j += 1
        size = sum(len(q["text"]) for q in paragraphs[i + 1:j])
        if best is None or size > best[0]:
            best = (size, i + 1, j)
    return paragraphs[best[1]:best[2]] if best and best[0] > 2000 else []


def prose(paragraphs: list[dict]) -> list[str]:
    """Pure: the paragraphs worth quoting: sentence-length plain text, never a heading or a row of figures."""
    out = []
    for p in paragraphs:
        t = " ".join(p["text"].split())
        if len(t) < PARAGRAPH_MIN_CHARS or p.get("emphasis") or NUMERIC_ROW.match(t) or sum(c.isdigit() for c in t) > 0.3 * len(t):
            continue
        out.append(t)
    return out


def _receipt(cik: str, accession: str, doc: str, form: str, filed: str) -> dict:
    return {"form": form, "accession": accession, "filed": filed, "document": doc,
            "url": f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession.replace('-', '')}/{doc}"}


async def read_periodic(edgar, cik: str, period_end: date, fetch: bool = True) -> dict | None:
    """The 10-Q or 10-K for the quarter ended period_end (EDGAR's reportDate), its MD&A as prose paragraphs, with its receipt
    (fetch=False: the receipt alone, from the submissions list)."""
    from app.services.risk_factors import blocks
    r = ((await edgar.get_submissions(cik)).get("filings") or {}).get("recent") or {}
    for form, rep, acc, doc, filed in zip(r.get("form") or [], r.get("reportDate") or [], r.get("accessionNumber") or [], r.get("primaryDocument") or [],
                                          r.get("filingDate") or []):
        if form in ("10-Q", "10-K") and rep == period_end.isoformat():
            if not fetch:
                return _receipt(cik, acc, doc, form, filed)
            html = await edgar.fetch_filing_html(cik, acc, doc)
            return {**_receipt(cik, acc, doc, form, filed), "paragraphs": prose(mdna(blocks(html))), "period_end": rep}
    return None


async def read_release(edgar, cik: str, *, after: date | None = None, within: int = RELEASE_DAYS, latest: bool = False, fetch: bool = True) -> dict | None:
    """An Item 2.02 8-K's exhibits as prose paragraphs, with its receipt: the first filed within `within` days after `after` (a
    quarter's release), or the latest within LAST_RELEASE_DAYS (latest=True, the outlook's)."""
    from app.services.risk_factors import blocks
    since = after or (date.today() - timedelta(days=LAST_RELEASE_DAYS))
    recs, _ = await edgar.get_8k_records_since(cik, since.isoformat())
    recs = [x for x in recs if "2.02" in (x.get("items") or "") and date.fromisoformat(x["filing_date"]) <= since + timedelta(days=within if not latest else LAST_RELEASE_DAYS)]
    if not recs:
        return None
    rec = max(recs, key=lambda x: x["filing_date"]) if latest else min(recs, key=lambda x: x["filing_date"])
    if not fetch:
        return _receipt(cik, rec["accession"], rec.get("primary_document") or "", "8-K", rec["filing_date"])
    names = [n for n in await edgar.list_filing_documents(cik, rec["accession"], every_exhibit=True) if n != rec.get("primary_document")]
    names = sorted(names, key=lambda n: (0 if re.search(r"ex[-_]?99|99[-_.]?1|press|release", n, re.I) else 1, n))[:3]
    paragraphs, doc = [], None
    for n in names:
        try:
            got = prose(blocks(await edgar.fetch_filing_document(cik, rec["accession"], n)))
        except Exception:
            continue
        if got and doc is None:
            doc = n
        paragraphs += got
    if not paragraphs:
        return None
    return {**_receipt(cik, rec["accession"], doc, "8-K", rec["filing_date"]), "paragraphs": paragraphs}


# ── the prompt and the checks ───────────────────────────────────────────────────────────────────────────────────────────────

def candidates(sources: dict, want: dict) -> list[tuple[str, str]]:
    """Pure: [(id, paragraph)] for the model: MD&A paragraphs M1.. and release paragraphs R1.. (the outlook's release O1..), only
    those that touch a wanted topic, within PROMPT_CHARS."""
    out, size = [], 0
    for tag, key in SOURCE_KEYS.items():
        src = sources.get(key)
        if not src:
            continue
        for i, p in enumerate(src["paragraphs"], 1):
            topics = [k for k in want if (k != "outlook" or tag == outlook_tag(sources)) and (k != "margins" or tag in margin_tags(sources))
                      and (k != "growth" or tag in ("M", "R"))]
            if not any(topic_re(k, want[k]).search(p) for k in topics):
                continue
            if size + len(p) > PROMPT_CHARS:
                return out
            out.append((f"{tag}{i}", p))
            size += len(p)
    return out


def margin_tags(sources: dict) -> tuple[str, ...]:
    """Pure: the paragraphs a margin quote may come from: the margin period's own filing (N) when it differs from the growth quarter's."""
    return ("N",) if sources.get("margin_periodic") else ("M", "R")


def outlook_tag(sources: dict) -> str:
    """Pure: the paragraphs an outlook may come from: the latest release (O), or the quarter's own (R) when that is the latest."""
    return "O" if sources.get("last_release") else "R"


def topic_re(key: str, about: dict) -> re.Pattern:
    return MARGIN_TOPIC.get(about.get("measure") or "gross", MARGIN_TOPIC["gross"]) if key == "margins" else TOPIC[key]


def paragraph(sources: dict, pid: str) -> str | None:
    key = SOURCE_KEYS.get(pid[:1])
    src = sources.get(key) if key else None
    try:
        return src["paragraphs"][int(pid[1:]) - 1] if src else None
    except (ValueError, IndexError):
        return None


def quote_problems(key: str, about: dict, quote: str, pid: str, sources: dict) -> list[str]:
    """Pure: why a picked passage cannot stand, or []."""
    from app.services.ask_ivy import sentences
    from app.services.release_reader import _norm
    out = []
    para = paragraph(sources, pid or "")
    if para is None:
        return [f"names no paragraph it was copied from ({pid})"]
    if not quote or _norm(quote) not in _norm(para):
        out.append(f"is not copied word for word from {pid}")
    elif not starts_a_sentence(para, quote):
        out.append("starts partway through a sentence")
    if len(sentences(quote or "")) > QUOTE_SENTENCES:
        out.append(f"more than {QUOTE_SENTENCES} sentences")
    if len((quote or "").split()) > QUOTE_WORDS:
        out.append(f"over {QUOTE_WORDS} words")
    if not topic_re(key, about).search(quote or ""):
        out.append(f"does not name {about['measure_words']}")
    if key in ("growth", "margins") and not REASON.search(quote or ""):
        out.append("states no reason for the change")
    if key == "outlook" and any(not TOPIC["outlook"].search(x) for x in sentences(quote or "")):
        out.append("a sentence of it states no expectation (an outlook quote is the outlook alone)")
    if key == "outlook" and pid[:1] != outlook_tag(sources):
        out.append("an outlook must come from its latest earnings release")
    if key == "growth" and pid[:1] not in ("M", "R"):
        out.append("comes from a filing for another quarter")
    if key == "margins" and pid[:1] not in margin_tags(sources):
        out.append("comes from a filing for another period")
    if key == "growth" and sequential_only(quote or ""):
        out.append("compares with the quarter before, not a year earlier")
    return out


def sequential_only(quote: str) -> bool:
    """Pure: the passage compares a quarter only with the quarter before: "sequentially" or "quarter over quarter" with no year-earlier
    comparison, or two quarters of the same year named ("the third quarter of 2026 ... the second quarter of 2026")."""
    if YEAR_AGO.search(quote):
        return False
    if SEQUENTIAL.search(quote):
        return True
    named = {(q.lower(), y) for q, y in QUARTER_OF.findall(quote)}
    return len(named) >= 2 and len({y for _, y in named}) == 1


def starts_a_sentence(para: str, quote: str) -> bool:
    """Pure: the quote begins where a sentence of the paragraph begins, never partway through one ("we are pleased to raise ..." after
    "As a result,"): it opens with a capital letter or a figure, and the text before it in the paragraph does not end in a comma,
    a semicolon or a word that runs on into it."""
    from app.services.release_reader import _norm, _norm_map
    q = (quote or "").lstrip(" \"\u201c")
    if not q or q[0].islower():
        return False
    flat, idx = _norm_map(para)
    at = flat.find(_norm(quote))
    if at <= 0:
        return at == 0
    before = para[:idx[at]].rstrip()
    return not before or not (before[-1] in ",;" or (before[-1].isalpha() and before.split()[-1].islower() and len(before.split()[-1]) <= 3))


def build_prompt(name: str, want: dict, cands: list[tuple[str, str]], redo: dict | None = None) -> str:
    sources_have_n = any(i.startswith("N") for i, _ in cands)
    asks = []
    if "growth" in want:
        a = want["growth"]
        asks.append(f'- "growth": the passage where {name} explains why its {a["noun"]} {a["direction"]} in {a["period"]} (the quarter ended {a["end"]}) against '
                    f"the same quarter a year earlier: its stated reason, best a passage that names the segment or market it credits. Not a comparison with "
                    f"the quarter before alone. From an M or R paragraph only.")
    if "margins" in want:
        a = want["margins"]
        asks.append(f'- "margins": the passage where {name} explains why its {a["measure_words"]} changed, for the period ended {a["end"]}. '
                    f"From {'an N' if sources_have_n else 'an M or R'} paragraph only.")
    if "outlook" in want:
        asks.append(f'- "outlook": the passage in its latest earnings release (an O paragraph, else R) where {name} says what it expects for its next quarter or '
                    f"year (its outlook or guidance). Only if the release gives one.")
    redo_block = ("\nYOUR LAST PICKS FAILED THESE CHECKS. Pick again so each passes, or return null:\n" + "\n".join(f"- {k}: {v}" for k, v in redo.items()) + "\n") if redo else ""
    shape = ", ".join(f'"{k}": {{"paragraph": "<id>", "quote": "<copied word for word>"}} or null' for k in want)
    return f"""You pick passages from {name}'s own filings; you never write or change a word.

PARAGRAPHS (M: its 10-Q or 10-K MD&A for the quarter; R: that quarter's earnings release; O: its latest earnings release; N: the MD&A
of its filing for the margin's period):
{chr(10).join(f"{i}: {p}" for i, p in cands)}
{redo_block}
PICK, for each of these, one or two whole consecutive sentences copied exactly from ONE paragraph (at most {QUOTE_WORDS} words), starting
where a sentence starts, or null when no paragraph does it:
{chr(10).join(asks)}
A passage that only restates the figure without saying why is not a reason. For "outlook", copy only the sentences that state the
expectation, never a sentence about results already reported. Never join sentences from two paragraphs.

Return JSON only: {{{shape}}}"""


def verification_prompt(name: str, want: dict, picks: dict[str, dict], sources: dict) -> str:
    rows = []
    for k, p in picks.items():
        a = want[k]
        task = (f"{name}'s own explanation of why its {a['noun']} {a['direction']} in {a['period']} against the same quarter a year earlier (a comparison "
                f"with the quarter before alone is unsupported)" if k == "growth" else
                f"{name}'s own explanation of why its {a['measure_words']} changed, for the period ended {a['end']}" if k == "margins" else
                f"what {name} says it expects for its next quarter or year")
        rows.append(f"{k}: PARAGRAPH {p['paragraph']}: {paragraph(sources, p['paragraph'])}\n   QUOTE: {p['quote']}\n   MUST BE: {task}")
    return f"""You are a rigorous fact-checker. Each QUOTE below was copied from the PARAGRAPH shown, from {name}'s own filing. Judge only
whether the quote is what it MUST BE, using the paragraph alone.
{chr(10).join(rows)}
RULES
- "supported": the quote is the company itself stating that, for that measure and that period (an outlook: a stated expectation).
- "unsupported": it is about another measure or period, only restates a figure without a reason, is a general description, or is
  a forward-looking-statements disclaimer.
- Bias toward "unsupported" when in doubt.
Return JSON only: {{"verdicts": [{{"id": "growth|margins|outlook", "status": "supported|unsupported", "reason": "one sentence"}}]}}"""


def parse_picks(content: str, want: dict) -> dict[str, dict]:
    m = re.search(r"\{.*\}", content or "", re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        d = {}
    out = {}
    for k in want:
        v = d.get(k)
        if isinstance(v, dict) and isinstance(v.get("quote"), str) and v["quote"].strip() and isinstance(v.get("paragraph"), str):
            out[k] = {"paragraph": v["paragraph"].strip(), "quote": " ".join(v["quote"].split())}
    return out


async def quotes_for(name: str, want: dict, sources: dict, *, client=None) -> dict:
    """{quotes: {key: {quote, paragraph, receipt}}, verdicts, dropped, cost_usd}. Two rounds at most; nothing unverified is kept."""
    from app.services.walkthrough_story import _call, _client, parse_verdicts
    cands = candidates(sources, want)
    if not cands or not want:
        return {"version": QUOTES_VERSION, "quotes": {}, "verdicts": {}, "dropped": [], "cost_usd": 0.0}
    client = client or _client()
    kept: dict[str, dict] = {}
    verdicts: dict[str, dict] = {}
    cost, redo = 0.0, None
    for rnd in (1, 2):
        ask = {k: v for k, v in want.items() if k not in kept and (redo is None or k in redo)}
        content, c = await _call(lambda p: client.generate_walkthrough(p, max_tokens=900), build_prompt(name, ask, cands, redo))
        cost += c or 0.0
        picks = parse_picks(content, ask)
        failed: dict[str, str] = {}
        clean = {}
        for k, p in picks.items():
            probs = quote_problems(k, want[k], p["quote"], p["paragraph"], sources)
            if probs:
                failed[k] = "; ".join(probs)
                verdicts[k] = {"status": "rejected", "reason": failed[k], "round": rnd, **p}
            else:
                clean[k] = p
        if clean:
            vcontent, vc = await _call(client.verify_walkthrough, verification_prompt(name, want, clean, sources))
            cost += vc or 0.0
            vs = parse_verdicts(vcontent)
            for k, p in clean.items():
                v = vs.get(k) or {"status": "unsupported", "reason": "no verdict returned"}
                verdicts[k] = {**v, "round": rnd, **p}
                if v.get("status") == "supported":
                    src = SOURCE_KEYS[p["paragraph"][:1]]
                    kept[k] = {**p, "receipt": {x: sources[src][x] for x in ("form", "accession", "filed", "document", "url")}}
                else:
                    failed[k] = v.get("reason") or "unsupported"
        if not failed or rnd == 2:
            break
        redo = failed
    dropped = [{"id": k, "reason": v["reason"]} for k, v in verdicts.items() if k not in kept]
    return {"version": QUOTES_VERSION, "quotes": kept, "verdicts": verdicts, "dropped": dropped, "cost_usd": round(cost, 4)}


# ── onto the payload ───────────────────────────────────────────────────────────────────────────────────────────────────────

def doc_words(receipt: dict) -> str:
    from app.services.briefing import fmt_date
    filed = fmt_date(date.fromisoformat(receipt["filed"][:10]))
    return f"its earnings release of {filed}" if receipt["form"] == "8-K" else f"its {receipt['form']} filed {filed}"


def source_label(receipt: dict) -> str:
    """Pure: "10-Q filed Aug 26, 2026", "Earnings release of Aug 26, 2026"."""
    w = doc_words(receipt).removeprefix("its ")
    return w[:1].upper() + w[1:]


def lead(key: str, name: str, about: dict, receipt: dict) -> str:
    """Pure: the line above a quote, built by rule (no colon: the walkthrough's copy carries none)."""
    if key == "growth":
        return f"How {name} explains its {about['noun']} in {about['period']}, in {doc_words(receipt)}"
    if key == "margins":
        return f"How {name} explains its {about['measure_words']}, in {doc_words(receipt)}"
    return f"What {name} said to expect, in {doc_words(receipt)}"


STEP_OF = {"growth": "growth", "margins": "margins", "outlook": "upcoming"}


def apply(payload: dict, stored: dict | None) -> None:
    """Pure (in place): each verified quote onto its step as {text, lead, source: {label, url}}."""
    want = (stored or {}).get("want") or {}
    by_key = {s["key"]: s for s in payload["steps"]}
    for k, q in ((stored or {}).get("quotes") or {}).items():
        st = by_key.get(STEP_OF[k])
        if not st or st["status"] == "absent" or k not in want:
            continue
        r = q["receipt"]
        st["quote"] = {"text": q["quote"], "lead": lead(k, payload["name"], want[k], r),
                       "source": {"label": source_label(r), "url": r["url"]}}


def wanted(payload: dict, growth_row: dict | None, margin: dict | None, periods: dict | None) -> dict:
    """Pure: what each step's quote must explain, from the step's own figures: {key: about}. Growth needs a quarter with a change in
    figures; margins needs a measure; the outlook needs a step 6 that shows."""
    from app.services.fiscal_periods import quarter
    from app.services.margins import MEASURE_LABEL
    by_key = {s["key"]: s for s in payload["steps"]}
    noun = payload.get("noun") or "revenue"
    out: dict = {}
    if growth_row and by_key["growth"]["status"] != "absent" and growth_row.get("growth_pct") is not None:
        g = float(growth_row["growth_pct"])
        end = growth_row["period_end"]
        out["growth"] = {"noun": noun, "direction": "rose" if g > 0 else "fell" if g < 0 else "held flat", "period": quarter(periods, end),
                         "end": str(end), "measure_words": noun}
    if margin and margin.get("ok") and by_key["margins"]["status"] != "absent":
        out["margins"] = {"measure": margin["measure"], "measure_words": MEASURE_LABEL[margin["measure"]], "end": str(margin["now_end"]), "noun": noun}
    if by_key["upcoming"]["status"] != "absent":
        out["outlook"] = {"measure_words": "an expectation", "noun": noun}
    return out


def fingerprint(want: dict, sources: dict) -> str:
    """The growth and margin quotes' noun is the walkthrough's word, not the filing's: it is hashed as "sales" whatever the walkthrough calls it
    (every company "revenue" since 2026-11-04), so the wording change re-picks no quote the company's filings still hold."""
    from app.services import walkthrough as W
    want = {k: ({**v, "noun": "sales"} if k in ("growth", "margins") and isinstance(v, dict) and "noun" in v else v) for k, v in want.items()}
    return W.fingerprint({"v": QUOTES_VERSION, "want": want, "acc": {k: (sources.get(k) or {}).get("accession") for k in SOURCE_KEYS.values()}})


async def gather(edgar, cik: str, want: dict, fetch: bool = True) -> dict:
    """The quote sources for one stock: the growth quarter's periodic filing and release, and the latest release (fetch=False:
    their receipts alone, to tell whether a stored reading still stands)."""
    out: dict = {}
    end = date.fromisoformat(want["growth"]["end"]) if "growth" in want else (date.fromisoformat(want["margins"]["end"]) if "margins" in want else None)
    if end:
        out["periodic"] = await asyncio.wait_for(read_periodic(edgar, cik, end, fetch), 120)
        out["release"] = await asyncio.wait_for(read_release(edgar, cik, after=end, fetch=fetch), 120)
    if "margins" in want and "growth" in want and want["margins"]["end"] != want["growth"]["end"]:
        out["margin_periodic"] = await asyncio.wait_for(read_periodic(edgar, cik, date.fromisoformat(want["margins"]["end"]), fetch), 120)
    if "outlook" in want:
        last = await asyncio.wait_for(read_release(edgar, cik, latest=True, fetch=fetch), 120)
        if last and (not out.get("release") or last["accession"] != out["release"]["accession"]):
            out["last_release"] = last              # the quarter's own release is the latest when the accessions match (outlook_tag)
    return {k: v for k, v in out.items() if v}


async def refresh(edgar, cik: str | None, want: dict, prior: dict | None, name: str, write_model: bool) -> dict:
    """One stock's stored quotes ({version, want, fingerprint, quotes, verdicts, dropped, cost_usd, sources?}): kept while what the
    steps show and the filings' accessions are unchanged; else the filings are read and, when write_model, the quotes picked again.
    Without a model pass a changed stock keeps no quotes (never a stale one)."""
    prior = prior or {}
    if not cik or not want:
        return {"version": QUOTES_VERSION, "want": want, "fingerprint": None, "quotes": {}}
    receipts = await gather(edgar, cik, want, fetch=False)
    fp = fingerprint(want, receipts)
    if prior.get("fingerprint") == fp and prior.get("version") == QUOTES_VERSION:
        return prior
    if not write_model:
        return {"version": QUOTES_VERSION, "want": want, "fingerprint": None, "quotes": {}}
    sources = await gather(edgar, cik, want)
    got = await quotes_for(name, want, sources)
    return {**got, "want": want, "fingerprint": fp}
